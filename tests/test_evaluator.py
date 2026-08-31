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
    review = ReviewResult(bug_found=True, explanation="Possible bug.", confidence=0.4)
    score = score_case(case, review)
    summary = summarize([score])
    assert summary.false_positive_rate == 1.0
    assert summary.detection_accuracy == 0.0

