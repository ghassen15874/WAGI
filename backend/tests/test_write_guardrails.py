import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kilo.agents.unified_self_healing import UnifiedSelfHealing
from kilo.shared.write_guard import normalize_generated_file_content
from kilo.tools.registry import ToolRegistry


class _DummyErrorAnalyzer:
    def analyze(self, *_args, **_kwargs):
        return {"type": "UNKNOWN", "fix": "", "severity": "MEDIUM"}


class _DummyContextBuilder:
    def build_context(self) -> str:
        return ""


class _DummyProvider:
    async def stream(self, *_args, **_kwargs):
        if False:
            yield ""


class _StreamingProvider:
    def __init__(self, response: str):
        self.response = response

    async def stream(self, *_args, **_kwargs):
        yield self.response


class _DecisionEngineStub:
    def __init__(self, decision: dict):
        self.decision = decision

    async def decide(self, *_args, **_kwargs):
        return dict(self.decision)


async def _collect(async_iterable):
    items = []
    async for item in async_iterable:
        items.append(item)
    return items


class TestWriteGuardrails:
    def test_write_guard_adds_lucide_react_to_frontend_package_json(self):
        normalized_content, notes = normalize_generated_file_content(
            "package.json",
            json.dumps(
                {
                    "name": "generated-frontend",
                    "scripts": {
                        "dev": "vite",
                        "build": "vite build",
                    },
                    "dependencies": {
                        "react": "^18.2.0",
                        "react-dom": "^18.2.0",
                    },
                }
            ),
        )

        package_data = json.loads(normalized_content)

        assert package_data["dependencies"]["lucide-react"] == "^0.344.0"
        assert any("added lucide-react dependency" in note for note in notes)

    def test_write_guard_backfills_mandatory_variables_css_tokens(self):
        normalized_content, notes = normalize_generated_file_content(
            "src/styles/variables.css",
            """
:root {
  --color-background: #ffffff;
  --color-foreground: #111827;
}
""".strip(),
        )

        for token in ("--background", "--foreground", "--card", "--card-foreground", "--border"):
            assert token in normalized_content
        assert any("inserted missing mandatory design tokens" in note for note in notes)

    def test_write_guard_converts_sqlite_boolean_bind_values_in_server_seed_data(self):
        normalized_content, notes = normalize_generated_file_content(
            "server/db/database.ts",
            """
const rows = [
  { featured: true, published: false, active: true, enabled: false, is_admin: true, verified: false }
];
""".strip(),
        )

        assert "featured: 1" in normalized_content
        assert "published: 0" in normalized_content
        assert "active: 1" in normalized_content
        assert "enabled: 0" in normalized_content
        assert "is_admin: 1" in normalized_content
        assert "verified: 0" in normalized_content
        assert all(token not in normalized_content for token in ("featured: true", "published: false"))
        assert any("converted boolean bind values to integers" in note for note in notes)

    def test_write_guard_corrects_jsx_import_extensions_to_tsx(self):
        normalized_content, notes = normalize_generated_file_content(
            "src/pages/Home.tsx",
            """
import Hero from '../components/Hero.jsx';
const LazyCard = import('../components/ProductCard.jsx');
""".strip(),
        )

        assert "../components/Hero.tsx" in normalized_content
        assert "../components/ProductCard.tsx" in normalized_content
        assert ".jsx" not in normalized_content
        assert any("corrected .jsx import extensions to .tsx" in note for note in notes)

    def test_tool_registry_rejects_malformed_multi_path_batch_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ToolRegistry(base_dir=tmp)
            result = asyncio.run(
                registry.execute(
                    "write_batch",
                    {
                        "files": [
                            {
                                "path": "src/main.tsx,src/App.tsx",
                                "content": "export default function App() { return null; }",
                            }
                        ]
                    },
                )
            )

            assert "Unsafe or malformed generated file path" in result

    def test_tool_registry_blocks_killing_reserved_ports(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ToolRegistry(base_dir=tmp)
            result = asyncio.run(
                registry.execute(
                    "execute_command",
                    {"command": "fuser -k 5173/tcp 8080/tcp 2>/dev/null || true", "timeout": 5},
                )
            )
            assert "Command blocked by safety policy" in result
            assert "8080" in result and "5173" in result

    def test_unified_repair_rejects_syntax_invalid_repair_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ToolRegistry(base_dir=tmp)
            repair = UnifiedSelfHealing(
                tmp,
                _DummyProvider(),
                registry,
                _DummyErrorAnalyzer(),
                _DummyContextBuilder(),
                "test-model",
            )

            written_paths, executed, messages = asyncio.run(
                repair._apply_parsed_calls(
                    [
                        {
                            "tool": "write_file",
                            "params": {
                                "path": "src/styles/global.css",
                                "content": "// FILE: src/styles/global.css\n```css\nbody {\n",
                            },
                        }
                    ]
                )
            )

            assert written_paths == []
            assert executed == 0
            assert any("Rejected syntax-invalid repair file src/styles/global.css" in message for message in messages)
            assert not os.path.exists(os.path.join(tmp, "src/styles/global.css"))

    def test_unified_repair_maps_expected_files_for_ui_style_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ToolRegistry(base_dir=tmp)
            repair = UnifiedSelfHealing(
                tmp,
                _StreamingProvider(
                    """
Code Blocktypescript

import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';

createRoot(document.getElementById('root')!).render(<App />);

Code Blocktypescript

export default function App() {
  return <main>Hello</main>;
}
""".strip()
                ),
                registry,
                _DummyErrorAnalyzer(),
                _DummyContextBuilder(),
                "deepseek-reasoner",
            )

            messages = asyncio.run(
                _collect(
                    repair._fix_syntax_error(
                        tmp,
                        "src/main.tsx, src/App.tsx",
                        "Repair the root app wiring.",
                        1,
                    )
                )
            )

            with open(os.path.join(tmp, "src/main.tsx"), "r", encoding="utf-8") as handle:
                main_content = handle.read()
            with open(os.path.join(tmp, "src/App.tsx"), "r", encoding="utf-8") as handle:
                app_content = handle.read()

            assert "createRoot" in main_content
            assert "render(<App />)" in main_content
            assert "export default function App()" in app_content
            assert any("📁 Fixed: src/main.tsx" in message for message in messages)
            assert any("📁 Fixed: src/App.tsx" in message for message in messages)

    def test_unified_repair_rejects_writes_outside_authorized_repair_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ToolRegistry(base_dir=tmp)
            repair = UnifiedSelfHealing(
                tmp,
                _StreamingProvider(
                    """
```json
// FILE: package.json
{
  "name": "unexpected-file"
}
```
""".strip()
                ),
                registry,
                _DummyErrorAnalyzer(),
                _DummyContextBuilder(),
                "test-model",
            )

            messages = asyncio.run(
                _collect(
                    repair._fix_syntax_error(
                        tmp,
                        "src/App.tsx",
                        "Only App.tsx is in scope for this repair.",
                        1,
                    )
                )
            )

            assert not os.path.exists(os.path.join(tmp, "package.json"))
            assert any("Unexpected file outside current batch: package.json" in message for message in messages)

    def test_build_repair_uses_full_owner_scope_for_multi_file_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ToolRegistry(base_dir=tmp)
            repair = UnifiedSelfHealing(
                tmp,
                _StreamingProvider(
                    """
```tsx
// FILE: src/context/AuthContext.tsx
export const AuthContext = {};
```

```tsx
// FILE: src/pages/Register.tsx
export default function Register() {
  return <div>Register</div>;
}
```
""".strip()
                ),
                registry,
                _DummyErrorAnalyzer(),
                _DummyContextBuilder(),
                "deepseek-reasoner",
            )
            repair.decision_engine = _DecisionEngineStub(
                {
                    "strategy": "fix_type_errors",
                    "fix_hint": "Rewrite the auth registration flow together.",
                    "write_files": "yes",
                    "target_files": ["src/context/AuthContext.tsx"],
                    "root_cause": "Type errors span AuthContext and Register.",
                }
            )
            repair.set_repair_context(
                owner_context="- src/context/AuthContext.tsx\n- src/pages/Register.tsx"
            )

            messages = asyncio.run(
                _collect(
                    repair._auto_fix_build(
                        tmp,
                        "src/context/AuthContext.tsx(3,10): error TS6133: 'AuthResponse' is declared but its value is never read.\n"
                        "src/pages/Register.tsx(20,16): error TS2345: missing confirmPassword in register call.",
                        1,
                    )
                )
            )

            with open(os.path.join(tmp, "src/context/AuthContext.tsx"), "r", encoding="utf-8") as handle:
                auth_context = handle.read()
            with open(os.path.join(tmp, "src/pages/Register.tsx"), "r", encoding="utf-8") as handle:
                register_page = handle.read()

            assert "AuthContext" in auth_context
            assert "Register" in register_page
            assert any(
                "AI decided repair scope: src/context/AuthContext.tsx, src/pages/Register.tsx" in message
                for message in messages
            )
            assert not any("Unexpected file outside current batch" in message for message in messages)

    def test_dependency_install_command_failure_falls_back_to_file_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = ToolRegistry(base_dir=tmp)
            repair = UnifiedSelfHealing(
                tmp,
                _DummyProvider(),
                registry,
                _DummyErrorAnalyzer(),
                _DummyContextBuilder(),
                "test-model",
            )

            decision, command_result, messages = asyncio.run(
                repair._resolve_decision_procedure(
                    {
                        "command": "printf 'npm ERR! Invalid Version:\\n'",
                        "command_kind": "dependency_install",
                        "target_files": ["package.json"],
                        "write_files": "no",
                        "return_query_result": "no",
                    },
                    error_log="package.json: MISSING_DEPENDENCY: lucide-react is missing.",
                )
            )

            assert "Invalid Version" in command_result
            assert decision["command"] is None
            assert decision["command_kind"] == "none"
            assert decision["write_files"] == "yes"
            assert any("Dependency install command failed" in message for message in messages)
