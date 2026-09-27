import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from patchbench.evaluator import summarize
from patchbench.history import (
    HistoryRepository,
    RunMetadata,
    RunMode,
    RunStatus,
    connect_history,
)
from patchbench.loader import load_cases
from patchbench.schemas import BenchmarkRun, CaseFailure, CaseScore, TokenPricing

PRICING = TokenPricing(
    input_usd_per_million=0.25,
    cached_input_usd_per_million=0.025,
    output_usd_per_million=2.0,
    source="https://example.com/pricing",
    as_of="2026-09-27",
)


def make_repository() -> tuple[sqlite3.Connection, HistoryRepository]:
    connection = connect_history(":memory:")
    return connection, HistoryRepository(connection)


def make_metadata(run_id: str = "run-1") -> RunMetadata:
    return RunMetadata(
        run_id=run_id,
        status=RunStatus.COMPLETED,
        mode=RunMode.OPENAI,
        benchmark_name="default",
        benchmark_version="coverage-v1",
        source_commit="060ce20",
        model="gpt-5-mini",
        prompt_version="review-v2",
        pricing=PRICING,
        configuration={"smoke_case": "division_by_zero"},
        created_at=datetime(2026, 9, 27, 10, 0, tzinfo=UTC),
        started_at=datetime(2026, 9, 27, 10, 1, tzinfo=UTC),
        completed_at=datetime(2026, 9, 27, 10, 2, tzinfo=UTC),
    )


def make_score(case_id: str, *, bug_present: bool) -> CaseScore:
    return CaseScore(
        case_id=case_id,
        detection_correct=True,
        category_correct=True if bug_present else None,
        file_correct=True if bug_present else None,
        line_correct=True if bug_present else None,
        false_positive=False,
        points_earned=4 if bug_present else 1,
        points_possible=4 if bug_present else 1,
        latency_ms=10.0,
        input_tokens=100,
        cached_input_tokens=20,
        output_tokens=25,
        estimated_cost_usd=0.001,
    )


def make_run(
    scores: list[CaseScore],
    *,
    failures: list[CaseFailure] | None = None,
    skipped_case_ids: list[str] | None = None,
) -> BenchmarkRun:
    failures = failures or []
    skipped_case_ids = skipped_case_ids or []
    summary = summarize(
        scores,
        model="gpt-5-mini",
        prompt_version="review-v2",
        pricing=PRICING,
    )
    case_order = [score.case_id for score in scores]
    case_order.extend(failure.case_id for failure in failures)
    case_order.extend(skipped_case_ids)
    return BenchmarkRun(
        max_concurrency=4,
        timeout_seconds=60,
        max_retries=1,
        case_order=case_order,
        requested_cases=len(case_order),
        completed_cases=len(scores),
        failed_cases=len(failures),
        skipped_cases=len(skipped_case_ids),
        failures=failures,
        skipped_case_ids=skipped_case_ids,
        summary=summary,
    )


def test_successful_run_round_trips_with_derived_summary() -> None:
    connection, repository = make_repository()
    metadata = make_metadata()
    benchmark_run = make_run(
        [make_score("buggy", bug_present=True), make_score("safe", bug_present=False)]
    )

    repository.save_run(metadata, benchmark_run, {"buggy": True, "safe": False})

    stored = repository.get_run(metadata.run_id)
    assert stored is not None
    assert stored.metadata == metadata
    assert stored.benchmark_run == benchmark_run
    assert repository.get_summary(metadata.run_id) == benchmark_run.summary
    connection.close()


def test_versioned_review_v2_baseline_round_trips() -> None:
    root = Path(__file__).parents[1]
    benchmark_run = BenchmarkRun.model_validate_json(
        (root / "results" / "gpt-5-mini-review-v2-baseline-2026-09-22.json").read_text()
    )
    assert benchmark_run.summary is not None
    connection, repository = make_repository()
    metadata = RunMetadata(
        run_id="review-v2-baseline",
        status=RunStatus.COMPLETED,
        mode=RunMode.OPENAI,
        benchmark_name="default",
        benchmark_version="coverage-v1",
        source_commit="1110315",
        model=benchmark_run.summary.model,
        prompt_version=benchmark_run.summary.prompt_version,
        pricing=benchmark_run.summary.pricing,
        configuration={"source": "versioned-baseline"},
        created_at=datetime(2026, 9, 22, 10, 0, tzinfo=UTC),
        started_at=datetime(2026, 9, 22, 10, 1, tzinfo=UTC),
        completed_at=datetime(2026, 9, 22, 10, 4, tzinfo=UTC),
    )
    expected = {case.case_id: case.expected.bug_present for case in load_cases(root / "benchmark")}

    repository.save_run(metadata, benchmark_run, expected)

    stored = repository.get_run(metadata.run_id)
    assert stored is not None
    assert stored.metadata == metadata
    assert stored.benchmark_run == benchmark_run
    connection.close()


def test_partial_run_preserves_completed_failed_and_skipped_order() -> None:
    connection, repository = make_repository()
    metadata = make_metadata("partial-run")
    benchmark_run = make_run(
        [make_score("completed", bug_present=False)],
        failures=[
            CaseFailure(
                case_id="failed",
                error_type="ModelAPIError",
                message="Unavailable",
                latency_ms=25.0,
            )
        ],
        skipped_case_ids=["skipped"],
    )

    repository.save_run(
        metadata,
        benchmark_run,
        {"completed": False, "failed": True, "skipped": False},
    )

    stored = repository.get_run(metadata.run_id)
    assert stored is not None
    assert stored.benchmark_run == benchmark_run
    assert connection.execute(
        "SELECT case_id, outcome FROM case_results ORDER BY position"
    ).fetchall() == [
        ("completed", "completed"),
        ("failed", "failed"),
        ("skipped", "skipped"),
    ]
    connection.close()


def test_invalid_case_data_rolls_back_the_entire_run() -> None:
    connection, repository = make_repository()
    metadata = make_metadata("invalid-run")
    benchmark_run = make_run([make_score("safe", bug_present=False)])

    with pytest.raises(sqlite3.IntegrityError):
        repository.save_run(metadata, benchmark_run, {"safe": True})

    assert repository.get_run(metadata.run_id) is None
    assert connection.execute("SELECT COUNT(*) FROM case_results").fetchone() == (0,)
    connection.close()


def test_all_failed_run_round_trips_without_a_summary() -> None:
    connection, repository = make_repository()
    metadata = make_metadata("failed-run").model_copy(update={"status": RunStatus.FAILED})
    benchmark_run = BenchmarkRun(
        max_concurrency=4,
        timeout_seconds=60,
        max_retries=0,
        case_order=["failed", "skipped"],
        requested_cases=2,
        completed_cases=0,
        failed_cases=1,
        skipped_cases=1,
        failures=[
            CaseFailure(
                case_id="failed",
                error_type="ModelAPIError",
                message="Unavailable",
                latency_ms=25.0,
            )
        ],
        skipped_case_ids=["skipped"],
        summary=None,
    )

    repository.save_run(metadata, benchmark_run, {"failed": True, "skipped": False})

    stored = repository.get_run(metadata.run_id)
    assert stored is not None
    assert stored.metadata == metadata
    assert stored.benchmark_run == benchmark_run
    assert repository.get_summary(metadata.run_id) is None
    connection.close()


def test_missing_run_returns_none() -> None:
    connection, repository = make_repository()

    assert repository.get_run("missing") is None
    assert repository.get_summary("missing") is None
    connection.close()
