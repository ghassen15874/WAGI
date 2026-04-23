import re

class ErrorAnalyzer:
    """
    Classifies build/runtime errors and maps them to fix strategies.
    Prevents repeating the same invalid fix.

    BUG FIX: Removed duplicate STRATEGIES keys.
    Previously HARDCODED_COLOR and MISSING_RETURN_JSX were each defined TWICE.
    Python's dict literal silently keeps only the LAST definition, discarding
    the first entry's patterns entirely. The two definitions are now merged
    into a single entry per key with all patterns combined.
    """
    
    STRATEGIES = {
        # --- REACT / FRONTEND ---
        "UNSUPPORTED_JSX_STYLE": {
            "patterns": [r"<style jsx>", r"jsx attribute is only for Next.ts"],
            "fix": "Replace <style jsx> with standard <style> or inline styles. Vite does not support the 'jsx' attribute.",
            "severity": "CRITICAL"
        },
        "MISMATCHED_IMPORT": {
            "patterns": [
                r"does not provide an export named",
                r"has no exported member",
                r"is a default export. Use: import \w+ from",
                r"Did you mean to use 'import .* from .*' instead\?",
            ],
            "fix": "Fix import/export mismatch. Use 'import Name' for default and 'import { Name }' for named exports.",
            "severity": "CRITICAL"
        },
        "MISSING_HOOK_IMPORT": {
            "patterns": [r"useState.*?not defined", r"useEffect.*?not defined", r"useContext.*?not defined"],
            "fix": "Add 'import { useState, useEffect } from \"react\";' to the top of the file. React hooks (useState, useEffect, useContext, useRef, useMemo, useCallback, useReducer) must ONLY be imported from 'react'. Do NOT import them from service files, custom modules, or utility files.",
            "severity": "HIGH"
        },
        "MISMATCHED_IMPORT_SOURCE": {
            "patterns": [
                r"imported from wrong source",
                r"MISMATCHED_IMPORT_SOURCE:",
            ],
            "fix": "A symbol is being imported from the wrong module. React hooks must come from 'react'. Verify the actual exported members of the source module before adding import statements.",
            "severity": "HIGH"
        },
        "STRICT_MODE_VIOLATION": {
            "patterns": [r"Legacy context API has been deprecated", r"findDOMNode is deprecated"],
            "fix": "Update component to use modern React APIs (e.g. useRef instead of findDOMNode).",
            "severity": "MEDIUM"
        },
        "JSX_IN_TS_FILE": {
            "patterns": [
                r"The JSX syntax extension is not currently enabled",
                r"Cannot use JSX unless the '--jsx' flag is provided",
                r"Transform failed.*\.ts",
                r"Unexpected token \'<.*?\'"
            ],
            "fix": "You put JSX (React elements) inside a .ts file. You MUST rename this file to use the .tsx extension (e.g., useAuth.tsx instead of useAuth.ts) AND make sure to output the fully rewritten file with the new // FILE: path.tsx header.",
            "severity": "CRITICAL"
        },
        # BUG FIX: Merged two HARDCODED_COLOR definitions into one with all patterns combined.
        "HARDCODED_COLOR": {
            "patterns": [
                r"Do not hardcode colors",
                r"hardcode colors in inline styles",
                r"Use CSS variables from variables\.css",
            ],
            "fix": "Replace hardcoded hex colors (#xxx), rgb(), and hsl() with CSS variables like var(--color-primary), var(--color-text), etc. from variables.css.",
            "severity": "LOW"
        },
        # BUG FIX: Merged two MISSING_RETURN_JSX definitions into one with all patterns combined.
        "MISSING_RETURN_JSX": {
            "patterns": [
                r"Missing return statement with JSX",
                r"Missing return statement",
            ],
            "fix": "Add a return statement that returns JSX. The component must return a React element.",
            "severity": "CRITICAL"
        },
        "RUNTIME_UI_BLANK_PAGE": {
            "patterns": [r'"rootEmpty": true', r'"blank_page": true', r"BLANK_PAGE_ERROR"],
            "fix": (
                "The React app rendered a blank page. Check App.tsx and main.tsx. "
                "Ensure Providers are correctly returning children, and that BrowserRouter "
                "wraps the App. If a component crashes, the ErrorBoundary (or React itself) "
                "unmounts the tree resulting in a blank page. Fix the underlying crash."
            ),
            "severity": "CRITICAL"
        },
        "RUNTIME_UI_CRASH": {
            "patterns": [
                r"RUNTIME_UI_ERROR",
                r"console_errors",
                r"Objects are not valid as a React child",
                r"is not a function",
                r"must be used within a [A-Z]\w*Provider",
            ],
            "fix": "A runtime exception occurred in the browser console. Analyze the specific typescript/React error in the payload and fix the corresponding component.",
            "severity": "CRITICAL"
        },
        "API_RESPONSE_ENVELOPE_MISMATCH": {
            "patterns": [
                r"API_RESPONSE_ENVELOPE_MISMATCH",
                r"wrapped JSON .*raw axios data",
                r"response\.data\.data",
            ],
            "fix": (
                "Standardize the API response envelope. If backend controllers return "
                "{ success, data }, frontend services/hooks/pages must unwrap response.data.data. "
                "If frontend code expects response.data directly, backend controllers must return raw arrays/objects instead."
            ),
            "severity": "CRITICAL"
        },
        "HTTP_CLIENT_MIXED": {
            "patterns": [
                r"HTTP_CLIENT_MIXED",
                r"mixes raw fetch\(\) and the axios-based shared client",
            ],
            "fix": (
                "Use one frontend request stack only. This pipeline standardizes on axios via src/services/api.ts. "
                "Remove raw fetch() calls and direct axios imports outside the shared api client."
            ),
            "severity": "HIGH"
        },
        "HTTP_CLIENT_CONTRACT_ERROR": {
            "patterns": [
                r"HTTP_CLIENT_CONTRACT_ERROR",
                r"Direct fetch\(\) is not allowed",
                r"Direct axios imports are not allowed outside src/services/api.ts",
            ],
            "fix": (
                "Use the shared axios client in src/services/api.ts for all frontend HTTP calls. "
                "Do not mix fetch() and axios or import axios directly in pages/components/hooks."
            ),
            "severity": "HIGH"
        },
        "TAILWIND_RUNTIME_MISSING": {
            "patterns": [
                r"TAILWIND_RUNTIME_MISSING",
                r"Tailwind-style utility classes",
                r"project does not include Tailwind config/runtime",
            ],
            "fix": (
                "Restore or add the Tailwind runtime instead of rewriting the UI back to semantic CSS. "
                "Update package.json, tailwind.config.js, postcss.config.js, src/main.tsx, and src/styles/global.css as needed so existing Tailwind utility classes render correctly."
            ),
            "severity": "HIGH"
        },
        "STYLESHEET_CLASS_MISSING": {
            "patterns": [
                r"STYLESHEET_CLASS_MISSING",
                r"semantic CSS classes .* are not defined",
            ],
            "fix": (
                "Rewrite the affected UI file together with src/styles/global.css or the owning stylesheet. "
                "Define the referenced semantic classes as real CSS rules backed by the design system."
            ),
            "severity": "HIGH"
        },
        "STYLESHEET_CLASS_EMPTY": {
            "patterns": [
                r"STYLESHEET_CLASS_EMPTY",
                r"empty placeholder blocks",
            ],
            "fix": (
                "Replace empty placeholder CSS selectors with real styling rules. "
                "Rewrite the affected UI file together with src/styles/global.css or the owning stylesheet."
            ),
            "severity": "HIGH"
        },
        "STYLESHEET_CLASS_INCOMPLETE": {
            "patterns": [
                r"STYLESHEET_CLASS_INCOMPLETE",
                r"selectors are missing and others only exist as empty placeholder blocks",
            ],
            "fix": (
                "Regenerate the affected UI file together with src/styles/global.css or the owning stylesheet. "
                "Implement every referenced semantic class with real CSS rules."
            ),
            "severity": "HIGH"
        },
        "FRONTEND_DESIGN_QUALITY_MISSING": {
            "patterns": [
                r"FRONTEND_DESIGN_QUALITY_RESPONSIVE_MISSING",
                r"FRONTEND_DESIGN_QUALITY_VISUAL_DEPTH_MISSING",
                r"FRONTEND_DESIGN_QUALITY_SECTION_RHYTHM_MISSING",
            ],
            "fix": (
                "Rewrite the affected page with stronger design quality: add responsive Tailwind breakpoints, "
                "multiple distinct sections for home/landing pages, and clearer visual hierarchy using surfaces, "
                "contrast, borders/rings, shadows, or gradient treatments."
            ),
            "severity": "HIGH"
        },
        "ROOT_PROVIDER_MISSING": {
            "patterns": [r"ROOT_PROVIDER_MISSING:", r"must be used within a [A-Z]\w*Provider"],
            "fix": "A global React provider is missing from src/main.tsx or src/App.tsx. Mount the required provider around the app and keep the consuming hook/component aligned with it.",
            "severity": "CRITICAL"
        },
        "FEATURE_VALIDATION_BRIDGE_ERROR": {
            "patterns": [r"FEATURE_VALIDATION_BRIDGE_ERROR", r"Frontend missing implementation for backend features"],
            "fix": "The backend exposes routes/features that the frontend UI is missing. You MUST implement the missing UI components (e.g., if backend has Auth, frontend must have Login/Register forms).",
            "severity": "CRITICAL"
        },

        # --- SERVER / BACKEND ---
        "CJS_ESM_MIX": {
            "patterns": [r"Remove 'export default' — server files", r"Use require\(\) not import", r"Legacy CommonJS detected"],
            "fix": "Convert to 100% ESM. Use 'export' and 'import'. Do NOT use 'require()' or 'module.exports' in server files.",
            "severity": "CRITICAL"
        },
        "MISSING_EXPRESS_LISTEN": {
            "patterns": [r"Express server missing app.listen\(\)"],
            "fix": "Add 'app.listen(port, ...)' to the entry point (server/index.ts).",
            "severity": "CRITICAL"
        },
        "RUNTIME_BACKEND_CRASH": {
            "patterns": [r"RUNTIME_BACKEND_ERROR", r"Server crashed on boot", r"Unhandled Promise Rejection"],
            "fix": "The Express server or Database seeding completely crashed during startup. Read the provided 'stderr' carefully. If it's a SQL error, fix the 'CREATE TABLE' statements inside database.ts. If it's a Node crash, fix the logic in server/index.ts or the file in the stack trace.",
            "severity": "CRITICAL"
        },
        "ROUTE_CALLBACK_ERROR": {
            "patterns": [
                r"Route\.\w+\(\) requires a callback function",
                r"requires a callback function but got a \[object Undefined\]",
                r"requires a callback function but got a \[object Object\]",
            ],
            "fix": (
                "The error is NOT in server/index.ts. "
                "A route file (e.g. routes/postRoutes.ts) is passing an undefined controller method to Express. "
                "FIX STEPS: (1) Open each file in server/routes/ and list every controller.method reference. "
                "(2) Open the corresponding controller and verify each method is exported with 'exports.methodName = async (req, res) => {...}'. "
                "(3) If the method is missing from the controller, add it. "
                "(4) If the controller uses 'module.exports = { methodA }' syntax, ensure all referenced methods are in that object. "
                "Do NOT touch server/index.ts — the entry file is correct."
            ),
            "severity": "CRITICAL",
        },
        "DATABASE_LOCK": {
            "patterns": [r"database is locked", r"SQLITE_BUSY"],
            "fix": "Ensure all database connections are properly closed or use a singleton connection pool.",
            "severity": "HIGH"
        },
        "ROUTE_NOT_FOUND": {
            "patterns": [r"Cannot GET /api/", r"404 Not Found on /api/"],
            "fix": "Register the route in server/index.ts using 'app.use('/api/...', router)'.",
            "severity": "HIGH"
        },
        "MIDDLEWARE_ORDER": {
            "patterns": [r"req.body is undefined", r"cors is not enabled"],
            "fix": "Move app.use(express.json()) and app.use(cors()) BEFORE route definitions.",
            "severity": "HIGH"
        },
        "DATABASE_UNINITIALIZED": {
            "patterns": [r"DATABASE_UNINITIALIZED", r"no database initialization found"],
            "fix": "Add database initialization (e.g., using better-sqlite3 or Sequelize) in server/index.ts. Ensure models are synchronized with the database.",
            "severity": "CRITICAL"
        },
        # BUG FIX: ROUTE_MIDDLEWARE_MISMATCH was detected here but missing from
        # decision_engine._TYPE_TO_LAYER. Now properly handled end-to-end.
        "ROUTE_MIDDLEWARE_MISMATCH": {
            "patterns": [
                r"exports an object of functions",
                r"Use destructuring.*require",
                r"used it directly as a function",
            ],
            "fix": (
                "Fix the require() import style to match the export style. "
                "If middleware exports an object (exports.protect = ...), use destructuring: "
                "const { protect } = require('./middleware/auth'). "
                "If it exports a single function (module.exports = fn), use: "
                "const protect = require('./middleware/auth') with no destructuring."
            ),
            "severity": "HIGH"
        },

        # --- CONFIG / VITE ---
        "MISSING_DEPENDENCY": {
            "patterns": [
                r"Module not found: Error: Can't resolve",
                r"Cannot find module '(?:@[^'./]+/)?[^'./][^']*'(?: or its corresponding type declarations)?",
                r'Cannot find module "(?:@[^"./]+/)?[^"./][^"]*"(?: or its corresponding type declarations)?',
                r"Missing \w+ dependency",
            ],
            "fix": "Add the missing package to the 'dependencies' section of package.json.",
            "severity": "CRITICAL"
        },
        "VITE_TERSER_MISSING": {
            "patterns": [r"Replace minify:'terser' with minify:'esbuild'"],
            "fix": "Update vite.config.ts to use build:{minify:'esbuild'}. terser is not installed.",
            "severity": "HIGH"
        },
        "INVALID_PROXY": {
            "patterns": [r"Proxy error: Could not proxy request", r"ECONNREFUSED 127.0.0.1:(?:3001|5000)"],
            "fix": "Ensure vite.config.ts proxy targets use the backend port 3001 (http://localhost:3001).",
            "severity": "HIGH"
        },

        # --- INFRASTRUCTURE / BUILD ---
        "SYNTAX_ERROR": {
            "patterns": [r"SyntaxError", r"Unexpected token", r"Invalid regular expression"],
            "fix": "Fix code syntax. Check for unclosed braces, missing commas, or typos.",
            "severity": "CRITICAL"
        },
        "INVALID_JSON": {
            "patterns": [r"Invalid JSON in package.json", r"JSON.parse error"],
            "fix": "Fix the JSON formatting. Ensure property names are quoted and there are no trailing commas.",
            "severity": "CRITICAL"
        },
        "PORT_COLLISION": {
            "patterns": [r"address already in use", r"EADDRINUSE"],
            "fix": "Use process.env.PORT || 3001 and ensure previous server instances are killed.",
            "severity": "MEDIUM"
        },
        "WATCHER_LIMIT_ERROR": {
            "patterns": [r"ENOSPC: System limit for number of file watchers reached", r"watcher limit reached"],
            "fix": "Add 'server: { watch: { usePolling: true } }' to vite.config.ts. This is a common environment limit issue on Linux (ENOSPC).",
            "severity": "MEDIUM"
        },

        # --- LOGIC / FULL-STACK INTEGRATION ---
        "CONNECTED_FEATURE_MISSING": {
            "patterns": [r"MISSING_FEATURE:", r"Backend has Auth but frontend"],
            "fix": "Implement the missing frontend pages/components to consume the backend functions.",
            "severity": "HIGH"
        },
        "DISCONNECTED_ROUTE": {
            "patterns": [r"DISCONNECTED_FEATURE:", r"no frontend component appears to call it"],
            "fix": "Add an axios api.get()/api.post() call using the src/services/api.ts service in a relevant Frontend component to utilize this backend route.",
            "severity": "MEDIUM"
        },
        "API_BASE_URL_HARDCODED": {
            "patterns": [r"http://localhost:5000/api", r"hardcoded localhost URL", r"/api/api/"],
            "fix": "Remove duplicate or hardcoded API prefixes. If axios baseURL is '/api', component calls must use resource paths like '/users' or '/orders', not '/api/users' or '/api/orders'. Use relative paths that produce a single /api prefix.",
            "severity": "HIGH"
        },
        "AUTH_INVALID": {
            "patterns": [r"AUTH_INVALID:"],
            "fix": (
                "AuthContext.tsx is not properly calling the backend auth endpoints. "
                "Ensure login() calls api.post('/auth/login', credentials) and "
                "register() calls api.post('/auth/register', data). "
                "Also verify the Authorization header is set on subsequent requests."
            ),
            "severity": "CRITICAL"
        },
        "AUTH_RESPONSE_CONTRACT_ERROR": {
            "patterns": [r"AUTH_RESPONSE_CONTRACT_ERROR:"],
            "fix": (
                "The frontend auth layer and backend auth controller disagree about the login/register response shape. "
                "Return the same fields the frontend consumes, such as `{ token, user }`, or update the frontend auth service/context consistently."
            ),
            "severity": "CRITICAL"
        },
        "SCHEMA_SYNC_ERROR": {
            "patterns": [r"SCHEMA_SYNC_ERROR:"],
            "fix": (
                "A controller is inserting/querying a column that does not exist in the DB schema. "
                "Fix by aligning the column names between the controller SQL and the CREATE TABLE "
                "statement in server/db/schema.ts (or equivalent schema file)."
            ),
            "severity": "CRITICAL"
        },
        "API_CONTRACT_DRIFT": {
            "patterns": [r"API_CONTRACT_DRIFT:"],
            "fix": (
                "Mixed field names are being used for the same resource across database schema, backend responses, "
                "shared types, hooks, and UI components. Pick one contract shape and align the full stack before "
                "attempting component-level fixes."
            ),
            "severity": "CRITICAL"
        },
        "BLUEPRINT_CONTRACT_DRIFT": {
            "patterns": [r"BLUEPRINT_CONTRACT_DRIFT"],
            "fix": "The generated files have drifted from the master blueprint contract. Regenerate all affected files using the contract graph as the source of truth.",
            "severity": "CRITICAL"
        },
        "BLUEPRINT_NOT_ENFORCED": {
            "patterns": [r"BLUEPRINT_NOT_ENFORCED"],
            "fix": "The execution layer wrote code that violates the master blueprint contract. Regenerate the full connected contract cluster and enforce schema, exports, and API shape before writing files.",
            "severity": "CRITICAL"
        },
        "BLUEPRINT_EXPORT_MISMATCH": {
            "patterns": [r"BLUEPRINT_EXPORT_MISMATCH"],
            "fix": "The export conventions across modules do not match the master blueprint. Update all modules and import sites in this cluster to adhere to the same blueprint convention.",
            "severity": "HIGH"
        },
        "BLUEPRINT_SCOPE_FAILURE": {
            "patterns": [r"BLUEPRINT_SCOPE_FAILURE"],
            "fix": "This fix requires coordinating changes across the full blueprint contract cluster rather than an isolated file patch. Regenerate the cluster.",
            "severity": "CRITICAL"
        },
        "STALE_SPEC_FRAGMENT": {
            "patterns": [r"STALE_SPEC_FRAGMENT"],
            "fix": "A local utils or spec fragment conflicts with the master blueprint contract. Treat the master blueprint as authoritative and either regenerate or ignore the stale fragment.",
            "severity": "MEDIUM"
        },
        "VALIDATOR_FALSE_POSITIVE": {
            "patterns": [r"VALIDATOR_FALSE_POSITIVE"],
            "fix": "The validator flagged an issue, but it does not violate the master blueprint architecture. Safe to ignore.",
            "severity": "LOW"
        },

        # --- ASSETS / UI ---
        "MISSING_ASSET": {
            "patterns": [r"GET .*\.(png|jpg|svg) 404", r"Image not found"],
            "fix": "Ensure asset is in the /public/ folder or correctly imported in the component.",
            "severity": "MEDIUM"
        },
        "FONT_LOAD_FAILURE": {
            "patterns": [r"Google Fonts URL format", r"Failed to load font"],
            "fix": "Check the Google Fonts URL in index.html (ensure it uses HTTPS and correct fontFamily names).",
            "severity": "LOW"
        },

        # --- PERFORMANCE / BEST PRACTICES ---
        "LARGE_COMPONENT": {
            "patterns": [r"Large component detected", r"Move styles to src/styles"],
            "fix": "Refactor: Extract sub-components and move large internal <style> blocks to external CSS files.",
            "severity": "LOW"
        },
        "UNSAFE_INNER_HTML": {
            "patterns": [r"dangerouslySetInnerHTML detected"],
            "fix": "Avoid dangerouslySetInnerHTML unless absolutely necessary. Use standard JSX child elements.",
            "severity": "MEDIUM"
        },
        "MISSING_VITE_TYPE": {
            "patterns": [r"Missing type=module script tag"],
            "fix": "Add type=\"module\" to the <script> tag in index.html for Vite projects.",
            "severity": "HIGH"
        },
        "ENV_VAR_UNPROTECTED": {
            "patterns": [r"VITE_ prefixed variable leaked", r"Sensitive key in frontend"],
            "fix": "Move sensitive keys (API_SECRET, etc.) to backend .env and NEVER prefix with VITE_.",
            "severity": "CRITICAL"
        },
        "Z_INDEX_WAR": {
            "patterns": [r"z-index: 999", r"z-index: 10000"],
            "fix": "Use a z-index scale (1, 10, 20, etc.) in variables.css instead of arbitrary large numbers.",
            "severity": "LOW"
        },
        "MOBILE_RESPONSIVENESS": {
            "patterns": [r"width: \d+px", r"fixed width container"],
            "fix": "Use max-width: 100% or flexbox/grid for better mobile responsiveness.",
            "severity": "MEDIUM"
        },
        "MISSING_META_TAGS": {
            "patterns": [r"Missing viewport meta", r"Missing SEO meta"],
            "fix": "Add standard <meta name=\"viewport\" ...> and <title> tags to index.html.",
            "severity": "LOW"
        },
        "UNOPTIMIZED_FETCH": {
            "patterns": [r"fetch inside useEffect missing dependency", r"infinite fetch loop"],
            "fix": "Add a dependency array [ ] to useEffect() to ensure fetch runs only once or on specific triggers.",
            "severity": "HIGH"
        },

        # --- LINTER-DETECTED ISSUES ---
        "MISSING_IMPORT_FILE": {
            "patterns": [r"Import .* not found", r"not found — create the missing file", r"fix the import path"],
            "fix": "The imported file does not exist. CREATE the missing file with the correct exports that match what the importing files expect. Do NOT modify the importing files.",
            "severity": "CRITICAL"
        },
        "IMPORT_SITE_ERROR": {
            "patterns": [r"IMPORT_SITE_ERROR"],
            "fix": "The file is importing a default or named export that the target DOES NOT provide. This is an over-eager import. Rewrite the import line in THIS file. Do *not* invent fake exports in the target file.",
            "severity": "CRITICAL"
        },
        "MODULE_EXPORT_MISSING": {
            "patterns": [r"MODULE_EXPORT_MISSING"],
            "fix": "The target module is supposed to provide a public API/symbol but it does not. Determine if you should add the export to the module, or if the consuming file made a mistake.",
            "severity": "HIGH"
        },
        "MISSING_EXPORT_DEFAULT": {
            "patterns": [r"Missing export default", r"is a default export\. Use:"],
            "fix": "Add 'export default' to the component function or add the missing named export. Ensure the export matches the import style used by consuming files.",
            "severity": "HIGH"
        },
        "JSON_SYNTAX_ERROR": {
            "patterns": [r"JSON syntax error", r"Expecting property name enclosed in double quotes"],
            "fix": "Fix JSON formatting: remove comments (/* ... */), ensure all property names are double-quoted, remove trailing commas.",
            "severity": "CRITICAL"
        },
    }

    def __init__(self):
        self.fix_history = {} # Path -> [List of strategies attempted]

    def _choose_best_match(self, matches: list[str]) -> str:
        """
        Build logs often contain several TS errors at once. Prefer the most
        actionable root cause instead of whichever pattern appeared first in the
        STRATEGIES dict.
        """
        if not matches:
            return "UNKNOWN"

        priority_order = (
            "BLUEPRINT_NOT_ENFORCED",
            "BLUEPRINT_SCOPE_FAILURE",
            "BLUEPRINT_CONTRACT_DRIFT",
            "SCHEMA_SYNC_ERROR",
            "API_CONTRACT_DRIFT",
            "RUNTIME_UI_CRASH",
            "RUNTIME_UI_BLANK_PAGE",
            "IMPORT_SITE_ERROR",
            "MODULE_EXPORT_MISSING",
            "BLUEPRINT_EXPORT_MISMATCH",
            "MISSING_HOOK_IMPORT",
            "MISMATCHED_IMPORT_SOURCE",
            "MISSING_DEPENDENCY",
            "STALE_SPEC_FRAGMENT",
            "MISSING_IMPORT_FILE",
            "JSON_SYNTAX_ERROR",
            "INVALID_JSON",
            "SYNTAX_ERROR",
            "JSX_IN_TS_FILE",
            "MISMATCHED_IMPORT",
            "VALIDATOR_FALSE_POSITIVE",
        )

        for error_type in priority_order:
            if error_type in matches:
                return error_type

        return matches[0]

    def analyze(self, error_string: str, file_path: str = None) -> dict:
        """
        Identify the error type and return a fix strategy.
        """
        matches = []
        for error_type, config in self.STRATEGIES.items():
            for pattern in config["patterns"]:
                if re.search(pattern, error_string, re.IGNORECASE):
                    matches.append(error_type)
                    break

        chosen_type = self._choose_best_match(matches)
        if chosen_type == "UNKNOWN":
            return {
                "type": "UNKNOWN",
                "fix": "Analyze the error carefully and provide a surgical fix. Do not regenerate the whole file if not needed.",
                "severity": "MEDIUM"
            }

        # Check if we've already tried this fix for this file
        if file_path:
            history = self.fix_history.get(file_path, [])
            if chosen_type in history:
                return {
                    "type": "RECURSIVE_FAILURE",
                    "fix": f"The previous fix for {chosen_type} failed. Try a completely different approach.",
                    "severity": "HIGH"
                }

            # Record the attempt
            if file_path not in self.fix_history:
                self.fix_history[file_path] = []
            self.fix_history[file_path].append(chosen_type)

        config = self.STRATEGIES[chosen_type]
        return {
            "type": chosen_type,
            "fix": config["fix"],
            "severity": config["severity"]
        }

    def reset_history(self):
        self.fix_history = {}
