"""Three-tier error taxonomy for the replay engine.

The three tiers are:
1. business_outcome — a valid answer to the caller's question (e.g., "not found")
2. recoverable     — something the engine can fix automatically (session timeout)
3. hard_failure    — stop, log, escalate to a human

This classification is critical because callers (AI agents) need to distinguish
"the member doesn't exist" from "our automation broke" — they require different
responses and different escalation paths.
"""

from typing import Any, Optional

from playwright.sync_api import Page

from src.artifact.schema import ErrorHandler, ReplayResult


class ErrorClassifier:
    """Inspects page state and matches known error patterns."""

    def detect_error(
        self,
        page: Page,
        known_errors: dict[str, ErrorHandler],
        step_error_handlers: dict[str, ErrorHandler],
    ) -> Optional[tuple[str, ErrorHandler]]:
        """Scan the current page for any known error condition.

        Returns (error_key, handler) if a condition is matched, else None.
        """
        all_handlers = {**known_errors, **step_error_handlers}
        try:
            body_text = page.inner_text("body")
        except Exception:
            body_text = ""

        for key, handler in all_handlers.items():
            if handler.detect and handler.detect.lower() in body_text.lower():
                return key, handler
        return None

    def handle(
        self,
        error_key: str,
        handler: ErrorHandler,
        step_number: int,
        evidence_path: str,
        page: Page,
    ) -> ReplayResult:
        """Convert a detected error into a structured ReplayResult."""
        if handler.classification == "business_outcome":
            return ReplayResult(
                status="business_outcome",
                business_outcome={
                    "code": error_key.upper(),
                    "message": handler.message,
                    "detected_on_page": page.url,
                },
                steps_completed=step_number,
                evidence_path=evidence_path,
            )

        if handler.classification == "hard_failure":
            return ReplayResult(
                status="hard_failure",
                error={
                    "code": error_key.upper(),
                    "message": handler.message,
                    "step": step_number,
                    "page_url": page.url,
                },
                steps_completed=step_number,
                evidence_path=evidence_path,
            )

        # recoverable — caller must decide whether to retry or escalate
        return ReplayResult(
            status="recoverable_failure",
            error={
                "code": error_key.upper(),
                "message": handler.message,
                "action": handler.action,
                "step": step_number,
            },
            steps_completed=step_number,
            evidence_path=evidence_path,
        )
