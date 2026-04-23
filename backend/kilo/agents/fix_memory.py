import json
import os
from typing import Dict, Any

MEMORY_FILE = os.path.join(os.path.dirname(__file__), "fix_memory.json")

def load_memory() -> Dict[str, Any]:
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_memory(memory: Dict[str, Any]) -> None:
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memory, f, indent=2)
    except Exception:
        pass

def update_memory(memory: Dict[str, Any], actions: list) -> Dict[str, Any]:
    for action in actions:
        file_path = action.get("file")
        content = action.get("content", "")
        if not file_path or not content:
            continue
            
        if file_path not in memory:
            memory[file_path] = {}
            
        # Detect export type safely
        if "export default" in content:
            memory[file_path]["export"] = "default"
        elif "export const" in content or "export function" in content or "export let" in content:
            memory[file_path]["export"] = "named"
            
    save_memory(memory)
    return memory
