import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kilo.orchestrator.planner import ExecutionPlanner
from kilo.orchestrator.planning_service import PlanningService
from kilo.orchestrator.project_spec import ProjectSpec
from kilo.orchestrator.repair_service import PlanRepairService


def _blog_spec() -> ProjectSpec:
    return ProjectSpec.from_dict(
        {
            "product_type": "blog",
            "app_kind": "blog",
            "summary": "Blog platform with categories",
            "features": ["Blog", "Categories"],
            "pages": [
                {"name": "Home", "route": "/", "purpose": "Primary blog landing", "auth": "public"},
                {"name": "PostDetail", "route": "/posts/:slug", "purpose": "Read a post", "auth": "public"},
            ],
            "api_resources": [
                {"name": "posts", "route": "/api/posts", "methods": ["list", "detail"], "entity": "Post", "frontend": True, "auth": "public"},
                {"name": "categories", "route": "/api/categories", "methods": ["list"], "entity": "Category", "frontend": True, "auth": "public"},
            ],
        }
    )


class TestPlanningServiceArtifacts:
    def test_persists_plan_json_only_and_removes_legacy_markdown(self):
        planner = ExecutionPlanner()
        planner.load_contract(_blog_spec())

        with tempfile.TemporaryDirectory() as tmp:
            planning = PlanningService(tmp, planner=planner)
            planning.persist(prompt="Create a blog platform with categories")

            assert os.path.exists(planning.plan_json_path())
            assert sorted(os.listdir(os.path.join(tmp, ".lovable"))) == ["plan.json"]

            with open(planning.plan_json_path(), "r", encoding="utf-8") as handle:
                payload = handle.read()
            console_report = planning.render_console_report()

            assert '"units"' in payload
            assert "EXECUTION PLAN STATUS" in console_report
            assert "API Resources:" in console_report
            assert "batch_post" in console_report or "batch_category" in console_report

    def test_restores_planner_from_plan_json_without_run_state(self):
        planner = ExecutionPlanner()
        planner.load_contract(_blog_spec())

        with tempfile.TemporaryDirectory() as tmp:
            planning = PlanningService(tmp, planner=planner)
            planning.persist(prompt="Create a blog platform with categories")

            restored = PlanningService(tmp)
            assert restored.restore(prompt="Create a blog platform with categories") is True
            assert restored.total_count == planner.total_count
            assert restored.project_spec is not None
            assert any(unit.paths for unit in restored.state.units)


class TestPlanAwareRepair:
    def test_blueprint_retry_scope_stays_inside_failed_plan_unit(self):
        planner = ExecutionPlanner()
        planner.load_contract(_blog_spec())

        with tempfile.TemporaryDirectory() as tmp:
            planning = PlanningService(tmp, planner=planner)
            planning.persist(prompt="Create a blog platform with categories")
            repair = PlanRepairService(planning)

            current_batch = [
                "server/controllers/postController.ts",
                "server/routes/postRoutes.ts",
                "src/pages/Home.tsx",
            ]
            error_text = (
                "server/routes/postRoutes.ts: BLUEPRINT_NOT_ENFORCED: "
                "The route contract was incomplete."
            )

            retry = repair.determine_retry_batch(error_text, current_batch)

            assert "server/routes/postRoutes.ts" in retry
            assert "server/controllers/postController.ts" in retry
            assert "src/pages/Home.tsx" not in retry

    def test_blueprint_retry_scope_keeps_api_connected_files_together(self):
        planner = ExecutionPlanner()
        planner.load_contract(_blog_spec())

        with tempfile.TemporaryDirectory() as tmp:
            planning = PlanningService(tmp, planner=planner)
            planning.persist(prompt="Create a blog platform with categories")
            repair = PlanRepairService(planning)

            current_batch = [
                "server/controllers/postController.ts",
                "server/routes/postRoutes.ts",
                "src/services/postService.ts",
                "src/hooks/usePosts.tsx",
            ]
            error_text = (
                "server/routes/postRoutes.ts: BLUEPRINT_NOT_ENFORCED: "
                "The route contract drifted from its connected consumers."
            )

            retry = repair.determine_retry_batch(error_text, current_batch)

            assert "server/controllers/postController.ts" in retry
            assert "server/routes/postRoutes.ts" in retry
            assert "src/services/postService.ts" in retry
            assert "src/hooks/usePosts.tsx" in retry

    def test_generic_file_format_validation_error_does_not_become_fake_retry_path(self):
        planner = ExecutionPlanner()
        planner.load_contract(_blog_spec())

        with tempfile.TemporaryDirectory() as tmp:
            planning = PlanningService(tmp, planner=planner)
            planning.persist(prompt="Create a blog platform with categories")
            repair = PlanRepairService(planning)

            retry = repair.determine_retry_batch(
                "No valid files were found in the response. Please provide the implementation as strict JSON with a top-level files[] payload (fallback: // FILE: path format).",
                ["package.json"],
            )

            assert retry == ["package.json"]

    def test_root_owned_package_json_error_narrows_retry_to_package_file(self):
        planner = ExecutionPlanner()
        planner.load_contract(_blog_spec())

        with tempfile.TemporaryDirectory() as tmp:
            planning = PlanningService(tmp, planner=planner)
            planning.persist(prompt="Create a blog platform with categories")
            repair = PlanRepairService(planning)

            retry = repair.determine_retry_batch(
                "package.json: Missing 'server' script",
                ["package.json", "vite.config.ts"],
            )

            assert retry == ["package.json"]
