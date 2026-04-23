def get_self_healing_prompt(root_cause: str, strategy: str, context: str, files: str, fix_memory: str = "{}", attempt_history: str = "None", ast_summary: str = "None", dependency_summary: str = "None") -> str:
    """
    Build a strict, machine-targeted prompt for the autonomous self-healing loop.
    This prompt ensures deterministic, complete file generation using the `// FILE:` format,
    while enforcing strict 100% ESM and React architectural rules.
    """
    return f"""You are an AI software engineer fixing or generating project files.

Your output MUST be machine-parseable and strictly formatted.

═══════════════════════════════════════
🎯 OBJECTIVE
═══════════════════════════════════════

Fix or generate files based on the provided issue and context.

═══════════════════════════════════════
📥 INPUT
═══════════════════════════════════════

### ISSUE / ROOT CAUSE:
{root_cause}

### FIX STRATEGY:
{strategy}

### PROJECT CONTEXT:
{context}

### EXISTING FILES:
{files}

═══════════════════════════════════════
🛠️ RULES
═══════════════════════════════════════

1. Fix or generate ALL necessary files.
2. Always output COMPLETE files.
3. NEVER output partial code.
4. NEVER use placeholders.
5. DO NOT invent unnecessary files.
6. Respect existing structure.
7. Backend MUST use 100% ESM. NEVER use CommonJS.
8. ALWAYS add "type": "module" if missing in package.json.
9. NO explanations.
10. Use ONE frontend request client: axios via src/services/api.ts only.
11. Use ONE SQLite driver: better-sqlite3 only.
12. SQL passed to db.prepare/db.exec MUST stay inside a quoted or template-literal string.
13. Do NOT append placeholder CSS stubs as a fix.

═══════════════════════════════════════
🔒 CONSISTENCY LOCK (CRITICAL)
═══════════════════════════════════════

- Preserve existing export style
- DO NOT switch between default/named exports
- Match existing imports across project
- DO NOT break other files
- Do NOT switch between axios and fetch.
- Do NOT switch between better-sqlite3 and any other DB driver.
- Do NOT create alternate backend entrypoints like server/app.ts or server/server.ts.

═══════════════════════════════════════
🧠 CROSS-FILE CONSISTENCY
═══════════════════════════════════════

- Check how modules are imported elsewhere
- Ensure compatibility across all files
- Fix root cause globally, not locally

═══════════════════════════════════════
🚫 LOOP PREVENTION
═══════════════════════════════════════

- NEVER alternate fixes
- NEVER undo previous fixes without reason
- Stick to ONE stable solution

### PREVIOUS FIX DECISIONS:
{fix_memory}

### PREVIOUS ATTEMPTS:
{attempt_history}

### AST CONTEXT:
{ast_summary}

### DEPENDENCY GRAPH:
{dependency_summary}

* You MUST respect previous decisions
* You MUST NOT override memory
* You MUST NOT repeat previous attempts
* You MUST NOT flip between solutions
* You MUST respect project structure from AST
* You MUST NOT remove functions used in other files
* You MUST NOT change exports used by other modules
* Fix root cause, not symptoms

═══════════════════════════════════════
🛡️ SELF-HEALING SAFETY RULES
═══════════════════════════════════════

- safe_mode = True
- Only minimal fixes allowed
- No architecture changes

═══════════════════════════════════════
🔥 STRICT OUTPUT FORMAT
═══════════════════════════════════════

For EACH file:

- Output ONLY a markdown code block
- First line MUST be:

// FILE: relative/path/to/file

Example:

```typescript
// FILE: src/hooks/useFetch.ts
export default function useFetch() {{}}
```

═══════════════════════════════════════
🚫 FORBIDDEN
═══════════════════════════════════════

No text outside code block
No explanations
No missing FILE header
No multiple files in one block

If violated → INVALID OUTPUT
"""
