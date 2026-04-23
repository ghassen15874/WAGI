import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kilo.orchestrator.runtime_validator import RuntimeValidator


def _write(rel_path: str, content: str, root: str) -> None:
    full_path = os.path.join(root, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as handle:
        handle.write(content)


class _JSONProvider:
    def __init__(self, payload: str):
        self.payload = payload

    async def stream(self, *_args, **_kwargs):
        yield self.payload


class TestRuntimeValidator:
    def test_landing_page_with_auth_links_does_not_require_inline_auth_form_or_navbar(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write("server/routes/authRoutes.ts", "module.exports = {};\n", tmp)
            validator = RuntimeValidator(tmp, tool_registry=None, provider=_JSONProvider("[]"), model_id="test-model")

            browser_result = {
                "status": "success",
                "ui": {
                    "hasNavbar": False,
                    "hasLogin": False,
                    "hasComments": False,
                    "hasContent": True,
                },
                "dom_snapshot": (
                    "<html><body><main>"
                    "<h1>FieldOps HQ</h1>"
                    "<p>Manage field operations in real time with a unified dashboard, jobs board, and team visibility.</p>"
                    "<a href='/login'>Sign in</a>"
                    "<a href='/register'>Create account</a>"
                    + (" Welcome back to FieldOps HQ." * 40)
                    + "</main></body></html>"
                ),
            }

            issues = asyncio.run(validator.check_missing_ui(browser_result))

            assert issues == []

    def test_ai_evaluated_navbar_does_not_fall_through_to_semantic_false_positive(self):
        with tempfile.TemporaryDirectory() as tmp:
            validator = RuntimeValidator(
                tmp,
                tool_registry=None,
                provider=_JSONProvider('[{"feature":"navbar","missing":false,"confidence":"HIGH","reason":"Custom app header is present"}]'),
                model_id="test-model",
            )

            browser_result = {
                "status": "success",
                "ui": {
                    "hasNavbar": False,
                    "hasLogin": False,
                    "hasComments": False,
                    "hasContent": True,
                },
                "dom_snapshot": (
                    "<html><body><main>"
                    "<div class='shell-top'><a href='/dashboard'>Dashboard</a><a href='/settings'>Settings</a></div>"
                    "<h1>Dashboard</h1>"
                    + (" Operational metrics ready." * 40)
                    + "</main></body></html>"
                ),
            }

            issues = asyncio.run(validator.check_missing_ui(browser_result))

            assert issues == []

    def test_landing_page_post_filter_drops_ai_only_navbar_and_auth_form_false_positives(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write("server/routes/authRoutes.ts", "module.exports = {};\n", tmp)
            validator = RuntimeValidator(
                tmp,
                tool_registry=None,
                provider=_JSONProvider(
                    '[{"feature":"navbar","missing":true,"confidence":"HIGH","reason":"No <nav> element found"},'
                    '{"feature":"login/register form","missing":true,"confidence":"HIGH","reason":"No form inputs detected"}]'
                ),
                model_id="test-model",
            )

            browser_result = {
                "status": "success",
                "ui": {
                    "hasNavbar": False,
                    "hasLogin": False,
                    "hasComments": False,
                    "hasContent": True,
                },
                "dom_snapshot": (
                    "<html><body><main>"
                    "<h1>FieldOps HQ</h1>"
                    "<p>Marketing copy about dashboards and job coordination.</p>"
                    "<a href='/login'>Sign in</a>"
                    "<a href='/register'>Register</a>"
                    + (" FieldOps keeps teams coordinated." * 40)
                    + "</main></body></html>"
                ),
            }

            issues = asyncio.run(validator.check_missing_ui(browser_result))

            assert issues == []
