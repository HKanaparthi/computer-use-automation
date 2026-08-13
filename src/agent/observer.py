"""Page state extraction: accessibility tree and screenshots.

We bias strongly toward the accessibility tree over raw DOM selectors because:
1. aria-labels survive cosmetic HTML restructuring (div wrappers, class renames)
2. They work identically on desktop apps via OS accessibility APIs
3. They reflect how AT (screen readers) parse the page — a reliable, stable view

The accessibility tree snapshot is sent to the LLM as the primary context.
Screenshots serve as fallback context and as evidence for the human reviewer.
"""

from typing import Any

from playwright.sync_api import Page


class PageObserver:
    """Extracts page state for the agent's observe step."""

    def extract_accessibility_tree(self, page: Page) -> str:
        """Return a compact text representation of the page's accessibility tree.

        We use Playwright's built-in accessibility snapshot API which returns
        the browser's computed accessibility tree (same data a screen reader sees).
        The snapshot is recursively flattened to a readable text format so it
        fits within the LLM context without token waste.

        interesting_only=False ensures we capture all nodes including spans with
        aria-labels used as data display elements in legacy table-layout apps.
        """
        try:
            snapshot = page.accessibility.snapshot(interesting_only=False)
            if snapshot is None:
                return "(empty accessibility tree)"
            return self._flatten_tree(snapshot, indent=0)
        except Exception as exc:
            return f"(accessibility tree unavailable: {exc})"

    def extract_page_text(self, page: Page) -> str:
        """Return the visible text of the page body as a plain string fallback."""
        try:
            text = page.inner_text("body")
            # Collapse whitespace runs for readability
            import re
            return re.sub(r"\s{3,}", "\n", text)[:3000]
        except Exception:
            return ""

    def _flatten_tree(self, node: dict[str, Any], indent: int) -> str:
        """Recursively format an accessibility node into a readable string."""
        parts = []
        prefix = "  " * indent

        role = node.get("role", "")
        name = node.get("name", "")
        value = node.get("value", "")
        description = node.get("description", "")

        line = f"{prefix}[{role}]"
        if name:
            line += f' name="{name}"'
        if value:
            line += f' value="{value}"'
        if description:
            line += f' desc="{description}"'
        parts.append(line)

        for child in node.get("children", []):
            parts.append(self._flatten_tree(child, indent + 1))

        return "\n".join(parts)

    def get_page_url(self, page: Page) -> str:
        """Return the current page URL."""
        return page.url

    def get_page_title(self, page: Page) -> str:
        """Return the current page title."""
        try:
            return page.title()
        except Exception:
            return "(unknown)"

    def build_state_summary(self, page: Page) -> dict[str, str]:
        """Return a dict with all page state needed by the planner.

        We always include page_text because the accessibility tree can be
        sparse for table-heavy legacy layouts — the visible text is a reliable
        fallback for data extraction even when the a11y tree is thin.
        """
        return {
            "url": self.get_page_url(page),
            "title": self.get_page_title(page),
            "accessibility_tree": self.extract_accessibility_tree(page),
            "page_text": self.extract_page_text(page),
        }
