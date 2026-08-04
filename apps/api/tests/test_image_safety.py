from io import BytesIO

import pytest
from PIL import Image

from agriverse.schemas import Citation, DiagnosisResult, PrimaryCondition
from agriverse.services.ai import RetrievedContext
from agriverse.workers import (
    InvalidImageError,
    apply_citation_safety,
    normalize_image,
)


def image_bytes() -> bytes:
    image = Image.new("RGB", (2200, 1200), color=(44, 110, 56))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def citation(tier: int) -> Citation:
    return Citation(
        chunk_id="f64c7a2f-5188-47e3-8ad4-63321bacbe61",
        publisher="CIB&RC" if tier == 1 else "ICAR",
        title="Registered label" if tier == 1 else "Practice guide",
        page=4,
        section="Treatment",
        licence="Government publication",
        source_url="https://example.gov.in/source",
        tier=tier,
    )


def diagnosis(citations: list[Citation]) -> DiagnosisResult:
    return DiagnosisResult(
        image_is_diagnosable=True,
        primary=PrimaryCondition(
            condition="Example condition",
            category="disease",
            confidence="moderate",
            visual_evidence="Example visible evidence",
        ),
        immediate_actions=["Apply 10 ml per litre of Product X"],
        citations=citations,
    )


def test_image_is_reencoded_and_downsampled() -> None:
    normalized = normalize_image(image_bytes())
    with Image.open(BytesIO(normalized)) as image:
        assert image.format == "JPEG"
        assert max(image.size) <= 1568
        assert image.mode == "RGB"


def test_invalid_image_is_rejected() -> None:
    with pytest.raises(InvalidImageError):
        normalize_image(b"not an image")


def test_unverified_dosage_is_removed_and_escalated() -> None:
    tier_two = citation(2)
    result = apply_citation_safety(
        diagnosis([tier_two]),
        RetrievedContext(similar_cases=[], citations=[tier_two]),
    )
    assert result.requires_expert
    assert all("10 ml" not in action for action in result.immediate_actions)
    assert result.citations == [tier_two]


def test_tier_one_dosage_and_known_citation_are_preserved() -> None:
    tier_one = citation(1)
    result = apply_citation_safety(
        diagnosis([tier_one]),
        RetrievedContext(similar_cases=[], citations=[tier_one]),
    )
    assert not result.requires_expert
    assert result.immediate_actions == ["Apply 10 ml per litre of Product X"]


def test_fabricated_citations_are_discarded() -> None:
    retrieved = citation(2)
    fabricated = citation(3).model_copy(update={"chunk_id": "03b9bca3-e5fd-47e9-b709-a24f817f93b7"})
    result = apply_citation_safety(
        diagnosis([fabricated]),
        RetrievedContext(similar_cases=[], citations=[retrieved]),
    )
    assert result.citations == []
