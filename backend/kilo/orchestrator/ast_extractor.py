import re
import json
import os
from typing import Optional


class ASTExtractor:
    """
    Regex-based project map builder. Takes an in-memory file_inventory dict
    (path → content) and produces a compact context string for the LLM.
    """

    def extract_all(self, file_inventory: dict) -> str:
        """
        Build a compact project map from all written files.
        Returns a string the LLM can use as context.
        """
        sections = {
            "components": [],
            "pages": [],
            "hooks": [],
            "utils": [],
            "server": [],
            "config": [],
            "styles": [],
        }

        for path, content in file_inventory.items():
            summary = self._extract_one(path, content)
            if not summary:
                continue

            if "/components/" in path:
                sections["components"].append(summary)
            elif "/pages/" in path:
                sections["pages"].append(summary)
            elif "/hooks/" in path:
                sections["hooks"].append(summary)
            elif "/utils/" in path or "/services/" in path or "/context/" in path:
                sections["utils"].append(summary)
            elif path.startswith("server/"):
                sections["server"].append(summary)
            elif path in ("package.json", "vite.config.ts"):
                sections["config"].append(summary)
            elif path.endswith(".css"):
                sections["styles"].append(summary)

        lines = ["### PROJECT MAP (context for compatibility)"]

        if sections["styles"]:
            lines.append("\n**Design System:**")
            lines.extend(sections["styles"])

        if sections["config"]:
            lines.append("\n**Config:**")
            lines.extend(sections["config"])

        if sections["components"]:
            lines.append("\n**Components:**")
            lines.extend(sections["components"])

        if sections["pages"]:
            lines.append("\n**Pages:**")
            lines.extend(sections["pages"])

        if sections["hooks"]:
            lines.append("\n**Hooks:**")
            lines.extend(sections["hooks"])

        if sections["utils"]:
            lines.append("\n**Utils:**")
            lines.extend(sections["utils"])

        if sections["server"]:
            lines.append("\n**Server:**")
            lines.extend(sections["server"])

        lines.append("\nUse these existing exports when importing. DO NOT rename or duplicate them.")
        return "\n".join(lines)

    def _extract_one(self, path: str, content: str) -> Optional[str]:
        """Extract one file into a compact summary line."""

        # ── CSS files ───────────────────────────────────────────────────────
        if path.endswith(".css"):
            vars_found = re.findall(r'(--[\w-]+)\s*:\s*([^;]+);', content)
            if not vars_found:
                return None
            important = [
                f"{k}:{v.strip()}"
                for k, v in vars_found
                if any(x in k for x in [
                    "primary", "secondary", "cta", "background",
                    "text", "font", "heading", "body"
                ])
            ]
            if important:
                return f"  `{path}` → {', '.join(important[:6])}"
            return None

        # ── package.json ─────────────────────────────────────────────────────
        if path == "package.json":
            try:
                pkg = json.loads(content)
                deps = list(pkg.get("dependencies", {}).keys())
                dev = list(pkg.get("devDependencies", {}).keys())
                all_deps = deps + dev
                notable = [d for d in all_deps if d in [
                    "react", "react-dom", "react-router-dom",
                    "express", "better-sqlite3", "chart.js",
                    "react-chartjs-2", "axios", "cors",
                    "concurrently", "@vitejs/plugin-react",
                    "bcryptjs", "jsonwebtoken", "dotenv",
                ]]
                script = pkg.get("scripts", {}).get("dev", "")
                return (
                    f"  `{path}` → "
                    f"deps:[{', '.join(notable)}] "
                    f"dev:\"{script[:60]}\""
                )
            except Exception:
                return None

        # ── Server JS files ───────────────────────────────────────────────────
        if path.startswith("server/") and path.endswith(".ts"):
            routes = re.findall(
                r'(?:router|app)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
                content
            )
            tables = re.findall(
                r'CREATE TABLE IF NOT EXISTS\s+(\w+)',
                content, re.IGNORECASE
            )
            requires = re.findall(
                r'require\(["\'](\.[^"\']+)["\']', content
            )
            local_requires = [
                r.split("/")[-1].replace(".ts", "")
                for r in requires
            ]
            
            # Extract server exports (e.g. exports.protect =, module.exports.login = )
            exports = set(re.findall(r'(?:module\.)?exports\.(\w+)\s*=', content))
            
            # Catch destructured module.exports = { a, b, c }
            destructured = re.search(r'module\.exports\s*=\s*\{([^}]+)\}', content)
            if destructured:
                exports.update(re.findall(r'(\w+)\s*[,:\}]', destructured.group(1)))

            # Internal logic markers (init, setup, start, schema)
            logic = re.findall(r'(?:function|const|var|async)\s+(\w*(?:init|setup|start|schema|db)\w*)\s*[(=]', content, re.IGNORECASE)

            # Also try to catch module.exports = router or class
            is_router = "express.Router()" in content

            parts = []
            if exports:
                parts.append(f"exports:[{', '.join(sorted(list(exports))[:8])}]")
            elif is_router:
                parts.append("export:router")
            
            if logic:
                parts.append(f"logic:[{', '.join(set(logic[:4]))}]")
                
            if routes:
                route_strs = [f"{m.upper()} {r}" for m, r in routes[:4]]
                parts.append(f"routes:[{', '.join(route_strs)}]")
            if tables:
                parts.append(f"tables:[{', '.join(tables)}]")
            if local_requires:
                parts.append(f"requires:[{', '.join(local_requires[:3])}]")

            if parts:
                return f"  `{path}` → {' | '.join(parts)}"
            return f"  `{path}` ✓"

        # ── JSX/JS frontend files ─────────────────────────────────────────────
        if path.endswith((".tsx", ".tsx", ".ts", ".ts")) and not path.startswith("server/"):
            # Default export name
            exp_match = re.search(
                r'export\s+default\s+(?:function\s+)?(\w+)', content
            )
            export_name = exp_match.group(1) if exp_match else None

            # Named exports
            named_exports = re.findall(
                r'export\s+(?:const|function|class)\s+(\w+)', content
            )

            # Local imports
            local_imports = re.findall(
                r'import\s+.*?from\s+["\'](\./[^"\']+|\.\./[^"\']+)["\']',
                content
            )
            import_names = [
                i.split("/")[-1]
                 .replace(".tsx", "")
                 .replace(".tsx", "")
                 .replace(".ts", "")
                for i in local_imports
            ]

            # Routes defined (for App.tsx)
            routes = re.findall(r'path=["\']([^"\']+)["\']', content)

            parts = []
            if export_name:
                parts.append(f"export:{export_name}")
            elif named_exports:
                parts.append(f"exports:[{', '.join(named_exports[:4])}]")
            if import_names:
                parts.append(f"imports:[{', '.join(import_names[:5])}]")
            if routes:
                parts.append(f"routes:[{', '.join(routes[:4])}]")

            if parts:
                return f"  `{path}` → {' | '.join(parts)}"
            return f"  `{path}` ✓"

        return None


ast_extractor = ASTExtractor()
