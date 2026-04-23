"""
ResponseParser — Markdown fallback parser for scraper models.
SAFE: Only ADDS to existing logic. Existing XML parser (from registry.py) is imported
and re-exposed as _parse_xml(). parse_markdown_files() is new — only runs when XML fails.
parse_tool_calls() is the unified entry point (JSON first, then XML/markdown fallbacks).
"""
import json
import re

from ...shared.write_guard import is_safe_generated_path


class _DuplicateJSONKeyError(ValueError):
    """Raised when a JSON object repeats a key."""


def _reject_duplicate_json_keys(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise _DuplicateJSONKeyError(f"Duplicate JSON key: {key}")
        data[key] = value
    return data


class ResponseParser:
    """
    Unified tool-call parser.
    Feature 1: Markdown fallback for scraper models that don't follow XML format.
    """
    _INVALID_FILE_HEADER_SENTINEL = "__INVALID_FILE_HEADER__"

    @staticmethod
    def _is_truncated(path: str, content: str) -> bool:
        """Returns True if the content appears to be truncated mid-code."""
        c_clean = content.strip()
        if not c_clean:
            return False
        lower = c_clean.lower()
        if any(
            marker in lower
            for marker in (
                "tokens truncated",
                "---log_chunk---",
                "build cancelled by user",
                "code blocktext",
            )
        ):
            return True
        
        # Check for truncated CSS variables or JS imports
        if any(c_clean.endswith(p) for p in ["var(--", "rgba(", "rgb(", "url(", "import ", "from "]):
            return True
        # Check for open blocks/brackets/commas/colons (abrupt ends)
        if c_clean.endswith(("{", "(", "[", ",", ":", '"', "'")):
            return True
        if path.endswith((".tsx", ".ts", ".jsx", ".js")) and c_clean.endswith(("...", "…")):
            return True
            
        # JS/JSX/TS specific brace balance check
        if path.endswith((".tsx", ".ts", ".jsx", ".js")):
            open_braces = c_clean.count('{')
            close_braces = c_clean.count('}')
            open_parens = c_clean.count('(')
            close_parens = c_clean.count(')')
            open_brackets = c_clean.count('[')
            close_brackets = c_clean.count(']')
            if open_braces > close_braces: # Strict check for truncation
                return True
            if open_parens > close_parens:
                return True
            if open_brackets > close_brackets:
                return True
            if c_clean.count("`") % 2 == 1:
                return True

        # Very short content for a .tsx file likely means a stall/cutoff
        if path.endswith((".tsx", ".ts")) and len(c_clean) < 75 and "import" not in c_clean and "export" not in c_clean:
            # Exception for short config/pure static files
            if "config" in path.lower() or path.endswith((".json", "env")):
                return False
            return True
        return False

    @staticmethod
    def _parse_xml(text: str) -> list[dict]:
        """XML parser for write_file and other tool calls."""
        calls = []
        pattern = re.compile(
            r'<write_file>\s*<path>(.*?)</path>\s*<content>(.*?)</content>\s*</write_file>',
            re.DOTALL
        )
        for m in pattern.finditer(text):
            calls.append({
                "tool": "write_file",
                "params": {
                    "path": m.group(1).strip(),
                    "content": m.group(2)
                }
            })
        # Also parse execute_command
        cmd_pattern = re.compile(
            r'<execute_command>\s*<command>(.*?)</command>\s*</execute_command>',
            re.DOTALL
        )
        for m in cmd_pattern.finditer(text):
            calls.append({
                "tool": "execute_command",
                "params": {"command": m.group(1).strip()}
            })
        return calls

    @staticmethod
    def _iter_json_objects(text: str) -> list[str]:
        """Return balanced top-level JSON object substrings from arbitrary text."""
        src = str(text or "")
        objects: list[str] = []
        depth = 0
        start = None
        in_string = False
        escape = False

        for idx, ch in enumerate(src):
            if in_string:
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue

            if ch == "{":
                if depth == 0:
                    start = idx
                depth += 1
                continue

            if ch == "}":
                if depth <= 0:
                    continue
                depth -= 1
                if depth == 0 and start is not None:
                    objects.append(src[start : idx + 1])
                    start = None

        return objects

    @staticmethod
    def _calls_from_generation_payload(payload: dict) -> list[dict]:
        """
        Parse strict generation payload JSON:
          {
            "files": [{"path":"...", "content":"..."}],
            "commands": [{"command":"..."}]
          }
        """
        if not isinstance(payload, dict):
            return []

        raw_files = payload.get("files")
        files: list[dict] = []
        if isinstance(raw_files, dict):
            for path, content in raw_files.items():
                files.append({"path": path, "content": content})
        elif isinstance(raw_files, list):
            files = [item for item in raw_files if isinstance(item, dict)]
        else:
            return []

        write_calls: list[dict] = []
        write_by_path: dict[str, dict] = {}
        for item in files:
            path = str(item.get("path", "") or "").strip().replace("\\", "/")
            if path == "process.env":
                path = ".env"
            if not path or not ResponseParser._is_valid_explicit_path(path):
                continue

            content = item.get("content", "")
            if content is None:
                content = ""
            if not isinstance(content, str):
                if isinstance(content, (dict, list)):
                    content = json.dumps(content, ensure_ascii=False, indent=2)
                else:
                    content = str(content)

            if ResponseParser._is_truncated(path, content):
                continue

            call = {"tool": "write_file", "params": {"path": path, "content": content}}
            write_by_path[path] = call

        write_calls.extend(write_by_path.values())

        command_calls: list[dict] = []
        raw_commands = payload.get("commands", [])
        if isinstance(raw_commands, list):
            for item in raw_commands:
                command = ""
                if isinstance(item, str):
                    command = item
                elif isinstance(item, dict):
                    command = str(item.get("command", item.get("cmd", "")) or "")
                if command.strip():
                    command_calls.append(
                        {
                            "tool": "execute_command",
                            "params": {"command": command.strip()},
                        }
                    )

        return write_calls + command_calls

    @staticmethod
    def _parse_partial_json_files_array(text: str) -> list[dict]:
        """
        Salvage complete entries from a truncated strict-JSON response.

        The model may cut off before closing the top-level object, but early
        items in `files: [ ... ]` are often complete and valid.
        """
        source = str(text or "")
        if not source.strip():
            return []

        files_key_index = source.find('"files"')
        if files_key_index == -1:
            return []

        colon_index = source.find(":", files_key_index)
        if colon_index == -1:
            return []

        array_start = source.find("[", colon_index)
        if array_start == -1:
            return []

        decoder = json.JSONDecoder(object_pairs_hook=_reject_duplicate_json_keys)
        parsed_files: list[dict] = []
        cursor = array_start + 1
        length = len(source)

        while cursor < length:
            while cursor < length and source[cursor] in {" ", "\t", "\r", "\n", ","}:
                cursor += 1
            if cursor >= length:
                break
            if source[cursor] == "]":
                break
            if source[cursor] != "{":
                break

            try:
                item, end_index = decoder.raw_decode(source, cursor)
            except Exception:
                # Stop at first malformed/truncated item; keep previously decoded items.
                break

            if isinstance(item, dict) and "path" in item and "content" in item:
                parsed_files.append(item)
            cursor = end_index

        if not parsed_files:
            return []

        return ResponseParser._calls_from_generation_payload(
            {
                "files": parsed_files,
                "commands": [],
            }
        )

    @staticmethod
    def _salvage_duplicate_key_files_array(text: str) -> list[dict]:
        """
        Recover file writes from malformed generation payloads where a single
        object inside files[] repeats "path"/"content" keys, e.g.:

          {"files":[{"path":"a","content":"...","path":"b","content":"..."}]}

        This is invalid JSON with duplicate keys, but we can still safely
        recover ordered path/content pairs from the files array segment.
        """
        source = str(text or "")
        if not source.strip():
            return []

        files_key_index = source.find('"files"')
        if files_key_index == -1:
            return []

        colon_index = source.find(":", files_key_index)
        if colon_index == -1:
            return []

        array_start = source.find("[", colon_index)
        if array_start == -1:
            return []

        # Find matching closing ] while respecting string literals.
        in_string = False
        escape = False
        depth = 0
        array_end = -1
        for idx in range(array_start, len(source)):
            ch = source[idx]
            if in_string:
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
                continue
            if ch == "[":
                depth += 1
                continue
            if ch == "]":
                depth -= 1
                if depth == 0:
                    array_end = idx
                    break

        segment = source[array_start + 1 : array_end if array_end != -1 else len(source)]
        if not segment.strip():
            return []

        # JSON string literal (supports escaped chars like \" and \\n)
        json_string = r'"(?:\\.|[^"\\])*"'
        key_value_pattern = re.compile(
            rf'"(?P<key>path|content)"\s*:\s*(?P<value>{json_string})',
            re.DOTALL,
        )

        recovered_files: list[dict] = []
        current_path: str | None = None
        for match in key_value_pattern.finditer(segment):
            key = str(match.group("key") or "")
            value_token = str(match.group("value") or "")
            try:
                value = json.loads(value_token)
            except Exception:
                continue

            if key == "path":
                current_path = str(value or "")
                continue

            # key == "content"
            if current_path is None:
                continue

            recovered_files.append(
                {
                    "path": current_path,
                    "content": str(value or ""),
                }
            )
            current_path = None

        if not recovered_files:
            return []

        return ResponseParser._calls_from_generation_payload(
            {
                "files": recovered_files,
                "commands": [],
            }
        )

    @staticmethod
    def _parse_json_generation_payload(text: str) -> tuple[list[dict], bool]:
        """
        Parse strict JSON generation payloads from raw model output.
        JSON is the primary protocol; XML/markdown are fallback paths only.
        """
        source = str(text or "")
        if not source.strip():
            return [], False

        candidate_texts: list[str] = [source]
        fenced_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", source, flags=re.IGNORECASE)
        candidate_texts.extend(block for block in fenced_blocks if str(block).strip())

        seen_payloads: set[str] = set()
        malformed_generation_json = False
        for candidate in candidate_texts:
            for obj in ResponseParser._iter_json_objects(candidate):
                normalized = obj.strip()
                if not normalized or normalized in seen_payloads:
                    continue
                seen_payloads.add(normalized)
                try:
                    parsed = json.loads(
                        normalized,
                        object_pairs_hook=_reject_duplicate_json_keys,
                    )
                except _DuplicateJSONKeyError:
                    if '"files"' in normalized or '"commands"' in normalized:
                        salvaged_calls = ResponseParser._salvage_duplicate_key_files_array(normalized)
                        if salvaged_calls:
                            return salvaged_calls, False
                        malformed_generation_json = True
                    continue
                except Exception:
                    continue
                calls = ResponseParser._calls_from_generation_payload(parsed)
                if calls:
                    return calls, False

            partial_calls = ResponseParser._parse_partial_json_files_array(candidate)
            if partial_calls:
                return partial_calls, False

        return [], malformed_generation_json

    @staticmethod
    def _parse_markdown_heading_blocks(text: str) -> list[dict]:
        """
        Extract files from markdown heading sections such as:

            ### FILE: src/App.tsx
            ```tsx
            // FILE: src/App.tsx
            export default function App() {}
            ```
        """
        calls = []
        pattern = re.compile(
            r'(?:^|\n)#{2,6}\s*FILE:\s*([^\n\r`]+)\s*\n(.*?)(?=(?:\n#{2,6}\s*FILE:\s*)|\Z)',
            re.DOTALL | re.IGNORECASE,
        )

        for match in pattern.finditer(text):
            path = match.group(1).strip().strip("`*# ")
            content = match.group(2).strip()

            content = re.sub(r"^```[^\n]*\n", "", content).strip()
            content = re.sub(r"\n```$", "", content).strip()
            content = re.sub(r"\n?```+$", "", content).strip()

            if path == "process.env":
                path = ".env"
            path = path.replace("\\", "/")

            if not path or not ResponseParser._is_valid_explicit_path(path) or len(content) < 5:
                continue
            
            # Stitching: collect all blocks for the same path
            existing = next((c for c in calls if c['params']['path'] == path), None)
            if existing:
                existing['params']['content'] += "\n" + content
            else:
                calls.append({"tool": "write_file", "params": {"path": path, "content": content}})

        # ── FINAL TRUNCATION GUARD ──
        valid_calls = []
        for call in calls:
            fpath = call["params"]["path"]
            fcontent = call["params"]["content"]
            if ResponseParser._is_truncated(fpath, fcontent):
                print(f"[PARSER] Detected truncation in {fpath} after stitching. Rejecting file.")
                continue
            valid_calls.append(call)
        return valid_calls

    @staticmethod
    def _find_inline_file_header(block: str) -> tuple[str | None, str]:
        lines = block.splitlines()
        for idx in range(min(len(lines), 5)):
            line = lines[idx].strip()
            match = re.search(r'(?://|#|/\*|--|<!--)\s*FILE:\s*([^\n\r*`]+)', line, re.IGNORECASE)
            if not match:
                continue
            path = match.group(1).strip().strip('`* /->')
            # Reject if path contains commas or multiple spaces (hallucinated list)
            if "," in path or "  " in path:
                content = "\n".join(lines[:idx] + lines[idx + 1:]).strip()
                return ResponseParser._INVALID_FILE_HEADER_SENTINEL, content
            content = "\n".join(lines[:idx] + lines[idx + 1:]).strip()
            return path or None, content
        return None, block.strip()

    @staticmethod
    def _language_matches_expected_path(language: str, path: str) -> bool:
        lang = str(language or "").strip().lower()
        normalized_path = str(path or "").strip().lower().replace("\\", "/")
        if not normalized_path:
            return False

        if lang in {"", "text", "plain"}:
            return True
        if lang in {"json"}:
            return normalized_path.endswith(".json")
        if lang in {"html"}:
            return normalized_path.endswith(".html")
        if lang in {"css"}:
            return normalized_path.endswith(".css")
        if lang in {"env", "dotenv"}:
            return normalized_path == ".env" or normalized_path.startswith(".env.")
        if lang in {"gitignore"}:
            return normalized_path.endswith(".gitignore")
        if lang in {"md", "markdown"}:
            return normalized_path.endswith((".md", ".mdx"))
        if lang in {"svg", "xml"}:
            return normalized_path.endswith((".svg", ".xml"))
        if lang in {"ts", "typescript"}:
            return normalized_path.endswith((".ts", ".tsx"))
        if lang in {"tsx"}:
            return normalized_path.endswith(".tsx")
        if lang in {"js", "javascript"}:
            return normalized_path.endswith((".js", ".jsx"))
        if lang in {"jsx"}:
            return normalized_path.endswith(".jsx")
        if lang in {"sh", "bash", "shell"}:
            return normalized_path.endswith((".sh", ".bash"))
        if lang in {"py", "python"}:
            return normalized_path.endswith(".py")
        return True

    @staticmethod
    def _parse_display_code_blocks(text: str, expected_files: list | None = None) -> list[dict]:
        """
        Parse UI-rendered blocks such as:

            Code Blockjson
            { ... }

            Code Blocktypescript
            // FILE: src/app.ts
            export const app = ...

        When a block has no explicit FILE header, we map it only to the current
        expected batch and only when the language matches the expected file type.
        """
        block_pattern = re.compile(r'(?im)^[ \t]*Code Block([A-Za-z0-9_+-]*)[ \t]*$')
        matches = list(block_pattern.finditer(text))
        if not matches:
            return []

        remaining_expected = [
            str(path).strip().replace("\\", "/")
            for path in list(expected_files or [])
            if str(path).strip()
        ]
        assigned_paths: set[str] = set()
        calls: list[dict] = []

        for idx, match in enumerate(matches):
            language = str(match.group(1) or "").strip().lower()
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            raw_block = text[start:end].strip()
            if not raw_block:
                continue

            path, content = ResponseParser._find_inline_file_header(raw_block)
            if path == ResponseParser._INVALID_FILE_HEADER_SENTINEL:
                continue
            if not path:
                candidate_index = None
                for expected_index, expected_path in enumerate(remaining_expected):
                    if expected_path in assigned_paths:
                        continue
                    if ResponseParser._language_matches_expected_path(language, expected_path):
                        candidate_index = expected_index
                        path = expected_path
                        break
                if candidate_index is None:
                    continue
                content = raw_block.strip()

            path = str(path or "").strip().replace("\\", "/")
            if path == "process.env":
                path = ".env"
            if not path or not ResponseParser._is_valid_explicit_path(path) or path in assigned_paths:
                continue

            content = re.sub(r'^[\r\n]+', '', content).strip()
            if len(content) < 3 and not path.endswith((".env", ".gitignore")):
                continue

            # Stitching
            existing = next((c for c in calls if c['params']['path'] == path), None)
            if existing:
                existing['params']['content'] += "\n" + content
            else:
                calls.append({"tool": "write_file", "params": {"path": path, "content": content}})
            assigned_paths.add(path)

        # ── FINAL TRUNCATION GUARD ──
        valid_calls = []
        for call in calls:
            fpath = call["params"]["path"]
            fcontent = call["params"]["content"]
            if ResponseParser._is_truncated(fpath, fcontent):
                print(f"[PARSER] Detected truncation in {fpath} after stitching. Rejecting file.")
                continue
            valid_calls.append(call)
        return valid_calls

    @staticmethod
    def _parse_comment_indexed_blocks(text: str) -> list[dict]:
        """
        Robustly extract files where the identifier '// FILE: path' is within
        the first few lines of a content block.
        Works for:
          - Standard markdown blocks: ```json\n// FILE: ...\n{}```
          - DeepSeek button-separated blocks: Copy\nDownload\n// FILE: ...\n{}
        """
        calls = []

        # Phase 1: Identify all potential block boundaries
        # 1. // FILE: markers
        marker_pattern = r'(?:^|\n|[a-z]+(?:Copy|Download|Run))[ \t]*(?://|#|/\*|--|<!--)\s*FILE:\s*([^\n\r]+)'
        markers = []
        for m in re.finditer(marker_pattern, text):
            # Find the actual start of the marker within the match (e.g. after 'javascriptCopyDownload')
            match_text = m.group(0)
            marker_start = re.search(r'(?://|#|/\*|<!--)\s*FILE:', match_text)
            actual_pos = m.start() + marker_start.start() if marker_start else m.start()
            markers.append((actual_pos, m.group(1).strip()))

        # 2. UI Button markers (Copy/Download/Run)
        langs = r'javascript|typescript|js|ts|jsx|tsx|html|css|json|python|py|sql|sh|bash|text|env|gitignore|markdown|md|txt|xml'
        buttons_seq = r'(?:Copy|Download|Run|Copy\s*Download|Download\s*Copy|Copy\s*Run|Copy\s*Download\s*Run|Download\s*Copy\s*Run)'
        
        # Combined pattern for buttons with mandatory prefix or line start
        button_pattern = rf'(?:\n|^|(?<!\.)[\w]+[\n ]*|(?<=;)|(?<=}})|(?<=\]))(?:(?:{langs})?{buttons_seq}(?:{langs})?)'
        buttons = []
        for m in re.finditer(button_pattern, text, flags=re.IGNORECASE):
            # Find the actual start of noise: search for language or button within the match
            match_text = m.group(0)
            noise_match = re.search(rf'(?:{langs}|Copy|Download|Run)', match_text, re.IGNORECASE)
            actual_pos = m.start() + noise_match.start() if noise_match else m.start()
            buttons.append(actual_pos)

        # Combine and sort all split points
        split_points = sorted(list(set([m[0] for m in markers] + buttons + [0, len(text)])))
        
        chunks = []
        for i in range(len(split_points) - 1):
            start = split_points[i]
            end = split_points[i+1]
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

        # Phase 2: Process each chunk
        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk or len(chunk) < 5:
                continue
                
            # Clean leading UI noise (language, buttons, more noise)
            # Repeatedly strip until no more noise at the start
            prev_chunk = None
            while chunk != prev_chunk:
                prev_chunk = chunk
                # Also strip random leading chars that might be left by prefixes (like a single 'n' from 'npm')
                chunk = re.sub(rf'^[\w\s]{{0,10}}((?:Copy|Download|Run|{langs})\s*)+', '', chunk, flags=re.IGNORECASE).strip()
            
            if chunk.startswith('FILE:'):
                chunk = '// ' + chunk # Restore for path logic

            lines = chunk.split('\n')
            path = None
            code = chunk
            
            # Identify path from marker in the first 3 lines
            for i in range(min(len(lines), 3)):
                line = lines[i].strip()
                m = re.search(r'(?://|#|/\*|--|<!--)\s*FILE:\s*([^\n\r*` ]+)', line, re.IGNORECASE)
                if m:
                    path = m.group(1).strip().strip('`* /->')
                    code = '\n'.join(lines[:i] + lines[i+1:]).strip()
                    break
            
            # Fail closed: only accept explicit FILE markers.
            if not path:
                continue
            if not ResponseParser._is_valid_explicit_path(path):
                continue

            # TRUNCATE explanation text after closing markdown backticks
            code_end_match = re.search(r'\n```[^\n]*(\n|$)', code)
            if code_end_match:
                code = code[:code_end_match.start()].strip()

            # CLEANUP: Strip trailing UI noise and language markers
            # Repeatedly strip from end
            prev_code = None
            while code != prev_code:
                prev_code = code
                code = re.sub(rf'[\n\r\s]*(?:Copy|Download|Run|{langs})+$', '', code, flags=re.IGNORECASE).strip()
            code = re.sub(r'```+$', '', code).strip()

            if path and len(code) > 5:
                # Stitching check: if path already exists, append content 
                existing = next((c for c in calls if c['params']['path'] == path), None)
                if existing:
                    # Avoid duplicate blocks appearing twice due to overlapping split points
                    if code[:50] not in existing['params']['content'][-500:]:
                        existing['params']['content'] += "\n" + code
                else:
                    calls.append({"tool": "write_file", "params": {"path": path, "content": code}})
        
        # ── FINAL TRUNCATION GUARD ──
        # Apply truncation check ONCE after all blocks for a file are gathered/stitched
        valid_calls = []
        for call in calls:
            fpath = call["params"]["path"]
            fcontent = call["params"]["content"]
            if ResponseParser._is_truncated(fpath, fcontent):
                print(f"[PARSER] Detected truncation in {fpath} after stitching. Rejecting file.")
                continue
            valid_calls.append(call)

        return valid_calls

    @staticmethod
    def _parse_deepseek_fallback(text: str, expected_files: list = None) -> list[dict]:
        """
        Fallback for DeepSeek Scraper output where markdown backticks are replaced
        by raw text UI elements 'Copy' and 'Download'.
        
        Two-phase approach:
        1. Try to split by '// FILE:' markers directly (most reliable)
        2. Fall back to splitting by UI button markers (Copy/Download),
           then sub-split each chunk by '// FILE:' if found within it.
        """
        import re
        calls = []
        expected_files = expected_files or []
        file_idx = 0

        # ── PHASE 1: Split by `// FILE:` or `# FILE:` or `<!-- FILE:` markers ──
        # This is the most reliable split when DeepSeek uses '// FILE: path' headers
        file_marker_pattern = r'(?:^|\n)[ \t]*(?://|#|/\*|--|<!--)\s*FILE:\s*([^\n\r]+)'
        file_marker_positions = [(m.start(), m.group(1).strip()) for m in re.finditer(file_marker_pattern, text)]

        if len(file_marker_positions) >= 2 or (len(file_marker_positions) == 1 and expected_files):
            # Split the full text into sections, each starting at a FILE: marker
            sections = []
            for idx, (pos, fname) in enumerate(file_marker_positions):
                next_pos = file_marker_positions[idx + 1][0] if idx + 1 < len(file_marker_positions) else len(text)
                raw_block = text[pos:next_pos]
                # Strip the FILE: header line itself from the code block
                header_end = raw_block.find('\n')
                code = raw_block[header_end:].strip() if header_end != -1 else ""
                # Clean button noise at start and end of block
                code = re.sub(r'^(?:Copy|Download|Run|text|typescript|css|html|jsx|tsx|json|sh|bash)\s*\n?', '', code, flags=re.IGNORECASE).strip()
                code = re.sub(r'\n?(?:Copy|Download|Run)\s*$', '', code, flags=re.IGNORECASE).strip()
                # TRUNCATE explanation text after closing markdown backticks
                code_end_match = re.search(r'\n```[^\n]*(\n|$)', code)
                if code_end_match:
                    code = code[:code_end_match.start()].strip()

                sections.append((fname.strip('`* '), code))

            for fname, code in sections:
                if len(code) < 5:
                    continue
                # Normalize path
                path = fname.strip("*/`_ :->.")
                if path == 'process.env':
                    path = '.env'
                calls.append({"tool": "write_file", "params": {"path": path, "content": code}})
            
            if calls:
                return calls

        # ── PHASE 2: Split by UI button markers, then sub-split by FILE: ────────
        button_pattern = r'(?:Copy|Download|Run)\s+(?:Copy|Download|Run|typescript|css|html|jsx|tsx|json|sh|bash)?\s*'
        raw_chunks = re.split(button_pattern, text, flags=re.IGNORECASE)
        
        if len(raw_chunks) < 2:
            # Last resort: simple newline-based split
            raw_chunks = re.split(r'(?:Download|Copy|Run)\s*\n', text, flags=re.IGNORECASE)
            if len(raw_chunks) < 2:
                return calls

        # Flatten: each raw_chunk might itself contain multiple FILE: markers
        # so we sub-split each chunk
        flat_chunks = []
        for chunk in raw_chunks[1:]:  # skip preamble
            sub_markers = [(m.start(), m.group(1).strip()) for m in re.finditer(file_marker_pattern, chunk)]
            if len(sub_markers) >= 2:
                # Sub-split this chunk by FILE: markers
                for idx, (pos, fname) in enumerate(sub_markers):
                    next_pos = sub_markers[idx + 1][0] if idx + 1 < len(sub_markers) else len(chunk)
                    raw_block = chunk[pos:next_pos]
                    header_end = raw_block.find('\n')
                    code = raw_block[header_end:].strip() if header_end != -1 else ""
                    flat_chunks.append((fname.strip('`* '), code))
            else:
                flat_chunks.append((None, chunk.strip()))

        current_path = "unknown.txt"
        for fname, code_block in flat_chunks:
            # Clean button/language noise from block
            code_block = re.sub(r'^(?:Copy|Download|Run|typescript|css|html|jsx|tsx|json|sh|bash|text)\s*\n?', '', code_block, flags=re.IGNORECASE).strip()
            code_block = re.sub(r'\n?(?:Copy|Download|Run)\s*$', '', code_block, flags=re.IGNORECASE).strip()

            path_found = False

            if fname:
                current_path = fname.strip("*/`_ :.")
                path_found = True
            else:
                # Check for // FILE: within the block
                id_match = re.search(r'(?://|#|/\*|--|<!--)\s*FILE:\s*([^\n\r*`]+)', code_block, re.IGNORECASE)
                if id_match and id_match.start() < 250:
                    temp_path = id_match.group(1).strip()
                    temp_path = re.sub(r'[*`_:\->]+$', '', temp_path).strip('.')
                    if temp_path:
                        current_path = temp_path
                        path_found = True
                        nl = code_block.find('\n', id_match.start())
                        if nl != -1:
                            code_block = code_block[nl:].strip()

            # Strip trailing language designators
            # Strip trailing language designators
            trailing_lang = re.search(r'([\n\r\s]*)(typescript|js|jsx|typescript|ts|tsx|html|css|json|python|py|sql|sh|bash)$', code_block, flags=re.IGNORECASE)
            if trailing_lang:
                code_block = code_block[:trailing_lang.start()].strip()

            if not path_found:
                continue

            path = current_path.strip("*/`_ :->.").replace("..", ".")
            if path == 'process.env':
                path = '.env'
            if not ResponseParser._is_valid_explicit_path(path):
                continue

            # Skip empty blocks
            if len(code_block) < 10 and not path.endswith(('.env', '.gitignore')):
                continue

            # Stitching
            existing = next((c for c in calls if c['params']['path'] == path), None)
            if existing:
                existing['params']['content'] += "\n" + code_block
            else:
                calls.append({"tool": "write_file", "params": {"path": path, "content": code_block}})

        # ── FINAL TRUNCATION GUARD ──
        valid_calls = []
        for call in calls:
            fpath = call["params"]["path"]
            fcontent = call["params"]["content"]
            if ResponseParser._is_truncated(fpath, fcontent):
                print(f"[PARSER] Detected truncation in {fpath} after stitching. Rejecting file.")
                continue
            valid_calls.append(call)
        return valid_calls

    @staticmethod
    def _parse_gemini_scraper(text: str) -> list[dict]:
        """
        Specialized parser for Gemini-scraper models which often concatenate
        files directly (e.g., ...}// FILE: next.ts) without markdown blocks.
        """
        calls = []
        # Find all // FILE: path markers (anywhere in text)
        # We avoid \s in path regex to prevent over-matching into the code body
        marker_pattern = r'(?://|#|/\*|--|<!--)\s*FILE:\s*([^\s\n\r*`<>|]+)'
        matches = list(re.finditer(marker_pattern, text))
        
        if not matches:
            return calls
            
        for i in range(len(matches)):
            start_match = matches[i]
            # Strip noise but PRESERVE leading dots for .env, .gitignore
            path = start_match.group(1).strip().strip('`*# ')
            
            # Start of this file's content: immediately after the line containing the marker
            # We find the newline after the marker
            line_end = text.find('\n', start_match.start())
            if line_end == -1:
                content_start = start_match.end()
            else:
                content_start = line_end + 1
                
            # End of this file's content is the start of the NEXT marker, or end of text
            content_end = matches[i+1].start() if i+1 < len(matches) else len(text)
            
            content = text[content_start:content_end].strip()
            
            # Clean up potential trailing artifacts (like a single backtick or newline)
            content = re.sub(r'```$', '', content).strip()
            # Also clean up potential preceding // FILE: markers that might be partially caught
            # if they were on the SAME line as previous content (e.g. "...}// FILE: ...")
            content = re.sub(r'(?://|#|/\*|--|<!--)\s*FILE:\s*$', '', content, flags=re.MULTILINE).strip()
            
            if path and (content or path.endswith(('.env', '.gitignore'))):
                path = path.replace('\\', '/')
                if not ResponseParser._is_valid_explicit_path(path):
                    continue
                
                # ── PHASE 3: Truncation Detection ──
                if ResponseParser._is_truncated(path, content):
                    print(f"[PARSER] Detected truncation in {path}. Rejecting block.")
                    continue

                # ── PHASE 4: Stray HTML Detection (Split swallowed index.html) ──
                html_start = re.search(r'^\s*(?:<!DOCTYPE html|<html)', content, re.IGNORECASE | re.MULTILINE)
                if html_start and "index.html" not in path:
                    real_content = content[:html_start.start()].strip()
                    stray_html = content[html_start.start():].strip()
                    calls.append({"tool": "write_file", "params": {"path": path, "content": real_content}})
                    calls.append({"tool": "write_file", "params": {"path": "index.html", "content": stray_html}})
                else:
                    calls.append({"tool": "write_file", "params": {"path": path, "content": content}})
        
        # Deduplicate paths
        unique_calls = {}
        for call in calls: unique_calls[call["params"]["path"]] = call
        return list(unique_calls.values())

    @staticmethod
    def parse_tool_calls(text: str, model_id: str = "", expected_files: list = None) -> list[dict]:
        """
        Unified tool-call parser.
        1. Try strict JSON payload (primary protocol).
        2. Fall back to XML.
        3. Fall back to markdown/scraper variants.
        """
        # 1. Try strict JSON first
        calls, malformed_json_payload = ResponseParser._parse_json_generation_payload(text)
        if malformed_json_payload:
            # Fail closed: malformed JSON payloads (especially duplicate-key objects)
            # must be retried as a whole batch, not partially recovered via fallbacks.
            return []

        # 2. Fall back to XML
        if not calls:
            calls = ResponseParser._parse_xml(text)

        if not calls:
            calls = ResponseParser._parse_markdown_heading_blocks(text)

        if not calls:
            calls = ResponseParser._parse_display_code_blocks(text, expected_files=expected_files)
        
        # 3. Gemini-specific override (if explicitly identified)
        if not calls and "gemini" in model_id.lower():
            calls = ResponseParser._parse_gemini_scraper(text)
            
        # 4. Try the robust 'comment-in-block' format (scraper/markdown fallback)
        if not calls:
            calls = ResponseParser._parse_comment_indexed_blocks(text)
            
        # 5. Try DeepSeek-specific fallback (multi-marker split)
        if not calls:
            calls = ResponseParser._parse_deepseek_fallback(text, expected_files=expected_files)
            
        # 6. Try Gemini fallback as last-ditch effort if no files found yet
        if not calls:
             calls = ResponseParser._parse_gemini_scraper(text)

        # 3. Handle execute_command: if no nested <command>, use body
        for call in calls:
            if call["tool"] == "execute_command":
                if not call["params"].get("command"):
                    m = re.search(r"<execute_command>(.*?)</execute_command>", text, re.DOTALL)
                    if m:
                        body = m.group(1).strip()
                        cmd_match = re.search(r"<command>(.*?)</command>", body, re.DOTALL)
                        if cmd_match:
                            call["params"]["command"] = cmd_match.group(1).strip()
                        else:
                            call["params"]["command"] = body
        
        return calls

    @staticmethod
    def parse_decision(text: str) -> dict:
        """
        Extract a structured AI Decision Engine response from raw LLM output.

        Expected shape (produced by DecisionEngine._build_prompt):
            {
              "layer":        "frontend | backend | database | integration | unknown",
              "confidence":   "HIGH | MEDIUM | LOW",
              "strategy":     "<machine-readable key>",
              "target_files": ["<relative/path>", ...],
              "root_cause":   "<one-sentence human description>",
              "fix_hint":     "<what the AI recommends fixing>"
            }

        Handles:
          - Clean JSON responses
          - Responses wrapped in ```json ... ``` fences
          - Responses with prose before/after the JSON block
          - Partial / malformed JSON → returns safe fallback

        Returns a dict guaranteed to have all six keys (never raises).
        """
        import json as _json

        # Safety-first fallback: if we can't parse a decision, do not mutate files.
        _FALLBACK = {
            "layer":        "unknown",
            "confidence":   "LOW",
            "strategy":     "unknown",
            "target_files": [],
            "root_cause":   "AI did not return a parseable decision",
            "fix_hint":     "Inspect the error log manually and fix the most likely culprit file.",
            "command":      None,
            "command_kind": "none",
            "probe_path":   "",
            "probe_content": "",
            "return_query_result": "no",
            "write_files":  "no",
        }

        if not text or not text.strip():
            return _FALLBACK

        # 1. Strip markdown fences if present
        cleaned = re.sub(r"```(?:json)?|```", "", text).strip()

        def _extract_first_json_object(src: str) -> str | None:
            """
            Extract the first valid JSON object substring from a blob of text.
            This is more robust than a greedy regex because LLM output may contain
            multiple brace blocks (or braces inside strings).
            """
            start_positions = [m.start() for m in re.finditer(r"\{", src)]
            if not start_positions:
                return None

            for start in start_positions:
                depth = 0
                in_str = False
                escape = False
                for i in range(start, len(src)):
                    ch = src[i]
                    if in_str:
                        if escape:
                            escape = False
                            continue
                        if ch == "\\":
                            escape = True
                            continue
                        if ch == '"':
                            in_str = False
                        continue

                    if ch == '"':
                        in_str = True
                        continue
                    if ch == "{":
                        depth += 1
                        continue
                    if ch == "}":
                        depth -= 1
                        if depth == 0:
                            return src[start : i + 1]
                # no matching close brace; try next start
            return None

        # 2. Extract JSON object from the response (model may prepend/append prose)
        candidate = _extract_first_json_object(cleaned)
        if not candidate:
            return _FALLBACK

        # 3. Parse
        parsed = None
        try:
            parsed = _json.loads(candidate)
        except (_json.JSONDecodeError, ValueError):
            # Last-ditch: try repairing common issues (trailing commas, single quotes)
            repaired = re.sub(r",\s*([}\]])", r"\1", candidate)  # trailing commas
            repaired = repaired.replace("'", '"')  # single → double quotes
            try:
                parsed = _json.loads(repaired)
            except Exception:
                # Try non-greedy candidates too (sometimes the first brace block isn't JSON)
                for m in re.finditer(r"\{[\s\S]*?\}", cleaned):
                    chunk = m.group(0)
                    try:
                        parsed = _json.loads(chunk)
                        break
                    except Exception:
                        continue
                if parsed is None:
                    kv_parsed = {}
                    def _string_field_pattern(field: str) -> str:
                        all_keys = (
                            "layer",
                            "confidence",
                            "strategy",
                            "target_files",
                            "root_cause",
                            "fix_hint",
                            "command",
                            "command_kind",
                            "probe_path",
                            "probe_content",
                            "return_query_result",
                            "write_files",
                        )
                        next_keys = "|".join(key for key in all_keys if key != field)
                        return (
                            rf'"?{field}"?\s*:\s*"([\s\S]*?)"'
                            rf'(?=\s*,\s*"(?:{next_keys})"|\s*}}$)'
                        )
                    scalar_patterns = {
                        "layer": r'"?layer"?\s*:\s*"?(frontend|backend|database|integration|unknown)"?',
                        "confidence": r'"?confidence"?\s*:\s*"?(HIGH|MEDIUM|LOW)"?',
                        "strategy": _string_field_pattern("strategy"),
                        "root_cause": _string_field_pattern("root_cause"),
                        "fix_hint": _string_field_pattern("fix_hint"),
                        "command": _string_field_pattern("command"),
                        "command_kind": r'"?command_kind"?\s*:\s*"?(query|dependency_install|runtime_probe|source_edit|none)"?',
                        "probe_path": _string_field_pattern("probe_path"),
                        "probe_content": _string_field_pattern("probe_content"),
                        "return_query_result": r'"?return_query_result"?\s*:\s*"?(yes|no)"?',
                        "write_files": r'"?write_files"?\s*:\s*"?(yes|no)"?',
                    }
                    for key, pattern in scalar_patterns.items():
                        match = re.search(pattern, cleaned, re.IGNORECASE)
                        if match:
                            kv_parsed[key] = match.group(1)
                    target_match = re.search(r'"?target_files"?\s*:\s*\[(.*?)\]', cleaned, re.DOTALL | re.IGNORECASE)
                    if target_match:
                        kv_parsed["target_files"] = [
                            part.strip().strip('"').strip("'")
                            for part in target_match.group(1).split(",")
                            if part.strip()
                        ]
                    if kv_parsed:
                        parsed = kv_parsed
                    else:
                        return _FALLBACK

        if not isinstance(parsed, dict):
            return _FALLBACK

        # 4. Normalise — ensure all required keys exist with safe defaults
        result = {
            "layer":        str(parsed.get("layer",        _FALLBACK["layer"])).lower(),
            "confidence":   str(parsed.get("confidence",   _FALLBACK["confidence"])).upper(),
            "strategy":     str(parsed.get("strategy",     _FALLBACK["strategy"])),
            "target_files": parsed.get("target_files",     []),
            "root_cause":   str(parsed.get("root_cause",   _FALLBACK["root_cause"])),
            "fix_hint":     str(parsed.get("fix_hint",     parsed.get("fix", _FALLBACK["fix_hint"]))),
            "command":      parsed.get("command",          _FALLBACK.get("command")),
            "command_kind": str(parsed.get("command_kind", _FALLBACK["command_kind"])).lower(),
            "probe_path":   str(parsed.get("probe_path",   _FALLBACK["probe_path"])),
            "probe_content": str(parsed.get("probe_content", _FALLBACK["probe_content"])),
            "return_query_result": str(parsed.get("return_query_result", "")).lower(),
            "write_files":  str(parsed.get("write_files",  "")).lower(),
        }

        # Ensure target_files is always a list
        if not isinstance(result["target_files"], list):
            result["target_files"] = [str(result["target_files"])]

        # Restrict layer to known values
        valid_layers = {"frontend", "backend", "database", "integration", "unknown"}
        if result["layer"] not in valid_layers:
            result["layer"] = "unknown"

        valid_command_kinds = {"query", "dependency_install", "runtime_probe", "source_edit", "none"}
        if result["command_kind"] not in valid_command_kinds:
            result["command_kind"] = "none"

        return result
    @staticmethod
    def _is_valid_explicit_path(path: str) -> bool:
        return is_safe_generated_path(path)
