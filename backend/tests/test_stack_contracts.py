import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kilo.agents.codegen.linter import CodeLinter
from kilo.agents.decision_engine import DecisionEngine
from kilo.orchestrator.error_analyzer import ErrorAnalyzer
from kilo.agents.codegen.prompts import (
    build_generation_user_prompt,
    build_stage_system_prompt,
    get_system_prompt,
)
from kilo.orchestrator.feature_validator import FeatureValidator
from kilo.orchestrator.loop import AgentLoop
from kilo.shared.design.engine import DesignEngine


def _write(rel_path: str, content: str, root: str) -> None:
    full_path = os.path.join(root, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as handle:
        handle.write(content)


class TestStackContracts:
    def test_package_json_enforces_single_runtime_and_database_stack(self):
        linter = CodeLinter()
        package_json = json.dumps(
            {
                "name": "demo",
                "type": "module",
                "scripts": {
                    "dev": "vite",
                    "server": "tsx server/index.ts",
                },
                "dependencies": {
                    "axios": "^1.6.2",
                    "better-sqlite3": "^9.4.3",
                    "sqlite3": "^5.1.7",
                },
            },
            indent=2,
        )

        errors = linter.lint_file("package.json", package_json)

        assert any("exactly 'node --import tsx server/index.ts'" in error for error in errors), errors
        assert any('Remove "type": "module"' in error for error in errors), errors
        assert any("better-sqlite3 must be pinned to '^12.2.0'" in error for error in errors), errors
        assert any("Remove 'sqlite3'" in error for error in errors), errors

    def test_linter_rejects_fetch_and_direct_axios_imports_outside_shared_client(self):
        linter = CodeLinter()

        fetch_errors = linter.lint_file(
            "src/pages/Home.tsx",
            "export default async function Home(){ const res = await fetch('/api/projects'); return <div />; }\n",
        )
        axios_errors = linter.lint_file(
            "src/hooks/useProjects.tsx",
            "import axios from 'axios';\nexport function useProjects(){ return axios.get('/api/projects'); }\n",
        )
        api_client_errors = linter.lint_file(
            "src/services/api.ts",
            "export const api = {};\n",
        )

        assert any("Direct fetch() call detected" in error for error in fetch_errors), fetch_errors
        assert any("Direct axios import detected" in error for error in axios_errors), axios_errors
        assert any("must be the shared axios client" in error for error in api_client_errors), api_client_errors

    def test_linter_rejects_unquoted_sql_and_wrong_route_controller_path(self):
        linter = CodeLinter()

        db_errors = linter.lint_file(
            "server/db/database.ts",
            "const db = require('../db/database');\ndb.prepare( INSERT INTO projects (title) VALUES (?) ).run('x');\nmodule.exports = db;\n",
        )
        route_errors = linter.lint_file(
            "server/routes/projectRoutes.ts",
            "const express = require('express');\nconst projectController = require('./projectController');\nmodule.exports = express.Router();\n",
        )

        assert any("must be wrapped in quotes or template literals" in error for error in db_errors), db_errors
        assert any("../controllers/..." in error for error in route_errors), route_errors

    def test_feature_validator_rejects_mixed_http_client_stack(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(
                "src/services/api.ts",
                "import axios from 'axios';\nexport const api = axios.create({ baseURL: '/api' });\nexport default api;\n",
                tmp,
            )
            _write(
                "src/pages/Home.tsx",
                "export default function Home(){ fetch('/api/projects'); return <main />; }\n",
                tmp,
            )

            errors = FeatureValidator(tmp)._check_frontend_http_client_contract()

            assert any("HTTP_CLIENT_MIXED" in error for error in errors), errors
            assert any("Direct fetch() is not allowed" in error for error in errors), errors

    def test_feature_validator_schema_parser_handles_nested_check_parentheses(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(
                "server/db/database.ts",
                (
                    "const Database = require('better-sqlite3');\n"
                    "function initDatabase() {\n"
                    "  const db = new Database('demo.db');\n"
                    "  db.exec(`\n"
                    "    CREATE TABLE IF NOT EXISTS users (\n"
                    "      id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
                    "      email TEXT UNIQUE NOT NULL,\n"
                    "      password TEXT NOT NULL,\n"
                    "      role TEXT CHECK(role IN ('admin', 'manager', 'technician')) DEFAULT 'manager',\n"
                    "      full_name TEXT,\n"
                    "      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n"
                    "    )\n"
                    "  `);\n"
                    "  return db;\n"
                    "}\n"
                    "module.exports = { initDatabase };\n"
                ),
                tmp,
            )
            _write(
                "server/controllers/authController.ts",
                (
                    "function register(req, res) {\n"
                    "  const db = getDatabase();\n"
                    "  db.prepare(`INSERT INTO users (email, password, full_name, role) VALUES (?, ?, ?, ?)`)\n"
                    "    .run(req.body.email, req.body.password, req.body.fullName, req.body.role);\n"
                    "}\n"
                    "module.exports = { register };\n"
                ),
                tmp,
            )

            errors = FeatureValidator(tmp)._check_schema_controller_column_sync()

            assert not any("full_name" in error for error in errors), errors

    def test_system_prompt_contains_single_stack_lock_rules(self):
        design = DesignEngine().generate("Build a portfolio website for a designer")
        prompt = get_system_prompt(design)

        assert "server\": \"node --import tsx server/index.ts\"" in prompt
        assert "better-sqlite3@^12.2.0" in prompt
        assert "src/services/api.ts` is the ONLY frontend file allowed to import `axios` directly" in prompt
        assert "SINGLE-STACK LOCK" in prompt

    def test_architecture_stage_prompt_includes_backend_contract_rules(self):
        design = DesignEngine().generate("Create a blog platform with categories")
        prompt = build_stage_system_prompt(design, "architecture")

        assert "BACKEND STAGE RULES" in prompt
        assert "server/index.ts" in prompt
        assert "CommonJS" in prompt
        assert "better-sqlite3" in prompt

    def test_generation_prompt_includes_package_runtime_contract_for_package_batch(self):
        prompt = build_generation_user_prompt(
            original_prompt="Create a blog platform with categories",
            stage_name="frontend",
            current_batch=["package.json", "vite.config.ts", "tsconfig.json"],
            scoped_blueprint={},
            project_context="",
            project_spec=None,
        )

        assert "PACKAGE RUNTIME CONTRACT (CRITICAL)" in prompt
        assert 'node --import tsx server/index.ts' in prompt
        assert '"type": "module"' in prompt
        assert "better-sqlite3" in prompt

    def test_generation_prompt_includes_frontend_design_quality_floor(self):
        prompt = build_generation_user_prompt(
            original_prompt="Create a coffee shop landing page",
            stage_name="frontend",
            current_batch=["src/pages/Home.tsx", "src/components/Hero.tsx"],
            scoped_blueprint={},
            project_context="",
            project_spec=None,
        )

        assert "FRONTEND DESIGN QUALITY FLOOR (CRITICAL)" in prompt
        assert "responsive Tailwind breakpoints" in prompt
        assert "visually distinct sections" in prompt

    def test_decision_engine_escalates_package_runtime_contract_errors_to_rewrite(self):
        engine = DecisionEngine(error_analyzer=ErrorAnalyzer())

        decision = engine._rule_classify(
            "package.json: Missing 'server' script\n"
            'package.json: Remove "type": "module" — backend server files use CommonJS require()/module.exports\n'
            "package.json: better-sqlite3 must be pinned to '^12.2.0' in dependencies.\n"
        )

        assert decision["strategy"] == "fix_package_runtime_contract"
        assert decision["write_files"] == "yes"
        assert decision["command_kind"] == "none"
        assert "package.json" in decision["target_files"]

    def test_loop_forces_grouped_rewrite_for_package_runtime_contract_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop = AgentLoop.__new__(AgentLoop)
            loop.sandbox_dir = tmp
            loop.repair_service = type(
                "RepairStub",
                (),
                {"extract_blueprint_scope_cluster": lambda self, text: []},
            )()
            loop.planner = type("PlannerStub", (), {"project_spec": None, "get_cluster_for_paths": lambda self, paths: []})()

            rewrite = loop._forced_validation_rewrite_decision(
                "package.json",
                [
                    "package.json: Missing 'server' script",
                    'package.json: Remove "type": "module" — backend server files use CommonJS require()/module.exports',
                    "package.json: better-sqlite3 must be pinned to '^12.2.0' in dependencies.",
                ],
            )

            assert rewrite is not None
            assert rewrite["strategy"] == "fix_package_runtime_contract"
            assert "package.json" in rewrite["target_files"]

    def test_package_json_batch_uses_architecture_stage_when_project_has_backend(self):
        loop = AgentLoop.__new__(AgentLoop)
        loop.planner = type(
            "PlannerStub",
            (),
            {
                "project_spec": type(
                    "SpecStub",
                    (),
                    {
                        "api_resources": [object()],
                        "auth": type("AuthStub", (), {"enabled": False})(),
                    },
                )(),
            },
        )()

        assert loop._generation_stage_for_batch(["package.json", "vite.config.ts"]) == "architecture"

    def test_loop_treats_blueprint_contract_repairs_as_focused_batches(self):
        loop = AgentLoop.__new__(AgentLoop)

        assert loop._uses_focused_validation_targets(
            {"strategy": "fix_api_contract"},
            [
                "src/services/projectService.ts: BLUEPRINT_NOT_ENFORCED: IMPORT_SITE_ERROR: "
                "Imported symbol 'api' is used by src/services/projectService.ts but is not exported."
            ],
        )

    def test_loop_uses_owner_scoped_targets_for_blueprint_contract_repairs(self):
        loop = AgentLoop.__new__(AgentLoop)
        loop.planner = type(
            "PlannerStub",
            (),
            {
                "project_spec": None,
                "get_cluster_for_paths": lambda self, paths: [],
            },
        )()
        loop.repair_service = type(
            "RepairStub",
            (),
            {
                "extract_blueprint_scope_cluster": lambda self, text: [],
                "extract_phase_error_paths": lambda self, errors, fallback_paths: fallback_paths,
            },
        )()

        targets = loop._focused_validation_repair_targets(
            "server/routes/projectRoutes.ts",
            [
                "server/routes/projectRoutes.ts: BLUEPRINT_NOT_ENFORCED: IMPORT_SITE_ERROR: "
                "Route files must require controllers from '../controllers/...', not './...'.",
                "server/controllers/projectController.ts: BLUEPRINT_NOT_ENFORCED: SCHEMA_SYNC_ERROR: "
                "projects.owner_id exists in server/db/database.ts but controller uses user_id.",
                "src/services/projectService.ts: BLUEPRINT_NOT_ENFORCED: IMPORT_SITE_ERROR: "
                "Imported symbol 'api' is used by src/services/projectService.ts but is not exported.",
            ],
            {
                "strategy": "fix_api_contract",
                "target_files": [
                    "server/routes/projectRoutes.ts",
                    "server/controllers/projectController.ts",
                    "src/services/projectService.ts",
                    "src/types/index.ts",
                ],
            },
        )

        assert "server/routes/projectRoutes.ts" in targets
        assert "server/controllers/projectController.ts" in targets
        assert "src/services/projectService.ts" in targets
        assert "src/types/index.ts" in targets
        assert "server/db/database.ts" in targets
