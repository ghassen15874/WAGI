from __future__ import annotations

import json
import re
from pathlib import PurePosixPath

_ALLOWED_REQUIRED_ROOT_PREFIXES = (
    "src/",
    "server/",
    "public/",
    "db/",
    "prisma/",
    "supabase/",
    "migrations/",
)

_ALLOWED_REQUIRED_ROOT_FILES = {
    "package.json",
    "tailwind.config.js",
    "postcss.config.js",
    "vite.config.ts",
    "vite.config.js",
    "tsconfig.json",
    "tsconfig.node.json",
    "index.html",
    ".env",
    ".gitignore",
    "README.md",
}

_MANDATORY_DESIGN_TOKENS = {
    "--background": "var(--color-background, #ffffff)",
    "--foreground": "var(--color-foreground, #0f172a)",
    "--card": "var(--background)",
    "--card-foreground": "var(--foreground)",
    "--border": "var(--color-border, rgba(15, 23, 42, 0.12))",
}

_DEFAULT_BACKEND_PROXY_PORT = "3001"

_IMAGE_SEED_STOPWORDS = {
    "images", "image", "assets", "asset", "img", "public", "static",
    "placeholder", "photo", "photos", "picture", "pictures",
    "jpg", "jpeg", "png", "webp", "avif", "gif",
}


def _build_dynamic_photo_url(token: str) -> str:
    lower = str(token or "").lower()
    words = [
        word
        for word in re.findall(r"[a-z0-9]+", lower)
        if word and word not in _IMAGE_SEED_STOPWORDS
    ]
    seed = "-".join(words[:4]) if words else "website-real"
    if any(word in lower for word in ("hero", "banner", "background", "cover")):
        size = "1600/1000"
    elif any(word in lower for word in ("avatar", "profile", "person", "team", "user")):
        size = "900/900"
    else:
        size = "1200/900"
    return f"https://picsum.photos/seed/{seed}/{size}"


def _normalize_image_sources(content: str) -> tuple[str, int]:
    normalized = str(content or "")
    replacements = 0
    pattern = re.compile(
        r"(?P<q>['\"])(?P<url>"
        r"(?:https?://via\.placeholder\.com/[^\s'\"`]+|"
        r"[^'\"\s`]*placeholder[^'\"\s`]*|"
        r"/?(?:images?|assets/images)/[^\s'\"`]+\.(?:png|jpe?g|webp|avif|gif)|"
        r"/[A-Za-z0-9_-]+\.(?:png|jpe?g|webp|avif|gif))"
        r")(?P=q)"
    )

    def _replace(match: re.Match[str]) -> str:
        nonlocal replacements
        quote = match.group("q")
        image_url = match.group("url")
        lower = image_url.lower()

        if lower.startswith(("http://", "https://")) and "placeholder" not in lower:
            return match.group(0)
        if lower.startswith("/api/"):
            return match.group(0)
        if any(word in lower for word in ("logo", "icon", "favicon", "avatar", "brand")):
            return match.group(0)

        real_url = _build_dynamic_photo_url(lower)
        replacements += 1
        return f"{quote}{real_url}{quote}"

    return pattern.sub(_replace, normalized), replacements


def _looks_like_frontend_package(package_data: dict) -> bool:
    dependencies = package_data.get("dependencies")
    dev_dependencies = package_data.get("devDependencies")
    scripts = package_data.get("scripts")

    dep_map = dependencies if isinstance(dependencies, dict) else {}
    dev_dep_map = dev_dependencies if isinstance(dev_dependencies, dict) else {}
    script_map = scripts if isinstance(scripts, dict) else {}

    markers = set(dep_map) | set(dev_dep_map)
    if markers.intersection({"react", "react-dom", "vite", "@vitejs/plugin-react", "tailwindcss"}):
        return True

    return any(name in script_map for name in ("dev", "build", "preview"))


def _ensure_mandatory_design_tokens(content: str) -> tuple[str, list[str]]:
    normalized_content = str(content or "")
    missing_tokens = [
        token
        for token in _MANDATORY_DESIGN_TOKENS
        if token not in normalized_content
    ]
    if not missing_tokens:
        if normalized_content and not normalized_content.endswith("\n"):
            normalized_content += "\n"
        return normalized_content, []

    root_match = re.search(r":root\s*\{(?P<body>[\s\S]*?)\}", normalized_content, re.MULTILINE)
    if root_match:
        body = root_match.group("body").rstrip()
        additions = "".join(
            f"\n  {token}: {_MANDATORY_DESIGN_TOKENS[token]};"
            for token in missing_tokens
        )
        new_body = body + additions
        if new_body and not new_body.startswith("\n"):
            new_body = "\n" + new_body
        replacement = f":root {{{new_body}\n}}"
        normalized_content = (
            normalized_content[:root_match.start()]
            + replacement
            + normalized_content[root_match.end():]
        )
    else:
        token_block = "\n".join(
            [":root {"]
            + [f"  {token}: {_MANDATORY_DESIGN_TOKENS[token]};" for token in _MANDATORY_DESIGN_TOKENS]
            + ["}"]
        )
        body = normalized_content.lstrip("\n")
        normalized_content = token_block + ("\n\n" + body if body else "\n")

    if normalized_content and not normalized_content.endswith("\n"):
        normalized_content += "\n"

    return (
        normalized_content,
        [
            "src/styles/variables.css: inserted missing mandatory design tokens "
            + ", ".join(missing_tokens)
        ],
    )


def normalize_generated_path(path: str) -> str:
    normalized = str(path or "").strip().replace("\\", "/")
    if not normalized or normalized in {".", "/"}:
        return ""
    if normalized.startswith("/"):
        return ""
    if any(char in normalized for char in ("\n", "\r", "\t", "`", "<", ">", "|", ";")):
        return ""
    if "," in normalized:
        return ""
    if re.search(r"\s", normalized):
        return ""

    parts = PurePosixPath(normalized).parts
    if any(part == ".." for part in parts):
        return ""
    return normalized


def is_safe_generated_path(path: str) -> bool:
    normalized = normalize_generated_path(path)
    if not normalized:
        return False
    if normalized in _ALLOWED_REQUIRED_ROOT_FILES:
        return True
    if normalized.startswith(".env"):
        return True
    return any(normalized.startswith(prefix) for prefix in _ALLOWED_REQUIRED_ROOT_PREFIXES)


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
    if local_fetch_declared:
        return False
    return bool(re.search(r"(?<![\w$.])fetch\s*\(", src))


def _src_import_path_to_api(normalized_path: str) -> str:
    path_obj = PurePosixPath(str(normalized_path or ""))
    parts = path_obj.parts
    if not parts or parts[0] != "src":
        return "src/services/api"
    depth = max(0, len(parts) - 2)
    prefix = "../" * depth
    return f"{prefix}services/api"


def _ensure_default_export(normalized_path: str, content: str, symbol: str) -> tuple[str, bool]:
    symbol_name = str(symbol or "").strip()
    if not symbol_name or not re.fullmatch(r"[A-Za-z_]\w*", symbol_name):
        return content, False
    if re.search(r"\bexport\s+default\b", content):
        return content, False
    if not re.search(rf"\b{re.escape(symbol_name)}\b", content):
        return content, False

    trailing_newline = "\n" if content.endswith("\n") else ""
    updated = content.rstrip() + f"\n\nexport default {symbol_name};\n"
    if trailing_newline and not updated.endswith("\n"):
        updated += "\n"
    return updated, updated != content


def _ensure_named_export(content: str, symbol: str) -> tuple[str, bool]:
    symbol_name = str(symbol or "").strip()
    if not symbol_name or not re.fullmatch(r"[A-Za-z_]\w*", symbol_name):
        return content, False
    if re.search(rf"\bexport\s+(?:const|function|class)\s+{re.escape(symbol_name)}\b", content):
        return content, False
    if re.search(rf"\bexport\s*\{{[^}}]*\b{re.escape(symbol_name)}\b[^}}]*\}}", content):
        return content, False
    if not re.search(rf"\b{re.escape(symbol_name)}\b", content):
        return content, False
    updated = content.rstrip() + f"\n\nexport {{ {symbol_name} }};\n"
    return updated, updated != content


def _rewrite_hook_fetch_calls(normalized_path: str, content: str) -> tuple[str, int]:
    if not normalized_path.startswith("src/hooks/"):
        return content, 0
    if not _has_raw_fetch_call(content):
        return content, 0

    updated = str(content or "")
    replacement_count = 0
    converted_response_vars: set[str] = set()

    fetch_pattern = re.compile(
        r"(?P<prefix>\b(?:const|let|var)\s+(?P<var>[A-Za-z_]\w*)\s*=\s*)"
        r"await\s+fetch\(\s*(?P<q>['\"])/api(?P<url>[^'\"]*)(?P=q)"
        r"\s*(?:,\s*\{(?P<opts>[\s\S]*?)\})?\s*\)",
        re.MULTILINE,
    )

    def _build_api_call(url_suffix: str, opts: str | None) -> str:
        endpoint = "/" + str(url_suffix or "").lstrip("/")
        options = str(opts or "")
        method_match = re.search(r"\bmethod\s*:\s*['\"]([A-Za-z]+)['\"]", options, re.IGNORECASE)
        method = (method_match.group(1).lower() if method_match else "get").strip()
        body_match = re.search(r"\bbody\s*:\s*([^,\n}]+)", options)
        body_expr = body_match.group(1).strip() if body_match else ""

        if method in {"get", "head", "options"}:
            return f"await api.get('{endpoint}')"
        if method == "delete":
            if body_expr:
                return f"await api.delete('{endpoint}', {{ data: {body_expr} }})"
            return f"await api.delete('{endpoint}')"
        if method in {"post", "put", "patch"}:
            if body_expr:
                return f"await api.{method}('{endpoint}', {body_expr})"
            return f"await api.{method}('{endpoint}')"
        if body_expr:
            return f"await api.request({{ url: '{endpoint}', method: '{method.upper()}', data: {body_expr} }})"
        return f"await api.request({{ url: '{endpoint}', method: '{method.upper()}' }})"

    def _replace_assigned_fetch(match: re.Match[str]) -> str:
        nonlocal replacement_count
        var_name = str(match.group("var") or "").strip()
        api_call = _build_api_call(match.group("url"), match.group("opts"))
        if var_name:
            converted_response_vars.add(var_name)
        replacement_count += 1
        return f"{match.group('prefix')}{api_call}"

    updated = fetch_pattern.sub(_replace_assigned_fetch, updated)

    direct_fetch_pattern = re.compile(
        r"await\s+fetch\(\s*(?P<q>['\"])/api(?P<url>[^'\"]*)(?P=q)"
        r"\s*(?:,\s*\{(?P<opts>[\s\S]*?)\})?\s*\)",
        re.MULTILINE,
    )

    def _replace_direct_fetch(match: re.Match[str]) -> str:
        nonlocal replacement_count
        replacement_count += 1
        return _build_api_call(match.group("url"), match.group("opts"))

    updated = direct_fetch_pattern.sub(_replace_direct_fetch, updated)

    for var_name in sorted(converted_response_vars):
        updated = re.sub(
            rf"await\s+{re.escape(var_name)}\.json\(\)",
            f"{var_name}.data",
            updated,
        )
        updated = re.sub(
            rf"!\s*{re.escape(var_name)}\.ok\b",
            f"!{var_name} || {var_name}.status >= 400",
            updated,
        )

    if replacement_count > 0 and "import api from" not in updated:
        import_target = _src_import_path_to_api(normalized_path)
        import_line = f"import api from '{import_target}'"
        lines = updated.splitlines()
        insert_at = 0
        while insert_at < len(lines) and lines[insert_at].strip().startswith("import "):
            insert_at += 1
        lines.insert(insert_at, import_line)
        updated = "\n".join(lines)
        if content.endswith("\n") and not updated.endswith("\n"):
            updated += "\n"

    return updated, replacement_count


def normalize_generated_file_content(path: str, content: str) -> tuple[str, list[str]]:
    normalized_path = str(path or "").strip().replace("\\", "/")
    normalized_content = str(content or "")
    notes: list[str] = []

    if normalized_path and not normalized_path.endswith((".md", ".mdx")):
        original_content = normalized_content
        lines = normalized_content.splitlines()

        def _first_nonempty_index() -> int | None:
            for idx, line in enumerate(lines):
                if line.strip():
                    return idx
            return None

        first_idx = _first_nonempty_index()
        if first_idx is not None and re.fullmatch(r"```[\w-]*", lines[first_idx].strip()):
            del lines[first_idx]
            notes.append(f"{normalized_path}: stripped leading markdown fence")

        first_idx = _first_nonempty_index()
        if first_idx is not None and re.match(
            r"(?://|#|/\*|--|<!--)\s*FILE:\s*",
            lines[first_idx].strip(),
            re.IGNORECASE,
        ):
            del lines[first_idx]
            notes.append(f"{normalized_path}: stripped inline FILE header artifact")

        # Some providers occasionally emit a markdown blockquote marker (">")
        # before real code (for example: ">import ..."), which breaks syntax.
        first_idx = _first_nonempty_index()
        if first_idx is not None:
            first_line = lines[first_idx]
            quote_code_match = re.match(
                r"^\s*>\s*(import|export|const|let|var|function|class|interface|type|enum)\b",
                first_line,
            )
            if quote_code_match:
                lines[first_idx] = re.sub(r"^\s*>\s*", "", first_line, count=1)
                notes.append(f"{normalized_path}: stripped leading blockquote marker from code line")

        while lines:
            last_idx = len(lines) - 1
            while last_idx >= 0 and not lines[last_idx].strip():
                last_idx -= 1
            if last_idx < 0:
                break
            if re.fullmatch(r"```+", lines[last_idx].strip()):
                del lines[last_idx]
                notes.append(f"{normalized_path}: stripped trailing markdown fence")
                continue
            break

        if lines != original_content.splitlines():
            normalized_content = "\n".join(lines).strip()
            if normalized_content and original_content.endswith("\n"):
                normalized_content += "\n"

    if normalized_path == "package.json":
        try:
            package_data = json.loads(normalized_content or "{}")
        except Exception:
            package_data = None

        if isinstance(package_data, dict):
            if not isinstance(package_data.get("dependencies"), dict):
                package_data["dependencies"] = {}
            if not isinstance(package_data.get("scripts"), dict):
                package_data["scripts"] = {}

            if package_data.get("type") != "module":
                package_data["type"] = "module"
                notes.append("package.json: enforced type=module for 100% ESM backend contract")

            dependencies = package_data.setdefault("dependencies", {})
            all_dependencies = {
                **dependencies,
                **(package_data.get("devDependencies", {}) if isinstance(package_data.get("devDependencies"), dict) else {}),
            }
            if dependencies.get("axios") is None:
                dependencies["axios"] = "^1.6.2"
                notes.append("package.json: added axios dependency required by shared frontend API client")

            if _looks_like_frontend_package(package_data) and all_dependencies.get("lucide-react") is None:
                dependencies["lucide-react"] = "^0.462.0"
                notes.append("package.json: added lucide-react dependency required by frontend icon imports")

            if dependencies.get("better-sqlite3") not in {None, "^12.2.0"}:
                dependencies["better-sqlite3"] = "^12.2.0"
                notes.append("package.json: pinned better-sqlite3 to ^12.2.0")

            backend_markers = {
                "express",
                "cors",
                "better-sqlite3",
            }
            if any(dep in dependencies for dep in backend_markers):
                scripts = package_data.setdefault("scripts", {})
                if scripts.get("server") != "node --import tsx server/index.ts":
                    scripts["server"] = "node --import tsx server/index.ts"
                    notes.append("package.json: normalized server script to canonical backend entrypoint")
                expected_preserver = f"fuser -k {_DEFAULT_BACKEND_PROXY_PORT}/tcp 2>/dev/null || true"
                if scripts.get("preserver") != expected_preserver:
                    scripts["preserver"] = expected_preserver
                    notes.append(
                        "package.json: added preserver script to clear port "
                        f"{_DEFAULT_BACKEND_PROXY_PORT} before backend start"
                    )

            normalized_content = json.dumps(package_data, indent=2) + "\n"

    if normalized_path in ("vite.config.ts", "vite.config.js"):
        fixed = re.sub(
            r"(target:\s*['\"])http://localhost:\d+(['\"])",
            r"\1http://localhost:3001\2",
            normalized_content,
        )
        fixed = re.sub(
            r"(server\s*:\s*\{[\s\S]*?\bport\s*:\s*)\d+",
            r"\g<1>3000",
            fixed,
            flags=re.DOTALL,
        )
        fixed = re.sub(
            r"(preview\s*:\s*\{[\s\S]*?\bport\s*:\s*)\d+",
            r"\g<1>3000",
            fixed,
            flags=re.DOTALL,
        )
        if fixed != normalized_content:
            normalized_content = fixed
            notes.append(
                "vite.config.ts: enforced frontend port=3000 and backend proxy target=3001"
            )

        has_server_block = bool(re.search(r"\bserver\s*:\s*\{", normalized_content))
        has_preview_block = bool(re.search(r"\bpreview\s*:\s*\{", normalized_content))
        has_server_port = bool(
            re.search(
                r"server\s*:\s*\{[\s\S]*?\bport\s*:\s*\d+",
                normalized_content,
                re.DOTALL,
            )
        )
        has_preview_port = bool(
            re.search(
                r"preview\s*:\s*\{[\s\S]*?\bport\s*:\s*\d+",
                normalized_content,
                re.DOTALL,
            )
        )
        has_server_proxy = bool(
            re.search(
                r"server\s*:\s*\{[\s\S]*?proxy\s*:\s*\{[\s\S]*?['\"]/api['\"]",
                normalized_content,
                re.DOTALL,
            )
        )
        has_preview_proxy = bool(
            re.search(
                r"preview\s*:\s*\{[\s\S]*?proxy\s*:\s*\{[\s\S]*?['\"]/api['\"]",
                normalized_content,
                re.DOTALL,
            )
        )

        if has_server_block and not has_server_proxy:
            updated = re.sub(
                r"(server\s*:\s*\{)",
                rf"\1\n    proxy: {{\n      '/api': {{ target: 'http://localhost:{_DEFAULT_BACKEND_PROXY_PORT}', changeOrigin: true }},\n    }},",
                normalized_content,
                count=1,
            )
            if updated != normalized_content:
                normalized_content = updated
                notes.append(
                    "vite.config.ts: injected missing server.proxy['/api'] targeting "
                    f"localhost:{_DEFAULT_BACKEND_PROXY_PORT}"
                )
        if has_server_block and not has_server_port:
            updated = re.sub(
                r"(server\s*:\s*\{)",
                r"\1\n    port: 3000,",
                normalized_content,
                count=1,
            )
            if updated != normalized_content:
                normalized_content = updated
                notes.append("vite.config.ts: injected missing server.port=3000")

        if has_preview_block and not has_preview_proxy:
            updated = re.sub(
                r"(preview\s*:\s*\{)",
                rf"\1\n    proxy: {{\n      '/api': {{ target: 'http://localhost:{_DEFAULT_BACKEND_PROXY_PORT}', changeOrigin: true }},\n    }},",
                normalized_content,
                count=1,
            )
            if updated != normalized_content:
                normalized_content = updated
                notes.append(
                    "vite.config.ts: injected missing preview.proxy['/api'] targeting "
                    f"localhost:{_DEFAULT_BACKEND_PROXY_PORT}"
                )
        if has_preview_block and not has_preview_port:
            updated = re.sub(
                r"(preview\s*:\s*\{)",
                r"\1\n    port: 3000,",
                normalized_content,
                count=1,
            )
            if updated != normalized_content:
                normalized_content = updated
                notes.append("vite.config.ts: injected missing preview.port=3000")

        if not has_server_block:
            updated = re.sub(
                r"(export\s+default\s+defineConfig\(\{)",
                rf"\1\n  server: {{\n    port: 3000,\n    proxy: {{\n      '/api': {{ target: 'http://localhost:{_DEFAULT_BACKEND_PROXY_PORT}', changeOrigin: true }},\n    }},\n  }},",
                normalized_content,
                count=1,
            )
            if updated != normalized_content:
                normalized_content = updated
                notes.append("vite.config.ts: injected missing server block with /api proxy")

        if not has_preview_block:
            updated = re.sub(
                r"(export\s+default\s+defineConfig\(\{)",
                rf"\1\n  preview: {{\n    port: 3000,\n    proxy: {{\n      '/api': {{ target: 'http://localhost:{_DEFAULT_BACKEND_PROXY_PORT}', changeOrigin: true }},\n    }},\n  }},",
                normalized_content,
                count=1,
            )
            if updated != normalized_content:
                normalized_content = updated
                notes.append("vite.config.ts: injected missing preview block with /api proxy")

    if normalized_path == "server/index.ts":
        fixed = normalized_content
        fixed = re.sub(
            r"(process\.env\.PORT\s*\|\|\s*)\d+",
            rf"\g<1>{_DEFAULT_BACKEND_PROXY_PORT}",
            fixed,
        )
        fixed = re.sub(
            r"(process\.env\.PORT\s*\?\?\s*)\d+",
            rf"\g<1>{_DEFAULT_BACKEND_PROXY_PORT}",
            fixed,
        )
        fixed = re.sub(
            r"\b(const|let|var)\s+(PORT|port)\s*=\s*\d+\s*;",
            rf"\1 \2 = Number(process.env.PORT || {_DEFAULT_BACKEND_PROXY_PORT});",
            fixed,
            count=1,
        )
        fixed = re.sub(
            r"app\.listen\(\s*\d+\s*,",
            f"app.listen(Number(process.env.PORT || {_DEFAULT_BACKEND_PROXY_PORT}),",
            fixed,
            count=1,
        )
        fixed = re.sub(
            r"app\.listen\(\s*\d+\s*\)",
            f"app.listen(Number(process.env.PORT || {_DEFAULT_BACKEND_PROXY_PORT}))",
            fixed,
            count=1,
        )
        if fixed != normalized_content:
            normalized_content = fixed
            notes.append(
                "server/index.ts: normalized backend listen/default port handling to process.env.PORT with fallback 3001"
            )

    if normalized_path == "src/styles/variables.css":
        normalized_content, token_notes = _ensure_mandatory_design_tokens(normalized_content)
        notes.extend(token_notes)

    if normalized_path == "src/styles/global.css":
        import_pattern = re.compile(
            r'^\s*@import\s+[\'"]\.\/variables\.css[\'"];\s*$',
            re.IGNORECASE | re.MULTILINE,
        )
        has_variables_import = bool(import_pattern.search(normalized_content))
        if not has_variables_import:
            body = normalized_content.lstrip("\n")
            normalized_content = '@import "./variables.css";\n\n' + body
            notes.append('src/styles/global.css: inserted missing @import "./variables.css"; at top')
        else:
            lines = normalized_content.splitlines()
            filtered_lines = [line for line in lines if not import_pattern.match(line)]
            normalized_content = '@import "./variables.css";\n'
            if filtered_lines:
                normalized_content += "\n" + "\n".join(filtered_lines).lstrip("\n")
            if not normalized_content.endswith("\n"):
                normalized_content += "\n"

    if normalized_path.startswith("src/") and normalized_path.endswith((".ts", ".tsx", ".js", ".jsx")):
        if normalized_path.startswith("src/hooks/") and normalized_path.endswith((".ts", ".tsx")):
            rewritten_hooks, fetch_replacements = _rewrite_hook_fetch_calls(normalized_path, normalized_content)
            if rewritten_hooks != normalized_content:
                normalized_content = rewritten_hooks
                if fetch_replacements > 0:
                    notes.append(
                        f"{normalized_path}: replaced {fetch_replacements} direct fetch() call(s) with shared axios api client"
                    )

        updated_content = re.sub(r"<style\s+jsx(\s*)>", r"<style\1>", normalized_content)
        if updated_content != normalized_content:
            notes.append(f"{normalized_path}: replaced unsupported <style jsx> with standard <style>")
            normalized_content = updated_content

        if normalized_path.endswith((".ts", ".tsx")):
            # System emits React source as .tsx/.ts files; normalize accidental .jsx import extensions.
            fixed = re.sub(r"(from\s+['\"][^'\"]+)\.jsx(['\"])", r"\1.tsx\2", normalized_content)
            fixed = re.sub(r"(import\s*\(\s*['\"][^'\"]+)\.jsx(['\"])", r"\1.tsx\2", fixed)
            if fixed != normalized_content:
                notes.append(f"{normalized_path}: corrected .jsx import extensions to .tsx")
                normalized_content = fixed

        contract_pairs = [
            ("created_at", "createdAt"),
            ("updated_at", "updatedAt"),
            ("published_at", "publishedAt"),
            ("category_id", "categoryId"),
            ("category_name", "categoryName"),
            ("author_id", "authorId"),
            ("author_name", "authorName"),
            ("image_url", "imageUrl"),
            ("post_id", "postId"),
            ("user_id", "userId"),
        ]
        for snake, camel in contract_pairs:
            replaced = re.sub(rf"\b{re.escape(snake)}\b", camel, normalized_content)
            if replaced != normalized_content:
                notes.append(f"{normalized_path}: normalized public contract field {snake} -> {camel}")
                normalized_content = replaced

        normalized_content, source_replacements = _normalize_image_sources(normalized_content)
        if source_replacements > 0:
            notes.append(
                f"{normalized_path}: replaced {source_replacements} placeholder/local image source(s) with real photo URLs"
            )

    if normalized_path.startswith("src/components/") and normalized_path.endswith((".ts", ".tsx")):
        component_name = PurePosixPath(normalized_path).stem
        if (
            re.search(r"\bexport\s+default\b", normalized_content) is None
            and (
                re.search(rf"\bexport\s+const\s+{re.escape(component_name)}\b", normalized_content)
                or re.search(rf"\bexport\s+function\s+{re.escape(component_name)}\b", normalized_content)
            )
        ):
            normalized_content, changed = _ensure_default_export(normalized_path, normalized_content, component_name)
            if changed:
                notes.append(f"{normalized_path}: added missing default export for {component_name}")

        # Keep component import styles resilient: allow both default and named imports.
        if re.search(r"\bexport\s+default\b", normalized_content):
            named_default_match = re.search(
                r"\bexport\s+default\s+function\s+([A-Za-z_]\w*)\b",
                normalized_content,
            ) or re.search(
                r"\bexport\s+default\s+([A-Za-z_]\w*)\b",
                normalized_content,
            )
            default_symbol = (
                str(named_default_match.group(1) or "").strip()
                if named_default_match else component_name
            )
            normalized_content, named_added = _ensure_named_export(normalized_content, default_symbol)
            if named_added:
                notes.append(
                    f"{normalized_path}: added named export for {default_symbol} to prevent default/named import mismatch"
                )

    if normalized_path.startswith("src/services/") and normalized_path.endswith((".ts", ".tsx")):
        if re.search(r"\bexport\s+default\b", normalized_content) is None:
            service_name = PurePosixPath(normalized_path).stem
            default_symbol = ""
            if re.search(rf"\bexport\s+const\s+{re.escape(service_name)}\b", normalized_content):
                default_symbol = service_name
            elif re.search(rf"\bexport\s+function\s+{re.escape(service_name)}\b", normalized_content):
                default_symbol = service_name
            else:
                first_export = re.search(
                    r"\bexport\s+(?:const|function)\s+([A-Za-z_]\w*)\b",
                    normalized_content,
                )
                if first_export:
                    default_symbol = str(first_export.group(1) or "").strip()
            if default_symbol:
                normalized_content, changed = _ensure_default_export(
                    normalized_path,
                    normalized_content,
                    default_symbol,
                )
                if changed:
                    notes.append(f"{normalized_path}: added missing default export ({default_symbol})")

    if normalized_path == "src/services/api.ts":
        if "from 'axios'" not in normalized_content and 'from "axios"' not in normalized_content:
            lines = normalized_content.splitlines()
            insert_at = 0
            while insert_at < len(lines) and lines[insert_at].strip().startswith("import "):
                insert_at += 1
            lines.insert(insert_at, "import axios from 'axios';")
            normalized_content = "\n".join(lines)
            if content.endswith("\n") and not normalized_content.endswith("\n"):
                normalized_content += "\n"
            notes.append("src/services/api.ts: added missing axios import for shared api client")

        if not re.search(r"\b(?:const|let|var)\s+api\s*=", normalized_content):
            bootstrap = "export const api = axios.create({ baseURL: '/api' });\n"
            lines = normalized_content.splitlines()
            insert_at = 0
            while insert_at < len(lines) and lines[insert_at].strip().startswith("import "):
                insert_at += 1
            lines.insert(insert_at, bootstrap.rstrip("\n"))
            normalized_content = "\n".join(lines)
            if content.endswith("\n") and not normalized_content.endswith("\n"):
                normalized_content += "\n"
            notes.append("src/services/api.ts: added missing named export `api` (axios client)")

        fixed = re.sub(
            r"(\(\s*response\s*\)\s*=>\s*)response\.data\b",
            r"\1response",
            normalized_content,
        )
        if fixed != normalized_content:
            notes.append("src/services/api.ts: normalized axios interceptor to return AxiosResponse")
            normalized_content = fixed

        fetch_fixed = re.sub(
            r"(\b(?:const|let|var)\s+\w+\s*=\s*)await\s+fetch\(\s*`?\$\{BASE_URL\}(/[^`'\"]*)`?\s*(?:,\s*\{[^}]*\})?\)",
            r"\1await api.get('\2')",
            normalized_content,
        )
        fetch_fixed = re.sub(
            r"(\b(?:const|let|var)\s+\w+\s*=\s*)await\s+fetch\(\s*['\"]/api([^'\"]*)['\"]\s*(?:,\s*\{[^}]*\})?\)",
            r"\1await api.get('/\2')",
            fetch_fixed,
        )
        fetch_fixed = re.sub(
            r"await\s+fetch\(\s*`?\$\{BASE_URL\}(/[^`'\"]*)`?\s*(?:,\s*\{[^}]*\})?\)",
            r"await api.get('\1')",
            fetch_fixed,
        )
        fetch_fixed = re.sub(
            r"await\s+fetch\(\s*['\"]/api([^'\"]*)['\"]\s*(?:,\s*\{[^}]*\})?\)",
            r"await api.get('/\1')",
            fetch_fixed,
        )
        fetch_fixed = re.sub(r"await\s+([A-Za-z_]\w*)\.json\(\)", r"\1.data", fetch_fixed)
        if fetch_fixed != normalized_content:
            normalized_content = fetch_fixed
            notes.append("src/services/api.ts: replaced direct fetch() usage with shared axios api client calls")

        normalized_content, named_changed = _ensure_named_export(normalized_content, "api")
        if named_changed:
            notes.append("src/services/api.ts: added missing named export `api`")

        rewritten_default = re.sub(
            r"\bexport\s+default\s+[^;\n]+;?",
            "",
            normalized_content,
        )
        if rewritten_default != normalized_content:
            normalized_content = rewritten_default.rstrip() + "\n"
            notes.append("src/services/api.ts: normalized default export target to shared `api` client")

        normalized_content, changed = _ensure_default_export("src/services/api.ts", normalized_content, "api")
        if changed:
            notes.append("src/services/api.ts: added missing default export")

    if normalized_path == "src/types/index.ts":
        page_match = re.search(
            r"(export\s+interface\s+Page\s*\{)([\s\S]*?)(\n\})",
            normalized_content,
            re.MULTILINE,
        )
        if page_match:
            page_body = str(page_match.group(2) or "")
            page_fields = {
                field.strip()
                for field in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\??\s*:", page_body)
            }
            required_page_fields = {"id", "slug", "title", "createdAt"}
            disallowed_page_fields = {"content", "description"}
            if (page_fields & disallowed_page_fields) or not required_page_fields.issubset(page_fields):
                canonical_page = (
                    "export interface Page {\n"
                    "  id: number;\n"
                    "  slug: string;\n"
                    "  title: string;\n"
                    "  createdAt: string;\n"
                    "}"
                )
                normalized_content = (
                    normalized_content[:page_match.start()]
                    + canonical_page
                    + normalized_content[page_match.end():]
                )
                notes.append(
                    "src/types/index.ts: normalized `Page` interface to canonical contract "
                    "(id, slug, title, createdAt)"
                )

    if normalized_path.startswith("server/") and normalized_path.endswith((".ts", ".js")):
        if normalized_path == "server/db/database.ts":
            fixed = normalized_content
            has_db_path_symbol = "DB_PATH" in fixed
            has_db_open = bool(re.search(r"\bnew\s+Database\s*\(\s*DB_PATH\s*\)", fixed))
            has_dir_creation = bool(
                re.search(r"mkdirSync\s*\([^)]*\{\s*recursive\s*:\s*true\s*\}\s*\)", fixed, re.DOTALL)
            )
            if has_db_path_symbol and has_db_open and not has_dir_creation:
                if not re.search(r"^\s*import\s+fs\s+from\s+['\"](?:node:)?fs['\"]\s*;?\s*$", fixed, re.MULTILINE):
                    import_matches = list(re.finditer(r"^\s*import[^\n]*\n", fixed, re.MULTILINE))
                    if import_matches:
                        insert_at = import_matches[-1].end()
                        fixed = fixed[:insert_at] + "import fs from 'fs';\n" + fixed[insert_at:]
                    else:
                        fixed = "import fs from 'fs';\n" + fixed

                open_match = re.search(
                    r"^(?P<indent>\s*).*\bnew\s+Database\s*\(\s*DB_PATH\s*\)",
                    fixed,
                    re.MULTILINE,
                )
                if open_match:
                    indent = open_match.group("indent")
                    guard = (
                        f"{indent}const dbDir = dirname(DB_PATH);\n"
                        f"{indent}if (!fs.existsSync(dbDir)) {{\n"
                        f"{indent}  fs.mkdirSync(dbDir, {{ recursive: true }});\n"
                        f"{indent}}}\n\n"
                    )
                    fixed = fixed[: open_match.start()] + guard + fixed[open_match.start() :]
                    notes.append(
                        f"{normalized_path}: ensured SQLite directory exists before opening DB_PATH"
                    )
                normalized_content = fixed

        # better-sqlite3 does not accept JS booleans as bind values.
        # Auto-convert common boolean columns in seed data objects:
        #   featured: true  -> featured: 1
        #   featured: false -> featured: 0
        fixed = normalized_content
        for column in ("featured", "published", "active", "enabled", "is_admin", "verified"):
            fixed = re.sub(rf"\b{column}:\s*true\b", f"{column}: 1", fixed)
            fixed = re.sub(rf"\b{column}:\s*false\b", f"{column}: 0", fixed)
        
        # Fix array/positional notation: , true] → , 1]  and , false] → , 0]
        # Only inside arrays e.g. [, true]
        fixed = re.sub(r",\s*true(\s*\])", r", 1\1", fixed)
        fixed = re.sub(r",\s*false(\s*\])", r", 0\1", fixed)

        if fixed != normalized_content:
            notes.append(
                f"{normalized_path}: converted boolean bind values to integers "
                f"(better-sqlite3 does not accept JS booleans)"
            )
            normalized_content = fixed

        # Enforce ESM purity for backend files by rewriting common CJS patterns.
        inline_requires = re.findall(
            r"^\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*require\((['\"])([^'\"]+)\2\)\s*;?\s*$",
            normalized_content,
            flags=re.MULTILINE,
        )
        import_lines: list[str] = []
        for var_name, _quote, module_name in inline_requires:
            normalized_content = re.sub(
                rf"^\s*(?:const|let|var)\s+{re.escape(var_name)}\s*=\s*require\(['\"]{re.escape(module_name)}['\"]\)\s*;?\s*$\n?",
                "",
                normalized_content,
                flags=re.MULTILINE,
            )
            import_stmt = f"import {var_name} from '{module_name}';"
            if import_stmt not in import_lines:
                import_lines.append(import_stmt)
                notes.append(
                    f"{normalized_path}: auto-converted inline require('{module_name}') to ESM import"
                )

        if import_lines:
            header = "\n".join(import_lines) + "\n"
            if not normalized_content.lstrip().startswith("\n"):
                normalized_content = header + normalized_content.lstrip("\n")
            else:
                normalized_content = header + normalized_content

        def _convert_module_exports_object(match: re.Match[str]) -> str:
            body = str(match.group("body") or "").strip()
            if not body:
                notes.append(f"{normalized_path}: removed empty CommonJS module.exports object")
                return ""
            notes.append(f"{normalized_path}: converted CommonJS module.exports object to ESM named export")
            return f"export {{ {body} }};"

        normalized_content = re.sub(
            r"module\.exports\s*=\s*\{\s*(?P<body>[^}]*)\s*\}\s*;?",
            _convert_module_exports_object,
            normalized_content,
            flags=re.MULTILINE,
        )

        def _convert_module_exports_default(match: re.Match[str]) -> str:
            identifier = str(match.group("identifier") or "").strip()
            if not identifier:
                notes.append(f"{normalized_path}: removed CommonJS module.exports assignment")
                return ""
            notes.append(f"{normalized_path}: converted CommonJS module.exports default to ESM export default")
            return f"export default {identifier};"

        normalized_content = re.sub(
            r"module\.exports\s*=\s*(?P<identifier>[A-Za-z_$][\w$]*)\s*;?",
            _convert_module_exports_default,
            normalized_content,
            flags=re.MULTILINE,
        )

        if "module.exports" in normalized_content:
            normalized_content = re.sub(r"module\.exports[^\n]*\n?", "", normalized_content)
            notes.append(f"{normalized_path}: removed unsupported CommonJS module.exports residue")

        normalized_content, source_replacements = _normalize_image_sources(normalized_content)
        if source_replacements > 0:
            notes.append(
                f"{normalized_path}: replaced {source_replacements} placeholder/local image source(s) with real photo URLs"
            )

    if normalized_path == "server/db/database.ts":
        # Force DB path inside sandbox — ../../ escapes the sandbox dir
        fixed = re.sub(
            r"join\(__dirname,\s*['\"](?:\.\.\/)*data\/",
            "join(__dirname, '../data/",
            normalized_content
        )
        # Also fix process.env.DB_PATH fallback path
        fixed = re.sub(
            r"(process\.env\.DB_PATH\s*\|\|\s*)join\(__dirname,\s*['\"](?:\.\.\/)+data\/",
            r"\1join(__dirname, '../data/",
            fixed
        )
        if fixed != normalized_content:
            notes.append("server/db/database.ts: corrected DB path to stay inside sandbox (removed ../../)")
            normalized_content = fixed

    # Auto-fix wrong controller import paths in route files.
    if normalized_path.startswith("server/routes/") and normalized_path.endswith(".ts"):
        fixed = re.sub(
            r"from\s+['\"]\.\/([A-Za-z0-9_-]+Controller(?:\.js)?)['\"]",
            r"from '../controllers/\1'",
            normalized_content,
        )
        if fixed != normalized_content:
            notes.append(
                f"{normalized_path}: auto-fixed controller import path from './' to '../controllers/'"
            )
            normalized_content = fixed

    return normalized_content, notes
