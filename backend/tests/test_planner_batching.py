import os
import sys
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kilo.orchestrator.planner import ExecutionPlanner
from kilo.orchestrator.project_spec import ProjectSpec


class TestPlannerBatching:
    def test_create_plan_falls_back_to_deterministic_contract_when_provider_errors(self):
        class BrokenProvider:
            async def stream(self, _messages, _model_id):
                if False:
                    yield ""
                raise RuntimeError("planner boom")

        planner = ExecutionPlanner()

        asyncio.run(
            planner.create_plan(
                prompt="Create a website",
                design=type("DesignStub", (), {"project_name": ""})(),
                provider=BrokenProvider(),
                model_id="test-model",
            )
        )

        assert planner.total_count > 0
        assert planner.project_spec is not None
        assert any(task.path == "package.json" for task in planner.tasks)
        assert any(task.path == "server/index.ts" for task in planner.tasks)

    def test_core_files_are_split_into_domain_batches(self):
        spec = ProjectSpec.from_dict(
            {
                "product_type": "website",
                "app_kind": "website",
                "features": ["Core"],
                "pages": [{"name": "Home", "route": "/", "purpose": "Primary page", "auth": "public"}],
                "api_resources": [
                    {"name": "items", "route": "/api/items", "methods": ["list"], "entity": "Item", "frontend": True, "auth": "public"},
                ],
                "entities": [
                    {"name": "Item", "fields": [{"name": "title", "required": True}]},
                ],
            }
        )

        planner = ExecutionPlanner()
        planner.load_contract(spec)
        files = {item.path: item for item in planner.tasks}

        assert files["src/styles/global.css"].unit_id == "batch_frontend_shell"
        assert files["server/db/database.ts"].unit_id == "batch_data"
        assert files["src/services/api.ts"].unit_id == "batch_client_shared"
        assert files["package.json"].unit_id == "batch_tooling"

    def test_shared_hubs_do_not_mix_frontend_shell_with_database_batch(self):
        spec = ProjectSpec.from_dict(
            {
                "product_type": "blog",
                "app_kind": "blog",
                "features": ["Blog", "Categories"],
                "pages": [{"name": "Home", "route": "/", "purpose": "Primary blog landing", "auth": "public"}],
                "api_resources": [
                    {"name": "posts", "route": "/api/posts", "methods": ["list", "detail"], "entity": "Post", "frontend": True, "auth": "public"},
                    {"name": "categories", "route": "/api/categories", "methods": ["list"], "entity": "Category", "frontend": True, "auth": "public"},
                ],
            }
        )

        planner = ExecutionPlanner()
        planner.load_contract(spec)

        first_batch = set(planner.get_smart_batch(batch_cap=20))

        assert not ({"src/styles/global.css", "server/db/database.ts"} <= first_batch), first_batch

    def test_server_index_scoped_blueprint_includes_route_dependencies(self):
        spec = ProjectSpec.from_dict(
            {
                "product_type": "website",
                "app_kind": "website",
                "features": ["Catalog", "Bookings"],
                "pages": [{"name": "Home", "route": "/", "purpose": "Primary page", "auth": "public"}],
                "api_resources": [
                    {"name": "products", "route": "/api/products", "methods": ["list"], "entity": "Product", "frontend": True, "auth": "public"},
                    {"name": "bookings", "route": "/api/bookings", "methods": ["list", "create"], "entity": "Booking", "frontend": True, "auth": "private"},
                ],
                "auth": {"enabled": True, "allow_registration": False},
            }
        )

        planner = ExecutionPlanner()
        planner.load_contract(spec)

        scoped = planner.build_scoped_blueprint(["server/index.ts"])
        scoped_paths = {item["path"] for item in scoped["blueprint"]}

        assert "server/index.ts" in scoped_paths
        assert "server/db/database.ts" in scoped_paths
        assert "server/routes/productRoutes.ts" in scoped_paths
        assert "server/routes/bookingRoutes.ts" in scoped_paths
        assert "server/routes/authRoutes.ts" in scoped_paths

    def test_connected_blog_contract_is_grouped_in_one_batch(self):
        spec = ProjectSpec.from_dict(
            {
                "product_type": "blog",
                "app_kind": "blog",
                "features": ["Blog", "Categories"],
                "pages": [
                    {"name": "Home", "route": "/", "purpose": "Primary blog landing", "auth": "public"},
                    {"name": "CategoryArchive", "route": "/categories/:slug", "purpose": "Browse a category", "auth": "public"},
                    {"name": "PostDetail", "route": "/posts/:slug", "purpose": "Read a post", "auth": "public"},
                ],
                "api_resources": [
                    {"name": "posts", "route": "/api/posts", "methods": ["list", "detail"], "entity": "Post", "frontend": True, "auth": "public"},
                    {"name": "categories", "route": "/api/categories", "methods": ["list"], "entity": "Category", "frontend": True, "auth": "public"},
                ],
            }
        )

        planner = ExecutionPlanner()
        planner.load_contract(spec)

        completed_paths = {
            "package.json",
            "vite.config.ts",
            "tsconfig.json",
            "tsconfig.node.json",
            "index.html",
            ".env",
            ".gitignore",
            "src/main.tsx",
            "src/App.tsx",
            "src/styles/variables.css",
            "src/styles/global.css",
            "src/services/api.ts",
            "src/types/index.ts",
            "server/index.ts",
            "server/db/database.ts",
            "src/components/Hero.tsx",
            "src/components/Navbar.tsx",
            "src/components/Footer.tsx",
        }
        for path in completed_paths:
            planner.mark_done(path)

        batch = planner.get_smart_batch(batch_cap=20)
        batch_set = set(batch)

        assert any(path.startswith("server/") for path in batch), batch
        assert any(path.startswith("src/") for path in batch), batch

        expected_related = {
            "server/controllers/postController.ts",
            "server/routes/postRoutes.ts",
            "src/services/postService.ts",
            "src/hooks/usePosts.tsx",
            "src/components/PostCard.tsx",
            "src/pages/Home.tsx",
            "server/controllers/categoryController.ts",
            "server/routes/categoryRoutes.ts",
            "src/services/categoryService.ts",
            "src/hooks/useCategories.tsx",
            "src/components/CategoryList.tsx",
            "src/pages/CategoryArchive.tsx",
        }

        missing = sorted(expected_related - batch_set)
        assert not missing, f"Expected connected resource/page files in one batch, missing: {missing}"

    def test_cluster_for_file_includes_reverse_dependents_and_shared_types(self):
        spec = ProjectSpec.from_dict(
            {
                "product_type": "blog",
                "app_kind": "blog",
                "features": ["Blog", "Categories"],
                "pages": [
                    {"name": "Home", "route": "/", "purpose": "Primary blog landing", "auth": "public"},
                    {"name": "CategoryArchive", "route": "/categories/:slug", "purpose": "Browse a category", "auth": "public"},
                ],
                "api_resources": [
                    {"name": "posts", "route": "/api/posts", "methods": ["list", "detail"], "entity": "Post", "frontend": True, "auth": "public"},
                    {"name": "categories", "route": "/api/categories", "methods": ["list"], "entity": "Category", "frontend": True, "auth": "public"},
                ],
            }
        )

        planner = ExecutionPlanner()
        planner.load_contract(spec)

        cluster = set(planner.get_cluster_for_file("server/controllers/postController.ts"))

        assert "server/routes/postRoutes.ts" in cluster
        assert "src/services/postService.ts" in cluster
        assert "src/hooks/usePosts.tsx" in cluster
        assert "src/components/PostCard.tsx" in cluster
        assert "src/pages/Home.tsx" in cluster
        assert "src/types/index.ts" in cluster

    def test_cluster_for_frontend_service_includes_backend_contract_owners(self):
        spec = ProjectSpec.from_dict(
            {
                "product_type": "blog",
                "app_kind": "blog",
                "features": ["Blog", "Categories"],
                "pages": [
                    {"name": "Home", "route": "/", "purpose": "Primary blog landing", "auth": "public"},
                    {"name": "PostDetail", "route": "/posts/:slug", "purpose": "Read a post", "auth": "public"},
                ],
                "api_resources": [
                    {"name": "posts", "route": "/api/posts", "methods": ["list", "detail"], "entity": "Post", "frontend": True, "auth": "public"},
                ],
            }
        )

        planner = ExecutionPlanner()
        planner.load_contract(spec)

        cluster = set(planner.get_cluster_for_file("src/services/postService.ts"))

        assert "server/controllers/postController.ts" in cluster
        assert "server/routes/postRoutes.ts" in cluster
        assert "src/hooks/usePosts.tsx" in cluster
        assert "src/pages/Home.tsx" in cluster

    def test_scoped_blueprint_exposes_units_relationships_and_shared_files(self):
        spec = ProjectSpec.from_dict(
            {
                "product_type": "blog",
                "app_kind": "blog",
                "features": ["Blog", "Categories"],
                "pages": [
                    {"name": "Home", "route": "/", "purpose": "Primary blog landing", "auth": "public"},
                    {"name": "PostDetail", "route": "/posts/:slug", "purpose": "Read a post", "auth": "public"},
                ],
                "api_resources": [
                    {"name": "posts", "route": "/api/posts", "methods": ["list", "detail"], "entity": "Post", "frontend": True, "auth": "public"},
                ],
            }
        )

        planner = ExecutionPlanner()
        planner.load_contract(spec)

        scoped = planner.build_scoped_blueprint(["src/services/postService.ts"])
        unit_ids = {unit["id"] for unit in scoped["units"]}
        relationships = {
            (item["source"], item["target"], item["type"])
            for item in scoped["relationships"]
        }

        assert "batch_post" in unit_ids
        assert "src/types/index.ts" in scoped["shared_files"]
        assert any(rel[0] == "src/services/postService.ts" and rel[2] == "uses_api" for rel in relationships)
        assert ("src/hooks/usePosts.tsx", "src/services/postService.ts", "depends_on") in relationships

    def test_portfolio_batch_uses_canonical_project_cluster_without_custom_backend_duplicates(self):
        spec = ProjectSpec.from_dict(
            {
                "product_type": "portfolio",
                "app_kind": "portfolio",
                "features": ["Portfolio"],
                "pages": [{"name": "Home", "route": "/", "purpose": "Primary portfolio landing", "auth": "public"}],
                "required_files": [
                    "server/routes/projects.ts",
                    "server/models/Project.ts",
                    "src/components/ProjectGrid.tsx",
                    "src/styles/motion.css",
                ],
            }
        )

        planner = ExecutionPlanner()
        planner.load_contract(spec)

        completed_paths = {
            "package.json",
            "vite.config.ts",
            "tsconfig.json",
            "tsconfig.node.json",
            "index.html",
            ".env",
            ".gitignore",
            "src/main.tsx",
            "src/App.tsx",
            "src/styles/variables.css",
            "src/styles/global.css",
            "src/services/api.ts",
            "src/types/index.ts",
            "server/index.ts",
            "server/db/database.ts",
            "src/components/Hero.tsx",
            "src/components/Navbar.tsx",
            "src/components/Footer.tsx",
        }
        for path in completed_paths:
            planner.mark_done(path)

        batch = set(planner.get_smart_batch(batch_cap=40))

        assert "server/controllers/projectController.ts" in batch
        assert "server/routes/projectRoutes.ts" in batch
        assert "src/services/projectService.ts" in batch
        assert "src/hooks/useProjects.tsx" in batch
        assert "src/components/ProjectCard.tsx" in batch
        assert "src/components/ProjectGrid.tsx" in batch
        assert "src/pages/ProjectDetail.tsx" in batch
        assert "server/routes/projects.ts" not in batch
        assert "server/models/Project.ts" not in batch

    def test_frontend_batches_reopen_shared_style_and_route_owners_for_coherence(self):
        spec = ProjectSpec.from_dict(
            {
                "product_type": "portfolio",
                "app_kind": "portfolio",
                "features": ["Portfolio"],
                "pages": [{"name": "Home", "route": "/", "purpose": "Primary portfolio landing", "auth": "public"}],
            }
        )

        planner = ExecutionPlanner()
        planner.load_contract(spec)

        completed_paths = {
            "package.json",
            "vite.config.ts",
            "tsconfig.json",
            "tsconfig.node.json",
            "index.html",
            ".env",
            ".gitignore",
            "src/main.tsx",
            "src/App.tsx",
            "src/styles/variables.css",
            "src/styles/global.css",
            "src/services/api.ts",
            "src/types/index.ts",
            "server/index.ts",
            "server/db/database.ts",
            "src/components/Hero.tsx",
            "src/components/Navbar.tsx",
            "src/components/Footer.tsx",
        }
        for path in completed_paths:
            planner.mark_done(path)

        batch = set(planner.get_smart_batch(batch_cap=40))

        assert "src/pages/Home.tsx" in batch
        assert "src/styles/global.css" in batch
        assert "src/styles/variables.css" in batch
        assert "src/App.tsx" in batch
        assert "src/types/index.ts" in batch
        assert "src/services/api.ts" in batch
