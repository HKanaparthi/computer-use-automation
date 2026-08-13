"""PII and sensitive data redaction from logs and artifacts.

We redact at the point of logging, not post-hoc, so that raw sensitive values
never touch disk in any form.  Passwords are simply never passed to the logger.
"""

import re

# Patterns for common PII that might appear in banking portal responses
_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_ACCOUNT_NUMBER_PATTERN = re.compile(r"\b\d{10,17}\b")
_FULL_CARD_PATTERN = re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b")


def redact(text: str) -> str:
    """Replace PII patterns in text with safe placeholders."""
    if not text:
        return text
    text = _SSN_PATTERN.sub("[SSN-REDACTED]", text)
    text = _FULL_CARD_PATTERN.sub("[CARD-REDACTED]", text)
    # Keep last 4 digits of account numbers
    text = _ACCOUNT_NUMBER_PATTERN.sub(lambda m: "[ACCT-XXXX" + m.group()[-4:] + "]", text)
    return text


def redact_dict(data: dict) -> dict:
    """Recursively redact PII from all string values in a dict."""
    result = {}
    for key, value in data.items():
        if key.lower() in {"password", "secret", "token", "api_key"}:
            result[key] = "[REDACTED]"
        elif isinstance(value, str):
            result[key] = redact(value)
        elif isinstance(value, dict):
            result[key] = redact_dict(value)
        elif isinstance(value, list):
            result[key] = [
                redact_dict(item) if isinstance(item, dict) else (redact(item) if isinstance(item, str) else item)
                for item in value
            ]
        else:
            result[key] = value
    return result
