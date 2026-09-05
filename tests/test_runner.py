from pathlib import Path

from patchbench.openai_reviewer import TimedReview
from patchbench.runner import run, run_openai
from patchbench.schemas import ReviewResult


def test_example_benchmark_scores_perfectly() -> None:
    root = Path(__file__).parents[1]
    summary = run(root / "benchmark", root / "examples" / "predictions.json")
    assert summary.detection_accuracy == 1.0
    assert summary.false_positive_rate == 0.0
    assert summary.total_accuracy == 1.0


class FakeReviewer:
    def review_patch(self, patch: str) -> TimedReview:
        bug_found = "completed / total" in patch
        return TimedReview(
            review=ReviewResult(
                bug_found=bug_found,
                category="division_by_zero" if bug_found else None,
                file="calculator.py" if bug_found else None,
                line=6 if bug_found else None,
                explanation="Mocked review.",
                confidence=0.9,
            ),
            latency_ms=12.5,
        )


def test_live_mode_reviews_patches_and_records_latency(tmp_path: Path) -> None:
    case_dir = tmp_path / "division_by_zero"
    case_dir.mkdir()
    (case_dir / "patch.diff").write_text(
        "diff --git a/calculator.py b/calculator.py\n+return completed / total\n"
    )
    (case_dir / "expected.json").write_text(
        '{"bug_present": true, "category": "division_by_zero", '
        '"file": "calculator.py", "line": 6, "explanation": "Missing zero guard."}'
    )

    summary = run_openai(tmp_path, FakeReviewer())

    assert summary.total_accuracy == 1.0
    assert [score.latency_ms for score in summary.cases] == [12.5]
