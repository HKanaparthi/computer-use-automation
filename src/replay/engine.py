"""Deterministic replay engine — executes a CapabilityArtifact with no LLM.

The engine is the production path.  It accepts a loaded artifact and a dict
of runtime parameters (e.g., {"member_id": "12346"}), launches a browser,
and walks through every step exactly as recorded — substituting parameter
templates, verifying checkpoints, and classifying any errors it encounters.

Key design decisions:
- No LLM is invoked at replay time.  The artifact is the complete program.
- The locator engine tries primary → fallbacks, never hardcoding one strategy.
- Session re-login is handled automatically as a recoverable condition.
- Hard failures and business outcomes are surfaced as typed ReplayResult objects.
"""

import re
import time
from typing import Any, Optional

from playwright.sync_api import Page, sync_playwright

from src.artifact.schema import ActionStep, CapabilityArtifact, ReplayResult
from src.escalation.detector import StuckDetector
from src.escalation.handoff import EscalationHandoff
from src.observability.evidence import EvidenceCollector
from src.observability.logger import StructuredLogger
from src.observability.screenshot import ScreenshotCapture
from src.replay.checkpoint import verify as verify_checkpoint
from src.replay.error_handler import ErrorClassifier
from src.replay.locator import ElementLocatorEngine
from src.safety.allowlist import SAFETY_CONFIG, is_domain_allowed, is_url_blocked
from src.safety.redactor import redact_dict


class ReplayEngine:
    """Executes a CapabilityArtifact deterministically."""

    def __init__(self, run_dir: str, run_id: str) -> None:
        self.run_dir = run_dir
        self.run_id = run_id
        self._locator = ElementLocatorEngine()
        self._error_classifier = ErrorClassifier()
        self._logger = StructuredLogger(run_dir=run_dir, run_id=run_id)
        self._screenshots = ScreenshotCapture(run_dir=run_dir)
        self._evidence = EvidenceCollector(run_dir=run_dir)
        self._stuck_detector = StuckDetector(threshold=SAFETY_CONFIG["max_retries"])
        self._handoff = EscalationHandoff()

    def run(
        self,
        artifact: CapabilityArtifact,
        params: dict[str, str],
    ) -> ReplayResult:
        """Execute the artifact with the given runtime parameters."""
        start_ms = int(time.time() * 1000)
        steps_total = len(artifact.steps)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False, slow_mo=200)
            page = browser.new_page()
            try:
                result = self._execute(page, artifact, params, steps_total)
            except Exception as exc:
                self._logger.log({"event": "unhandled_exception", "error": str(exc)})
                self._screenshots.capture_error(page, "unhandled")
                result = ReplayResult(
                    status="hard_failure",
                    error={"code": "UNEXPECTED_EXCEPTION", "message": str(exc)},
                    steps_completed=0,
                    steps_total=steps_total,
                    evidence_path=self.run_dir,
                )
            finally:
                browser.close()

        duration_ms = int(time.time() * 1000) - start_ms
        result.duration_ms = duration_ms
        result.steps_total = steps_total
        result.evidence_path = self.run_dir

        if result.status in {"hard_failure", "escalated"}:
            self._evidence.save_error_report(result.model_dump(mode="json"))

        return result

    def _execute(
        self,
        page: Page,
        artifact: CapabilityArtifact,
        params: dict[str, str],
        steps_total: int,
    ) -> ReplayResult:
        entry_url = artifact.entry_url

        if not is_domain_allowed(entry_url) or is_url_blocked(entry_url):
            return ReplayResult(
                status="hard_failure",
                error={"code": "SAFETY_BLOCK", "message": "Entry URL blocked by safety policy"},
                steps_total=steps_total,
            )

        page.goto(entry_url, wait_until="domcontentloaded", timeout=15000)
        self._logger.log({"event": "replay_start", "url": entry_url, "params": params})
        self._screenshots.capture(page, "00_start")

        extracted: dict[str, str] = {}

        for step in artifact.steps:
            step_num = step.step_number
            self._screenshots.capture_before(page, step_num)

            # Check for known errors before executing the step.
            # Skip session_expired detection when we're legitimately at the
            # entry URL — "Sign In" appears there by design, not as an error.
            on_entry_page = page.url == artifact.entry_url
            pre_error = self._error_classifier.detect_error(
                page, artifact.known_errors, step.error_handlers
            ) if not on_entry_page else None
            if pre_error:
                error_key, handler = pre_error
                self._logger.log({"event": "error_detected_pre_step", "error_key": error_key, "step": step_num})
                self._screenshots.capture_error(page, f"step_{step_num}_error")
                result = self._error_classifier.handle(error_key, handler, step_num, self.run_dir, page)
                if result.status == "recoverable_failure":
                    recovered = self._attempt_recovery(page, handler, artifact, params)
                    if not recovered:
                        return self._escalate(page, artifact, step_num, f"Recovery failed: {handler.action}")
                    continue
                return result

            # Resolve the locator
            element = self._locator.find(page, step.locator, step.timeout_ms)
            if element is None:
                self._logger.log({"event": "locator_failed", "step": step_num, "description": step.locator.primary.description})
                self._screenshots.capture_error(page, f"step_{step_num}_locator_fail")
                return ReplayResult(
                    status="hard_failure",
                    error={
                        "code": "LOCATOR_FAILED",
                        "message": f"Step {step_num}: could not locate '{step.locator.primary.description}'",
                        "step": step_num,
                    },
                    steps_completed=step_num - 1,
                )

            # Execute the step action
            input_value = _substitute(step.input_template, params)
            success = self._execute_step(page, step, element, input_value)

            self._screenshots.capture_after(page, step_num)

            # If it was a read step, capture the extracted text
            if step.action == "read":
                try:
                    text = element.inner_text(timeout=step.timeout_ms)
                    extracted[step.locator.primary.description] = text
                except Exception:
                    pass

            log_entry = redact_dict({
                "event": "step_executed",
                "step": step_num,
                "action": step.action,
                "locator": step.locator.primary.description,
                "input": input_value or "",
                "success": success,
                "url": page.url,
            })
            self._logger.log(log_entry)

            if not success:
                return self._escalate(page, artifact, step_num, f"Step {step_num} execution failed")

            # Verify checkpoint
            passed, detail = verify_checkpoint(page, step.checkpoint, timeout_ms=step.timeout_ms)
            self._logger.log({"event": "checkpoint", "step": step_num, "passed": passed, "detail": detail})

            if not passed:
                # Check if this is a known error condition
                post_error = self._error_classifier.detect_error(
                    page, artifact.known_errors, step.error_handlers
                )
                if post_error:
                    error_key, handler = post_error
                    self._screenshots.capture_error(page, f"step_{step_num}_post_error")
                    result = self._error_classifier.handle(error_key, handler, step_num, self.run_dir, page)
                    if result.status == "recoverable_failure":
                        recovered = self._attempt_recovery(page, handler, artifact, params)
                        if not recovered:
                            return self._escalate(page, artifact, step_num, f"Recovery failed after step {step_num}")
                        continue
                    return result

                # Checkpoint failed with no known error — hard failure
                self._screenshots.capture_error(page, f"step_{step_num}_checkpoint_fail")
                return ReplayResult(
                    status="hard_failure",
                    error={
                        "code": "CHECKPOINT_FAILED",
                        "message": f"Step {step_num} checkpoint failed: {detail}",
                        "step": step_num,
                    },
                    steps_completed=step_num,
                )

        # All steps completed — check for known errors on the final page before
        # claiming success.  Business outcomes (member not found) appear after
        # the last navigation step, so we can only detect them here.
        final_error = self._error_classifier.detect_error(
            page, artifact.known_errors, {}
        )
        if final_error:
            error_key, handler = final_error
            self._logger.log({"event": "final_error_detected", "error_key": error_key})
            self._screenshots.capture_error(page, "final_state")
            return self._error_classifier.handle(error_key, handler, steps_total, self.run_dir, page)

        # Verify the success condition
        success_passed, success_detail = verify_checkpoint(page, artifact.success_condition, timeout_ms=5000)
        self._logger.log({"event": "success_condition", "passed": success_passed, "detail": success_detail})

        # Extract visible data from the final page
        extracted.update(_extract_aria_values(page))

        if not success_passed and not extracted:
            self._screenshots.capture_error(page, "success_check_failed")
            return ReplayResult(
                status="hard_failure",
                error={"code": "SUCCESS_CONDITION_FAILED", "message": success_detail},
                steps_completed=steps_total,
            )

        return ReplayResult(
            status="success",
            outputs=extracted,
            steps_completed=steps_total,
        )

    def _execute_step(self, page: Page, step: ActionStep, element, input_value: Optional[str]) -> bool:
        """Perform the Playwright action for a step."""
        try:
            if step.action == "click":
                element.click(timeout=step.timeout_ms)
                # Wait for any navigation triggered by the click to complete.
                # This is necessary for form submissions that redirect.
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=8000)
                except Exception:
                    pass  # Navigation might not happen for all clicks
            elif step.action == "type":
                element.fill(input_value or "", timeout=step.timeout_ms)
            elif step.action == "read":
                pass  # Reading happens in the caller
            elif step.action == "wait":
                time.sleep(2)
            return True
        except Exception as exc:
            self._logger.log({"event": "step_execution_error", "error": str(exc), "step": step.step_number})
            return False

    def _attempt_recovery(
        self,
        page: Page,
        handler,
        artifact: CapabilityArtifact,
        params: dict[str, str],
    ) -> bool:
        """Attempt automatic recovery for a recoverable condition."""
        if handler.action == "re_login":
            return self._re_login(page, artifact.entry_url)
        if handler.action == "retry":
            page.reload(wait_until="domcontentloaded", timeout=10000)
            return True
        if handler.action == "dismiss_dialog":
            try:
                page.keyboard.press("Escape")
                return True
            except Exception:
                return False
        return False

    def _re_login(self, page: Page, entry_url: str) -> bool:
        """Navigate back to the login page and re-authenticate."""
        try:
            page.goto(entry_url, wait_until="domcontentloaded", timeout=10000)
            username_field = page.get_by_label("Username")
            username_field.wait_for(state="visible", timeout=5000)
            username_field.fill("admin")
            page.get_by_label("Password").fill("admin123")
            page.get_by_label("Sign in to portal").click()
            page.wait_for_url("**/search", timeout=8000)
            self._logger.log({"event": "re_login_success"})
            return True
        except Exception as exc:
            self._logger.log({"event": "re_login_failed", "error": str(exc)})
            return False

    def _escalate(self, page: Page, artifact: CapabilityArtifact, step_num: int, reason: str) -> ReplayResult:
        """Pause execution and hand control to a human operator."""
        self._screenshots.capture_error(page, f"escalation_step_{step_num}")
        intervention = self._handoff.request_intervention(
            capability=artifact.name,
            stuck_at_step=step_num,
            reason=reason,
            page_url=page.url,
            evidence_path=self.run_dir,
            page=page,
        )
        if intervention == "abort":
            return ReplayResult(
                status="escalated",
                error={"code": "HUMAN_ABORTED", "message": reason, "step": step_num},
                steps_completed=step_num,
            )
        # Human resolved — signal caller to retry or continue
        return ReplayResult(
            status="escalated",
            error={"code": "HUMAN_INTERVENTION_COMPLETE", "message": "Human resolved the issue", "step": step_num},
            steps_completed=step_num,
        )


def _substitute(template: Optional[str], params: dict[str, str]) -> Optional[str]:
    """Replace {{param_name}} placeholders with runtime values."""
    if template is None:
        return None
    result = template
    for key, value in params.items():
        result = result.replace(f"{{{{{key}}}}}", value)
    return result


def _extract_aria_values(page: Page) -> dict[str, str]:
    """Extract text from elements with aria-label attributes for outputs."""
    result: dict[str, str] = {}
    targets = {
        "savings_balance": "Savings balance",
        "checking_balance": "Checking balance",
        "member_name": "Member name",
        "account_type": "Account type",
        "member_id_display": "Member ID",
    }
    for key, aria_label in targets.items():
        try:
            el = page.get_by_label(aria_label)
            el.wait_for(state="visible", timeout=2000)
            result[key] = el.inner_text(timeout=2000).strip()
        except Exception:
            pass
    return result
