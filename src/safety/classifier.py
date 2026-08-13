"""Action risk classification: safe/reversible vs risky/irreversible."""

from typing import Literal

# Actions that only read state — no mutations
READ_ONLY_ACTIONS = {"read", "navigate", "wait"}

# Actions that type into forms are safe unless they target a submit button
# Clicks on confirmations or destructive paths are state-changing
STATE_CHANGING_KEYWORDS = {
    "confirm",
    "submit",
    "open sub-account",
    "open subaccount",
    "delete",
    "remove",
    "transfer",
    "apply",
}


def classify_action(
    action: str,
    locator_description: str = "",
    input_value: str = "",
) -> Literal["read_only", "state_changing", "destructive"]:
    """Classify an action by its potential impact on system state.

    Returns:
        "read_only"     – safe to execute without confirmation
        "state_changing" – modifies state, should be logged prominently
        "destructive"   – irreversible, requires explicit confirmation
    """
    if action in READ_ONLY_ACTIONS:
        return "read_only"

    combined = (locator_description + " " + input_value).lower()

    destructive_signals = {"delete", "remove", "close account", "write off"}
    if any(kw in combined for kw in destructive_signals):
        return "destructive"

    if action == "click" and any(kw in combined for kw in STATE_CHANGING_KEYWORDS):
        return "state_changing"

    if action == "type":
        return "read_only"  # Typing alone doesn't mutate; submission does

    return "read_only"


def is_reversible(classification: str) -> bool:
    """Return True if actions of this classification can be undone."""
    return classification == "read_only"
