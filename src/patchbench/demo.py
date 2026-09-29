"""Seed a read-only deployment with the versioned PatchBench baseline results."""

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from patchbench.history import (
    HistoryRepository,
    RunMetadata,
    RunMode,
    RunStatus,
    connect_history,
)
from patchbench.loader import load_cases
from patchbench.schemas import BenchmarkRun


@dataclass(frozen=True)
class DemoRun:
    run_id: str
    filename: str
    source_commit: str
    completed_at: datetime


DEMO_RUNS = (
    DemoRun(
        run_id="baseline-review-v1-2026-09-11",
        filename="gpt-5-mini-review-v1-baseline-2026-09-11.json",
        source_commit="81bd6ce",
        completed_at=datetime(2026, 9, 11, 15, 49, 50, tzinfo=UTC),
    ),
    DemoRun(
        run_id="baseline-review-v2-2026-09-22",
        filename="gpt-5-mini-review-v2-baseline-2026-09-22.json",
        source_commit="1110315",
        completed_at=datetime(2026, 9, 22, 12, 0, tzinfo=UTC),
    ),
)


def _load_benchmark_run(path: Path) -> BenchmarkRun:
    payload: dict[str, Any] = json.loads(path.read_text())
    if "case_order" not in payload:
        summary = payload["summary"]
        completed_ids = [case["case_id"] for case in summary["cases"]]
        failed_ids = [failure["case_id"] for failure in payload["failures"]]
        payload = {
            "max_concurrency": 1,
            "timeout_seconds": 60.0,
            "max_retries": 0,
            "case_order": completed_ids + failed_ids,
            "requested_cases": payload["requested_cases"],
            "completed_cases": payload["completed_cases"],
            "failed_cases": payload["failed_cases"],
            "skipped_cases": 0,
            "failures": payload["failures"],
            "skipped_case_ids": [],
            "summary": summary,
        }
    return BenchmarkRun.model_validate(payload)


def seed_demo_history(
    database_path: Path,
    benchmark_dir: Path,
    results_dir: Path,
) -> int:
    """Insert missing versioned baselines and return the number of new runs."""

    expected_by_case = {
        case.case_id: case.expected.bug_present for case in load_cases(benchmark_dir)
    }
    database_path.parent.mkdir(parents=True, exist_ok=True)
    inserted = 0

    with connect_history(database_path) as connection:
        repository = HistoryRepository(connection)
        for demo_run in DEMO_RUNS:
            if repository.get_record(demo_run.run_id) is not None:
                continue

            benchmark_run = _load_benchmark_run(results_dir / demo_run.filename)
            missing_cases = set(benchmark_run.case_order) - expected_by_case.keys()
            if missing_cases:
                raise ValueError(f"Baseline contains unknown cases: {sorted(missing_cases)}")
            summary = benchmark_run.summary
            if summary is None:
                raise ValueError(f"Demo baseline has no summary: {demo_run.filename}")

            metadata = RunMetadata(
                run_id=demo_run.run_id,
                status=RunStatus.COMPLETED,
                mode=RunMode.OPENAI,
                benchmark_name="default",
                benchmark_version="coverage-v1",
                source_commit=demo_run.source_commit,
                model=summary.model,
                prompt_version=summary.prompt_version,
                pricing=summary.pricing,
                configuration={
                    "demo_seed": True,
                    "result_file": demo_run.filename,
                    "source": "versioned-baseline",
                },
                created_at=demo_run.completed_at,
                started_at=demo_run.completed_at,
                completed_at=demo_run.completed_at,
            )
            repository.save_run(
                metadata,
                benchmark_run,
                {case_id: expected_by_case[case_id] for case_id in benchmark_run.case_order},
            )
            inserted += 1

    return inserted


def main() -> None:
    inserted = seed_demo_history(
        Path(os.environ.get("PATCHBENCH_DATABASE", "results/patchbench.db")),
        Path(os.environ.get("PATCHBENCH_BENCHMARK", "benchmark")),
        Path(os.environ.get("PATCHBENCH_RESULTS", "results")),
    )
    print(f"PatchBench demo history ready ({inserted} baseline run(s) added).")


if __name__ == "__main__":
    main()
