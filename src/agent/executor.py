"""Playwright action execution: turns agent decisions into browser actions.

The executor is intentionally thin — it translates the action dict from the
planner into Playwright calls, tries the primary locator, and falls back to
the ordered list of alternatives on failure.

Element location order:
  1. accessibility_label  → page.get_by_label(value)
  2. text_content         → page.get_by_text(value, exact=False)
  3. role_and_name        → page.get_by_role(role, name=name)
  4. css_selector         → page.locator(value)

This order reflects stability: accessibility labels survive layout changes;
CSS selectors break when tables are restructured.
"""

import time
from typing import Any, Optional

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout


class ActionExecutor:
    """Executes agent actions via Playwright."""

    DEFAULT_TIMEOUT_MS = 5000

    def execute(
        self,
        page: Page,
        action_dict: dict[str, Any],
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> dict[str, Any]:
        """Execute a single action and return a result dict.

        Returns:
            {"success": bool, "error": str|None, "extracted": dict|None}
        """
        action = action_dict.get("action", "")
        locator_data = action_dict.get("locator", {})
        input_value = action_dict.get("input_value", "")

        if action == "navigate":
            # navigate_url is the correct field; fall back to locator.value only
            # if the agent mistakenly put the URL there.
            url = action_dict.get("navigate_url") or locator_data.get("value", "")
            return self._navigate(page, url)

        if action == "wait":
            time.sleep(2)
            return {"success": True, "error": None, "extracted": None}

        if action in {"done", "stuck"}:
            return {
                "success": action == "done",
                "error": None,
                "extracted": action_dict.get("extracted_data", {}),
            }

        if action == "read":
            return self._read(page, locator_data, timeout_ms)

        if action == "click":
            return self._click(page, locator_data, timeout_ms)

        if action == "type":
            return self._type(page, locator_data, input_value, timeout_ms)

        return {"success": False, "error": f"Unknown action: {action}", "extracted": None}

    def _resolve_element(self, page: Page, locator_data: dict[str, Any], timeout_ms: int):
        """Try locator strategies in priority order, return a Playwright locator."""
        strategies = [
            {
                "strategy": locator_data.get("strategy", "accessibility_label"),
                "value": locator_data.get("value", ""),
            }
        ] + locator_data.get("fallbacks", [])

        last_exc: Optional[Exception] = None
        for strat in strategies:
            try:
                element = self._apply_strategy(page, strat["strategy"], strat["value"])
                element.wait_for(state="visible", timeout=timeout_ms)
                return element
            except Exception as exc:
                last_exc = exc
                continue

        raise RuntimeError(
            f"All locator strategies failed for '{locator_data.get('description', '')}'. "
            f"Last error: {last_exc}"
        )

    def _apply_strategy(self, page: Page, strategy: str, value: str):
        """Map a strategy name to a Playwright locator."""
        if strategy == "accessibility_label":
            return page.get_by_label(value)
        if strategy == "text_content":
            return page.get_by_text(value, exact=False)
        if strategy == "role_and_name":
            parts = value.split(":", 1)
            role = parts[0].strip()
            name = parts[1].strip() if len(parts) > 1 else ""
            return page.get_by_role(role, name=name)
        # css_selector is the fallback of last resort
        return page.locator(value)

    def _click(self, page: Page, locator_data: dict[str, Any], timeout_ms: int) -> dict[str, Any]:
        try:
            element = self._resolve_element(page, locator_data, timeout_ms)
            element.click(timeout=timeout_ms)
            return {"success": True, "error": None, "extracted": None}
        except Exception as exc:
            return {"success": False, "error": str(exc), "extracted": None}

    def _type(
        self, page: Page, locator_data: dict[str, Any], text: str, timeout_ms: int
    ) -> dict[str, Any]:
        try:
            element = self._resolve_element(page, locator_data, timeout_ms)
            element.fill(text, timeout=timeout_ms)
            return {"success": True, "error": None, "extracted": None}
        except Exception as exc:
            return {"success": False, "error": str(exc), "extracted": None}

    def _read(self, page: Page, locator_data: dict[str, Any], timeout_ms: int) -> dict[str, Any]:
        try:
            element = self._resolve_element(page, locator_data, timeout_ms)
            text = element.inner_text(timeout=timeout_ms)
            return {"success": True, "error": None, "extracted": {"text": text}}
        except Exception as exc:
            return {"success": False, "error": str(exc), "extracted": None}

    def _navigate(self, page: Page, url: str) -> dict[str, Any]:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            return {"success": True, "error": None, "extracted": None}
        except Exception as exc:
            return {"success": False, "error": str(exc), "extracted": None}
