from concurrent.futures import Executor, Future
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from patchbench.api import BenchmarkService, create_app
from patchbench.evaluator import summarize
from patchbench.loader import load_cases
from patchbench.schemas import BenchmarkRun, CaseScore


class ManualExecutor(Executor):
    def __init__(self) -> None:
        self.jobs: list[tuple[Any, tuple[Any, ...], dict[str, Any], Future[Any]]] = []

    def submit(self, fn, /, *args, **kwargs):
        future: Future[Any] = Future()
        self.jobs.append((fn, args, kwargs, future))
        return future

    def run_next(self) -> None:
        fn, args, kwargs, future = self.jobs.pop(0)
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001 - mirrors Executor behavior in the test double
            future.set_exception(exc)

    def shutdown(self, wait=True, *, cancel_futures=False) -> None:
        if cancel_futures:
            for _, _, _, future in self.jobs:
                future.cancel()


class FakeReviewer:
    model = "gpt-test"
    prompt_version = "review-v2"
    pricing = None
    timeout_seconds = 30.0
    max_retries = 0


def successful_run(
    benchmark_dir: Path,
    reviewer: FakeReviewer,
    *,
    max_concurrency: int,
    smoke_case: str | None,
) -> BenchmarkRun:
    del smoke_case
    cases = load_cases(benchmark_dir)
    scores = [
        CaseScore(
            case_id=case.case_id,
            detection_correct=True,
            category_correct=True if case.expected.bug_present else None,
            file_correct=True if case.expected.bug_present else None,
            line_correct=True if case.expected.bug_present else None,
            false_positive=False,
            points_earned=4 if case.expected.bug_present else 1,
            points_possible=4 if case.expected.bug_present else 1,
        )
        for case in cases
    ]
    return BenchmarkRun(
        max_concurrency=max_concurrency,
        timeout_seconds=reviewer.timeout_seconds,
        max_retries=reviewer.max_retries,
        case_order=[case.case_id for case in cases],
        requested_cases=len(cases),
        completed_cases=len(cases),
        failed_cases=0,
        skipped_cases=0,
        failures=[],
        skipped_case_ids=[],
        summary=summarize(
            scores,
            model=reviewer.model,
            prompt_version=reviewer.prompt_version,
            pricing=reviewer.pricing,
        ),
    )


def make_service(tmp_path: Path, executor: ManualExecutor, run_function=successful_run):
    root = Path(__file__).parents[1]
    current = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)

    def clock() -> datetime:
        nonlocal current
        value = current
        current += timedelta(seconds=1)
        return value

    return BenchmarkService(
        database_path=tmp_path / "history.sqlite3",
        benchmark_dir=root / "benchmark",
        source_commit="dff2515",
        executor=executor,
        reviewer_factory=lambda request: FakeReviewer(),
        run_function=run_function,
        clock=clock,
        id_factory=lambda: "run-api-1",
    )


def test_run_endpoints_queue_without_blocking_and_return_saved_results(tmp_path) -> None:
    executor = ManualExecutor()
    app = create_app(make_service(tmp_path, executor))

    with TestClient(app) as client:
        response = client.post(
            "/runs",
            json={"model": "gpt-test", "max_concurrency": 2, "max_retries": 0},
        )

        assert response.status_code == 202
        assert response.json()["metadata"]["status"] == "queued"
        assert len(executor.jobs) == 1
        assert client.get("/runs/run-api-1").json()["metadata"]["status"] == "queued"
        assert client.get("/runs/run-api-1/results").status_code == 409

        executor.run_next()

        status_response = client.get("/runs/run-api-1")
        assert status_response.status_code == 200
        assert status_response.json()["metadata"]["status"] == "completed"
        result_response = client.get("/runs/run-api-1/results")
        assert result_response.status_code == 200
        assert result_response.json()["benchmark_run"]["requested_cases"] == 24
        assert result_response.json()["benchmark_run"]["summary"]["total_accuracy"] == 1.0


def test_validation_and_missing_run_responses(tmp_path) -> None:
    executor = ManualExecutor()
    app = create_app(make_service(tmp_path, executor))

    with TestClient(app) as client:
        assert client.post("/runs", json={}).status_code == 422
        invalid_smoke = client.post(
            "/runs", json={"model": "gpt-test", "smoke_case": "not-a-case"}
        )
        assert invalid_smoke.status_code == 400
        assert invalid_smoke.json()["detail"] == "Unknown smoke case: not-a-case"
        assert client.get("/runs/missing").status_code == 404
        assert client.get("/runs/missing/results").status_code == 404
        assert executor.jobs == []


def test_worker_failure_is_visible_through_status(tmp_path) -> None:
    def fail_run(*args, **kwargs):
        raise RuntimeError("worker stopped")

    executor = ManualExecutor()
    app = create_app(make_service(tmp_path, executor, run_function=fail_run))

    with TestClient(app) as client:
        assert client.post("/runs", json={"model": "gpt-test"}).status_code == 202
        executor.run_next()

        response = client.get("/runs/run-api-1")
        assert response.status_code == 200
        assert response.json()["metadata"]["status"] == "failed"
        assert response.json()["error_type"] == "RuntimeError"
        assert response.json()["error_message"] == "worker stopped"
        assert client.get("/runs/run-api-1/results").status_code == 409
