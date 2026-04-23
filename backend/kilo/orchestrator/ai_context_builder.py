import json
import os
from .ast_extractor import ast_extractor
from .project_map import ProjectMapManager

class AIContextBuilder:
    """
    Combines strict structured memory (project_map.json) with
    human-readable architecture context (ASTExtractor) for the AI.
    """
    def __init__(self, project_map: ProjectMapManager):
        self.project_map = project_map

    @staticmethod
    def _normalize_path(path: str) -> str:
        return str(path or "").strip().replace("\\", "/")

    def _allowed_paths(self, stage_name: str = "", focus_paths: list[str] | None = None) -> set[str]:
        stage = str(stage_name or "").strip().lower()
        allowed = {
            self._normalize_path(path)
            for path in (focus_paths or [])
            if self._normalize_path(path)
        }

        shared_by_stage = {
            "backend": {
                "server/db/database.ts",
                "src/types/index.ts",
            },
            "frontend": {
                "src/main.tsx",
                "src/services/api.ts",
                "src/types/index.ts",
            },
            "architecture": {
                "src/services/api.ts",
                "src/types/index.ts",
            },
        }
        allowed.update(shared_by_stage.get(stage, set()))
        return {path for path in allowed if path}

    def _path_matches_stage(self, rel_path: str, stage_name: str, allowed_paths: set[str]) -> bool:
        return True

    def build_context(self, stage_name: str = "", focus_paths: list[str] | None = None, compact: bool = False) -> str:
        """
        Produce a combined context string containing both the structured
        project map and the clean architecture summary by reading all
        generated files from the sandbox.
        """
        sandbox_dir = self.project_map.sandbox_dir
        file_inventory = {}
        allowed_paths = self._allowed_paths(stage_name, focus_paths)

        arch_context = ""
        if not compact:
            # 1. Read all generated files from the sandbox
            if os.path.exists(sandbox_dir):
                for root, dirs, files in os.walk(sandbox_dir):
                    dirs[:] = [
                        d for d in dirs
                        if d not in {"node_modules", ".git", "dist", "__pycache__"}
                        and d != ".lovable"
                        and not d.startswith(".")
                    ]
                    if ".lovable" in root:
                        continue
                    for file in files:
                        full_path = os.path.join(root, file)
                        if file.endswith((".ts", ".tsx", ".ts", ".tsx", ".css", ".html", ".json", ".py")):
                            try:
                                with open(full_path, "r", encoding="utf-8") as f:
                                    rel_path = os.path.relpath(full_path, sandbox_dir)
                                    if not self._path_matches_stage(rel_path, stage_name, allowed_paths):
                                        continue
                                    file_inventory[rel_path] = f.read()
                            except Exception:
                                pass

            # 2. Architecture Context (ASTExtractor)
            arch_context = ast_extractor.extract_all(file_inventory)
        
        # 3. Project Map Context (Dependency Graph)
        map_context = "\n### PROJECT DEPENDENCY GRAPH (ProjectMap)\n"
        for f in self.project_map.data.get("files", []):
            fname = f.get("relative_path") or f.get("filename")
            if not self._path_matches_stage(fname, stage_name, allowed_paths):
                continue
            imports = ", ".join(f.get("imports", []))
            api_calls = ", ".join(f.get("api_calls", []))
            map_context += f"- **{fname}**:\n"
            if imports: map_context += f"  - Imports: {imports}\n"
            if api_calls: map_context += f"  - API Calls: {api_calls}\n"

        if compact:
            return map_context
        return arch_context + "\n" + map_context
