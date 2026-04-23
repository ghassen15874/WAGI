import json
import logging
import os
import re
import asyncio

class RuntimeValidator:
    """
    Smart Runtime Validator (Browser & UI Bridge) with AI-first decision making.

    Detection pipeline:
      1. DOM availability gate   — if browser check failed or DOM is empty/tiny,
                                   skip all UI checks (prevents false signals).
      2. AI analysis (primary)   — ask the validation-stage LLM to make the real decision.
      3. Semantic heuristics     — lightweight keyword scan only when AI is absent.
      4. Static route presence   — only used to gate login/comment checks, never
                                   as a standalone trigger.

    False-signal protection:
      - No issues are flagged when the DOM is missing or shorter than MIN_DOM_LENGTH.
      - AI must return HIGH or MEDIUM confidence before an issue is emitted.
      - Semantic heuristics are clearly marked [Semantic] so the caller can
        distinguish them from AI-confirmed findings.
    """

    # Minimum characters in DOM snapshot before we trust the page has rendered.
    MIN_DOM_LENGTH = 500

    def __init__(
        self,
        sandbox_dir,
        tool_registry,
        error_analyzer=None,
        provider=None,
        model_id: str = "",
        frontend_port: int = 3000,
    ):
        self.sandbox_dir   = sandbox_dir
        self.tool_registry = tool_registry
        self.error_analyzer = error_analyzer
        self.provider = provider
        self.model_id = model_id
        self.frontend_port = int(frontend_port)
        self.logger = logging.getLogger(__name__)
        # Populated by check_missing_ui(); callers can stream this list to the UI
        self._gate_log: list = []

    # ------------------------------------------------------------------
    # Public: backend & browser checks (unchanged API contract)
    # ------------------------------------------------------------------

    def _parse_json_from_output(self, output: str) -> dict:
        """Extract the last valid JSON object from mixed validator output."""
        if not output or not output.strip():
            return None

        raw = str(output)
        decoder = json.JSONDecoder()
        starts = [idx for idx, ch in enumerate(raw) if ch == "{"]

        # Prefer objects near the end, since validator payloads are emitted last.
        for start in reversed(starts):
            candidate = raw[start:]
            try:
                parsed, consumed = decoder.raw_decode(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and not candidate[consumed:].strip():
                return parsed

        # Fallback: attempt line-wise decode from bottom to top.
        for line in reversed([l.strip() for l in raw.splitlines() if l.strip()]):
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed

        # Regex fallback: search for JSON-looking object windows from the end.
        for match in reversed(list(re.finditer(r"\{[\s\S]*?\}", raw))):
            candidate = match.group(0)
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed

        return None

    async def run_backend_check(self):
        """Run the NodeJS backend validator script."""
        try:
            raw_output = await self.tool_registry.execute("backend_validator", {})
            if "Command timed out after" in str(raw_output):
                return {
                    "status": "error",
                    "crashed": True,
                    "infra_error": True,
                    "errors": [f"BACKEND_VALIDATOR_TIMEOUT: {str(raw_output).strip()[-300:]}"],
                    "raw_output": str(raw_output or ""),
                }
            result = self._parse_json_from_output(raw_output)
            if not result:
                 raw_text = str(raw_output or "")
                 return {
                    "status": "error",
                    "crashed": True,
                    "infra_error": True,
                    "errors": [f"No valid JSON output from backend validator. Raw tail: {raw_text[-300:]}"],
                    "raw_output": raw_text,
                }
            return result
        except Exception as e:
            self.logger.error(f"[RuntimeValidator] backend_validator failed: {e}")
            return {
                "status": "error",
                "crashed": True,
                "infra_error": True,
                "errors": [f"Validator exception: {str(e)}"],
            }

    async def run_browser_check(self):
        """Run the Playwright browser verification."""
        max_attempts = 4
        delays = [2, 4, 6]
        last_result = None
        last_error = None

        for attempt in range(1, max_attempts + 1):
            try:
                raw_output = await self.tool_registry.execute(
                    "browser_check",
                    {"frontend_port": self.frontend_port},
                )
                result = self._parse_json_from_output(raw_output)
                if not result:
                    last_result = {
                        "status": "error",
                        "errors": [f"No valid JSON output from browser validator. Raw: {str(raw_output)[:200]}"],
                    }
                else:
                    last_result = result
                    if result.get("status") != "error":
                        return result

                    blob = " ".join(
                        [
                            str(item)
                            for item in (
                                list(result.get("runtime_errors", []) or [])
                                + list(result.get("network_errors", []) or [])
                                + list(result.get("errors", []) or [])
                            )
                        ]
                    ).lower()
                    is_boot_timing_error = any(
                        token in blob
                        for token in (
                            "err_connection_refused",
                            "err_aborted",
                            "unable to reach preview server",
                            "chrome-error://chromewebdata",
                            "navigation to",
                        )
                    )

                    if not is_boot_timing_error:
                        return result

            except Exception as e:
                last_error = e
                self.logger.error(f"[RuntimeValidator] browser_check attempt {attempt} failed: {e}")

            if attempt < max_attempts:
                await asyncio.sleep(delays[attempt - 1] if attempt - 1 < len(delays) else delays[-1])

        if last_result is not None:
            return last_result
        return {"status": "error", "errors": [f"Validator exception: {str(last_error)}"]}

    # ------------------------------------------------------------------
    # Public: AI-first UI check
    # ------------------------------------------------------------------

    async def check_missing_ui(self, browser_result: dict) -> list:
        """
        Detect missing UI features using AI-first decision making.

        Returns a de-duplicated list of confirmed issue strings.
        Returns [] (empty list) when:
          - browser_result has status == "error"  (browser didn't load — can't judge)
          - DOM snapshot is absent or too short   (page may still be loading)
          - AI returns high confidence that UI is present
        """

        # Reset gate log for each run so callers can stream it
        self._gate_log: list = []

        # ── Gate 1: Did the browser check succeed? ─────────────────────
        if browser_result.get("status") == "error":
            _msg = (
                "🚫 [Gate 1: Status] browser_result.status == 'error' — "
                "browser did not load the page. "
                "Skipping ALL UI checks to prevent false positives."
            )
            self._gate_log.append(_msg)
            self.logger.info(_msg)
            b_errors = browser_result.get("errors", ["Browser failed to load page."])
            return [f"[Browser Crash] {e}" for e in b_errors]
        self._gate_log.append("✅ [Gate 1: Status] Browser loaded the page successfully.")

        # ── Gate 2: Is there a real DOM snapshot? ──────────────────────
        dom = browser_result.get("dom_snapshot", "")
        dom_len = len(dom)
        if not dom or dom_len < self.MIN_DOM_LENGTH:
            _msg = (
                f"🚫 [Gate 2: DOM Length] DOM is only {dom_len} chars "
                f"(minimum required: {self.MIN_DOM_LENGTH}). "
                "Page has not finished rendering. Skipping UI checks."
            )
            self._gate_log.append(_msg)
            self.logger.info(_msg)
            return [f"[Blank Page] DOM is less than {self.MIN_DOM_LENGTH} chars (got {dom_len}). Page appears blank or failed to render."]
        self._gate_log.append(
            f"✅ [Gate 2: DOM Length] DOM is {dom_len} chars — large enough to analyse."
        )

        # ── Gate 3: Did the page actually render visible content? ───────
        visible_text = re.sub(r'<[^>]+>', '', dom).strip()
        visible_len  = len(visible_text)
        if visible_len < 100:
            _msg = (
                f"🚫 [Gate 3: Visible Text] Only {visible_len} chars of visible text found "
                "(minimum required: 100). "
                "DOM contains tags but no real readable content — "
                "blank or still-loading page. Skipping UI checks."
            )
            self._gate_log.append(_msg)
            self.logger.info(_msg)
            return [f"[Blank Page] DOM has insufficient visible text (got {visible_len} chars). Page appears blank."]
        self._gate_log.append(
            f"✅ [Gate 3: Visible Text] {visible_len} chars of visible text — page is rendered."
        )

        issues = []
        feature_keys = self._determine_ui_feature_scope(dom, browser_result)

        # ── Layer 1: AI analysis (primary decision maker) ──────────────
        if self.provider is not None:
            try:
                ai_issues = await self._analyze_dom_with_ai(dom, browser_result, feature_keys)
                issues.extend(ai_issues)
                _ai_msg = f"🤖 [AI Layer] AI analysis returned {len(ai_issues)} issue(s)."
                self._gate_log.append(_ai_msg)
                self.logger.info(_ai_msg)
                # If AI ran successfully, trust it and skip heuristics for
                # every feature it evaluated, not only the ones it flagged.
                ai_covered = set(feature_keys)
                issues.extend(
                    self._run_semantic_checks(dom, covered=ai_covered)
                )
            except Exception as e:
                _fb_msg = f"⚠️ [AI Layer] AI analysis failed ({e}) — falling back to semantic checks."
                self._gate_log.append(_fb_msg)
                self.logger.warning(_fb_msg)
                issues.extend(self._run_semantic_checks(dom, covered=set(), feature_scope=feature_keys))
        else:
            self._gate_log.append("ℹ️ [AI Layer] No LLM provider available — using semantic heuristics only.")
            issues.extend(self._run_semantic_checks(dom, covered=set(), feature_scope=feature_keys))

        # De-duplicate while preserving insertion order
        seen: set = set()
        unique: list = []
        for issue in issues:
            if issue not in seen:
                seen.add(issue)
                unique.append(issue)

        if self._should_ignore_ai_landing_page_false_positive(dom, unique):
            self._gate_log.append(
                "ℹ️ [Post Filter] Ignoring AI-only navbar/login findings on a rendered landing page that already exposes login/register entry links."
            )
            return []

        return unique

    # ------------------------------------------------------------------
    # Private: AI analysis
    # ------------------------------------------------------------------

    def _determine_ui_feature_scope(self, dom: str, browser_result: dict) -> set[str]:
        ui = browser_result.get("ui", {}) or {}
        dom_text = re.sub(r"<[^>]+>", " ", str(dom or ""))

        auth_routes_present = os.path.exists(os.path.join(self.sandbox_dir, "server", "routes", "authRoutes.ts"))
        comment_routes_present = os.path.exists(os.path.join(self.sandbox_dir, "server", "routes", "commentRoutes.ts"))

        auth_entrypoint_patterns = (
            r'href=["\']/(?:login|register)["\']',
            r">\s*(?:sign in|log in|register|create account)\s*<",
        )
        auth_page_patterns = (
            r"<form[\s>]",
            r'type=["\']password["\']',
            r'autocomplete=["\']current-password["\']',
            r'autocomplete=["\']new-password["\']',
        )
        app_shell_patterns = (
            r'href=["\']/(?:dashboard|jobs|team|settings)["\']',
            r">\s*logout\s*<",
        )
        comment_surface_patterns = (
            r"<textarea[\s>]",
            r"\b(?:comment|discussion|reply)\b",
        )

        has_auth_entrypoints = any(re.search(pattern, dom, re.IGNORECASE) for pattern in auth_entrypoint_patterns)
        looks_like_auth_page = bool(ui.get("hasLogin")) or any(
            re.search(pattern, dom, re.IGNORECASE) for pattern in auth_page_patterns
        )
        looks_like_app_shell = bool(ui.get("hasNavbar")) or any(
            re.search(pattern, dom_text, re.IGNORECASE) for pattern in app_shell_patterns
        )
        looks_like_comment_surface = bool(ui.get("hasComments")) or any(
            re.search(pattern, dom, re.IGNORECASE) for pattern in comment_surface_patterns
        )

        features: set[str] = set()

        if looks_like_app_shell:
            features.add("navbar")
        else:
            self._gate_log.append(
                "ℹ️ [Feature Scope] Skipping navbar audit on the current rendered page because it does not look like the authenticated app shell."
            )

        if auth_routes_present and looks_like_auth_page:
            features.add("login")
        elif auth_routes_present and has_auth_entrypoints:
            self._gate_log.append(
                "ℹ️ [Feature Scope] Auth routes exist and entry links are visible on this page, so login/register form audit is skipped for the current route."
            )

        if comment_routes_present and looks_like_comment_surface:
            features.add("comment")

        return features

    def _should_ignore_ai_landing_page_false_positive(self, dom: str, issues: list[str]) -> bool:
        normalized_issues = [str(issue or "").strip() for issue in list(issues or []) if str(issue or "").strip()]
        if not normalized_issues:
            return False

        allowed_prefixes = (
            "[AI] Missing navbar",
            "[AI] Missing login/register form",
        )
        if not all(issue.startswith(allowed_prefixes) for issue in normalized_issues):
            return False

        has_auth_links = bool(re.search(r'href=["\']/(?:login|register)["\']', str(dom or ""), re.IGNORECASE))
        has_password_input = bool(re.search(r'type=["\']password["\']', str(dom or ""), re.IGNORECASE))
        has_structural_nav = bool(
            re.search(
                r'<nav[\s>]|role=["\']navigation["\']|href=["\']/(?:dashboard|jobs|team|settings)["\']|>\s*logout\s*<',
                str(dom or ""),
                re.IGNORECASE,
            )
        )
        has_rendered_content = len(re.sub(r"<[^>]+>", " ", str(dom or "")).strip()) >= 100

        return has_auth_links and not has_password_input and not has_structural_nav and has_rendered_content

    async def _analyze_dom_with_ai(self, dom: str, browser_result: dict, feature_keys: set[str] | None = None) -> list:
        """
        AI-first DOM analysis with confidence gating.

        The AI is asked to evaluate three specific UI features and return a
        structured JSON response with a confidence level per finding.
        Only HIGH or MEDIUM confidence issues are propagated.

        Returns a list of issue strings.
        """
        ui = browser_result.get("ui", {})

        # Build a concise prompt — send first 4000 chars of DOM to avoid token bloat
        dom_excerpt = dom[:4000]

        # Summarise what the static browser check already found (if any)
        static_summary = (
            f"Static browser check: "
            f"hasNavbar={ui.get('hasNavbar', 'unknown')}, "
            f"hasLogin={ui.get('hasLogin', 'unknown')}, "
            f"hasComments={ui.get('hasComments', 'unknown')}"
        )

        requested_features = set(feature_keys or set())
        features_to_check = []
        if "navbar" in requested_features:
            features_to_check.append("navbar")
        if "login" in requested_features:
            features_to_check.append("login/register form")
        if "comment" in requested_features:
            features_to_check.append("comment section")

        if not features_to_check:
            self._gate_log.append(
                "ℹ️ [Feature Scope] No route-appropriate UI features were selected for AI audit on the current page."
            )
            return []

        prompt = (
            "You are a frontend QA engineer auditing a React application.\n"
            "Your job is to identify REAL missing UI features based on what is "
            "actually present in the HTML DOM snapshot below.\n\n"
            f"Static browser check summary: {static_summary}\n\n"
            f"Features to audit: {', '.join(features_to_check)}\n\n"
            "DOM SNAPSHOT (first 4000 chars):\n"
            f"{dom_excerpt}\n\n"
            "For EACH feature, decide:\n"
            "  - Is it present in the DOM? (yes/no)\n"
            "  - Confidence level: HIGH | MEDIUM | LOW\n\n"
            "RULES:\n"
            "  - Only flag a feature as missing if you are HIGH or MEDIUM confidence.\n"
            "  - If the DOM is clearly rendered (has headings, paragraphs, links) "
            "    but a specific feature is absent, that is a valid finding.\n"
            "  - If the DOM looks like a loading spinner or error screen, "
            "    report NO issues (confidence is LOW for everything).\n"
            "  - Do NOT flag issues for features whose backend route files don't exist.\n\n"
            "Respond ONLY with a JSON array. Each element has:\n"
            '  {"feature": "<name>", "missing": true|false, "confidence": "HIGH"|"MEDIUM"|"LOW", '
            '"reason": "<one short sentence>"}\n\n'
            "Examples:\n"
            '[{"feature": "navbar", "missing": false, "confidence": "HIGH", "reason": "Found <nav> element"}]\n'
            '[{"feature": "login/register form", "missing": true, "confidence": "HIGH", '
            '"reason": "No password input or login form detected in the rendered DOM"}]\n'
            "If nothing is missing, respond with: []"
        )

        if self.provider is None:
            self.logger.debug("[RuntimeValidator] No LLM provider supplied for DOM analysis")
            return []

        from ..providers import is_provider_status_token

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a frontend QA engineer. "
                    "Return only JSON and do not include markdown fences."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        raw_chunks: list[str] = []
        async for token in self.provider.stream(messages, self.model_id):
            if is_provider_status_token(token):
                continue
            raw_chunks.append(token)

        raw = "".join(raw_chunks).strip()
        return self._parse_ai_response(raw)

    def _parse_ai_response(self, raw) -> list:
        """
        Parse the AI response into a list of issue strings.
        Only emits issues with HIGH or MEDIUM confidence.
        """
        issues = []

        # Normalise to a list of dicts
        findings = []
        if isinstance(raw, list):
            findings = raw
        elif isinstance(raw, str):
            # Strip markdown fences if present
            cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
            try:
                parsed = json.loads(cleaned)
                if isinstance(parsed, list):
                    findings = parsed
                elif isinstance(parsed, dict):
                    findings = [parsed]
            except (json.JSONDecodeError, ValueError):
                # Last resort: if it's a plain-text issue description, emit as-is
                if raw.strip() and len(raw) < 200:
                    issues.append(f"[AI] {raw.strip()}")
                return issues
        elif isinstance(raw, dict):
            # ErrorAnalyzer.analyze() style: {"type": ..., "fix": ..., "severity": ...}
            fix = raw.get("fix", "")
            if fix and raw.get("type") not in ("UNKNOWN", None):
                issues.append(f"[AI] {fix}")
            return issues

        # Process structured findings
        for item in findings:
            if not isinstance(item, dict):
                continue
            if not item.get("missing", False):
                continue
            confidence = item.get("confidence", "LOW").upper()
            if confidence not in ("HIGH", "MEDIUM"):
                self.logger.debug(
                    f"[RuntimeValidator] Skipping low-confidence AI finding: {item}"
                )
                continue
            feature = item.get("feature", "unknown feature")
            reason  = item.get("reason", "")
            label   = f"[AI] Missing {feature}"
            if reason:
                label += f" — {reason}"
            issues.append(label)

        return issues

    # ------------------------------------------------------------------
    # Private: semantic heuristics (fallback layer)
    # ------------------------------------------------------------------

    def _run_semantic_checks(self, dom: str, covered: set, feature_scope: set[str] | None = None) -> list:
        """
        Lightweight keyword/pattern scan of the DOM.
        Only runs checks for features NOT already covered by the AI layer.

        Returns a list of [Semantic] prefixed issue strings.
        """
        issues = []
        scope = set(feature_scope or set())

        # ── Navbar ─────────────────────────────────────────────────────
        if "navbar" in scope and "navbar" not in covered:
            navbar_patterns = [
                r'<nav[\s>]',
                r'<header[\s>]',
                r'class=["\'][^"\']*navbar[^"\']*["\']',
                r'class=["\'][^"\']*nav-bar[^"\']*["\']',
                r'class=["\'][^"\']*site-header[^"\']*["\']',
                r'class=["\'][^"\']*top-bar[^"\']*["\']',
                r'id=["\'][^"\']*navbar[^"\']*["\']',
                r'id=["\'][^"\']*navigation[^"\']*["\']',
                r'role=["\']navigation["\']',
                r'role=["\']banner["\']',
            ]
            if not any(re.search(p, dom, re.IGNORECASE) for p in navbar_patterns):
                issues.append(
                    "[Semantic] Possible missing navbar — "
                    "no <nav>, <header>, or navbar/navigation class/role detected"
                )

        # ── Login / Auth ───────────────────────────────────────────────
        if "login" in scope and "login" not in covered:
            auth_routes = os.path.join(
                self.sandbox_dir, "server", "routes", "authRoutes.ts"
            )
            if os.path.exists(auth_routes):
                login_patterns = [
                    r'type=["\']password["\']',
                    r'class=["\'][^"\']*login[^"\']*["\']',
                    r'class=["\'][^"\']*signin[^"\']*["\']',
                    r'class=["\'][^"\']*auth[^"\']*["\']',
                    r'id=["\'][^"\']*login[^"\']*["\']',
                    r'id=["\'][^"\']*signin[^"\']*["\']',
                    r'name=["\']password["\']',
                    r'placeholder=["\'][^"\']*password[^"\']*["\']',
                    r'autocomplete=["\']current-password["\']',
                ]
                if not any(re.search(p, dom, re.IGNORECASE) for p in login_patterns):
                    issues.append(
                        "[Semantic] Possible missing login form — "
                        "no password input, login/auth class, or signin element detected"
                    )

        # ── Comment section ────────────────────────────────────────────
        if "comment" in scope and "comment" not in covered:
            comment_routes = os.path.join(
                self.sandbox_dir, "server", "routes", "commentRoutes.ts"
            )
            if os.path.exists(comment_routes):
                comment_patterns = [
                    r'class=["\'][^"\']*comment[^"\']*["\']',
                    r'class=["\'][^"\']*discussion[^"\']*["\']',
                    r'class=["\'][^"\']*reply[^"\']*["\']',
                    r'id=["\'][^"\']*comment[^"\']*["\']',
                    r'<textarea[\s>]',
                    r'placeholder=["\'][^"\']*comment[^"\']*["\']',
                    r'placeholder=["\'][^"\']*reply[^"\']*["\']',
                ]
                if not any(re.search(p, dom, re.IGNORECASE) for p in comment_patterns):
                    issues.append(
                        "[Semantic] Possible missing comment section — "
                        "no comment/reply class or textarea detected"
                    )

        return issues
