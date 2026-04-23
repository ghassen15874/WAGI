"""
linter.py — Fixed version
"""
import os
import re
import json
import subprocess
import shutil
import textwrap

class SyntaxValidator:
    """Real syntax-checking for generated files using Node/Babel/PostCSS."""
    _NODE = shutil.which("node") or "node"
    _TIMEOUT = 8

    _JS_SCRIPT = textwrap.dedent("""\
        const acorn = require('acorn');
        const src = require('fs').readFileSync(process.argv[1], 'utf8');
        try {
            acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'module' });
        } catch (e) {
            process.stderr.write(e.message + '\\n');
            process.exit(1);
        }
    """)

    _BABEL_SCRIPT = textwrap.dedent("""\
        const parser = require('@babel/parser');
        const src = require('fs').readFileSync(process.argv[1], 'utf8');
        try {
            parser.parse(src, {
                sourceType: 'module',
                plugins: ['jsx', 'typescript', 'classProperties',
                          'decorators-legacy', 'optionalChaining', 'nullishCoalescingOperator'],
                errorRecovery: false,
            });
        } catch (e) {
            process.stderr.write((e.reasonCode ? e.reasonCode + ': ' : '') + e.message + '\\n');
            process.exit(1);
        }
    """)

    _CSS_SCRIPT = textwrap.dedent("""\
        const postcss = require('postcss');
        const src = require('fs').readFileSync(process.argv[1], 'utf8');
        try {
            postcss.parse(src, { from: process.argv[1] });
        } catch (e) {
            process.stderr.write(e.message + '\\n');
            process.exit(1);
        }
    """)

    @staticmethod
    def _strip_jsonc_comments(content: str) -> str:
        text = str(content or "")
        text = re.sub(r"/\*[\s\S]*?\*/", "", text)
        text = re.sub(r"(^|[^:])//.*?$", r"\1", text, flags=re.MULTILINE)
        return text

    @classmethod
    def _parse_json_like(cls, path: str, content: str) -> tuple[object | None, json.JSONDecodeError | None]:
        normalized = str(path or "").replace("\\", "/").lower()
        raw = str(content or "")

        try:
            return json.loads(raw), None
        except json.JSONDecodeError as strict_error:
            if os.path.basename(normalized) not in {"tsconfig.json", "tsconfig.node.json", "jsconfig.json"}:
                return None, strict_error

            jsonc = cls._strip_jsonc_comments(raw)
            jsonc = re.sub(r",(\s*[}\]])", r"\1", jsonc)
            try:
                return json.loads(jsonc), None
            except json.JSONDecodeError as jsonc_error:
                return None, jsonc_error

    @classmethod
    def _node_check(cls, script: str, filepath: str) -> str | None:
        try:
            result = subprocess.run(
                [cls._NODE, "-e", script, filepath],
                capture_output=True, text=True, timeout=cls._TIMEOUT
            )
            if result.returncode != 0:
                msg = (result.stderr or result.stdout).strip()
                return msg[:300] if msg else "syntax error (no message)"
        except subprocess.TimeoutExpired:
            return "syntax check timed out"
        except FileNotFoundError:
            return None
        return None

    @classmethod
    def validate(cls, path: str, content: str, sandbox_dir: str = "") -> list[str]:
        import tempfile
        errors: list[str] = []
        ext = os.path.splitext(path)[1].lower()

        if ext not in ('.js', '.jsx', '.ts', '.tsx', '.css', '.json', '.html'):
            return errors

        if ext == '.json':
            _parsed, error = cls._parse_json_like(path, content)
            if error:
                errors.append(f"{path}: JSON syntax error — {error.msg} (line {error.lineno}, col {error.colno})")
            return errors

        if ext == '.html':
            VOID = {'area','base','br','col','embed','hr','img','input',
                    'link','meta','param','source','track','wbr'}
            open_tags = re.findall(r'<([a-zA-Z][a-zA-Z0-9]*)(?:\s[^>]*)?>(?!\s*/)', content)
            open_tags = [t.lower() for t in open_tags if t.lower() not in VOID]
            open_tags = [t for t in open_tags
                         if not re.search(rf'<{re.escape(t)}(?:\s[^>]*)?\s*/>', content, re.IGNORECASE)]
            close_tags = re.findall(r'</([a-zA-Z][a-zA-Z0-9]*)>', content)
            close_tags = [t.lower() for t in close_tags]
            opens  = len(open_tags)
            closes = len(close_tags)
            if abs(opens - closes) > 3:
                errors.append(
                    f"{path}: HTML tag imbalance detected "
                    f"({opens} open vs {closes} close tags). File may be truncated."
                )
            return errors

        suffix = ext
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False, encoding='utf-8') as tmp:
                tmp.write(content)
                tmp_path = tmp.name
        except Exception:
            return errors

        try:
            if ext == '.js':
                err = cls._node_check(cls._JS_SCRIPT, tmp_path)
            elif ext in ('.jsx', '.tsx', '.ts'):
                err = cls._node_check(cls._BABEL_SCRIPT, tmp_path)
            elif ext == '.css':
                err = cls._node_check(cls._CSS_SCRIPT, tmp_path)
            else:
                err = None

            if err:
                errors.append(f"{path}: syntax error — {err}")
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

        return errors


class CodeLinter:
    @staticmethod
    def _has_raw_fetch_call(content: str) -> bool:
        src = str(content or "")
        if not src:
            return False

        if re.search(r"\b(?:window|globalThis)\.fetch\s*\(", src):
            return True

        local_fetch_declared = bool(
            re.search(r"\b(?:const|let|var|function)\s+fetch\b", src)
            or re.search(r"\bimport\s+fetch\s+from\b", src)
            or re.search(r"\bimport\s*\{\s*fetch(?:\s+as\s+\w+)?\s*\}\s*from\b", src)
            or re.search(r"\b(?:const|let|var)\s*\{\s*fetch(?:\s*:\s*\w+)?\s*\}\s*=", src)
        )

        if re.search(r"\b(?:await|return)\s+fetch\s*\(", src) and not local_fetch_declared:
            return True

        if re.search(r"(?<![\w$.])fetch\s*\(", src) and not local_fetch_declared:
            return True

        return False

    @staticmethod
    def _extract_js_object_block(content: str, key: str) -> str:
        match = re.search(rf"\b{re.escape(key)}\s*:\s*\{{", content)
        if not match:
            return ""

        start = match.end() - 1
        depth = 0
        for idx in range(start, len(content)):
            char = content[idx]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return content[start:idx + 1]
        return ""

    def lint_all(self, sandbox_dir: str) -> list[str]:
        errors = []
        if not os.path.isdir(sandbox_dir):
            return errors
            
        errors.extend(self.run_tsc_check(sandbox_dir))
        
        for root, dirs, files in os.walk(sandbox_dir):
            dirs[:] = [d for d in dirs if d not in ('node_modules', '.git')]
            for fname in files:
                path = os.path.join(root, fname)
                rel_path = os.path.relpath(path, sandbox_dir)
                if not os.path.isfile(path):
                    continue
                try:
                    with open(path, encoding="utf-8", errors='ignore') as f:
                        content = f.read()
                    errors.extend(self.lint_file(rel_path, content, sandbox_dir))
                except Exception:
                    pass
        return errors

    def lint_file(self, path: str, content: str, sandbox_dir: str = "") -> list[str]:
        errors = []
        ext = os.path.splitext(path)[1].lower()

        if ext in ('.ts', '.tsx', '.jsx', '.js'):
            errors.extend(self._check_imports(content, path, sandbox_dir))
            errors.extend(self._check_js(content, path))
            errors.extend(self._check_frontend_http_client(content, path))
            errors.extend(self._check_server(content, path))
            errors.extend(self._check_forbidden_imports(content, path))
        if ext in ('.tsx', '.jsx'):
            errors.extend(self._jsx(content, path))
        if ext == '.css':
            errors.extend(self._css(content, path))
        if ext == '.json' and 'package.json' in path:
            errors.extend(self._pkg(content, path))
        if ext == '.html':
            errors.extend(self._html(content, path))
        if 'vite.config' in path:
            errors.extend(self._check_vite(content, path))

        errors.extend(SyntaxValidator.validate(path, content, sandbox_dir))
        return errors

    def run_tsc_check(self, sandbox_dir: str) -> list[str]:
        errors = []
        try:
            result = subprocess.run(
                ["npx", "tsc", "--noEmit", "--skipLibCheck"],
                cwd=sandbox_dir, capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                output = result.stdout + result.stderr
                for line in output.splitlines()[:20]:
                    if ": error TS" in line:
                        errors.append(f"TypeScript: {line.strip()}")
        except Exception:
            pass
        return errors

    def _html(self, c, f):
        errors = []
        if 'type="module"' not in c and '<script' in c:
            errors.append(f"{f}: Missing type=\"module\" script tag")
        abs_src = re.search(r'<script[^>]+src=["\']/(?:home|root|usr|var|tmp)/[^"\']+["\']', c)
        if abs_src:
            errors.append(f"{f}: Absolute filesystem path in <script src>. This BREAKS Vite. Use: <script type=\"module\" src=\"/src/main.tsx\">")
        return errors

    def _css(self, c, f):
        errors = []
        if c.count("{") != c.count("}"):
            errors.append(f"{f}: Unbalanced CSS braces")
        if "--color-primary" not in c and "--primary" not in c and "variables" in f:
            errors.append(f"{f}: Missing CSS custom properties (--color-primary)")
        
        if f.endswith("global.css"):
            if "@import" not in c or "variables.css" not in c:
                errors.append(f"{f}: Missing '@import \"./variables.css\";' at the top. Variables will not resolve.")
        return errors

    def _check_js(self, content: str, filename: str) -> list:
        errors = []
        # Neutralized: Permitting CJS/ESM mix for transitional files if needed, 
        # but 100% ESM is the final target.
        pass
        if "server/index.ts" in filename or filename == "server/index.ts":
            if "app.listen" not in content:
                errors.append(f"{filename}: Express server missing app.listen()")
        return errors

    def _check_frontend_http_client(self, content: str, path: str) -> list:
        errors = []
        normalized = str(path or "").replace("\\", "/")
        if not normalized.startswith("src/"):
            return errors

        axios_import = bool(
            re.search(r"import\s+.+?\s+from\s+['\"]axios['\"]", content)
            or re.search(r"require\(['\"]axios['\"]\)", content)
        )
        if normalized == "src/services/api.ts":
            if not axios_import:
                errors.append(
                    f"{path}: src/services/api.ts must be the shared axios client and import `axios` directly."
                )
            if self._has_raw_fetch_call(content):
                errors.append(
                    f"{path}: Do not implement src/services/api.ts with fetch(). This pipeline standardizes on axios."
                )
            return errors

        if self._has_raw_fetch_call(content):
            errors.append(
                f"{path}: Direct fetch() call detected. This pipeline standardizes on axios via src/services/api.ts only."
            )
        if axios_import:
            errors.append(
                f"{path}: Direct axios import detected. Import the shared `api` client from src/services/api.ts instead."
            )
        return errors

    def _jsx(self, c, f):
        ENTRY_FILES = {"main.tsx", "main.jsx", "index.tsx", "index.jsx"}
        filename_only = os.path.basename(f)
        if filename_only in ENTRY_FILES:
            return []

        errors = []
        
        # --- NEW LOGIC: Ignore React Hooks (useAuth, usePosts) ---
        if filename_only.startswith('use'):
            return errors 

        if "export default" not in c and "export const" not in c and "export function" not in c:
            errors.append(f"{f}: Missing export default or named export")
        
        if 'Context.tsx' not in f:
            if not re.search(r"return\s*\(|return\s*<|return\s*null|=>\s*<", c):
                if ".tsx" in f:
                    errors.append(f"{f}: Missing return statement with JSX")
        
        if self._has_raw_fetch_call(c) and "api." not in c and "import api from" in c:
             errors.append(f"{f}: Direct fetch() call detected. Use the imported 'api' service instead.")

        return errors

    def _pkg(self, c, f):
        errors = []
        try:
            pkg = json.loads(c)
            if "scripts" not in pkg:
                errors.append(f"{f}: Missing scripts field")
            elif "dev" not in pkg.get("scripts", {}):
                errors.append(f"{f}: Missing 'dev' script")
            elif "server" not in pkg.get("scripts", {}):
                errors.append(f"{f}: Missing 'server' script")
            else:
                server_script = str(pkg.get("scripts", {}).get("server", "") or "")
                if server_script.strip() != "node --import tsx server/index.ts":
                    errors.append(
                        f"{f}: 'server' script must be exactly 'node --import tsx server/index.ts' "
                        "for the canonical backend entrypoint."
                    )

            dependencies = dict(pkg.get("dependencies", {}) or {})
            dev_dependencies = dict(pkg.get("devDependencies", {}) or {})
            all_dependency_names = {str(name).strip() for name in (dependencies.keys() | dev_dependencies.keys()) if str(name).strip()}

            # Neutralized: Enforcing target "type": "module" for ESM projects.
            if str(pkg.get("type", "") or "").strip().lower() != "module":
                # Only warn if it's already a TS project
                if all_dependency_names.intersection({"typescript", "tsx"}):
                    errors.append(f'{f}: Missing "type": "module" — backend server must use native ESM.')

            if dependencies.get("axios") is None:
                errors.append(f"{f}: Missing axios dependency. Frontend API calls must use the shared axios client.")

            better_sqlite_version = str(dependencies.get("better-sqlite3", "") or "").strip()
            if better_sqlite_version != "^12.2.0":
                errors.append(f"{f}: better-sqlite3 must be pinned to '^12.2.0' in dependencies.")

            conflicting_db_packages = ["sqlite3", "prisma", "@prisma/client", "sequelize", "mongoose", "knex", "pg"]
            for package_name in conflicting_db_packages:
                if package_name in all_dependency_names:
                    errors.append(
                        f"{f}: Remove '{package_name}' — this pipeline uses a single SQL stack: better-sqlite3 only."
                    )
        except Exception:
            errors.append(f"{f}: Invalid JSON in package.json")
        return errors

    def _check_imports(self, content: str, path: str, sandbox_dir: str) -> list:
        errors = []
        
        def check_exists(base_resolved: str) -> bool:
            variations = [base_resolved]
            if base_resolved.endswith('.js'):
                variations.extend([base_resolved[:-3] + '.ts', base_resolved[:-3] + '.tsx'])
            for r in variations:
                for ext in ['', '.tsx', '.ts', '.jsx', '.js', '/index.tsx', '/index.ts']:
                    if os.path.exists(r + ext):
                        return True
            return False

        local_imports = re.findall(r'import\s+.*?\s+from\s+[\'"](\./[^\'"]+|\.\./[^\'"]+)[\'"]', content)
        for imp in local_imports:
            file_dir = os.path.dirname(os.path.join(sandbox_dir, path))
            resolved = os.path.normpath(os.path.join(file_dir, imp))
            if not check_exists(resolved):
                if "Controller" in imp and imp.startswith("./") and "routes" in path:
                    errors.append(
                        f"{path}: WRONG_IMPORT_PATH: '{imp}' uses './' but controller is in "
                        f"'../controllers/'. Fix the import path, do NOT create a new file."
                    )
                else:
                    errors.append(f"{path}: Import '{imp}' not found — create the missing file")

        if sandbox_dir:
            alias_imports = re.findall(r'import\s+.*?\s+from\s+[\'"](@/[^\'"]+)[\'"]', content)
            src_dir = os.path.join(sandbox_dir, "src")
            for imp in alias_imports:
                rel_from_src = imp[2:]
                resolved = os.path.normpath(os.path.join(src_dir, rel_from_src))
                if not check_exists(resolved):
                    errors.append(f"{path}: Aliased import '{imp}' not found.")
        return errors

    def _check_css_imports(self, content: str, path: str) -> list:
        return []

    def _check_server(self, content: str, path: str) -> list:
        errors = []
        if 'server' in path and path.endswith('.ts'):
            # Strip strings/comments before CJS detection to avoid false positives
            # from plain text messages mentioning "require(".
            stripped = re.sub(r"/\*[\s\S]*?\*/", "", content)
            stripped = re.sub(r"//.*?$", "", stripped, flags=re.MULTILINE)
            stripped = re.sub(r"(['\"`])(?:\\.|(?!\1).)*\1", "''", stripped)
            if re.search(r"\brequire\s*\(", stripped) or re.search(r"\bmodule\.exports\b", stripped):
                errors.append(f"{path}: Legacy CommonJS detected. You MUST use 'import' and 'export' for 100% ESM purity.")
            if re.search(r"\bdb\.(?:prepare|exec)\(\s*(?:SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|WITH)\b", content, re.IGNORECASE):
                errors.append(
                    f"{path}: SQL passed to db.prepare/db.exec must be wrapped in quotes or template literals."
                )
            normalized = str(path).replace("\\", "/")
            if normalized.startswith("server/routes/"):
                if re.search(r"require\(['\"]\./[A-Za-z0-9_-]+Controller['\"]\)", content):
                    errors.append(
                        f"{path}: Route files must require controllers from '../controllers/...', not './...'."
                    )
                if re.search(r"from\s+['\"]\./[A-Za-z0-9_-]+Controller['\"]", content):
                    errors.append(
                        f"{path}: Route files must import controllers from '../controllers/...', not './...'."
                    )
        return errors

    def _check_forbidden_imports(self, content: str, path: str) -> list:
        return []

    def _check_vite(self, content: str, path: str) -> list:
        errors = []
        if "vite.config" in path:
            server_block = self._extract_js_object_block(content, "server")
            preview_block = self._extract_js_object_block(content, "preview")

            has_server_proxy = bool(
                server_block
                and re.search(r"\bproxy\s*:", server_block)
                and re.search(r"\btarget\s*:", server_block)
            )
            has_preview_proxy = bool(
                preview_block
                and re.search(r"\bproxy\s*:", preview_block)
                and re.search(r"\btarget\s*:", preview_block)
            )
            if not has_server_proxy:
                errors.append(f"{path}: CRITICAL ERROR - The Vite dev proxy is missing! You MUST include server: {{ proxy: {{ '/api': {{ target: 'http://localhost:3001', changeOrigin: true }} }} }}")
            if not has_preview_proxy:
                errors.append(f"{path}: CRITICAL ERROR - The Vite preview proxy is missing! You MUST include preview: {{ proxy: {{ '/api': {{ target: 'http://localhost:3001', changeOrigin: true }} }} }}")

            if server_block:
                server_target_match = re.search(r"/api[\s\S]*?target\s*:\s*['\"]http://localhost:(\d+)['\"]", server_block)
                if server_target_match and server_target_match.group(1) != "3001":
                    errors.append(
                        f"{path}: INVALID_PROXY_PORT: proxy target must be exactly "
                        f"'http://localhost:3001'. "
                        f"Run: sed -i \"s|target:.*localhost:[0-9]*|target: 'http://localhost:3001'|g\" vite.config.ts"
                    )
            if preview_block:
                preview_target_match = re.search(r"/api[\s\S]*?target\s*:\s*['\"]http://localhost:(\d+)['\"]", preview_block)
                if preview_target_match and preview_target_match.group(1) != "3001":
                    errors.append(
                        f"{path}: INVALID_PROXY_PORT: proxy target must be exactly "
                        f"'http://localhost:3001'. "
                        f"Run: sed -i \"s|target:.*localhost:[0-9]*|target: 'http://localhost:3001'|g\" vite.config.ts"
                    )
        return errors

    def format_for_ai(self, errors: list[str]) -> str:
        if not errors: return ""
        lines = ["🔧 LINTER FOUND ERRORS — fix ALL using write_file tool:"]
        for i, e in enumerate(errors, 1): lines.append(f"  {i}. {e}")
        return "\n".join(lines)
