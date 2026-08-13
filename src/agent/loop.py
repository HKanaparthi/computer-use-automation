"""Observe → Decide → Act loop for discovery mode.

The loop is the orchestrator: it holds the Playwright browser session open,
coordinates the observer, planner, and executor, and terminates cleanly on
goal completion, max-step limit, or hard failure.

No LLM calls happen outside this module during discovery.  The artifact
recorder is invoked at the end of a successful run to convert the raw action
trace into a typed, reusable CapabilityArtifact.
"""

import time
from typing import Any, Optional

from playwright.sync_api import Browser, Page, sync_playwright

from src.agent.executor import ActionExecutor
from src.agent.observer import PageObserver
from src.agent.planner import AgentPlanner
from src.artifact.recorder import build_artifact
from src.artifact.schema import CapabilityArtifact
from src.artifact.store import ArtifactStore
from src.observability.evidence import EvidenceCollector
from src.observability.logger import StructuredLogger
from src.observability.screenshot import ScreenshotCapture
from src.safety.allowlist import is_action_allowed, is_domain_allowed, is_url_blocked
from src.safety.redactor import redact_dict


MAX_STEPS = 20
TIMEOUT_SECONDS = 120
STUCK_THRESHOLD = 5  # Same URL for this many steps → escalate


def run_discovery(
    goal: str,
    target_url: str,
    artifact_output_path: str,
    run_dir: str,
    model: str = "claude-sonnet-4-6",
    credentials: Optional[str] = None,
) -> Optional[CapabilityArtifact]:
    """Run the discovery agent loop and save the resulting artifact.

    This is the primary entry point for discovery mode.  It launches a real
    browser, drives it with LLM guidance until the goal is achieved, then
    emits a CapabilityArtifact that can be replayed deterministically.

    Returns the artifact on success, None on failure.
    """
    logger = StructuredLogger(run_dir=run_dir, run_id="discovery")
    screenshots = ScreenshotCapture(run_dir=run_dir)
    evidence = EvidenceCollector(run_dir=run_dir)

    # If credentials were provided, append them to the goal so the planner
    # can use them without guessing.  Credentials are never logged.
    effective_goal = goal
    if credentials:
        effective_goal = f"{goal} [Credentials to use if needed: {credentials}]"

    observer = PageObserver()
    planner = AgentPlanner(model=model)
    executor = ActionExecutor()
    store = ArtifactStore()

    action_trace: list[dict[str, Any]] = []
    extracted_outputs: dict[str, str] = {}
    # Track URL+action fingerprints to detect stuck state.
    # We do NOT compare accessibility trees because typing into form fields
    # does not change the tree structure — leading to false "stuck" detections.
    previous_fingerprint: Optional[str] = None
    stuck_counter = 0

    start_time = time.time()

    with sync_playwright() as pw:
        browser: Browser = pw.chromium.launch(headless=False, slow_mo=300)
        page: Page = browser.new_page()

        try:
            # Safety check on the target URL before we navigate
            if not is_domain_allowed(target_url):
                logger.log({"event": "safety_block", "reason": "domain not in allowlist", "url": target_url})
                return None
            if is_url_blocked(target_url):
                logger.log({"event": "safety_block", "reason": "url matches blocked pattern", "url": target_url})
                return None

            page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
            logger.log({"event": "navigation", "url": target_url})
            screenshots.capture(page, "00_initial")

            for step in range(1, MAX_STEPS + 1):
                if time.time() - start_time > TIMEOUT_SECONDS:
                    logger.log({"event": "timeout", "step": step, "elapsed_s": TIMEOUT_SECONDS})
                    break

                # OBSERVE
                page_state = observer.build_state_summary(page)

                # Stuck detection: compare URL + recent-action fingerprint.
                # Accessibility tree alone is a bad signal because form filling
                # (type username, type password) happens on the same page and
                # tree structure stays the same — we'd false-positive every login.
                current_fp = page.url
                if current_fp == previous_fingerprint:
                    stuck_counter += 1
                else:
                    stuck_counter = 0
                previous_fingerprint = current_fp

                if stuck_counter >= STUCK_THRESHOLD:
                    logger.log({"event": "stuck_detected", "step": step, "stuck_count": stuck_counter})
                    screenshots.capture_error(page, "stuck")
                    break

                # DECIDE
                action_dict = planner.decide(
                    goal=effective_goal,
                    page_state=page_state,
                    action_history=action_trace,
                )

                action_type = action_dict.get("action", "")
                logger.log(
                    redact_dict({
                        "event": "agent_decision",
                        "step": step,
                        "action": action_type,
                        "reasoning": action_dict.get("reasoning", ""),
                        "locator": action_dict.get("locator", {}),
                        "checkpoint": action_dict.get("checkpoint", ""),
                    })
                )

                # Safety gate
                if not is_action_allowed(action_type) and action_type not in {"done", "stuck"}:
                    logger.log({"event": "safety_block", "reason": "action not allowed", "action": action_type})
                    break

                # ACT
                result = executor.execute(page, action_dict)

                screenshots.capture_after(page, step)

                trace_entry = {
                    "step": step,
                    "action": action_type,
                    "locator": action_dict.get("locator", {}),
                    "input_value": action_dict.get("input_value", ""),
                    "checkpoint": action_dict.get("checkpoint", ""),
                    "success": result["success"],
                    "error": result.get("error"),
                    "url_after": page.url,
                }
                action_trace.append(trace_entry)
                logger.log(redact_dict({"event": "action_result", **trace_entry}))

                if action_type == "done":
                    extracted_outputs = result.get("extracted", {}) or {}
                    logger.log({"event": "goal_achieved", "outputs": extracted_outputs})
                    break

                if action_type == "stuck" or not result["success"]:
                    logger.log({"event": "agent_stuck_or_failed", "step": step, "error": result.get("error")})
                    screenshots.capture_error(page, f"step_{step}_failure")
                    break

        finally:
            browser.close()

    # Build and save artifact from the recorded trace
    completed_trace = [t for t in action_trace if t["action"] not in {"done", "stuck"}]
    artifact = build_artifact(
        name=_goal_to_name(goal),
        description=goal,
        entry_url=target_url,
        action_trace=completed_trace,
        extracted_outputs=extracted_outputs,
        input_params=_infer_params(completed_trace),
    )

    saved_path = store.save(artifact, artifact_output_path)
    evidence.save_artifact(artifact.model_dump(mode="json"), filename="artifact.json")
    logger.log({"event": "artifact_saved", "path": saved_path})

    return artifact


def _goal_to_name(goal: str) -> str:
    """Convert a free-text goal into a snake_case artifact name."""
    words = goal.lower().split()[:5]
    return "_".join(w.strip(".,") for w in words if w.isalpha() or "_" in w)


def _infer_params(trace: list[dict[str, Any]]) -> dict[str, Any]:
    """Heuristically extract input params from the action trace.

    If the agent typed a 5-digit number into a Member ID field, treat that
    as the member_id parameter.
    """
    params: dict[str, Any] = {}
    for action in trace:
        if action.get("action") == "type":
            desc = action.get("locator", {}).get("description", "").lower()
            val = action.get("input_value", "")
            if "member" in desc and val:
                params["member_id"] = val
            elif "username" in desc or "user" in desc:
                pass  # credentials are never exposed as params
    return params
