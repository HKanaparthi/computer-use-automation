"""Converts the raw agent action trace into a typed CapabilityArtifact."""

from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse

from src.artifact.schema import (
    ActionStep,
    CapabilityArtifact,
    Checkpoint,
    ElementLocator,
    ErrorHandler,
    LocatorStrategy,
    OutputSpec,
    ParamSpec,
)


def build_artifact(
    name: str,
    description: str,
    entry_url: str,
    action_trace: list[dict[str, Any]],
    extracted_outputs: dict[str, str],
    input_params: dict[str, Any],
) -> CapabilityArtifact:
    """Convert an agent action trace into a deterministic CapabilityArtifact.

    The recorder maps each raw agent action dict to a typed ActionStep.
    Input templates are inserted where the agent used a parameter value so
    that the replay engine can substitute different values at runtime.
    """
    domain = _extract_domain(entry_url)
    steps = []

    for i, action in enumerate(action_trace, start=1):
        locator_data = action.get("locator", {})
        primary = LocatorStrategy(
            strategy=locator_data.get("strategy", "accessibility_label"),
            value=locator_data.get("value", ""),
            description=locator_data.get("description", ""),
        )
        fallbacks = _build_fallbacks(locator_data)
        locator = ElementLocator(
            primary=primary,
            fallbacks=fallbacks,
            reasoning=locator_data.get("reasoning", "Primary accessibility label from discovery run"),
        )

        # Replace literal param values with template placeholders
        raw_input = action.get("input_value")
        input_template = _templatize(raw_input, input_params)

        checkpoint = Checkpoint(
            type="element_visible",
            expected=action.get("checkpoint", "page loaded"),
            description=action.get("checkpoint", "Step completed successfully"),
        )

        error_handlers = _default_error_handlers(action.get("action", ""))

        step = ActionStep(
            step_number=i,
            action=action.get("action", "click"),
            locator=locator,
            input_template=input_template,
            checkpoint=checkpoint,
            timeout_ms=action.get("timeout_ms", 5000),
            is_reversible=action.get("is_reversible", True),
            error_handlers=error_handlers,
        )
        steps.append(step)

    success_condition = Checkpoint(
        type="text_present",
        expected="savings_balance",
        description="Extracted data is present in the page state",
    )

    output_schema = {
        key: OutputSpec(type="string", description=f"Extracted {key}", extract_from=key)
        for key in extracted_outputs
    }

    param_specs = {
        key: ParamSpec(type="string", required=True, description=f"Input {key}", example=str(val))
        for key, val in input_params.items()
    }

    return CapabilityArtifact(
        name=name,
        description=description,
        created_at=datetime.utcnow(),
        discovered_from=entry_url,
        entry_url=entry_url,
        input_params=param_specs,
        output_schema=output_schema,
        steps=steps,
        success_condition=success_condition,
        allowed_domains=[domain],
        requires_confirmation=False,
        sensitivity_level="read_only",
        known_errors=_global_error_handlers(),
    )


def _extract_domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc or "localhost"


def _build_fallbacks(locator_data: dict[str, Any]) -> list[LocatorStrategy]:
    """Build fallback locator strategies from the agent's locator hints."""
    fallbacks = []
    raw_fallbacks = locator_data.get("fallbacks", [])
    for fb in raw_fallbacks:
        fallbacks.append(
            LocatorStrategy(
                strategy=fb.get("strategy", "text_content"),
                value=fb.get("value", ""),
                description=fb.get("description", "Fallback locator"),
            )
        )
    # Always add a text-content fallback if one is not present
    if not any(f.strategy == "text_content" for f in fallbacks):
        text_hint = locator_data.get("text_hint", "")
        if text_hint:
            fallbacks.append(
                LocatorStrategy(
                    strategy="text_content",
                    value=text_hint,
                    description="Text content fallback",
                )
            )
    return fallbacks


def _templatize(raw_input: Optional[str], params: dict[str, Any]) -> Optional[str]:
    """Replace literal param values with {{param_name}} placeholders."""
    if raw_input is None:
        return None
    result = raw_input
    for key, val in params.items():
        result = result.replace(str(val), f"{{{{{key}}}}}")
    return result


def _default_error_handlers(action: str) -> dict[str, ErrorHandler]:
    """Standard per-step error handlers that apply to most steps."""
    handlers: dict[str, ErrorHandler] = {
        "session_timeout": ErrorHandler(
            detect="Sign In",
            classification="recoverable",
            action="re_login",
            message="Session expired; re-authenticating and retrying from last checkpoint",
        ),
        "system_error": ErrorHandler(
            detect="Unexpected system error",
            classification="recoverable",
            action="retry",
            message="Transient system error; retrying the step",
        ),
    }
    if action == "type":
        handlers["element_missing"] = ErrorHandler(
            detect="",
            classification="hard_failure",
            action="escalate",
            message="Target input field not found; locator may be stale after UI update",
        )
    return handlers


def _global_error_handlers() -> dict[str, ErrorHandler]:
    return {
        "member_not_found": ErrorHandler(
            detect="No member found",
            classification="business_outcome",
            action="report",
            message="Member ID does not exist in the system",
        ),
        "permission_denied": ErrorHandler(
            detect="Access Denied",
            classification="hard_failure",
            action="escalate",
            message="Insufficient permissions to access this member record",
        ),
        "session_expired": ErrorHandler(
            detect="Sign In",
            classification="recoverable",
            action="re_login",
            message="Session cookie expired; re-login required",
        ),
    }
