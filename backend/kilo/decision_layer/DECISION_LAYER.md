# Decision Layer

The Decision Layer is an LLM-based intent-classification and routing system
added **around** the existing AI Builder generation pipeline.
It does not modify the existing code generation system.

---

## Architecture

```
POST /api/chat
  └─> DecisionRouter.route()
        │
        ├─ [First Pass] DecisionLayerService.decide()
        │       └─ LLM → DecisionResult JSON
        │
        ├─ [Context? Yes] ProjectContextBuilder.fulfill_context_requests()
        │       ├─ file_tree
        │       ├─ read_file
        │       ├─ search
        │       ├─ ast        (wraps ast_extractor.py)
        │       ├─ dependency_graph (wraps project_map.py)
        │       └─ memory     (.lovable/memory.json)
        │
        ├─ [Second Pass] DecisionLayerService.decide_with_context()
        │       └─ LLM → refined DecisionResult JSON
        │
        └─> DecisionRouter._dispatch()
              ├─ existing_generation_path → start_generation_task() [UNCHANGED]
              ├─ normal_chat_path         → NormalChatHandler (SSE stream)
              ├─ project_*_path           → ProjectActionExecutor (SSE stream)
              └─ clarification_path       → short question (SSE stream)
```

The **existing `POST /api/generate`** route is **never touched**.

---

## Files

| File | Purpose |
|---|---|
| `types.py` | `DecisionResult`, `ContextRequest`, type literals, validation |
| `prompt.py` | LLM system prompt + message builder |
| `service.py` | `DecisionLayerService` — two-pass LLM calls |
| `context_builder.py` | `ProjectContextBuilder` — read-only context collection |
| `chat_handler.py` | `NormalChatHandler` — conversational replies |
| `project_action_executor.py` | `ProjectActionExecutor` — all project actions |
| `router.py` | `DecisionRouter` — orchestrates the full pipeline |
| `__init__.py` | Package re-exports |

New route: `backend/kilo/server/routes/chat.py` → `POST /api/chat`

---

## Intent Taxonomy

| Intent | Route |
|---|---|
| `new_generation` | `existing_generation_path` |
| `normal_chat` | `normal_chat_path` |
| `modify_project` | `project_context_builder` → `project_modification_path` |
| `add_feature` | `project_context_builder` → `project_modification_path` |
| `delete_file` | `project_context_builder` → `delete_file_path` |
| `rename_file` | `project_context_builder` → `rename_file_path` |
| `explain_file` | `project_context_builder` → `project_explanation_path` |
| `ask_about_project` | `project_context_builder` → `project_explanation_path` |
| `generate_project_summary` | `project_context_builder` → `project_summary_path` |
| `inspect_project` | `inspect_project_path` |
| `needs_more_context` | `project_context_builder` → re-classify |
| `unknown` | `clarification_path` |

---

## API

### `POST /api/chat`
Same authentication and key-resolution as `/api/generate`.

**Request body:**
```json
{
  "message": "Add dark mode to the dashboard",
  "provider": "openai",
  "model": "gpt-4o",
  "model_id": "",
  "api_key": "",
  "projectId": "abc-123",
  "chat_history": []
}
```

**Response — generation path:**
```json
{"session_id": "abc-123", "status": "GENERATING"}
```
Then subscribe to `GET /api/generate/{session_id}/logs` exactly as before.

**Response — all other paths:**
SSE stream:
```
data: {"type": "token", "content": "Here is how..."}
data: {"type": "done"}
```

---

## Decision Logging

Decisions are logged at `DEBUG` level with `[decision_layer]` prefix:
```
[decision_layer] Decision (first pass): intent=add_feature route=project_context_builder confidence=0.90 reason='Feature addition to existing project.'
```

Internal chain-of-thought is **never** logged or exposed.

---

## Extending

To add a new intent:
1. Add the intent string to `IntentType` in `types.py`.
2. Add the route to `RouteType` if needed.
3. Add an example to `DECISION_SYSTEM_PROMPT` in `prompt.py`.
4. Add a handler branch in `ProjectActionExecutor.execute()`.
