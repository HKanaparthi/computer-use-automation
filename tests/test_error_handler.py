"""Tests for the replay error taxonomy and classification."""

import pytest
from unittest.mock import MagicMock, patch

from src.artifact.schema import ErrorHandler, ReplayResult
from src.replay.error_handler import ErrorClassifier
from src.safety.classifier import classify_action, is_reversible
from src.safety.redactor import redact, redact_dict
from src.safety.allowlist import is_domain_allowed, is_url_blocked, is_action_allowed


class TestErrorClassifier:
    def _make_handler(self, detect: str, classification: str, action: str) -> ErrorHandler:
        return ErrorHandler(
            detect=detect,
            classification=classification,
            action=action,
            message="Test error",
        )

    def _mock_page(self, body_text: str) -> MagicMock:
        page = MagicMock()
        page.inner_text.return_value = body_text
        page.url = "http://localhost:5000/search"
        return page

    def test_detects_business_outcome(self):
        classifier = ErrorClassifier()
        page = self._mock_page("No member found with ID: 99999")
        handlers = {
            "member_not_found": self._make_handler("No member found", "business_outcome", "report")
        }
        result = classifier.detect_error(page, handlers, {})
        assert result is not None
        key, handler = result
        assert key == "member_not_found"
        assert handler.classification == "business_outcome"

    def test_detects_hard_failure(self):
        classifier = ErrorClassifier()
        page = self._mock_page("Access Denied — This member account is flagged as restricted.")
        handlers = {
            "permission_denied": self._make_handler("Access Denied", "hard_failure", "escalate")
        }
        result = classifier.detect_error(page, handlers, {})
        assert result is not None
        _, handler = result
        assert handler.classification == "hard_failure"

    def test_no_match_returns_none(self):
        classifier = ErrorClassifier()
        page = self._mock_page("Welcome back, admin.")
        handlers = {
            "member_not_found": self._make_handler("No member found", "business_outcome", "report")
        }
        result = classifier.detect_error(page, handlers, {})
        assert result is None

    def test_handle_business_outcome(self):
        classifier = ErrorClassifier()
        handler = self._make_handler("No member found", "business_outcome", "report")
        page = self._mock_page("No member found")
        result = classifier.handle("member_not_found", handler, step_number=3, evidence_path="/tmp", page=page)
        assert result.status == "business_outcome"
        assert result.business_outcome is not None
        assert result.business_outcome["code"] == "MEMBER_NOT_FOUND"

    def test_handle_hard_failure(self):
        classifier = ErrorClassifier()
        handler = self._make_handler("Access Denied", "hard_failure", "escalate")
        page = self._mock_page("Access Denied")
        result = classifier.handle("permission_denied", handler, step_number=2, evidence_path="/tmp", page=page)
        assert result.status == "hard_failure"
        assert result.error["code"] == "PERMISSION_DENIED"

    def test_handle_recoverable(self):
        classifier = ErrorClassifier()
        handler = self._make_handler("Sign In", "recoverable", "re_login")
        page = self._mock_page("Sign In")
        result = classifier.handle("session_timeout", handler, step_number=4, evidence_path="/tmp", page=page)
        assert result.status == "recoverable_failure"
        assert result.error["action"] == "re_login"


class TestActionClassifier:
    def test_read_is_read_only(self):
        assert classify_action("read") == "read_only"

    def test_navigate_is_read_only(self):
        assert classify_action("navigate") == "read_only"

    def test_type_is_read_only(self):
        assert classify_action("type", "Member ID field", "12345") == "read_only"

    def test_confirm_click_is_state_changing(self):
        result = classify_action("click", "Confirm opening sub-account", "")
        assert result == "state_changing"

    def test_delete_click_is_destructive(self):
        result = classify_action("click", "Delete member account", "")
        assert result == "destructive"

    def test_reversibility(self):
        assert is_reversible("read_only") is True
        assert is_reversible("state_changing") is False
        assert is_reversible("destructive") is False


class TestSafetyRedactor:
    def test_ssn_redacted(self):
        text = "Member SSN: 123-45-6789 on file"
        assert "[SSN-REDACTED]" in redact(text)
        assert "123-45-6789" not in redact(text)

    def test_card_number_redacted(self):
        text = "Card: 4111 1111 1111 1111"
        assert "[CARD-REDACTED]" in redact(text)

    def test_clean_text_unchanged(self):
        text = "Member Alice Johnson, balance $15,234.56"
        assert redact(text) == text

    def test_password_field_redacted(self):
        data = {"username": "admin", "password": "admin123", "member_id": "12345"}
        result = redact_dict(data)
        assert result["password"] == "[REDACTED]"
        assert result["username"] == "admin"
        assert result["member_id"] == "12345"

    def test_nested_dict_redacted(self):
        data = {"user": {"password": "secret", "name": "Alice"}}
        result = redact_dict(data)
        assert result["user"]["password"] == "[REDACTED]"
        assert result["user"]["name"] == "Alice"

    def test_empty_string_unchanged(self):
        assert redact("") == ""


class TestAllowlist:
    def test_localhost_allowed(self):
        assert is_domain_allowed("http://127.0.0.1:5001/login") is True

    def test_external_domain_blocked(self):
        assert is_domain_allowed("http://evil.com/login") is False

    def test_admin_url_blocked(self):
        assert is_url_blocked("http://127.0.0.1:5001/admin/users") is True

    def test_normal_url_not_blocked(self):
        assert is_url_blocked("http://127.0.0.1:5001/search") is False

    def test_allowed_actions(self):
        for action in ["click", "type", "read", "navigate", "wait"]:
            assert is_action_allowed(action) is True

    def test_disallowed_action(self):
        assert is_action_allowed("execute_script") is False
