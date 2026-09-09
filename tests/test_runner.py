from pathlib import Path

from patchbench.openai_reviewer import TimedReview
from patchbench.runner import run, run_openai
from patchbench.schemas import ReviewResult, TokenPricing


def test_example_benchmark_scores_perfectly() -> None:
    root = Path(__file__).parents[1]
    summary = run(root / "benchmark", root / "examples" / "predictions.json")
    assert summary.detection_accuracy == 1.0
    assert summary.false_positive_rate == 0.0
    assert summary.total_accuracy == 1.0
    assert summary.average_latency_ms is None
    assert summary.total_input_tokens is None
    assert summary.total_estimated_cost_usd is None
    assert summary.usage_available_cases == 0
    assert summary.cost_estimated_cases == 0


class FakeReviewer:
    model = "gpt-5-mini"
    prompt_version = "review-v1"
    pricing = TokenPricing(
        input_usd_per_million=0.25,
        cached_input_usd_per_million=0.025,
        output_usd_per_million=2.0,
        source="https://example.com/pricing",
        as_of="2026-09-10",
    )

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
            input_tokens=100,
            cached_input_tokens=20,
            output_tokens=25,
            estimated_cost_usd=0.0000705,
        )


def test_live_mode_reviews_patches_and_records_latency(tmp_path: Path) -> None:
    case_dir = tmp_path / "division_by_zero"
    case_dir.mkdir()
    (case_dir / "patch.diff").write_text(
        """diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -6 +6 @@
-return 0
+return completed / total
"""
    )
    (case_dir / "expected.json").write_text(
        '{"bug_present": true, "category": "division_by_zero", '
        '"file": "calculator.py", "line": 6, "explanation": "Missing zero guard."}'
    )

    summary = run_openai(tmp_path, FakeReviewer())

    assert summary.total_accuracy == 1.0
    assert [score.latency_ms for score in summary.cases] == [12.5]
    assert summary.model == "gpt-5-mini"
    assert summary.prompt_version == "review-v1"
    assert summary.average_latency_ms == 12.5
    assert summary.total_input_tokens == 100
    assert summary.total_cached_input_tokens == 20
    assert summary.total_output_tokens == 25
    assert summary.total_estimated_cost_usd == 0.0000705
    assert summary.usage_available_cases == 1
    assert summary.cost_estimated_cases == 1
