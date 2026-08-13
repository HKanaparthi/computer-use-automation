"""Typed capability artifact schema.

The artifact is the central contract of this system: it is what transforms a
one-off LLM discovery run into a reusable, deterministic, parameterized
capability that an AI agent can invoke like a function.

Design decisions:
- Pydantic v2 for strict runtime validation and clean JSON serialisation.
- Multiple locator strategies per element (primary + fallbacks) so that the
  replay engine degrades gracefully when a single selector breaks.
- Per-step error handlers rather than a global catch because different steps
  have different failure modes (login can time out; a search can return "not
  found"; a confirmation can be denied).
- Sensitivity level on the artifact rather than individual steps so that the
  safety layer can gate the entire capability before execution begins.
"""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class LocatorStrategy(BaseModel):
    """A single strategy for finding an element on the page."""

    strategy: Literal["accessibility_label", "text_content", "role_and_name", "css_selector"]
    value: str
    description: str  # Human-readable: "The Member ID search input field"


class ElementLocator(BaseModel):
    """A robust element locator with an ordered fallback chain.

    The primary strategy is tried first.  If it fails (element not found within
    the step timeout), fallbacks are tried in order.  This mirrors how a
    skilled tester would escalate from the most-stable identifier to less-stable
    ones only when forced to.
    """

    primary: LocatorStrategy
    fallbacks: list[LocatorStrategy] = Field(default_factory=list)
    reasoning: str  # Why this locator is expected to remain stable


class Checkpoint(BaseModel):
    """A verifiable condition that must hold after a step succeeds."""

    type: Literal["element_visible", "element_contains", "url_matches", "text_present"]
    locator: Optional[ElementLocator] = None
    expected: str
    description: str


class ErrorHandler(BaseModel):
    """Per-step handler for a known error condition.

    Three-tier taxonomy:
    - business_outcome: A legitimate result (e.g., "member not found").
      The caller asked a question and got a valid answer — not a failure.
    - recoverable: Something we can fix automatically (session timeout,
      transient dialog, slow page load).
    - hard_failure: Stop, log, escalate. We cannot safely continue.
    """

    detect: str  # Text content or element attribute that signals this condition
    classification: Literal["business_outcome", "recoverable", "hard_failure"]
    action: Literal["report", "retry", "re_login", "escalate", "dismiss_dialog"]
    message: str  # Human-readable description for logs and escalation reports


class ActionStep(BaseModel):
    """One atomic step in a capability flow."""

    step_number: int
    action: Literal["click", "type", "navigate", "wait", "read"]
    locator: ElementLocator
    input_template: Optional[str] = None  # e.g. "{{member_id}}" for param substitution
    checkpoint: Checkpoint
    timeout_ms: int = 5000
    is_reversible: bool = True
    error_handlers: dict[str, ErrorHandler] = Field(default_factory=dict)


class ParamSpec(BaseModel):
    """Specification for a single capability input parameter."""

    type: Literal["string", "integer", "boolean"]
    required: bool = True
    description: str = ""
    example: Optional[str] = None


class OutputSpec(BaseModel):
    """Specification for a single capability output value."""

    type: Literal["string", "integer", "boolean"]
    description: str = ""
    extract_from: Optional[str] = None  # aria-label or step reference


class CapabilityArtifact(BaseModel):
    """The complete, serialisable description of a reusable UI capability.

    An agent can treat this like a function signature:
        lookup_member_balance(member_id="12345") → {"savings_balance": "$15,234.56"}

    The artifact is self-contained: it includes everything needed to replay the
    flow in a fresh browser session without consulting the LLM again.
    """

    # ---- Metadata ----
    name: str
    version: str = "1.0.0"
    description: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    discovered_from: str  # URL of the target app when discovered

    # ---- Contract ----
    input_params: dict[str, ParamSpec] = Field(default_factory=dict)
    output_schema: dict[str, OutputSpec] = Field(default_factory=dict)

    # ---- Flow ----
    entry_url: str
    steps: list[ActionStep]
    success_condition: Checkpoint

    # ---- Error taxonomy ----
    known_errors: dict[str, ErrorHandler] = Field(default_factory=dict)

    # ---- Safety ----
    allowed_domains: list[str] = Field(default_factory=list)
    requires_confirmation: bool = False
    sensitivity_level: Literal["read_only", "state_changing", "destructive"] = "read_only"

    # ---- Drift detection ----
    target_app_fingerprint: Optional[str] = None


class ReplayResult(BaseModel):
    """The structured result returned after a replay execution."""

    status: Literal["success", "business_outcome", "recoverable_failure", "hard_failure", "escalated"]
    outputs: Optional[dict[str, str]] = None
    business_outcome: Optional[dict[str, Any]] = None
    error: Optional[dict[str, Any]] = None
    steps_completed: int = 0
    steps_total: int = 0
    evidence_path: str = ""
    duration_ms: int = 0
