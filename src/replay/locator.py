"""Element location with a cascading fallback chain.

The replay engine never guesses — it tries each strategy in the order the
artifact recorded them, from most-stable (accessibility label) to least-stable
(CSS selector).  If all strategies fail, it returns None so the caller can
classify the failure appropriately.
"""

from typing import Optional

from playwright.sync_api import Page


class ElementLocatorEngine:
    """Resolves ElementLocator objects into live Playwright locators."""

    def find(self, page: Page, locator, timeout_ms: int = 5000):
        """Resolve an ElementLocator, trying primary then each fallback.

        Args:
            page: The active Playwright page.
            locator: An ElementLocator schema object.
            timeout_ms: Per-strategy timeout.

        Returns:
            A Playwright locator that is visible, or None if all strategies fail.
        """
        strategies = [locator.primary] + list(locator.fallbacks)
        for strategy in strategies:
            result = self._try_strategy(page, strategy, timeout_ms)
            if result is not None:
                return result
        return None

    def _try_strategy(self, page: Page, strategy, timeout_ms: int):
        """Attempt a single locator strategy.  Returns None on failure."""
        try:
            element = self._build_locator(page, strategy)
            element.wait_for(state="visible", timeout=timeout_ms)
            return element
        except Exception:
            return None

    def _build_locator(self, page: Page, strategy):
        """Map a LocatorStrategy to a Playwright locator object."""
        strat = strategy.strategy
        val = strategy.value

        if strat == "accessibility_label":
            return page.get_by_label(val)
        if strat == "text_content":
            return page.get_by_text(val, exact=False)
        if strat == "role_and_name":
            parts = val.split(":", 1)
            role = parts[0].strip()
            name = parts[1].strip() if len(parts) > 1 else ""
            return page.get_by_role(role, name=name)
        # css_selector is last resort
        return page.locator(val)
