"""Tests for the CapabilityArtifact schema validation."""

import pytest
from pydantic import ValidationError

from src.artifact.schema import (
    ActionStep,
    CapabilityArtifact,
    Checkpoint,
    ElementLocator,
    ErrorHandler,
    LocatorStrategy,
    OutputSpec,
    ParamSpec,
    ReplayResult,
)


def _make_locator() -> ElementLocator:
    return ElementLocator(
        primary=LocatorStrategy(
            strategy="accessibility_label",
            value="Member ID search field",
            description="The member ID input on the search page",
        ),
        fallbacks=[
            LocatorStrategy(
                strategy="text_content",
                value="Member ID",
                description="Text content fallback",
            )
        ],
        reasoning="aria-label is the most stable attribute across layout changes",
    )


def _make_checkpoint() -> Checkpoint:
    return Checkpoint(
        type="element_visible",
        expected="member-detail",
        description="Member detail page header is visible",
    )


def _make_step(step_number: int = 1) -> ActionStep:
    return ActionStep(
        step_number=step_number,
        action="click",
        locator=_make_locator(),
        checkpoint=_make_checkpoint(),
        timeout_ms=5000,
        is_reversible=True,
    )


class TestLocatorStrategy:
    def test_valid_strategies(self):
        for strategy in ["accessibility_label", "text_content", "role_and_name", "css_selector"]:
            ls = LocatorStrategy(strategy=strategy, value="val", description="desc")
            assert ls.strategy == strategy

    def test_invalid_strategy_rejected(self):
        with pytest.raises(ValidationError):
            LocatorStrategy(strategy="xpath", value="//input", description="bad")


class TestElementLocator:
    def test_primary_required(self):
        with pytest.raises(ValidationError):
            ElementLocator(fallbacks=[], reasoning="test")

    def test_fallbacks_default_empty(self):
        locator = ElementLocator(
            primary=LocatorStrategy(strategy="accessibility_label", value="x", description="y"),
            reasoning="test",
        )
        assert locator.fallbacks == []


class TestCheckpoint:
    def test_valid_types(self):
        for ctype in ["element_visible", "element_contains", "url_matches", "text_present"]:
            cp = Checkpoint(type=ctype, expected="something", description="test")
            assert cp.type == ctype

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            Checkpoint(type="css_match", expected="x", description="test")


class TestActionStep:
    def test_minimal_step(self):
        step = _make_step()
        assert step.step_number == 1
        assert step.is_reversible is True
        assert step.timeout_ms == 5000

    def test_error_handlers_default_empty(self):
        step = _make_step()
        assert step.error_handlers == {}

    def test_action_types(self):
        for action in ["click", "type", "navigate", "wait", "read"]:
            step = ActionStep(
                step_number=1,
                action=action,
                locator=_make_locator(),
                checkpoint=_make_checkpoint(),
            )
            assert step.action == action

    def test_invalid_action_rejected(self):
        with pytest.raises(ValidationError):
            ActionStep(
                step_number=1,
                action="scroll",
                locator=_make_locator(),
                checkpoint=_make_checkpoint(),
            )


class TestCapabilityArtifact:
    def _make_artifact(self) -> CapabilityArtifact:
        return CapabilityArtifact(
            name="lookup_member_balance",
            description="Look up the savings balance for a given member ID",
            discovered_from="http://localhost:5000/login",
            entry_url="http://localhost:5000/login",
            steps=[_make_step(1), _make_step(2)],
            success_condition=_make_checkpoint(),
            input_params={"member_id": ParamSpec(type="string", required=True, description="5-digit member ID")},
            output_schema={"savings_balance": OutputSpec(type="string", description="Member savings balance")},
            allowed_domains=["localhost:5000"],
            sensitivity_level="read_only",
        )

    def test_artifact_roundtrip(self):
        """Artifact should serialise and deserialise with identical data."""
        artifact = self._make_artifact()
        data = artifact.model_dump(mode="json")
        restored = CapabilityArtifact.model_validate(data)
        assert restored.name == artifact.name
        assert len(restored.steps) == len(artifact.steps)

    def test_sensitivity_levels(self):
        for level in ["read_only", "state_changing", "destructive"]:
            artifact = self._make_artifact()
            artifact.sensitivity_level = level
            assert artifact.sensitivity_level == level

    def test_invalid_sensitivity_rejected(self):
        artifact = self._make_artifact()
        with pytest.raises(ValidationError):
            CapabilityArtifact(
                **{**artifact.model_dump(), "sensitivity_level": "extremely_destructive"}
            )

    def test_step_ordering_preserved(self):
        artifact = self._make_artifact()
        assert artifact.steps[0].step_number == 1
        assert artifact.steps[1].step_number == 2


class TestReplayResult:
    def test_success_result(self):
        result = ReplayResult(
            status="success",
            outputs={"savings_balance": "$15,234.56"},
            steps_completed=5,
            steps_total=5,
            evidence_path="evidence/replay_run_1",
            duration_ms=3400,
        )
        assert result.status == "success"
        assert result.outputs["savings_balance"] == "$15,234.56"

    def test_business_outcome_result(self):
        result = ReplayResult(
            status="business_outcome",
            business_outcome={"code": "MEMBER_NOT_FOUND", "message": "No member with ID 99999"},
            steps_completed=3,
            steps_total=5,
        )
        assert result.status == "business_outcome"
        assert result.business_outcome["code"] == "MEMBER_NOT_FOUND"
        assert result.outputs is None

    def test_hard_failure_result(self):
        result = ReplayResult(
            status="hard_failure",
            error={"code": "PERMISSION_DENIED", "message": "Restricted account"},
            steps_completed=2,
        )
        assert result.status == "hard_failure"
        assert result.error["code"] == "PERMISSION_DENIED"

    def test_all_status_values_valid(self):
        for status in ["success", "business_outcome", "recoverable_failure", "hard_failure", "escalated"]:
            r = ReplayResult(status=status)
            assert r.status == status

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            ReplayResult(status="partial_success")
