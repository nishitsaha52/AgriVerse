import pytest
from pydantic import ValidationError

from agriverse.schemas import (
    DiagnosisResult,
    PrimaryCondition,
    ReviewDecision,
    SoilTestCreate,
)


def test_diagnosable_result_requires_primary_condition() -> None:
    with pytest.raises(ValidationError):
        DiagnosisResult(image_is_diagnosable=True)


def test_rejected_result_requires_reason() -> None:
    with pytest.raises(ValidationError):
        DiagnosisResult(image_is_diagnosable=False)


def test_valid_diagnosis_schema() -> None:
    result = DiagnosisResult(
        image_is_diagnosable=True,
        primary=PrimaryCondition(
            condition="Early blight",
            category="disease",
            confidence="moderate",
            visual_evidence="Concentric lesions are visible.",
        ),
        requires_expert=True,
    )
    assert result.primary is not None
    assert result.primary.condition == "Early blight"


def test_review_decision_requires_independent_label() -> None:
    with pytest.raises(ValidationError):
        ReviewDecision(decision="confirmed")
    assert ReviewDecision(decision="indeterminate").confirmed_diagnosis is None


def test_soil_values_reject_negative_or_impossible_ph() -> None:
    base = {
        "n": 1,
        "p": 1,
        "k": 1,
        "ph": 7,
        "ec": 1,
        "oc": 1,
        "s": 1,
        "zn": 1,
        "fe": 1,
        "cu": 1,
        "mn": 1,
        "b": 1,
    }
    with pytest.raises(ValidationError):
        SoilTestCreate(**{**base, "n": -1})
    with pytest.raises(ValidationError):
        SoilTestCreate(**{**base, "ph": 15})
