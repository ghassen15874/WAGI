from typing import List, Dict, Any

def apply_diff_guard(actions: List[Dict[str, Any]], memory: Dict[str, Any]) -> List[Dict[str, Any]]:
    filtered_actions = []
    
    for action in actions:
        file_path = action.get("file")
        content = action.get("content", "")
        
        if not file_path or not content:
            filtered_actions.append(action)
            continue
            
        if file_path in memory:
            mem = memory[file_path]
            export_pref = mem.get("export")
            
            if export_pref == "default":
                if "export default" not in content and "module.exports" not in content:
                    print(f"[DiffGuard] REJECTED {file_path}: Missing expected default export")
                    continue
            elif export_pref == "named":
                if "export const" not in content and "export function" not in content and "export let" not in content and "exports." not in content:
                    print(f"[DiffGuard] REJECTED {file_path}: Missing expected named export")
                    continue
                    
        filtered_actions.append(action)
        
    return filtered_actions
