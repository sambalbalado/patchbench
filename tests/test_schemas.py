import pytest
from pydantic import ValidationError

from patchbench.schemas import ExpectedFinding, FindingCategory, ReviewResult


def test_safe_case_rejects_bug_location_details() -> None:
    with pytest.raises(ValidationError, match="Safe cases cannot specify"):
        ExpectedFinding(
            bug_present=False,
            category="data_loss",
            file="module.py",
            line=1,
            explanation="Marked safe but still has finding details.",
        )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "bug_found": True,
            "category": None,
            "file": None,
            "line": None,
            "explanation": "Claims a bug without locating it.",
            "confidence": 0.7,
        },
        {
            "bug_found": False,
            "category": "data_loss",
            "file": "audit.py",
            "line": 4,
            "explanation": "Claims safety but includes a finding.",
            "confidence": 0.7,
        },
    ],
)
def test_review_result_rejects_inconsistent_finding_details(payload: dict) -> None:
    with pytest.raises(ValidationError):
        ReviewResult.model_validate(payload)


def test_review_result_rejects_unknown_category() -> None:
    with pytest.raises(ValidationError, match="Input should be"):
        ReviewResult(
            bug_found=True,
            category="arbitrary_model_wording",
            file="module.py",
            line=1,
            explanation="Uses a category outside the reviewed taxonomy.",
            confidence=0.8,
        )


def test_ground_truth_rejects_non_specific_other_category() -> None:
    with pytest.raises(ValidationError, match="specific category"):
        ExpectedFinding(
            bug_present=True,
            category="other",
            file="module.py",
            line=1,
            explanation="Ground truth must remain reproducible.",
        )


def test_review_schema_exposes_the_canonical_category_enum() -> None:
    category_schema = ReviewResult.model_json_schema()["$defs"]["FindingCategory"]

    assert category_schema["enum"] == [category.value for category in FindingCategory]
