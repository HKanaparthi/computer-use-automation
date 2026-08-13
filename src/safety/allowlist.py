"""Allowlist enforcement for domains, routes, and action types."""

import re
from urllib.parse import urlparse

SAFETY_CONFIG = {
    "allowed_domains": ["localhost:5001", "127.0.0.1:5001"],
    "allowed_actions": ["click", "type", "read", "navigate", "wait"],
    "blocked_url_patterns": ["/admin/*", "/delete/*"],
    "max_steps": 20,
    "max_retries": 3,
    "require_confirmation_for": ["state_changing", "destructive"],
}


def is_domain_allowed(url: str) -> bool:
    """Return True if the URL's host is in the allowed domains list."""
    parsed = urlparse(url)
    netloc = parsed.netloc
    return netloc in SAFETY_CONFIG["allowed_domains"]


def is_url_blocked(url: str) -> bool:
    """Return True if the URL matches a blocked pattern."""
    parsed = urlparse(url)
    path = parsed.path
    for pattern in SAFETY_CONFIG["blocked_url_patterns"]:
        regex = "^" + pattern.replace("*", ".*") + "$"
        if re.match(regex, path):
            return True
    return False


def is_action_allowed(action: str) -> bool:
    """Return True if the action type appears on the allow list."""
    return action in SAFETY_CONFIG["allowed_actions"]


def requires_confirmation(sensitivity_level: str) -> bool:
    """Return True if this sensitivity level requires human confirmation."""
    return sensitivity_level in SAFETY_CONFIG["require_confirmation_for"]
