"""
DiffEngine — Python port of refs/cline/src/core/assistant-message/diff.ts

Implements the same 3-tier matching strategy as Cline:
  1. Exact match       — str.indexOf equivalent
  2. Line-trimmed      — trim whitespace on each line before comparing
  3. Block-anchor      — match first + last line of 3+ line blocks

Also ports from diff_ref.ts:
  - getLineNumberFromCharIndex()
  - everyLineHasLineNumbers() / removeLineNumbers()
  - Streaming partial-block handler (constructNewFileContentV1 pattern)
  - Out-of-order replacement support
  - Empty SEARCH block: new file & full replacement
  - DiffResult structured return type
  - build_diff_block() helper

# Algorithm from refs/cline/src/core/assistant-message/diff.ts
"""
from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from typing import Optional

# ── Marker patterns (mirrors diff_ref.ts regex constants) ───────────────────
# From refs/cline diff.ts: SEARCH_BLOCK_START_REGEX, SEARCH_BLOCK_END_REGEX,
# REPLACE_BLOCK_END_REGEX, plus legacy </<< variants
SEARCH_BLOCK_START = "------- SEARCH"
SEARCH_BLOCK_END   = "======="
REPLACE_BLOCK_END  = "+++++++ REPLACE"

SEARCH_BLOCK_CHAR  = "-"
REPLACE_BLOCK_CHAR = "+"
LEGACY_SEARCH_CHAR = "<"
LEGACY_REPLACE_CHAR = ">"

SEARCH_START_RE  = re.compile(r'^[-]{3,} SEARCH>?$|^[<]{3,} SEARCH>?$')
SEARCH_END_RE    = re.compile(r'^[=]{3,}$')
REPLACE_END_RE   = re.compile(r'^[+]{3,} REPLACE>?$|^[>]{3,} REPLACE>?$')

# ── Line-number utilities (from diff_ref.ts) ────────────────────────────────

_LINE_NUM_RE = re.compile(r'^\s*\d+\s*[|:]?\s?')


def get_line_number_from_char_index(content: str, char_index: int) -> int:
    """Convert a character index to a 1-based line number.

    # From diff_ref.ts getLineNumberFromCharIndex()
    """
    if char_index <= 0:
        return 1
    return content[:char_index].count('\n') + 1


def every_line_has_line_numbers(text: str) -> bool:
    """Check if every non-empty line starts with a line-number prefix.

    # From diff_ref.ts everyLineHasLineNumbers()
    """
    for line in text.splitlines():
        if line.strip() and not _LINE_NUM_RE.match(line):
            return False
    return True


def remove_line_numbers(text: str) -> str:
    """Strip leading line-number prefixes from every line.

    # From diff_ref.ts removeLineNumbers()
    """
    return '\n'.join(
        _LINE_NUM_RE.sub('', line) if line.strip() else line
        for line in text.splitlines()
    ) + ('\n' if text.endswith('\n') else '')


# ── Marker detection helpers ────────────────────────────────────────────────

def _is_search_start(line: str) -> bool:
    """# From diff_ref.ts isSearchBlockStart()"""
    return bool(SEARCH_START_RE.match(line))


def _is_search_end(line: str) -> bool:
    """# From diff_ref.ts isSearchBlockEnd()"""
    return bool(SEARCH_END_RE.match(line))


def _is_replace_end(line: str) -> bool:
    """# From diff_ref.ts isReplaceBlockEnd()"""
    return bool(REPLACE_END_RE.match(line))


def _is_partial_marker(line: str) -> bool:
    """Check if a line looks like an incomplete/partial marker.

    # From diff_ref.ts partial marker guard in constructNewFileContentV1
    """
    return (
        (line.startswith(SEARCH_BLOCK_CHAR) or
         line.startswith(LEGACY_SEARCH_CHAR) or
         line.startswith('=') or
         line.startswith(REPLACE_BLOCK_CHAR) or
         line.startswith(LEGACY_REPLACE_CHAR))
        and not _is_search_start(line)
        and not _is_search_end(line)
        and not _is_replace_end(line)
    )


# ── Tier-2: Line-trimmed fallback ───────────────────────────────────────────

def _line_trimmed_fallback(
    original: str, search: str, start_index: int
) -> tuple[int, int] | None:
    """
    Attempts a line-trimmed fallback match.

    Lines are compared after stripping leading/trailing whitespace.
    Returns (match_start, match_end) character indices or None.

    # From refs/cline diff.ts lineTrimmedFallbackMatch()
    """
    orig_lines = original.split('\n')
    srch_lines = search.split('\n')

    # Remove trailing empty line (artifact of trailing \n)
    if srch_lines and srch_lines[-1] == '':
        srch_lines.pop()

    if not srch_lines:
        return None

    # Find line number corresponding to start_index
    start_line = 0
    cur_idx = 0
    while cur_idx < start_index and start_line < len(orig_lines):
        cur_idx += len(orig_lines[start_line]) + 1
        start_line += 1

    # Slide over orig_lines looking for a contiguous trimmed match
    for i in range(start_line, len(orig_lines) - len(srch_lines) + 1):
        if all(
            orig_lines[i + j].strip() == srch_lines[j].strip()
            for j in range(len(srch_lines))
        ):
            # Compute character positions
            match_start = sum(len(orig_lines[k]) + 1 for k in range(i))
            match_end = match_start + sum(
                len(orig_lines[i + k]) + 1 for k in range(len(srch_lines))
            )
            return match_start, match_end

    return None


# ── Tier-3: Block-anchor fallback ───────────────────────────────────────────

def _block_anchor_fallback(
    original: str, search: str, start_index: int
) -> tuple[int, int] | None:
    """
    Matches using first and last lines as anchors (for blocks of 3+ lines).

    # From refs/cline diff.ts blockAnchorFallbackMatch()
    """
    orig_lines = original.split('\n')
    srch_lines = search.split('\n')

    if srch_lines and srch_lines[-1] == '':
        srch_lines.pop()

    if len(srch_lines) < 3:
        return None

    first_anchor = srch_lines[0].strip()
    last_anchor = srch_lines[-1].strip()
    block_size = len(srch_lines)

    start_line = 0
    cur_idx = 0
    while cur_idx < start_index and start_line < len(orig_lines):
        cur_idx += len(orig_lines[start_line]) + 1
        start_line += 1

    for i in range(start_line, len(orig_lines) - block_size + 1):
        if (orig_lines[i].strip() == first_anchor and
                orig_lines[i + block_size - 1].strip() == last_anchor):
            match_start = sum(len(orig_lines[k]) + 1 for k in range(i))
            match_end = match_start + sum(
                len(orig_lines[i + k]) + 1 for k in range(block_size)
            )
            return match_start, match_end

    return None


# ── 3-tier search cascade ──────────────────────────────────────────────────

def _find_match(
    original_content: str,
    search_content: str,
    last_processed: int,
) -> tuple[int, int, bool]:
    """
    Locate search_content in original_content using the 3-tier cascade.

    Returns (match_start, match_end, out_of_order).
    Raises ValueError if not found.

    # From diff_ref.ts constructNewFileContentV1 search/match section
    """
    if not search_content:
        # Empty SEARCH → new file or full replacement
        if len(original_content) == 0:
            return 0, 0, False           # new file: pure insertion
        else:
            return 0, len(original_content), False   # full replacement

    out_of_order = False

    # Tier 1: exact match from last_processed
    idx = original_content.find(search_content, last_processed)
    if idx != -1:
        return idx, idx + len(search_content), False

    # Tier 2: line-trimmed fallback
    m = _line_trimmed_fallback(original_content, search_content, last_processed)
    if m:
        return m[0], m[1], False

    # Tier 3: block-anchor fallback
    m = _block_anchor_fallback(original_content, search_content, last_processed)
    if m:
        return m[0], m[1], False

    # Last resort: search from beginning (out-of-order edit)
    idx = original_content.find(search_content, 0)
    if idx != -1:
        return idx, idx + len(search_content), idx < last_processed

    raise ValueError(
        f"SEARCH block does not match anything in file:\n"
        f"{search_content[:200]}"
    )


# ── DiffResult / Replacement types ─────────────────────────────────────────

@dataclass
class Replacement:
    """A single SEARCH→REPLACE operation."""
    start: int
    end: int
    content: str


@dataclass
class DiffResult:
    """Structured result from apply_diff.

    # From diff_ref.ts { newContent, matchIndices } return type
    """
    new_content: str
    match_indices: list[int] = field(default_factory=list)


# ── Core: apply_diff (V1 — constructNewFileContentV1 port) ─────────────────

def apply_diff(
    original_content: str,
    diff_content: str,
    _lang: str = "",
    *,
    is_final: bool = True,
) -> str:
    """
    Apply a SEARCH/REPLACE diff to original_content.

    Diff format:
        ------- SEARCH
        [exact content to find]
        =======
        [replacement content]
        +++++++ REPLACE

    Matching strategy (3 tiers, from diff_ref.ts):
      1. Exact str.find()
      2. Line-trimmed comparison
      3. Block-anchor (first+last line) for 3+ line blocks

    Also supports:
      - Out-of-order replacements (from diff_ref.ts V1)
      - Empty SEARCH blocks (new file / full replacement)
      - Partial marker stripping (streaming guard)

    # Algorithm from refs/cline/src/core/assistant-message/diff.ts
    #   constructNewFileContentV1
    """
    result = apply_diff_v1(original_content, diff_content, is_final=is_final)
    return result.new_content


def apply_diff_v1(
    original_content: str,
    diff_content: str,
    *,
    is_final: bool = True,
) -> DiffResult:
    """
    Full V1 implementation returning DiffResult with match indices.

    Ports constructNewFileContentV1 from diff_ref.ts including:
      - Partial marker stripping
      - Out-of-order replacement support
      - isFinal rebuild pass that re-applies all replacements in order

    # From diff_ref.ts constructNewFileContentV1
    """
    lines = diff_content.split('\n')

    # Strip partial/incomplete trailing marker lines (streaming guard)
    if lines and _is_partial_marker(lines[-1]):
        lines.pop()

    replacements: list[Replacement] = []
    in_search = False
    in_replace = False
    current_search = ''
    current_replace = ''
    last_processed = 0
    search_match_start = -1
    search_match_end = -1
    pending_out_of_order = False

    # Streaming result (built incrementally for in-order replacements)
    result = ''

    for line in lines:
        if _is_search_start(line):
            in_search = True
            in_replace = False
            current_search = ''
            current_replace = ''
            search_match_start = -1
            search_match_end = -1
            continue

        if _is_search_end(line):
            in_search = False
            in_replace = True

            # Resolve match using 3-tier cascade
            try:
                ms, me, ooo = _find_match(
                    original_content, current_search, last_processed
                )
                search_match_start = ms
                search_match_end = me
                pending_out_of_order = ooo
            except ValueError:
                # Could not match — skip this block gracefully
                in_replace = False
                continue

            # For in-order replacements, output everything up to match
            if not pending_out_of_order:
                result += original_content[last_processed:search_match_start]
            continue

        if _is_replace_end(line):
            if search_match_start == -1:
                raise ValueError(
                    "Malformed diff: REPLACE block without SEARCH match"
                )

            replacements.append(Replacement(
                start=search_match_start,
                end=search_match_end,
                content=current_replace,
            ))

            if not pending_out_of_order:
                last_processed = search_match_end

            # Reset for next block
            in_search = False
            in_replace = False
            current_search = ''
            current_replace = ''
            search_match_start = -1
            search_match_end = -1
            pending_out_of_order = False
            continue

        # Accumulate content for search or replace
        if in_search:
            current_search += line + '\n'
        elif in_replace:
            current_replace += line + '\n'
            # Output replacement lines immediately for in-order replacements
            if search_match_start != -1 and not pending_out_of_order:
                result += line + '\n'

    # Handle unterminated replace block at end (from diff_ref.ts isFinal)
    if is_final and in_replace and search_match_start != -1:
        replacements.append(Replacement(
            start=search_match_start,
            end=search_match_end,
            content=current_replace,
        ))
        if not pending_out_of_order:
            last_processed = search_match_end

    # Final rebuild pass: sort and apply all replacements
    if is_final:
        replacements.sort(key=lambda r: r.start)
        result = ''
        pos = 0
        for rep in replacements:
            result += original_content[pos:rep.start]
            result += rep.content
            pos = rep.end
        result += original_content[pos:]

    return DiffResult(
        new_content=result,
        match_indices=[r.start for r in replacements],
    )


# ── V2: State-machine based processor ──────────────────────────────────────
# From diff_ref.ts NewFileContentConstructor (class-based V2)

class _ProcessingState(enum.IntFlag):
    IDLE = 0
    SEARCH = 1
    REPLACE = 2


class NewFileContentConstructor:
    """
    State-machine based diff processor (V2).

    Ports the NewFileContentConstructor class from diff_ref.ts.
    Processes lines one at a time, maintains state, and produces output.

    # From diff_ref.ts NewFileContentConstructor
    """

    def __init__(self, original_content: str, is_final: bool = True) -> None:
        self._original = original_content
        self._is_final = is_final
        self._state = _ProcessingState.IDLE
        self._result = ''
        self._last_processed = 0
        self._current_search = ''
        self._search_match_start = -1
        self._search_match_end = -1
        self._pending_lines: list[str] = []

    def _reset_for_next_block(self) -> None:
        self._state = _ProcessingState.IDLE
        self._current_search = ''
        self._search_match_start = -1
        self._search_match_end = -1

    def _before_replace(self) -> None:
        """Resolve the search match when entering replace mode.

        # From diff_ref.ts NewFileContentConstructor.beforeReplace()
        """
        try:
            ms, me, _ = _find_match(
                self._original, self._current_search, self._last_processed
            )
            self._search_match_start = ms
            self._search_match_end = me
        except ValueError:
            raise

        if self._search_match_start < self._last_processed:
            raise ValueError(
                f"SEARCH block matched out-of-order content in V2 mode:\n"
                f"{self._current_search[:200]}"
            )

        # Output everything up to the match location
        self._result += self._original[self._last_processed:self._search_match_start]

    def process_line(self, line: str) -> None:
        """Process a single line of diff content.

        # From diff_ref.ts NewFileContentConstructor.processLine()
        """
        if _is_search_start(line):
            self._state = _ProcessingState.SEARCH
            self._current_search = ''
        elif _is_search_end(line):
            self._state |= _ProcessingState.REPLACE
            self._before_replace()
        elif _is_replace_end(line):
            self._last_processed = self._search_match_end
            self._reset_for_next_block()
        else:
            if self._state & _ProcessingState.REPLACE:
                if self._search_match_start != -1:
                    self._result += line + '\n'
            elif self._state & _ProcessingState.SEARCH:
                self._current_search += line + '\n'
            else:
                self._pending_lines.append(line)

    def get_result(self) -> DiffResult:
        """Return the final result.

        # From diff_ref.ts NewFileContentConstructor.getResult()
        """
        if self._is_final and self._last_processed < len(self._original):
            self._result += self._original[self._last_processed:]
        if self._is_final and self._state != _ProcessingState.IDLE:
            raise ValueError(
                "File processing incomplete — SEARCH/REPLACE still active"
            )
        return DiffResult(new_content=self._result, match_indices=[])


def apply_diff_v2(
    original_content: str,
    diff_content: str,
    *,
    is_final: bool = True,
) -> DiffResult:
    """
    V2 implementation using the state-machine processor.

    # From diff_ref.ts constructNewFileContentV2
    """
    constructor = NewFileContentConstructor(original_content, is_final)

    lines = diff_content.split('\n')

    # Strip partial/incomplete trailing marker lines
    if lines and _is_partial_marker(lines[-1]):
        lines.pop()

    for line in lines:
        constructor.process_line(line)

    return constructor.get_result()


# ── Helpers ─────────────────────────────────────────────────────────────────

def build_diff_block(search: str, replace: str) -> str:
    """
    Helper: build a diff block string from search/replace text.
    Useful for testing and for the debug agent.
    """
    return f"------- SEARCH\n{search}\n=======\n{replace}\n+++++++ REPLACE\n"
