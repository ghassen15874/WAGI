import json
import os
import re

class ProjectMapManager:
    """
    Manages the project_map.json file in the sandbox.
    Tracks file metadata, exports, and imports to build a dependency graph.
    """

    def __init__(self, sandbox_dir: str):
        self.sandbox_dir = sandbox_dir
        self.map_path = os.path.join(sandbox_dir, "project_map.json")
        self.data = {"files": []}
        self.load()

    def load(self):
        """Load existing map if it exists."""
        if os.path.exists(self.map_path):
            try:
                with open(self.map_path, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
            except:
                self.data = {"files": []}

    def reset(self):
        """Clear the project map — call this at the start of each new generation."""
        self.data = {"files": []}
        if os.path.exists(self.map_path):
            try:
                os.remove(self.map_path)
            except Exception:
                pass

    def save(self):
        """Save map to disk."""
        os.makedirs(os.path.dirname(self.map_path), exist_ok=True)
        with open(self.map_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2)

    def add_file(self, metadata: dict):
        """
        Add or update a file in the project map.
        Metadata should be from ProjectAnalyzer.
        """
        relative_path = str(metadata.get("relative_path") or metadata.get("filename") or "").strip().replace("\\", "/")
        if not relative_path:
            return

        metadata = dict(metadata)
        metadata["relative_path"] = relative_path
        metadata["filename"] = os.path.basename(relative_path)

        # Replace if exists, else append
        self.data["files"] = [
            f for f in self.data["files"]
            if str(f.get("relative_path") or f.get("filename") or "").replace("\\", "/") != relative_path
        ]
        self.data["files"].append(metadata)
        self.save()

    def get_summary_for_ai(self) -> str:
        """ Generate a concise summary of the project structure for the AI. """
        if not self.data["files"]:
            return "No files generated yet."

        summary = "### EXISTING PROJECT STRUCTURE (PROJECT MAP)\n"
        for f in self.data["files"]:
            fname = f.get("relative_path") or f.get("filename")
            exports = ", ".join(f.get("exports", []))
            summary += f"- **{fname}**: Exports: [{exports}]\n"
            if f.get("ast_summary", {}).get("functions"):
                funcs = ", ".join(f.get("ast_summary").get("functions"))
                summary += f"  - Internal Functions: {funcs}\n"
        
        summary += "\nUse these existing exports when importing. DO NOT rename or duplicate them."
        return summary
