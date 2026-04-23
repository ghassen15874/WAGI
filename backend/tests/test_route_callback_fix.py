"""
Tests for the Route Callback Error fix.
Covers:
  1. error_analyzer: ROUTE_CALLBACK_ERROR pattern recognition
  2. feature_validator: strengthened _check_route_controller_sync
     - detects missing exports (exports.fn style)
     - detects missing exports (module.exports = {} style)
     - detects destructured require mismatches
     - no false positives for correct exports
  3. loop helpers: _extract_broken_server_file, _collect_broken_files_from_sync_errors

Run:
    cd /home/kali/Desktop/New\ Folder/lovable-clone
    python3 -m pytest backend/tests/test_route_callback_fix.py -v
"""
import sys, os, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from kilo.orchestrator.error_analyzer import ErrorAnalyzer
from kilo.orchestrator.feature_validator import FeatureValidator
from kilo.orchestrator.loop import _extract_broken_server_file, _collect_broken_files_from_sync_errors


# ─── error_analyzer tests ────────────────────────────────────────────────────

class TestErrorAnalyzerRouteCallback:
    def _analyzer(self):
        return ErrorAnalyzer()

    def test_exact_express_error(self):
        err = "Error: Route.get() requires a callback function but got a [object Undefined]"
        result = self._analyzer().analyze(err)
        assert result["type"] == "ROUTE_CALLBACK_ERROR"
        assert result["severity"] == "CRITICAL"

    def test_other_http_verbs(self):
        for verb in ("post", "put", "delete", "patch"):
            err = f"Error: Route.{verb}() requires a callback function but got a [object Undefined]"
            result = self._analyzer().analyze(err)
            assert result["type"] == "ROUTE_CALLBACK_ERROR", f"Failed for verb: {verb}"

    def test_object_object_variant(self):
        err = "Route.get() requires a callback function but got a [object Object]"
        result = self._analyzer().analyze(err)
        assert result["type"] == "ROUTE_CALLBACK_ERROR"

    def test_fix_mentions_routes_not_index(self):
        err = "Route.get() requires a callback function but got a [object Undefined]"
        result = self._analyzer().analyze(err)
        assert "server/index.ts" not in result["fix"] or "NOT" in result["fix"]
        assert "routes" in result["fix"].lower() or "controller" in result["fix"].lower()


# ─── feature_validator._check_route_controller_sync tests ────────────────────

def _make_project(tmp_dir: str, route_content: str, ctrl_content: str,
                  route_file="postRoutes.ts", ctrl_file="postController.ts"):
    """Helper: write minimal route + controller files in a temp project layout."""
    routes_dir = os.path.join(tmp_dir, "server", "routes")
    ctrl_dir   = os.path.join(tmp_dir, "server", "controllers")
    os.makedirs(routes_dir, exist_ok=True)
    os.makedirs(ctrl_dir, exist_ok=True)
    with open(os.path.join(routes_dir, route_file), "w") as f:
        f.write(route_content)
    with open(os.path.join(ctrl_dir, ctrl_file), "w") as f:
        f.write(ctrl_content)
    return FeatureValidator(tmp_dir)


class TestRouteSyncDetection:
    # ── exports.fn style ──────────────────────────────────────────────────────
    def test_missing_method_exports_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            route = (
                "const postController = require('../controllers/postController');\n"
                "router.get('/', postController.getAll);\n"
                "router.post('/', postController.create);\n"
            )
            ctrl = "exports.getAll = async (req, res) => {};\n"  # create is MISSING
            fv = _make_project(tmp, route, ctrl)
            errs = fv._check_route_controller_sync()
            assert any("create" in e and "ROUTE_SYNC_ERROR" in e for e in errs), \
                f"Expected missing 'create' error, got: {errs}"

    def test_no_false_positive_exports_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            route = "const c = require('../controllers/postController');\nrouter.get('/', c.getAll);\n"
            ctrl  = "exports.getAll = async (req, res) => {};\n"
            fv = _make_project(tmp, route, ctrl)
            errs = fv._check_route_controller_sync()
            sync_errs = [e for e in errs if "ROUTE_SYNC_ERROR" in e]
            assert sync_errs == [], f"False positive: {sync_errs}"

    # ── module.exports = {} style ─────────────────────────────────────────────
    def test_missing_method_module_exports_object_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            route = "const c = require('../controllers/postController');\nrouter.get('/', c.getAll);\nrouter.delete('/:id', c.remove);\n"
            ctrl  = "module.exports = { getAll };\nfunction getAll(req,res){}\n"  # remove MISSING
            fv = _make_project(tmp, route, ctrl)
            errs = fv._check_route_controller_sync()
            assert any("remove" in e for e in errs), \
                f"Expected missing 'remove', got: {errs}"

    def test_no_false_positive_module_exports_object_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            route = "const c = require('../controllers/postController');\nrouter.get('/', c.getAll);\n"
            ctrl  = "module.exports = { getAll };\nfunction getAll(req,res){}\n"
            fv = _make_project(tmp, route, ctrl)
            errs = fv._check_route_controller_sync()
            sync_errs = [e for e in errs if "ROUTE_SYNC_ERROR" in e]
            assert sync_errs == [], f"False positive: {sync_errs}"

    # ── destructured require style ─────────────────────────────────────────────
    def test_missing_method_destructured_require(self):
        with tempfile.TemporaryDirectory() as tmp:
            route = "const { login, register } = require('../controllers/authController');\nrouter.post('/login', login);\nrouter.post('/register', register);\n"
            ctrl  = "exports.login = async (req, res) => {};\n"  # register MISSING
            fv = _make_project(tmp, route, ctrl, "authRoutes.ts", "authController.ts")
            errs = fv._check_route_controller_sync()
            assert any("register" in e for e in errs), \
                f"Expected missing 'register', got: {errs}"

    def test_no_false_positive_destructured_require(self):
        with tempfile.TemporaryDirectory() as tmp:
            route = "const { login } = require('../controllers/authController');\nrouter.post('/login', login);\n"
            ctrl  = "exports.login = async (req, res) => {};\n"
            fv = _make_project(tmp, route, ctrl, "authRoutes.ts", "authController.ts")
            errs = fv._check_route_controller_sync()
            sync_errs = [e for e in errs if "ROUTE_SYNC_ERROR" in e]
            assert sync_errs == [], f"False positive: {sync_errs}"

    def test_missing_controller_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            route = "const c = require('../controllers/missingController');\nrouter.get('/', c.doSomething);\n"
            routes_dir = os.path.join(tmp, "server", "routes")
            ctrl_dir   = os.path.join(tmp, "server", "controllers")
            os.makedirs(routes_dir, exist_ok=True)
            os.makedirs(ctrl_dir, exist_ok=True)
            with open(os.path.join(routes_dir, "someRoutes.ts"), "w") as f:
                f.write(route)
            fv = FeatureValidator(tmp)
            errs = fv._check_route_controller_sync()
            assert any("missing controller" in e.lower() for e in errs), \
                f"Expected missing controller error, got: {errs}"


# ─── loop helper function tests ────────────────────────────────────────────────

class TestExtractBrokenServerFile:
    def test_skips_node_modules(self):
        log = "/home/kali/project/node_modules/express/lib/router/route.ts:216\n  throw new Error(msg);\nError: Route.get() requires a callback function but got a [object Undefined]"
        result = _extract_broken_server_file(log, "/home/kali/project")
        assert "node_modules" not in result
        # Should NOT default to index.ts since it's a route callback error — expects routes/ file or index.ts fallback
        assert result != ""

    def test_finds_route_file_in_log(self):
        log = (
            "Error: Route.get() requires a callback function but got a [object Undefined]\n"
            "    at /home/kali/project/server/routes/postRoutes.ts:10"
        )
        result = _extract_broken_server_file(log, "/home/kali/project")
        assert "postRoutes.ts" in result or "routes/" in result

    def test_falls_back_to_index_for_non_route_errors(self):
        log = "SyntaxError: Unexpected token '}' at server/index.ts:42"
        result = _extract_broken_server_file(log, "")
        assert result == "server/index.ts"


class TestCollectBrokenFiles:
    def test_extracts_controller_and_route(self):
        sync_errors = [
            "ROUTE_SYNC_ERROR: server/routes/postRoutes.ts calls 'postController.create' but 'server/controllers/postController.ts' does not export 'create'."
        ]
        result = _collect_broken_files_from_sync_errors(sync_errors, "")
        assert "server/controllers/postController.ts" in result
        assert "server/routes/postRoutes.ts" in result

    def test_controllers_come_before_routes(self):
        sync_errors = [
            "ROUTE_SYNC_ERROR: server/routes/postRoutes.ts calls 'postController.create' but 'server/controllers/postController.ts' does not export 'create'.",
            "ROUTE_SYNC_ERROR: server/routes/authRoutes.ts destructures 'register' from 'server/controllers/authController.ts' but that method is not exported."
        ]
        result = _collect_broken_files_from_sync_errors(sync_errors, "")
        ctrl_idx = min(i for i, f in enumerate(result) if "controllers" in f)
        route_idx = min(i for i, f in enumerate(result) if "routes" in f)
        assert ctrl_idx < route_idx, "Controllers should come before routes in the fix order"

    def test_deduplication(self):
        sync_errors = [
            "ROUTE_SYNC_ERROR: server/routes/postRoutes.ts calls 'c.create' but 'server/controllers/postController.ts' does not export 'create'.",
            "ROUTE_SYNC_ERROR: server/routes/postRoutes.ts calls 'c.update' but 'server/controllers/postController.ts' does not export 'update'.",
        ]
        result = _collect_broken_files_from_sync_errors(sync_errors, "")
        assert result.count("server/routes/postRoutes.ts") == 1
        assert result.count("server/controllers/postController.ts") == 1

    def test_fallback_to_index_when_empty(self):
        result = _collect_broken_files_from_sync_errors([], "")
        assert result == ["server/index.ts"]
