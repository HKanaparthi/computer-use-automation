"""Screenshot capture utilities."""

from pathlib import Path
from typing import Optional

from playwright.sync_api import Page


class ScreenshotCapture:
    """Captures and saves page screenshots at key automation moments."""

    def __init__(self, run_dir: str) -> None:
        self.screenshots_dir = Path(run_dir) / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self._counter = 0

    def capture(self, page: Page, label: str) -> str:
        """Save a full-page screenshot and return its relative path."""
        self._counter += 1
        filename = f"step_{self._counter:03d}_{label}.png"
        full_path = self.screenshots_dir / filename
        try:
            page.screenshot(path=str(full_path), full_page=True)
        except Exception:
            # Never let screenshot failure crash the automation
            pass
        return str(full_path)

    def capture_before(self, page: Page, step: int) -> str:
        return self.capture(page, f"{step:03d}_before")

    def capture_after(self, page: Page, step: int) -> str:
        return self.capture(page, f"{step:03d}_after")

    def capture_error(self, page: Page, context: str) -> str:
        return self.capture(page, f"error_{context}")
