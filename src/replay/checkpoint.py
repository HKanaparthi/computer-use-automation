"""Checkpoint verification after each replay step.

A checkpoint is a declarative assertion about what the page should look like
after an action succeeds.  Checking checkpoints after every step gives us
early signal that the UI drifted or that a business outcome occurred (e.g.,
"Member not found" appears instead of the expected member detail).
"""

import re

from playwright.sync_api import Page

from src.replay.locator import ElementLocatorEngine

_locator_engine = ElementLocatorEngine()


def verify(page: Page, checkpoint, timeout_ms: int = 5000) -> tuple[bool, str]:
    """Verify that the page satisfies the checkpoint condition.

    Returns:
        (passed: bool, detail: str) — detail is a human-readable description
        of what was found or why verification failed.
    """
    ctype = checkpoint.type

    if ctype == "url_matches":
        current = page.url
        matched = re.search(checkpoint.expected, current) is not None
        return matched, f"URL '{current}' {'matches' if matched else 'does not match'} '{checkpoint.expected}'"

    if ctype == "text_present":
        try:
            page.wait_for_function(
                f"document.body.innerText.includes(arguments[0])",
                arg=checkpoint.expected,
                timeout=timeout_ms,
            )
            return True, f"Text '{checkpoint.expected}' found on page"
        except Exception:
            body = ""
            try:
                body = page.inner_text("body")[:200]
            except Exception:
                pass
            return False, f"Text '{checkpoint.expected}' not found. Page starts with: {body}"

    if ctype in {"element_visible", "element_contains"}:
        if checkpoint.locator is None:
            return True, "No locator specified for checkpoint — skipped"
        element = _locator_engine.find(page, checkpoint.locator, timeout_ms)
        if element is None:
            return False, f"Checkpoint element not found: {checkpoint.description}"
        if ctype == "element_contains":
            try:
                text = element.inner_text(timeout=timeout_ms)
                contained = checkpoint.expected.lower() in text.lower()
                return contained, f"Element text '{text[:100]}' {'contains' if contained else 'missing'} '{checkpoint.expected}'"
            except Exception as exc:
                return False, f"Could not read element text: {exc}"
        return True, f"Checkpoint element visible: {checkpoint.description}"

    return False, f"Unknown checkpoint type: {ctype}"
