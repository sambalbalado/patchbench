from pathlib import Path
from threading import Barrier, Lock
from time import sleep

import pytest

from patchbench.openai_reviewer import ModelAPIError, TimedReview
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
    timeout_seconds = 60.0
    max_retries = 1
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

    result = run_openai(tmp_path, FakeReviewer())
    summary = result.summary

    assert summary is not None
    assert result.case_order == ["division_by_zero"]
    assert result.max_concurrency == 4
    assert result.timeout_seconds == 60.0
    assert result.max_retries == 1
    assert (result.requested_cases, result.completed_cases) == (1, 1)
    assert (result.failed_cases, result.skipped_cases) == (0, 0)
    assert result.failures == []
    assert result.skipped_case_ids == []
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


def write_safe_case(root: Path, case_id: str, marker: str) -> None:
    case_dir = root / case_id
    case_dir.mkdir()
    (case_dir / "patch.diff").write_text(
        f"""diff --git a/settings.py b/settings.py
--- a/settings.py
+++ b/settings.py
@@ -0,0 +1 @@
+{marker} = True
"""
    )
    (case_dir / "expected.json").write_text(
        '{"bug_present": false, "category": null, "file": null, "line": null, '
        '"explanation": "Safe test case."}'
    )


class ConcurrentFakeReviewer(FakeReviewer):
    def __init__(self) -> None:
        self._lock = Lock()
        self._first_workers_ready = Barrier(2)
        self._calls = 0
        self._active = 0
        self.max_active = 0

    def review_patch(self, patch: str) -> TimedReview:
        with self._lock:
            self._calls += 1
            call_number = self._calls
            self._active += 1
            self.max_active = max(self.max_active, self._active)

        try:
            if call_number <= 2:
                self._first_workers_ready.wait(timeout=1)
            if "SLOW" in patch:
                sleep(0.02)
            if "FAIL" in patch:
                raise ModelAPIError("Synthetic API failure", latency_ms=7.5)
            return super().review_patch(patch)
        finally:
            with self._lock:
                self._active -= 1


def test_live_mode_bounds_concurrency_isolates_failures_and_preserves_order(
    tmp_path: Path,
) -> None:
    write_safe_case(tmp_path, "a_slow", "SLOW")
    write_safe_case(tmp_path, "b_failure", "FAIL")
    write_safe_case(tmp_path, "c_fast", "FAST")
    reviewer = ConcurrentFakeReviewer()

    result = run_openai(tmp_path, reviewer, max_concurrency=2)

    assert reviewer.max_active == 2
    assert result.case_order == ["a_slow", "b_failure", "c_fast"]
    assert (result.requested_cases, result.completed_cases) == (3, 2)
    assert (result.failed_cases, result.skipped_cases) == (1, 0)
    assert result.summary is not None
    assert [score.case_id for score in result.summary.cases] == ["a_slow", "c_fast"]
    assert [failure.case_id for failure in result.failures] == ["b_failure"]
    assert result.failures[0].error_type == "ModelAPIError"
    assert result.failures[0].message == "Synthetic API failure"
    assert result.failures[0].latency_ms == 7.5
    assert result.skipped_case_ids == []


def test_live_mode_reports_an_all_failed_run_without_summarizing(tmp_path: Path) -> None:
    write_safe_case(tmp_path, "failed_case", "FAIL")

    class FailedReviewer(FakeReviewer):
        def review_patch(self, patch: str) -> TimedReview:
            raise RuntimeError("Synthetic unexpected failure")

    result = run_openai(tmp_path, FailedReviewer(), max_concurrency=1)

    assert (result.requested_cases, result.completed_cases) == (1, 0)
    assert (result.failed_cases, result.skipped_cases) == (1, 0)
    assert result.summary is None
    assert result.failures[0].case_id == "failed_case"
    assert result.failures[0].error_type == "RuntimeError"
    assert result.failures[0].message == "Synthetic unexpected failure"


def test_live_mode_reuses_successful_smoke_case(tmp_path: Path) -> None:
    write_safe_case(tmp_path, "a_regular", "REGULAR_A")
    write_safe_case(tmp_path, "b_smoke", "SMOKE")
    write_safe_case(tmp_path, "c_regular", "REGULAR_C")

    class TrackingReviewer(FakeReviewer):
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.lock = Lock()

        def review_patch(self, patch: str) -> TimedReview:
            with self.lock:
                self.calls.append(patch)
            return super().review_patch(patch)

    reviewer = TrackingReviewer()
    result = run_openai(tmp_path, reviewer, max_concurrency=2, smoke_case="b_smoke")

    assert "SMOKE" in reviewer.calls[0]
    assert len(reviewer.calls) == 3
    assert sum("SMOKE" in patch for patch in reviewer.calls) == 1
    assert (result.completed_cases, result.failed_cases, result.skipped_cases) == (3, 0, 0)
    assert result.summary is not None
    assert [score.case_id for score in result.summary.cases] == [
        "a_regular",
        "b_smoke",
        "c_regular",
    ]


def test_live_mode_stops_after_failed_smoke_case(tmp_path: Path) -> None:
    write_safe_case(tmp_path, "a_regular", "REGULAR")
    write_safe_case(tmp_path, "b_smoke", "SMOKE")

    class FailedSmokeReviewer(FakeReviewer):
        def __init__(self) -> None:
            self.calls = 0

        def review_patch(self, patch: str) -> TimedReview:
            self.calls += 1
            raise ModelAPIError("Synthetic smoke failure", latency_ms=8.0)

    reviewer = FailedSmokeReviewer()
    result = run_openai(tmp_path, reviewer, smoke_case="b_smoke")

    assert reviewer.calls == 1
    assert (result.completed_cases, result.failed_cases, result.skipped_cases) == (0, 1, 1)
    assert result.summary is None
    assert [failure.case_id for failure in result.failures] == ["b_smoke"]
    assert result.skipped_case_ids == ["a_regular"]


@pytest.mark.parametrize("max_concurrency", [0, 9])
def test_live_mode_rejects_unsafe_concurrency(max_concurrency: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 8"):
        run_openai(Path("unused"), FakeReviewer(), max_concurrency=max_concurrency)
