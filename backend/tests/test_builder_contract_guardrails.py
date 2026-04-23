import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kilo.orchestrator.feature_validator import FeatureValidator
from kilo.orchestrator.loop import AgentLoop
from kilo.orchestrator.planner import ExecutionPlanner
from kilo.orchestrator.project_spec import ProjectSpec, compile_file_blueprint, parse_project_spec_response


def _write(rel_path: str, content: str, root: str) -> None:
    full_path = os.path.join(root, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)


class TestProjectSpecBlueprint:
    def test_server_index_blueprint_depends_on_route_modules_generically(self):
        spec = ProjectSpec.from_dict(
            {
                "product_type": "website",
                "app_kind": "website",
                "features": ["Catalog", "Bookings"],
                "pages": [{"name": "Home", "route": "/", "purpose": "Primary page", "auth": "public"}],
                "api_resources": [
                    {"name": "products", "route": "/api/products", "methods": ["list", "detail"], "entity": "Product", "frontend": True, "auth": "public"},
                    {"name": "bookings", "route": "/api/bookings", "methods": ["list", "create"], "entity": "Booking", "frontend": True, "auth": "private"},
                ],
                "auth": {"enabled": True, "allow_registration": False},
            }
        )

        files = {item["path"]: item for item in compile_file_blueprint(spec)}
        server_index = files["server/index.ts"]

        assert "server/db/database.ts" in server_index["depends_on"]
        assert "server/routes/productRoutes.ts" in server_index["depends_on"]
        assert "server/routes/bookingRoutes.ts" in server_index["depends_on"]
        assert "server/routes/authRoutes.ts" in server_index["depends_on"]

        import_targets = {item["target"] for item in server_index["imports"]}
        assert "server/db/database.ts" in import_targets
        assert "server/routes/productRoutes.ts" in import_targets
        assert "server/routes/bookingRoutes.ts" in import_targets
        assert "server/routes/authRoutes.ts" in import_targets

    def test_blog_blueprint_adds_resource_ui_helpers(self):
        spec = ProjectSpec.from_dict(
            {
                "product_type": "blog",
                "app_kind": "blog",
                "features": ["Blog", "Categories", "Comments"],
                "pages": [
                    {"name": "Home", "route": "/", "purpose": "Primary blog landing", "auth": "public"},
                    {"name": "CategoryArchive", "route": "/categories/:slug", "purpose": "Browse a category", "auth": "public"},
                    {"name": "PostDetail", "route": "/posts/:slug", "purpose": "Read a post", "auth": "public"},
                ],
                "api_resources": [
                    {"name": "posts", "route": "/api/posts", "methods": ["list", "detail"], "entity": "Post", "frontend": True, "auth": "public"},
                    {"name": "categories", "route": "/api/categories", "methods": ["list"], "entity": "Category", "frontend": True, "auth": "public"},
                    {"name": "comments", "route": "/api/comments", "methods": ["list", "create"], "entity": "Comment", "frontend": True, "auth": "public"},
                ],
            }
        )

        files = {item["path"]: item for item in compile_file_blueprint(spec)}

        assert "src/components/PostCard.tsx" in files
        assert "src/components/CategoryList.tsx" in files
        assert "src/components/CommentSection.tsx" in files

        home_depends = set(files["src/pages/Home.tsx"]["depends_on"])
        category_depends = set(files["src/pages/CategoryArchive.tsx"]["depends_on"])
        post_detail_depends = set(files["src/pages/PostDetail.tsx"]["depends_on"])

        assert "src/components/PostCard.tsx" in home_depends
        assert "src/components/CategoryList.tsx" in home_depends
        assert "src/components/PostCard.tsx" in category_depends
        assert "src/components/CategoryList.tsx" in category_depends
        assert "src/components/CommentSection.tsx" in post_detail_depends

    def test_blueprint_exports_match_compiler_owned_auth_and_service_contracts(self):
        spec = ProjectSpec.from_dict(
            {
                "product_type": "blog",
                "app_kind": "blog",
                "features": ["Auth", "Blog"],
                "pages": [{"name": "Home", "route": "/", "purpose": "Primary page", "auth": "public"}],
                "auth": {"enabled": True, "allow_registration": True},
                "api_resources": [
                    {"name": "posts", "route": "/api/posts", "methods": ["list"], "entity": "Post", "frontend": True, "auth": "public"}
                ],
            }
        )

        files = {item["path"]: item for item in compile_file_blueprint(spec)}

        type_exports = set(files["src/types/index.ts"]["exports"])
        assert {"User", "AuthResponse", "LoginCredentials", "RegisterCredentials"} <= type_exports
        assert "LoginPayload" not in type_exports

        assert set(files["server/utils/jwt.ts"]["exports"]) == {"generateToken", "verifyToken"}
        assert set(files["src/context/AuthContext.tsx"]["exports"]) == {"AuthContext", "AuthProvider", "useAuth"}
        assert set(files["src/services/postService.ts"]["exports"]) == {"default"}

    def test_parse_project_spec_response_aligns_prompt_contract_for_any_site_type(self):
        parsed = parse_project_spec_response(
            """
            {
              "product_type": "website",
              "app_kind": "website",
              "features": ["Auth", "Blog", "Categories"],
              "pages": [
                {"name": "Home", "route": "/", "purpose": "Primary page", "auth": "public"},
                {"name": "Login", "route": "/login", "purpose": "Sign in", "auth": "public"},
                {"name": "Register", "route": "/register", "purpose": "Sign up", "auth": "public"}
              ],
              "auth": {
                "enabled": true,
                "allow_registration": true,
                "identifiers": ["email"]
              },
              "api_resources": [
                {"name": "posts", "route": "/api/posts", "methods": ["list"], "entity": "Post", "frontend": true, "auth": "public"},
                {"name": "categories", "route": "/api/categories", "methods": ["list"], "entity": "Category", "frontend": true, "auth": "public"}
              ]
            }
            """.strip(),
            prompt="Create a restaurant landing page",
            feature_lines=["Landing Page", "Marketing Website"],
        )

        assert parsed.auth.enabled is False
        assert parsed.app_kind == "landing_page"
        assert parsed.product_type == "landing_page"
        assert "Auth" not in parsed.features
        assert all(page.route not in {"/login", "/register"} for page in parsed.pages)
        assert all("login" not in check.lower() and "register" not in check.lower() for check in parsed.acceptance_checks)

    def test_normalize_merges_missing_default_fields_for_known_entities(self):
        spec = ProjectSpec.from_dict(
            {
                "product_type": "blog",
                "app_kind": "blog",
                "features": ["Blog", "Categories"],
                "entities": [
                    {
                        "name": "Post",
                        "fields": [
                            {"name": "title", "required": True},
                            {"name": "slug", "required": True},
                            {"name": "content", "required": True, "type": "text"},
                        ],
                    },
                    {
                        "name": "Category",
                        "fields": [
                            {"name": "name", "required": True},
                            {"name": "slug", "required": True},
                        ],
                    },
                ],
                "api_resources": [
                    {"name": "posts", "route": "/api/posts", "methods": ["list"], "entity": "Post", "frontend": True, "auth": "public"},
                    {"name": "categories", "route": "/api/categories", "methods": ["list"], "entity": "Category", "frontend": True, "auth": "public"},
                ],
            }
        )

        post = next(entity for entity in spec.entities if entity.name == "Post")
        category = next(entity for entity in spec.entities if entity.name == "Category")

        assert any(field.name == "categoryId" for field in post.fields)
        assert any(field.name == "excerpt" for field in post.fields)
        assert any(field.name == "description" for field in category.fields)

    def test_portfolio_blueprint_is_compiler_owned_without_route_service_page_overrides(self):
        spec = ProjectSpec.from_dict(
            {
                "product_type": "portfolio",
                "app_kind": "portfolio",
                "features": ["Portfolio"],
                "pages": [{"name": "Home", "route": "/", "purpose": "Primary portfolio landing", "auth": "public"}],
                "required_files": [
                    "server/routes/projects.ts",
                    "server/models/Project.ts",
                    "src/services/projectService.ts",
                    "src/pages/ProjectDetail.tsx",
                    "src/components/ProjectGrid.tsx",
                    "src/styles/motion.css",
                ],
            }
        )

        files = {item["path"]: item for item in compile_file_blueprint(spec)}

        assert "server/routes/projectRoutes.ts" in files
        assert "server/controllers/projectController.ts" in files
        assert "src/services/projectService.ts" in files
        assert "src/hooks/useProjects.tsx" in files
        assert "src/pages/ProjectDetail.tsx" in files
        assert "src/components/ProjectCard.tsx" in files
        assert "src/components/ProjectGrid.tsx" in files
        assert "src/styles/motion.css" in files

        assert "server/routes/projects.ts" not in files
        assert "server/models/Project.ts" not in files

    def test_portfolio_defaults_add_project_resource_page_and_entity_fields(self):
        spec = ProjectSpec.from_dict(
            {
                "product_type": "portfolio",
                "app_kind": "portfolio",
                "features": ["Portfolio"],
                "pages": [{"name": "Home", "route": "/", "purpose": "Primary portfolio landing", "auth": "public"}],
                "api_resources": [],
                "entities": [],
            }
        )

        project_resource = next((resource for resource in spec.api_resources if resource.name == "projects"), None)
        project_entity = next((entity for entity in spec.entities if entity.name == "Project"), None)

        assert project_resource is not None
        assert project_resource.route == "/api/projects"
        assert set(project_resource.methods) == {"list", "detail"}
        assert any(page.route == "/projects/:id" for page in spec.pages)
        assert project_entity is not None
        assert any(field.name == "slug" for field in project_entity.fields)
        assert any(field.name == "imageUrl" for field in project_entity.fields)


class TestFeatureValidatorContractChecks:
    def test_feature_validator_flags_missing_semantic_css_class_definitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(
                "src/pages/Home.tsx",
                (
                    "export default function Home() {\n"
                    "  return (\n"
                    "    <section className=\"hero-section project-grid-section contact-actions\">\n"
                    "      <div className=\"hero-content section-title project-card contact-button\">Hello</div>\n"
                    "    </section>\n"
                    "  );\n"
                    "}\n"
                ),
                tmp,
            )
            _write(
                "src/styles/global.css",
                ".container { max-width: 1200px; }\n.section-title { font-size: 2rem; }\n",
                tmp,
            )

            validator = FeatureValidator(tmp)
            errors = validator._check_frontend_styling_contract()

            assert any("STYLESHEET_CLASS_MISSING" in error for error in errors), errors

    def test_validate_frontend_phase_flags_basic_homepage_design_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = ProjectSpec.from_dict(
                {
                    "product_type": "website",
                    "app_kind": "website",
                    "features": ["Core"],
                    "pages": [{"name": "Home", "route": "/", "purpose": "Primary page", "auth": "public"}],
                    "api_resources": [],
                }
            )

            _write(
                "src/App.tsx",
                (
                    "import { Routes, Route } from 'react-router-dom';\n"
                    "import Home from './pages/Home';\n"
                    "export default function App() {\n"
                    "  return <Routes><Route path=\"/\" element={<Home />} /></Routes>;\n"
                    "}\n"
                ),
                tmp,
            )
            _write(
                "src/pages/Home.tsx",
                (
                    "export default function Home() {\n"
                    "  return (\n"
                    "    <section className=\"p-4\">\n"
                    "      <h1>Morning Bloom</h1>\n"
                    "      <p>Welcome.</p>\n"
                    "    </section>\n"
                    "  );\n"
                    "}\n"
                ),
                tmp,
            )

            validator = FeatureValidator(tmp, spec)
            errors = validator.validate_frontend_phase(["src/App.tsx", "src/pages/Home.tsx"], spec)

            assert any("FRONTEND_DESIGN_QUALITY_RESPONSIVE_MISSING" in error for error in errors), errors
            assert any("FRONTEND_DESIGN_QUALITY_VISUAL_DEPTH_MISSING" in error for error in errors), errors
            assert any("FRONTEND_DESIGN_QUALITY_SECTION_RHYTHM_MISSING" in error for error in errors), errors

    def test_validate_frontend_phase_accepts_richer_homepage_design_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = ProjectSpec.from_dict(
                {
                    "product_type": "website",
                    "app_kind": "website",
                    "features": ["Core"],
                    "pages": [{"name": "Home", "route": "/", "purpose": "Primary page", "auth": "public"}],
                    "api_resources": [],
                }
            )

            _write(
                "src/App.tsx",
                (
                    "import { Routes, Route } from 'react-router-dom';\n"
                    "import Home from './pages/Home';\n"
                    "export default function App() {\n"
                    "  return <Routes><Route path=\"/\" element={<Home />} /></Routes>;\n"
                    "}\n"
                ),
                tmp,
            )
            _write(
                "src/pages/Home.tsx",
                (
                    "export default function Home() {\n"
                    "  return (\n"
                    "    <div className=\"bg-amber-50 text-slate-900\">\n"
                    "      <section className=\"bg-gradient-to-br from-amber-100 to-white px-6 py-14 md:px-12 lg:py-20 rounded-3xl shadow-xl\">\n"
                    "        <h1 className=\"text-4xl md:text-5xl font-bold\">Morning Bloom</h1>\n"
                    "      </section>\n"
                    "      <section className=\"mt-8 grid gap-6 md:grid-cols-2\">\n"
                    "        <article className=\"bg-white border border-amber-200 rounded-2xl p-6 shadow-md\">Menu</article>\n"
                    "        <article className=\"bg-white border border-amber-200 rounded-2xl p-6 shadow-md\">About</article>\n"
                    "      </section>\n"
                    "    </div>\n"
                    "  );\n"
                    "}\n"
                ),
                tmp,
            )

            validator = FeatureValidator(tmp, spec)
            errors = validator.validate_frontend_phase(["src/App.tsx", "src/pages/Home.tsx"], spec)

            assert not any("FRONTEND_DESIGN_QUALITY_" in error for error in errors), errors

    def test_prewrite_normalizer_preserves_generated_types_file_content(self):
        spec = ProjectSpec.from_dict(
            {
                "product_type": "blog",
                "app_kind": "blog",
                "features": ["Blog", "Categories"],
                "pages": [{"name": "Home", "route": "/", "purpose": "Primary page", "auth": "public"}],
                "api_resources": [
                    {"name": "posts", "route": "/api/posts", "methods": ["list", "detail"], "entity": "Post", "frontend": True, "auth": "public"},
                    {"name": "categories", "route": "/api/categories", "methods": ["list"], "entity": "Category", "frontend": True, "auth": "public"},
                ],
            }
        )

        planner = ExecutionPlanner()
        planner.load_contract(spec)

        loop = AgentLoop.__new__(AgentLoop)
        loop.planner = planner

        normalized_files, notes = loop._normalize_generated_batch_payload(
            [
                {
                    "path": "src/types/index.ts",
                    "content": "export interface Post { id: string; created_at: string; category_id: string; }\n",
                }
            ]
        )

        assert normalized_files[0]["content"] == "export interface Post { id: string; createdAt: string; categoryId: string; }\n"
        assert any("created_at -> createdAt" in note for note in notes)
        assert any("category_id -> categoryId" in note for note in notes)

    def test_prewrite_normalizer_sanitizes_ui_style_jsx_and_public_field_names(self):
        planner = ExecutionPlanner()
        planner.project_spec = ProjectSpec.from_dict(
            {
                "product_type": "blog",
                "app_kind": "blog",
                "features": ["Blog"],
                "pages": [{"name": "Home", "route": "/", "purpose": "Primary page", "auth": "public"}],
                "api_resources": [],
            }
        )

        loop = AgentLoop.__new__(AgentLoop)
        loop.planner = planner

        normalized_files, _notes = loop._normalize_generated_batch_payload(
            [
                {
                    "path": "src/components/Footer.tsx",
                    "content": (
                        "export default function Footer() {\n"
                        "  return <><span>{post.created_at}</span><span>{post.category_name}</span><style jsx>{``}</style></>;\n"
                        "}\n"
                    ),
                }
            ]
        )

        normalized_content = normalized_files[0]["content"]
        assert "<style jsx>" not in normalized_content
        assert "<style>" in normalized_content
        assert "createdAt" in normalized_content
        assert "categoryName" in normalized_content

    def test_prewrite_normalizer_strips_markdown_fences_and_file_headers(self):
        planner = ExecutionPlanner()
        planner.project_spec = ProjectSpec.from_dict(
            {
                "product_type": "blog",
                "app_kind": "blog",
                "features": ["Blog"],
                "pages": [{"name": "Home", "route": "/", "purpose": "Primary page", "auth": "public"}],
                "api_resources": [],
            }
        )

        loop = AgentLoop.__new__(AgentLoop)
        loop.planner = planner

        normalized_files, notes = loop._normalize_generated_batch_payload(
            [
                {
                    "path": "src/App.tsx",
                    "content": (
                        "```tsx\n"
                        "// FILE: src/App.tsx\n"
                        "export default function App() {\n"
                        "  return <div>Hello</div>;\n"
                        "}\n"
                        "```\n"
                    ),
                }
            ]
        )

        normalized_content = normalized_files[0]["content"]
        assert normalized_content == (
            "export default function App() {\n"
            "  return <div>Hello</div>;\n"
            "}\n"
        )
        assert any("markdown fence" in note for note in notes), notes
        assert any("FILE header artifact" in note for note in notes), notes

    def test_validate_response_keeps_valid_peer_when_one_file_is_syntax_broken(self):
        loop = AgentLoop.__new__(AgentLoop)
        loop.planner = ExecutionPlanner()
        loop.sandbox_dir = ""

        ok, error, calls = loop._validate_response(
            [
                {
                    "tool": "write_file",
                    "params": {
                        "path": "src/App.tsx",
                        "content": (
                            "```tsx\n"
                            "// FILE: src/App.tsx\n"
                            "export default function App() {\n"
                            "  return <div>Hello</div>;\n"
                            "}\n"
                            "```\n"
                        ),
                    },
                },
                {
                    "tool": "write_file",
                    "params": {
                        "path": "src/pages/Home.tsx",
                        "content": (
                            "export default function Home() {\n"
                            "  return (\n"
                            "    <section>\n"
                        ),
                    },
                },
            ],
            ["src/App.tsx", "src/pages/Home.tsx"],
        )

        assert ok is True
        assert error == ""
        write_paths = [call["params"]["path"] for call in calls if call["tool"] == "write_file"]
        assert write_paths == ["src/App.tsx"]
        assert calls[0]["params"]["content"].startswith("export default function App()")

    def test_commit_write_calls_rejects_residual_syntax_errors_before_writing(self):
        class RecordingToolRegistry:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict]] = []

            async def execute(self, tool_name: str, params: dict) -> str:
                self.calls.append((tool_name, params))
                return json.dumps({"status": "ok", "written": [item["path"] for item in params.get("files", [])]})

        loop = AgentLoop.__new__(AgentLoop)
        loop.planner = ExecutionPlanner()
        loop.pipeline_config = {}
        loop.feature_validator_enabled = False
        loop.tool_registry = RecordingToolRegistry()
        loop.sandbox_dir = ""

        ok, message, written = asyncio.run(
            loop._commit_write_calls(
                [
                    {
                        "tool": "write_file",
                        "params": {
                            "path": "src/pages/Home.tsx",
                            "content": (
                                "export default function Home() {\n"
                                "  return (\n"
                                "    <section>\n"
                            ),
                        },
                    }
                ],
                allowed_paths=["src/pages/Home.tsx"],
            )
        )

        assert ok is False
        assert "pre-write syntax validation failed" in message
        assert written == []
        assert loop.tool_registry.calls == []

    def test_determine_retry_batch_uses_exact_missing_files_for_partial_response(self):
        loop = AgentLoop.__new__(AgentLoop)
        loop.planner = ExecutionPlanner()
        loop.pipeline_config = {"builder_single_batch_mode": False}

        retry = loop._determine_retry_batch(
            "Partial batch response. Missing files: src/pages/Home.tsx, src/pages/PostDetail.tsx",
            ["src/services/api.ts", "src/pages/Home.tsx", "src/pages/PostDetail.tsx"],
        )

        assert retry == ["src/pages/Home.tsx", "src/pages/PostDetail.tsx"]

    def test_augment_batch_with_runtime_scaffold_adds_tailwind_files_for_frontend_batch(self):
        spec = ProjectSpec.from_dict(
            {
                "product_type": "website",
                "app_kind": "website",
                "features": ["Core"],
                "pages": [{"name": "Home", "route": "/", "purpose": "Primary page", "auth": "public"}],
                "api_resources": [],
            }
        )

        planner = ExecutionPlanner()
        planner.load_contract(spec)

        loop = AgentLoop.__new__(AgentLoop)
        loop.planner = planner
        loop.feature_validator = type(
            "FeatureValidatorStub",
            (),
            {"_project_has_tailwind_runtime": lambda self: False},
        )()

        augmented = loop._augment_batch_with_runtime_scaffold(
            ["src/pages/Home.tsx", "src/components/Hero.tsx"],
            batch_cap=20,
        )

        assert "package.json" in augmented
        assert "tailwind.config.js" in augmented
        assert "postcss.config.js" in augmented

    def test_augment_batch_with_runtime_scaffold_keeps_batch_when_runtime_already_ready(self):
        spec = ProjectSpec.from_dict(
            {
                "product_type": "website",
                "app_kind": "website",
                "features": ["Core"],
                "pages": [{"name": "Home", "route": "/", "purpose": "Primary page", "auth": "public"}],
                "api_resources": [],
            }
        )

        planner = ExecutionPlanner()
        planner.load_contract(spec)

        loop = AgentLoop.__new__(AgentLoop)
        loop.planner = planner
        loop.feature_validator = type(
            "FeatureValidatorStub",
            (),
            {"_project_has_tailwind_runtime": lambda self: True},
        )()

        original = ["src/pages/Home.tsx", "src/components/Hero.tsx"]
        augmented = loop._augment_batch_with_runtime_scaffold(
            original,
            batch_cap=20,
        )

        assert augmented == original

    def test_pre_write_style_gate_allows_tailwind_utilities_when_runtime_scaffold_is_in_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop = AgentLoop.__new__(AgentLoop)
            loop.feature_validator_enabled = True
            loop.feature_validator = FeatureValidator(tmp)

            files_to_write = [
                {
                    "path": "src/components/Hero.tsx",
                    "content": (
                        "export default function Hero() {\n"
                        "  return <section className=\"bg-amber-600 text-white px-8 py-6 rounded-xl flex items-center justify-between shadow-lg\">Hi</section>;\n"
                        "}\n"
                    ),
                }
            ]

            blocked = loop._validate_pre_write_style_gate(
                files_to_write,
                target_paths=["src/components/Hero.tsx"],
            )
            assert any("TAILWIND_RUNTIME_MISSING" in err for err in blocked), blocked

            allowed = loop._validate_pre_write_style_gate(
                files_to_write,
                target_paths=[
                    "src/components/Hero.tsx",
                    "package.json",
                    "tailwind.config.js",
                    "postcss.config.js",
                ],
            )
            assert allowed == [], allowed

    def test_partial_batch_response_keeps_valid_files(self):
        loop = AgentLoop.__new__(AgentLoop)
        ok, error, _calls = loop._validate_response(
            [
                {
                    "tool": "write_file",
                    "params": {
                        "path": "src/App.tsx",
                        "content": "export default function App() {\n  return <div>Hello</div>;\n}\n",
                    },
                }
            ],
            ["src/App.tsx", "src/pages/Home.tsx"],
        )

        assert ok is True
        assert error == ""

    def test_validate_response_flags_malformed_json_payload_before_partial_recovery(self):
        loop = AgentLoop.__new__(AgentLoop)
        loop.planner = ExecutionPlanner()
        loop.sandbox_dir = ""

        ok, error, _calls = loop._validate_response(
            [],
            ["package.json", "tailwind.config.js"],
            raw_response=(
                '{"files":[{"path":"package.json","content":"{}","path":"tailwind.config.js","content":"export default {}"}],'
                '"commands":[]}'
            ),
        )

        assert ok is False
        assert "Malformed JSON generation payload detected" in error

    def test_recover_partial_stream_response_keeps_completed_files(self):
        loop = AgentLoop.__new__(AgentLoop)
        loop.model_id = "test-model"

        recovered, calls, notice = loop._recover_partial_stream_response(
            """
### FILE: src/App.tsx
```tsx
export default function App() {
  return <div>Hello</div>;
}
```

### FILE: src/pages/Home.tsx
```tsx
export default function Home() {
  return (
""".strip(),
            ["src/App.tsx", "src/pages/Home.tsx"],
            parser_model_id="test-model",
        )

        assert recovered is True
        assert [call["params"]["path"] for call in calls if call["tool"] == "write_file"] == ["src/App.tsx"]
        assert "continuing with the missing tail only" in notice

    def test_save_resume_state_persists_retry_batch_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop = AgentLoop.__new__(AgentLoop)
            loop.sandbox_dir = tmp
            loop.planner = ExecutionPlanner()
            loop.triage_cache = {}
            loop.validation_repair_state = {}
            loop.generation_retry_state = {
                "sig-1": {
                    "count": 2,
                    "kind": "batch_write",
                    "batch": ["src/types/index.ts"],
                    "retry": ["src/types/index.ts"],
                    "error_preview": ["Error: blueprint execution validation failed"],
                }
            }
            loop.retry_batch_override = [
                "src/types/index.ts",
                "src/services/postService.ts",
            ]

            loop._save_resume_state(original_prompt="demo", iteration=4)
            restored = loop._load_resume_state()

            assert restored["retry_batch_override"] == [
                "src/types/index.ts",
                "src/services/postService.ts",
            ]
            assert restored["generation_retry_state"]["sig-1"]["count"] == 2

    def test_provider_retry_policy_uses_shorter_defaults(self):
        loop = AgentLoop.__new__(AgentLoop)
        loop.pipeline_config = {}

        retries, backoff = loop._provider_retry_policy()

        assert retries == 3
        assert backoff[:3] == [3, 8, 15]

    def test_generation_failure_limit_trips_on_repeated_same_signature(self):
        loop = AgentLoop.__new__(AgentLoop)
        loop.pipeline_config = {}
        loop.generation_retry_state = {}

        first = loop._record_generation_failure(
            "batch_write",
            ["src/types/index.ts", "src/pages/Home.tsx"],
            "Error: blueprint execution validation failed",
            ["src/types/index.ts", "src/pages/Home.tsx"],
        )
        second = loop._record_generation_failure(
            "batch_write",
            ["src/types/index.ts", "src/pages/Home.tsx"],
            "Error: blueprint execution validation failed",
            ["src/types/index.ts", "src/pages/Home.tsx"],
        )
        third = loop._record_generation_failure(
            "batch_write",
            ["src/types/index.ts", "src/pages/Home.tsx"],
            "Error: blueprint execution validation failed",
            ["src/types/index.ts", "src/pages/Home.tsx"],
        )

        assert first[1:] == (1, False)
        assert second[1:] == (2, False)
        assert third[1:] == (3, True)

    def test_determine_retry_batch_shrinks_blueprint_retry_to_failing_subset(self):
        spec = ProjectSpec.from_dict(
            {
                "product_type": "blog",
                "app_kind": "blog",
                "features": ["Blog", "Categories"],
                "pages": [
                    {"name": "Home", "route": "/", "purpose": "Primary page", "auth": "public"},
                    {"name": "CategoryArchive", "route": "/category/:slug", "purpose": "Category page", "auth": "public"},
                    {"name": "PostDetail", "route": "/post/:slug", "purpose": "Post page", "auth": "public"},
                ],
                "api_resources": [
                    {"name": "posts", "route": "/api/posts", "methods": ["list", "detail"], "entity": "Post", "frontend": True, "auth": "public"},
                    {"name": "categories", "route": "/api/categories", "methods": ["list"], "entity": "Category", "frontend": True, "auth": "public"},
                ],
            }
        )

        planner = ExecutionPlanner()
        planner.load_contract(spec)

        loop = AgentLoop.__new__(AgentLoop)
        loop.planner = planner
        loop.pipeline_config = {"builder_single_batch_mode": False}

        current_batch = [
            "src/services/api.ts",
            "src/types/index.ts",
            "src/services/postService.ts",
            "src/hooks/usePosts.tsx",
            "src/components/PostCard.tsx",
            "src/services/categoryService.ts",
            "src/hooks/useCategories.tsx",
            "src/components/CategoryList.tsx",
            "src/pages/Home.tsx",
            "src/pages/CategoryArchive.tsx",
            "src/pages/PostDetail.tsx",
        ]

        retry = loop._determine_retry_batch(
            "\n".join(
                [
                    "Error: blueprint execution validation failed",
                    "- src/types/index.ts: BLUEPRINT_NOT_ENFORCED: IMPORT_SITE_ERROR: Type 'Post' declares fields ['category'] that are outside the blueprint contract.",
                    "- src/services/postService.ts: BLUEPRINT_NOT_ENFORCED: BLUEPRINT_EXPORT_MISMATCH: Unexpected export 'postService' is outside the blueprint contract.",
                    "- src/services/categoryService.ts: BLUEPRINT_NOT_ENFORCED: BLUEPRINT_EXPORT_MISMATCH: Unexpected export 'categoryService' is outside the blueprint contract.",
                ]
            ),
            current_batch,
        )

        assert "src/services/postService.ts" in retry
        assert "src/services/categoryService.ts" in retry
        assert "src/types/index.ts" in retry
        assert "src/pages/Home.tsx" not in retry

    def test_determine_retry_batch_keeps_full_pending_set_in_single_batch_mode(self):
        spec = ProjectSpec.from_dict(
            {
                "product_type": "website",
                "app_kind": "website",
                "features": ["Core"],
                "pages": [{"name": "Home", "route": "/", "purpose": "Primary page", "auth": "public"}],
                "api_resources": [
                    {
                        "name": "products",
                        "route": "/api/products",
                        "methods": ["list"],
                        "entity": "Product",
                        "frontend": True,
                        "auth": "public",
                    }
                ],
            }
        )

        planner = ExecutionPlanner()
        planner.load_contract(spec)
        planner.mark_done("package.json")

        loop = AgentLoop.__new__(AgentLoop)
        loop.planner = planner
        loop.pipeline_config = {"builder_single_batch_mode": True}

        retry = loop._determine_retry_batch(
            "Error: backend phase gate failed for server/index.ts",
            ["server/index.ts"],
        )

        expected_pending = [
            task.path
            for task in planner.tasks
            if not task.is_done
        ]
        assert retry == expected_pending

    def test_scaffold_phase_only_checks_targeted_scaffold_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write("package.json", '{"name":"demo"}\n', tmp)
            _write(
                "vite.config.ts",
                """import { defineConfig } from 'vite';
export default defineConfig({
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:3001',
        changeOrigin: true,
      },
    },
  },
  preview: {
    proxy: {
      '/api': {
        target: 'http://localhost:3001',
        changeOrigin: true,
      },
    },
  },
});
""",
                tmp,
            )

            fv = FeatureValidator(tmp)
            errors = fv.validate_scaffold_phase(
                target_paths=["package.json", "vite.config.ts"],
            )

            assert errors == [], errors

    def test_detects_api_response_envelope_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(
                "src/services/postService.ts",
                """
import api from './api';

export const list = async () => {
  const { data } = await api.get<Post[]>('/posts');
  return data;
};
""".strip(),
                tmp,
            )
            _write(
                "server/controllers/postController.ts",
                """
exports.list = async (_req, res) => {
  const posts = [];
  return res.json({ success: true, data: posts, count: posts.length });
};
""".strip(),
                tmp,
            )

            spec = ProjectSpec.from_dict(
                {
                    "product_type": "blog",
                    "app_kind": "blog",
                    "features": ["Blog"],
                    "pages": [{"name": "Home", "route": "/", "purpose": "Primary page", "auth": "public"}],
                    "api_resources": [
                        {"name": "posts", "route": "/api/posts", "methods": ["list"], "entity": "Post", "frontend": True, "auth": "public"}
                    ],
                }
            )
            fv = FeatureValidator(tmp, spec)

            errors = fv._check_api_response_envelope_contract()

            assert any("API_RESPONSE_ENVELOPE_MISMATCH" in err for err in errors), errors
            assert any("src/services/postService.ts" in err for err in errors), errors
            assert any("server/controllers/postController.ts" in err for err in errors), errors

    def test_detects_tailwind_utilities_without_tailwind_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(
                "package.json",
                json.dumps({"name": "demo", "dependencies": {}, "devDependencies": {}}, indent=2),
                tmp,
            )
            _write(
                "src/pages/Landing.tsx",
                """
export default function Landing() {
  return (
    <main className="min-h-screen bg-white px-4 py-12 md:px-8 max-w-7xl mx-auto text-gray-600 rounded-xl shadow-lg">
      <section className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <div className="bg-red-50 p-6 rounded-xl">Hello</div>
      </section>
    </main>
  );
}
""".strip(),
                tmp,
            )

            fv = FeatureValidator(tmp)
            errors = fv._check_frontend_styling_contract()

            assert any("TAILWIND_RUNTIME_MISSING" in err for err in errors), errors

    def test_allows_tailwind_utilities_when_tailwind_is_declared(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(
                "package.json",
                json.dumps(
                    {
                        "name": "demo",
                        "dependencies": {},
                        "devDependencies": {"tailwindcss": "^3.4.0"},
                    },
                    indent=2,
                ),
                tmp,
            )
            _write(
                "src/pages/Landing.tsx",
                """
export default function Landing() {
  return <main className="min-h-screen bg-white px-4 py-12 md:px-8 max-w-7xl mx-auto text-gray-600 rounded-xl shadow-lg">Hello</main>;
}
""".strip(),
                tmp,
            )

            fv = FeatureValidator(tmp)

            assert fv._check_frontend_styling_contract() == []

    def test_blueprint_execution_gate_rejects_schema_symbol_and_envelope_drift(self):
        spec = ProjectSpec.from_dict(
            {
                "product_type": "blog",
                "app_kind": "blog",
                "features": ["Blog"],
                "pages": [{"name": "Home", "route": "/", "purpose": "Primary page", "auth": "public"}],
                "api_resources": [
                    {"name": "posts", "route": "/api/posts", "methods": ["list", "create"], "entity": "Post", "frontend": True, "auth": "public"}
                ],
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            fv = FeatureValidator(tmp, spec)
            errors = fv.validate_blueprint_execution_batch(
                {
                    "server/controllers/postController.ts": """
const db = require('../db/database');

exports.create = (_req, res) => {
  db.prepare('INSERT INTO posts (title, tags) VALUES (?, ?)').run('hello', 'news');
  return res.json({ success: true, data: { id: 1, title: 'hello' } });
};
""".strip(),
                    "src/types/index.ts": """
export interface Post {
  id: number;
  title: string;
  tags?: string[];
}
""".strip(),
                    "src/services/postService.ts": """
import api from './api';
import type { CreateMessageData, Post } from '../types';

const service = {
  list: async (): Promise<Post[]> => {
    const response = await api.get<Post[]>('/posts');
    return response.data.data;
  },
};

export default service;
""".strip(),
                },
                target_paths=[
                    "server/controllers/postController.ts",
                    "src/types/index.ts",
                    "src/services/postService.ts",
                ],
            )

            assert any("BLUEPRINT_NOT_ENFORCED" in err for err in errors), errors
            assert any("SCHEMA_SYNC_ERROR" in err and "tags" in err for err in errors), errors
            assert any("IMPORT_SITE_ERROR" in err and "CreateMessageData" in err for err in errors), errors
            assert any("API_RESPONSE_ENVELOPE_MISMATCH" in err for err in errors), errors

    def test_full_stack_suppresses_style_fixes_when_contract_breaks_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = ProjectSpec.from_dict(
                {
                    "product_type": "blog",
                    "app_kind": "blog",
                    "features": ["Blog"],
                    "pages": [{"name": "Home", "route": "/", "purpose": "Primary page", "auth": "public"}],
                    "api_resources": [
                        {"name": "posts", "route": "/api/posts", "methods": ["list"], "entity": "Post", "frontend": True, "auth": "public"}
                    ],
                }
            )

            _write(
                "package.json",
                json.dumps({"name": "demo", "dependencies": {}, "devDependencies": {}}, indent=2),
                tmp,
            )
            _write(
                "server/db/database.ts",
                """
const Database = require('better-sqlite3');
const db = new Database(':memory:');
db.exec(`
  CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    slug TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  );
`);
module.exports = db;
""".strip(),
                tmp,
            )
            _write(
                "server/controllers/postController.ts",
                """
const db = require('../db/database');

exports.list = (_req, res) => {
  const rows = db.prepare('SELECT id, title, slug, content FROM posts').all();
  return res.json({ success: true, data: rows });
};
""".strip(),
                tmp,
            )
            _write(
                "src/services/postService.ts",
                """
import api from './api';

const service = {
  list: async () => {
    const response = await api.get('/posts');
    return response.data;
  },
};

export default service;
""".strip(),
                tmp,
            )
            _write(
                "src/pages/Home.tsx",
                """
export default function Home() {
  return (
    <main className="min-h-screen bg-white px-4 py-12 md:px-8 max-w-7xl mx-auto text-gray-600 rounded-xl shadow-lg">
      Hello
    </main>
  );
}
""".strip(),
                tmp,
            )

            fv = FeatureValidator(tmp, spec)
            errors = fv.validate_full_stack(spec)

            assert errors, errors
            assert not any("TAILWIND_RUNTIME_MISSING" in err for err in errors), errors

    def test_symbol_validator_does_not_attach_external_imports_to_next_local_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(
                "src/App.tsx",
                """
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Home from './pages/Home'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
""".strip(),
                tmp,
            )
            _write(
                "src/pages/Home.tsx",
                """
export default function Home() {
  return <main>Home</main>;
}
""".strip(),
                tmp,
            )

            fv = FeatureValidator(tmp)
            errors = fv._check_frontend_symbol_contracts()

            assert errors == [], errors
