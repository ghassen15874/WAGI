
import subprocess
import json
import os
import re

class ProjectAnalyzer:
    """
    Analyzes generated JS/TS code to extract exports, imports, and structure.
    Uses Node + Acorn for real AST parsing, with a regex fallback.
    """

    def __init__(self, script_path: str = None):
        self.script_path = script_path or os.path.join(
            os.path.dirname(__file__), "..", "..", "scripts", "analyze_ast.js"
        )

    def analyze_file(self, file_path: str, relative_path: str | None = None) -> dict:
        """Analyze a file on disk and return metadata."""
        normalized_relative = (relative_path or file_path).replace("\\", "/")
        try:
            # 1. Try real AST analysis using Node
            result = subprocess.run(
                ["node", self.script_path, file_path, normalized_relative],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                data["relative_path"] = str(data.get("relative_path") or normalized_relative)
                data["filename"] = os.path.basename(data["relative_path"])
                return data
        except Exception:
            pass

        # 2. Fallback: Robust Regex Analysis (if Node/Acorn fails)
        return self.analyze_content_regex(file_path, normalized_relative)

    def analyze_content_regex(self, file_path: str, relative_path: str | None = None) -> dict:
        """Regex-based fallback for AST parsing."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except:
            rel = (relative_path or file_path).replace("\\", "/")
            return {"filename": os.path.basename(rel), "relative_path": rel, "exports": [], "imports": []}

        rel = (relative_path or file_path).replace("\\", "/")

        metadata = {
            "filename": os.path.basename(rel),
            "relative_path": rel,
            "exports": [],
            "imports": [],
            "api_calls": [],
            "ast_summary": {"functions": [], "classes": []}
        }

        # Find exports
        # export function Name
        for m in re.finditer(r'export\s+function\s+([A-Za-z0-9_]+)', content):
            metadata["exports"].append(m.group(1))
            metadata["ast_summary"]["functions"].append(m.group(1))
        
        # export const Name =
        for m in re.finditer(r'export\s+const\s+([A-Za-z0-9_]+)\s*=', content):
            metadata["exports"].append(m.group(1))

        # export default function Name
        for m in re.finditer(r'export\s+default\s+(?:function\s+|class\s+)?([A-Za-z0-9_]+)', content):
            metadata["exports"].append(m.group(1))

        # Find imports
        for m in re.finditer(r'import\s+.*\s+from\s+[\'"](.+)[\'"]', content):
            metadata["imports"].append(m.group(1))

        # Find API calls (e.g. axios.get('/api/...'))
        for m in re.finditer(r'[\'"](/api/[^\'"]+)[\'"]', content):
            metadata["api_calls"].append(m.group(1))

        return metadata
