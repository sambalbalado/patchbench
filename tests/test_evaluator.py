from pathlib import Path

from patchbench.evaluator import score_case, summarize
from patchbench.schemas import BenchmarkCase, ExpectedFinding, ReviewResult


def bug_case() -> BenchmarkCase:
    return BenchmarkCase(
        case_id="division_by_zero",
        patch_path=Path("patch.diff"),
        expected=ExpectedFinding(
            bug_present=True,
            category="division_by_zero",
            file="calculator.py",
            line=10,
            explanation="A denominator can be zero.",
        ),
    )


def test_scores_correct_bug_with_line_tolerance() -> None:
    review = ReviewResult(
        bug_found=True,
        category="division_by_zero",
        file="calculator.py",
        line=12,
        explanation="The guard is missing.",
        confidence=0.9,
    )
    score = score_case(bug_case(), review)
    assert score.accuracy == 1.0


def test_counts_false_positive_on_safe_change() -> None:
    case = BenchmarkCase(
        case_id="safe",
        patch_path=Path("patch.diff"),
        expected=ExpectedFinding(bug_present=False, explanation="Safe change."),
    )
    review = ReviewResult(
        bug_found=True,
        category="other",
        file="module.py",
        line=1,
        explanation="Possible bug.",
        confidence=0.4,
    )
    score = score_case(case, review)
    summary = summarize([score])
    assert summary.false_positive_rate == 1.0
    assert summary.detection_accuracy == 0.0


def test_missed_bug_cannot_receive_partial_credit_from_details() -> None:
    review = ReviewResult(
        bug_found=False,
        explanation="The change appears safe.",
        confidence=0.9,
    )

    score = score_case(bug_case(), review)

    assert score.points_earned == 0
    assert score.points_possible == 4
    assert score.detection_correct is False
    assert score.category_correct is False
    assert score.file_correct is False
    assert score.line_correct is False


def test_line_outside_tolerance_does_not_receive_location_credit() -> None:
    review = ReviewResult(
        bug_found=True,
        category="division_by_zero",
        file="calculator.py",
        line=13,
        explanation="The guard is missing.",
        confidence=0.9,
    )

    score = score_case(bug_case(), review)

    assert score.line_correct is False
    assert score.points_earned == 3


def test_summarizes_available_operational_metrics_without_inventing_missing_data() -> None:
    review = ReviewResult(
        bug_found=True,
        category="division_by_zero",
        file="calculator.py",
        line=10,
        explanation="The guard is missing.",
        confidence=0.9,
    )
    measured = score_case(
        bug_case(),
        review,
        latency_ms=10,
        input_tokens=100,
        cached_input_tokens=20,
        output_tokens=25,
        estimated_cost_usd=0.001,
    )
    unmeasured = score_case(bug_case(), review, latency_ms=20)

    summary = summarize([measured, unmeasured])

    assert summary.average_latency_ms == 15
    assert summary.total_input_tokens == 100
    assert summary.total_cached_input_tokens == 20
    assert summary.total_output_tokens == 25
    assert summary.total_estimated_cost_usd == 0.001
    assert summary.usage_available_cases == 1
    assert summary.cost_estimated_cases == 1
