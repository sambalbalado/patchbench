import os
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import Executor, ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from patchbench.history import (
    HistoryRepository,
    RunMetadata,
    RunMode,
    RunRecord,
    RunStatus,
    StoredRun,
    connect_history,
)
from patchbench.loader import load_cases
from patchbench.openai_reviewer import (
    DEFAULT_MAX_RETRIES,
    MAX_RETRIES,
    OpenAIReviewer,
)
from patchbench.runner import DEFAULT_MAX_CONCURRENCY, MAX_CONCURRENCY, run_openai
from patchbench.schemas import BenchmarkCase, BenchmarkRun

DEFAULT_TIMEOUT_SECONDS = 60.0


class StartRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    max_concurrency: Annotated[int, Field(ge=1, le=MAX_CONCURRENCY)] = DEFAULT_MAX_CONCURRENCY
    timeout_seconds: Annotated[float, Field(gt=0)] = DEFAULT_TIMEOUT_SECONDS
    max_retries: Annotated[int, Field(ge=0, le=MAX_RETRIES)] = DEFAULT_MAX_RETRIES
    smoke_case: str | None = None


ReviewerFactory = Callable[[StartRunRequest], OpenAIReviewer]
RunFunction = Callable[..., BenchmarkRun]


class BenchmarkService:
    """Coordinate background runs while keeping HTTP handlers free of persistence details."""

    def __init__(
        self,
        *,
        database_path: Path,
        benchmark_dir: Path,
        source_commit: str | None = None,
        benchmark_name: str = "default",
        benchmark_version: str = "coverage-v1",
        executor: Executor | None = None,
        reviewer_factory: ReviewerFactory | None = None,
        run_function: RunFunction = run_openai,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._database_path = database_path
        self._benchmark_dir = benchmark_dir
        self._source_commit = source_commit
        self._benchmark_name = benchmark_name
        self._benchmark_version = benchmark_version
        self._executor = executor or ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="patchbench-run"
        )
        self._reviewer_factory = reviewer_factory or self._make_reviewer
        self._run_function = run_function
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: uuid4().hex)

    def start_run(self, request: StartRunRequest) -> RunRecord:
        reviewer = self._reviewer_factory(request)
        cases = load_cases(self._benchmark_dir)
        expected_bug_present = self._expected_cases(cases, request.smoke_case)
        run_id = self._id_factory()
        metadata = RunMetadata(
            run_id=run_id,
            status=RunStatus.QUEUED,
            mode=RunMode.OPENAI,
            benchmark_name=self._benchmark_name,
            benchmark_version=self._benchmark_version,
            source_commit=self._source_commit,
            model=reviewer.model,
            prompt_version=reviewer.prompt_version,
            pricing=reviewer.pricing,
            configuration={"smoke_case": request.smoke_case},
            created_at=self._clock(),
        )
        with self._repository() as repository:
            repository.create_run(
                metadata,
                max_concurrency=request.max_concurrency,
                timeout_seconds=request.timeout_seconds,
                max_retries=request.max_retries,
            )

        try:
            self._executor.submit(
                self._execute_run,
                run_id,
                reviewer,
                request,
                expected_bug_present,
            )
        except Exception as exc:
            self._record_failure(run_id, exc)
            raise

        record = self.get_run_record(run_id)
        if record is None:  # pragma: no cover - the preceding insert guarantees this
            raise RuntimeError(f"Queued run disappeared from history: {run_id}")
        return record

    def get_run_record(self, run_id: str) -> RunRecord | None:
        with self._repository() as repository:
            return repository.get_record(run_id)

    def get_results(self, run_id: str) -> StoredRun | None:
        with self._repository() as repository:
            return repository.get_run(run_id)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)

    def _execute_run(
        self,
        run_id: str,
        reviewer: OpenAIReviewer,
        request: StartRunRequest,
        expected_bug_present: Mapping[str, bool],
    ) -> None:
        try:
            with self._repository() as repository:
                repository.mark_running(run_id, self._clock())
            benchmark_run = self._run_function(
                self._benchmark_dir,
                reviewer,
                max_concurrency=request.max_concurrency,
                smoke_case=request.smoke_case,
            )
            with self._repository() as repository:
                repository.finish_run(
                    run_id,
                    benchmark_run,
                    expected_bug_present,
                    self._clock(),
                )
        except Exception as exc:  # noqa: BLE001 - persist worker failures for status polling
            self._record_failure(run_id, exc)

    def _record_failure(self, run_id: str, exc: Exception) -> None:
        with self._repository() as repository:
            record = repository.get_record(run_id)
            if record is not None and record.metadata.status in (
                RunStatus.QUEUED,
                RunStatus.RUNNING,
            ):
                repository.fail_run(
                    run_id,
                    completed_at=self._clock(),
                    error_type=type(exc).__name__,
                    error_message=str(exc) or "Benchmark execution failed without an error message",
                )

    @contextmanager
    def _repository(self) -> Iterator[HistoryRepository]:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = connect_history(self._database_path)
        try:
            yield HistoryRepository(connection)
        finally:
            connection.close()

    @staticmethod
    def _expected_cases(cases: list[BenchmarkCase], smoke_case: str | None) -> dict[str, bool]:
        expected = {case.case_id: case.expected.bug_present for case in cases}
        if smoke_case is not None and smoke_case not in expected:
            raise ValueError(f"Unknown smoke case: {smoke_case}")
        return expected

    @staticmethod
    def _make_reviewer(request: StartRunRequest) -> OpenAIReviewer:
        return OpenAIReviewer(
            model=request.model,
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            timeout_seconds=request.timeout_seconds,
            max_retries=request.max_retries,
        )


def create_app(service: BenchmarkService | None = None) -> FastAPI:
    benchmark_service = service or BenchmarkService(
        database_path=Path(os.environ.get("PATCHBENCH_DATABASE", "results/patchbench.db")),
        benchmark_dir=Path(os.environ.get("PATCHBENCH_BENCHMARK", "benchmark")),
        source_commit=os.environ.get("PATCHBENCH_SOURCE_COMMIT"),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        benchmark_service.shutdown()

    application = FastAPI(title="PatchBench API", version="0.1.0", lifespan=lifespan)

    @application.post(
        "/runs",
        response_model=RunRecord,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def start_run(request: StartRunRequest) -> RunRecord:
        try:
            return benchmark_service.start_run(request)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @application.get("/runs/{run_id}", response_model=RunRecord)
    def get_run(run_id: str) -> RunRecord:
        record = benchmark_service.get_run_record(run_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        return record

    @application.get("/runs/{run_id}/results", response_model=StoredRun)
    def get_results(run_id: str) -> StoredRun:
        record = benchmark_service.get_run_record(run_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        if record.metadata.status in (RunStatus.QUEUED, RunStatus.RUNNING):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Run results are not ready",
            )
        stored_run = benchmark_service.get_results(run_id)
        if stored_run is None or not stored_run.benchmark_run.case_order:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Run failed before producing case results",
            )
        return stored_run

    return application


app = create_app()


def main() -> None:
    uvicorn.run("patchbench.api:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
