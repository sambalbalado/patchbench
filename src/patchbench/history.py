import json
import re
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from importlib.resources import files
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from patchbench.schemas import (
    BenchmarkRun,
    BenchmarkSummary,
    CaseFailure,
    CaseScore,
    TokenPricing,
)

MIGRATION_PATTERN = re.compile(r"^(?P<version>[0-9]{3})_[a-z0-9_]+\.sql$")
DEFAULT_RUN_LIST_LIMIT = 50
MAX_RUN_LIST_LIMIT = 100


class RunMode(StrEnum):
    OFFLINE = "offline"
    OPENAI = "openai"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RunMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    status: RunStatus
    mode: RunMode
    benchmark_name: str = Field(min_length=1)
    benchmark_version: str = Field(min_length=1)
    source_commit: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    pricing: TokenPricing | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_reproducible_metadata(self) -> "RunMetadata":
        timestamps = (self.created_at, self.started_at, self.completed_at)
        if any(value is not None and value.utcoffset() is None for value in timestamps):
            raise ValueError("History timestamps must include a timezone")
        if self.mode is RunMode.OPENAI and not (self.model and self.prompt_version):
            raise ValueError("OpenAI history requires model and prompt_version")
        is_terminal = self.status in (RunStatus.COMPLETED, RunStatus.FAILED)
        if is_terminal != (self.completed_at is not None):
            raise ValueError("Only completed or failed runs may have a completed_at timestamp")
        return self


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata: RunMetadata
    max_concurrency: int = Field(ge=1)
    timeout_seconds: float = Field(gt=0)
    max_retries: int = Field(ge=0)
    error_type: str | None = None
    error_message: str | None = None


class StoredRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata: RunMetadata
    benchmark_run: BenchmarkRun


def _migrations() -> list[tuple[int, str, str]]:
    migration_dir = files("patchbench").joinpath("migrations")
    migrations: list[tuple[int, str, str]] = []
    for resource in migration_dir.iterdir():
        match = MIGRATION_PATTERN.fullmatch(resource.name)
        if match:
            migrations.append((int(match.group("version")), resource.name, resource.read_text()))

    migrations.sort(key=lambda migration: migration[0])
    versions = [version for version, _, _ in migrations]
    if not versions or versions != list(range(1, len(versions) + 1)):
        raise RuntimeError("History migrations must start at 001 and remain contiguous")
    return migrations


def initialize_history(connection: sqlite3.Connection) -> int:
    """Apply every pending bundled migration and return the current schema version."""

    if connection.in_transaction:
        raise ValueError("History initialization requires a connection outside a transaction")

    connection.execute("PRAGMA foreign_keys = ON")
    foreign_keys_enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]
    if foreign_keys_enabled != 1:
        raise RuntimeError("SQLite foreign-key enforcement could not be enabled")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )
    connection.commit()

    applied = dict(
        connection.execute("SELECT version, name FROM schema_migrations ORDER BY version")
    )
    migrations = _migrations()
    known_names = {version: name for version, name, _ in migrations}
    if unknown := applied.keys() - known_names.keys():
        raise RuntimeError(f"Database contains unknown history migrations: {sorted(unknown)}")
    mismatched = [
        version for version, applied_name in applied.items() if applied_name != known_names[version]
    ]
    if mismatched:
        raise RuntimeError(f"Database contains renamed history migrations: {mismatched}")

    for version, name, sql in migrations:
        if version in applied:
            continue
        safe_name = name.replace("'", "''")
        script = (
            "BEGIN IMMEDIATE;\n"
            f"{sql}\n"
            "INSERT INTO schema_migrations (version, name) "
            f"VALUES ({version}, '{safe_name}');\n"
            "COMMIT;"
        )
        try:
            connection.executescript(script)
        except sqlite3.Error:
            if connection.in_transaction:
                connection.rollback()
            raise

    return migrations[-1][0]


def connect_history(path: str | Path) -> sqlite3.Connection:
    """Open a history database with migrations and foreign keys ready for use."""

    connection = sqlite3.connect(path)
    try:
        initialize_history(connection)
    except Exception:
        connection.close()
        raise
    return connection


class HistoryRepository:
    """Persist complete benchmark runs while leaving connection ownership to the caller."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        initialize_history(connection)
        self._connection = connection

    def create_run(
        self,
        metadata: RunMetadata,
        *,
        max_concurrency: int,
        timeout_seconds: float,
        max_retries: int,
    ) -> None:
        """Create a queued run before background execution begins."""

        if metadata.status is not RunStatus.QUEUED:
            raise ValueError("New background runs must start in queued status")
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if self._connection.in_transaction:
            raise ValueError("Creating a run requires a connection outside a transaction")

        with self._connection:
            self._insert_run(
                metadata,
                max_concurrency=max_concurrency,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            )

    def mark_running(self, run_id: str, started_at: datetime) -> None:
        if started_at.utcoffset() is None:
            raise ValueError("History timestamps must include a timezone")
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE runs
                SET status = 'running', started_at = ?
                WHERE run_id = ? AND status = 'queued'
                """,
                (started_at.isoformat(), run_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Run is missing or no longer queued: {run_id}")

    def finish_run(
        self,
        run_id: str,
        benchmark_run: BenchmarkRun,
        expected_bug_present: Mapping[str, bool],
        completed_at: datetime,
    ) -> None:
        """Atomically attach case outcomes and move a queued/running run to a terminal state."""

        if completed_at.utcoffset() is None:
            raise ValueError("History timestamps must include a timezone")
        record = self.get_record(run_id)
        if record is None or record.metadata.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
            raise ValueError(f"Run is missing or already terminal: {run_id}")
        expected_ids = set(benchmark_run.case_order)
        if set(expected_bug_present) != expected_ids:
            raise ValueError("Expected-case metadata must match benchmark case_order exactly")
        if any(not isinstance(value, bool) for value in expected_bug_present.values()):
            raise TypeError("Expected bug values must be booleans")
        self._validate_summary_metadata(record.metadata, benchmark_run.summary)
        status = RunStatus.COMPLETED if benchmark_run.summary is not None else RunStatus.FAILED

        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE runs
                SET status = ?, completed_at = ?, error_type = NULL, error_message = NULL
                WHERE run_id = ? AND status IN ('queued', 'running')
                """,
                (status.value, completed_at.isoformat(), run_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Run is missing or already terminal: {run_id}")
            self._insert_case_results(run_id, benchmark_run, expected_bug_present)

    def fail_run(
        self,
        run_id: str,
        *,
        completed_at: datetime,
        error_type: str,
        error_message: str,
    ) -> None:
        """Record an orchestration failure that occurred before case results were available."""

        if completed_at.utcoffset() is None:
            raise ValueError("History timestamps must include a timezone")
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE runs
                SET status = 'failed', completed_at = ?, error_type = ?, error_message = ?
                WHERE run_id = ? AND status IN ('queued', 'running')
                """,
                (completed_at.isoformat(), error_type, error_message, run_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Run is missing or already terminal: {run_id}")

    def save_run(
        self,
        metadata: RunMetadata,
        benchmark_run: BenchmarkRun,
        expected_bug_present: Mapping[str, bool],
    ) -> None:
        if metadata.status not in (RunStatus.COMPLETED, RunStatus.FAILED):
            raise ValueError("Only terminal benchmark runs can be saved with case outcomes")
        expected_ids = set(benchmark_run.case_order)
        if set(expected_bug_present) != expected_ids:
            raise ValueError("Expected-case metadata must match benchmark case_order exactly")
        if any(not isinstance(value, bool) for value in expected_bug_present.values()):
            raise TypeError("Expected bug values must be booleans")
        self._validate_summary_metadata(metadata, benchmark_run.summary)
        if self._connection.in_transaction:
            raise ValueError("Saving a run requires a connection outside a transaction")

        configuration_json = json.dumps(
            metadata.configuration, allow_nan=False, sort_keys=True, separators=(",", ":")
        )
        with self._connection:
            self._insert_run(
                metadata,
                max_concurrency=benchmark_run.max_concurrency,
                timeout_seconds=benchmark_run.timeout_seconds,
                max_retries=benchmark_run.max_retries,
                configuration_json=configuration_json,
            )
            self._insert_case_results(metadata.run_id, benchmark_run, expected_bug_present)

    def get_record(self, run_id: str) -> RunRecord | None:
        run_row = self._fetch_one("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        if run_row is None:
            return None
        return self._record_from_row(run_row)

    def list_records(
        self,
        *,
        status: RunStatus | None = None,
        limit: int = DEFAULT_RUN_LIST_LIMIT,
    ) -> list[RunRecord]:
        """List newest-created runs, optionally filtered to one exact lifecycle status."""

        if not 1 <= limit <= MAX_RUN_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_RUN_LIST_LIMIT}")
        if status is None:
            rows = self._fetch_all(
                """
                SELECT * FROM runs
                ORDER BY created_at DESC, run_id DESC
                LIMIT ?
                """,
                (limit,),
            )
        else:
            rows = self._fetch_all(
                """
                SELECT * FROM runs
                WHERE status = ?
                ORDER BY created_at DESC, run_id DESC
                LIMIT ?
                """,
                (status.value, limit),
            )
        return [self._record_from_row(row) for row in rows]

    def get_run(self, run_id: str) -> StoredRun | None:
        run_row = self._fetch_one("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        if run_row is None:
            return None

        case_rows = self._fetch_all(
            "SELECT * FROM case_results WHERE run_id = ? ORDER BY position", (run_id,)
        )
        if not case_rows:
            return None
        summary_row = self._fetch_one("SELECT * FROM run_summaries WHERE run_id = ?", (run_id,))
        if summary_row is None:
            raise RuntimeError(f"Missing derived summary for stored run: {run_id}")

        pricing = self._pricing_from_row(run_row)
        metadata = self._metadata_from_row(run_row)

        scores: list[CaseScore] = []
        failures: list[CaseFailure] = []
        skipped_case_ids: list[str] = []
        for row in case_rows:
            if row["outcome"] == "completed":
                scores.append(self._score_from_row(row))
            elif row["outcome"] == "failed":
                failures.append(
                    CaseFailure(
                        case_id=row["case_id"],
                        error_type=row["error_type"],
                        message=row["error_message"],
                        latency_ms=row["latency_ms"],
                    )
                )
            else:
                skipped_case_ids.append(row["case_id"])

        summary = (
            BenchmarkSummary(
                cases=scores,
                detection_accuracy=summary_row["detection_accuracy"],
                false_positive_rate=(
                    summary_row["false_positive_rate"]
                    if summary_row["false_positive_rate"] is not None
                    else 0.0
                ),
                total_accuracy=summary_row["total_accuracy"],
                model=metadata.model,
                prompt_version=metadata.prompt_version,
                pricing=pricing,
                average_latency_ms=summary_row["average_latency_ms"],
                total_input_tokens=summary_row["total_input_tokens"],
                total_cached_input_tokens=summary_row["total_cached_input_tokens"],
                total_output_tokens=summary_row["total_output_tokens"],
                total_estimated_cost_usd=summary_row["total_estimated_cost_usd"],
                usage_available_cases=summary_row["usage_available_cases"],
                cost_estimated_cases=summary_row["cost_estimated_cases"],
            )
            if scores
            else None
        )
        benchmark_run = BenchmarkRun(
            max_concurrency=run_row["max_concurrency"],
            timeout_seconds=run_row["timeout_seconds"],
            max_retries=run_row["max_retries"],
            case_order=[row["case_id"] for row in case_rows],
            requested_cases=summary_row["requested_cases"],
            completed_cases=summary_row["completed_cases"],
            failed_cases=summary_row["failed_cases"],
            skipped_cases=summary_row["skipped_cases"],
            failures=failures,
            skipped_case_ids=skipped_case_ids,
            summary=summary,
        )
        return StoredRun(metadata=metadata, benchmark_run=benchmark_run)

    def get_summary(self, run_id: str) -> BenchmarkSummary | None:
        stored_run = self.get_run(run_id)
        return stored_run.benchmark_run.summary if stored_run else None

    def _insert_run(
        self,
        metadata: RunMetadata,
        *,
        max_concurrency: int,
        timeout_seconds: float | None,
        max_retries: int | None,
        configuration_json: str | None = None,
    ) -> None:
        pricing = metadata.pricing
        self._connection.execute(
            """
            INSERT INTO runs (
                run_id, status, mode, benchmark_name, benchmark_version, source_commit,
                model, prompt_version, max_concurrency, timeout_seconds, max_retries,
                input_usd_per_million, cached_input_usd_per_million,
                output_usd_per_million, pricing_source, pricing_as_of,
                configuration_json, created_at, started_at, completed_at
            ) VALUES (
                :run_id, :status, :mode, :benchmark_name, :benchmark_version, :source_commit,
                :model, :prompt_version, :max_concurrency, :timeout_seconds, :max_retries,
                :input_price, :cached_input_price, :output_price, :pricing_source,
                :pricing_as_of, :configuration_json, :created_at, :started_at, :completed_at
            )
            """,
            {
                "run_id": metadata.run_id,
                "status": metadata.status.value,
                "mode": metadata.mode.value,
                "benchmark_name": metadata.benchmark_name,
                "benchmark_version": metadata.benchmark_version,
                "source_commit": metadata.source_commit,
                "model": metadata.model,
                "prompt_version": metadata.prompt_version,
                "max_concurrency": max_concurrency,
                "timeout_seconds": timeout_seconds,
                "max_retries": max_retries,
                "input_price": pricing.input_usd_per_million if pricing else None,
                "cached_input_price": pricing.cached_input_usd_per_million if pricing else None,
                "output_price": pricing.output_usd_per_million if pricing else None,
                "pricing_source": pricing.source if pricing else None,
                "pricing_as_of": pricing.as_of if pricing else None,
                "configuration_json": configuration_json
                or json.dumps(
                    metadata.configuration, allow_nan=False, sort_keys=True, separators=(",", ":")
                ),
                "created_at": metadata.created_at.isoformat(),
                "started_at": metadata.started_at.isoformat() if metadata.started_at else None,
                "completed_at": metadata.completed_at.isoformat() if metadata.completed_at else None,
            },
        )

    def _insert_case_results(
        self,
        run_id: str,
        benchmark_run: BenchmarkRun,
        expected_bug_present: Mapping[str, bool],
    ) -> None:
        scores = (
            {score.case_id: score for score in benchmark_run.summary.cases}
            if benchmark_run.summary is not None
            else {}
        )
        failures = {failure.case_id: failure for failure in benchmark_run.failures}
        skipped = set(benchmark_run.skipped_case_ids)
        for position, case_id in enumerate(benchmark_run.case_order):
            case_values = self._case_values(
                run_id,
                case_id,
                position,
                expected_bug_present[case_id],
                scores.get(case_id),
                failures.get(case_id),
                case_id in skipped,
            )
            self._connection.execute(
                """
                INSERT INTO case_results (
                    run_id, case_id, position, outcome, expected_bug_present,
                    detection_correct, category_correct, file_correct, line_correct,
                    false_positive, points_earned, points_possible, latency_ms,
                    input_tokens, cached_input_tokens, output_tokens, estimated_cost_usd,
                    error_type, error_message
                ) VALUES (
                    :run_id, :case_id, :position, :outcome, :expected_bug_present,
                    :detection_correct, :category_correct, :file_correct, :line_correct,
                    :false_positive, :points_earned, :points_possible, :latency_ms,
                    :input_tokens, :cached_input_tokens, :output_tokens, :estimated_cost_usd,
                    :error_type, :error_message
                )
                """,
                case_values,
            )

    def _metadata_from_row(self, row: dict[str, Any]) -> RunMetadata:
        return RunMetadata(
            run_id=row["run_id"],
            status=row["status"],
            mode=row["mode"],
            benchmark_name=row["benchmark_name"],
            benchmark_version=row["benchmark_version"],
            source_commit=row["source_commit"],
            model=row["model"],
            prompt_version=row["prompt_version"],
            pricing=self._pricing_from_row(row),
            configuration=json.loads(row["configuration_json"]),
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )

    def _record_from_row(self, row: dict[str, Any]) -> RunRecord:
        return RunRecord(
            metadata=self._metadata_from_row(row),
            max_concurrency=row["max_concurrency"],
            timeout_seconds=row["timeout_seconds"],
            max_retries=row["max_retries"],
            error_type=row["error_type"],
            error_message=row["error_message"],
        )

    @staticmethod
    def _validate_summary_metadata(metadata: RunMetadata, summary: BenchmarkSummary | None) -> None:
        if summary is None:
            return
        if (
            summary.model != metadata.model
            or summary.prompt_version != metadata.prompt_version
            or summary.pricing != metadata.pricing
        ):
            raise ValueError("Run metadata must match the benchmark summary configuration")

    @staticmethod
    def _case_values(
        run_id: str,
        case_id: str,
        position: int,
        expected_bug_present: bool,
        score: CaseScore | None,
        failure: CaseFailure | None,
        skipped: bool,
    ) -> dict[str, Any]:
        common: dict[str, Any] = {
            "run_id": run_id,
            "case_id": case_id,
            "position": position,
            "expected_bug_present": expected_bug_present,
            "detection_correct": None,
            "category_correct": None,
            "file_correct": None,
            "line_correct": None,
            "false_positive": None,
            "points_earned": None,
            "points_possible": None,
            "latency_ms": None,
            "input_tokens": None,
            "cached_input_tokens": None,
            "output_tokens": None,
            "estimated_cost_usd": None,
            "error_type": None,
            "error_message": None,
        }
        if score is not None:
            common.update(
                outcome="completed",
                detection_correct=score.detection_correct,
                category_correct=score.category_correct,
                file_correct=score.file_correct,
                line_correct=score.line_correct,
                false_positive=score.false_positive,
                points_earned=score.points_earned,
                points_possible=score.points_possible,
                latency_ms=score.latency_ms,
                input_tokens=score.input_tokens,
                cached_input_tokens=score.cached_input_tokens,
                output_tokens=score.output_tokens,
                estimated_cost_usd=score.estimated_cost_usd,
            )
        elif failure is not None:
            common.update(
                outcome="failed",
                latency_ms=failure.latency_ms,
                error_type=failure.error_type,
                error_message=failure.message,
            )
        elif skipped:
            common["outcome"] = "skipped"
        else:
            raise ValueError(f"Case has no completed, failed, or skipped outcome: {case_id}")
        return common

    @staticmethod
    def _pricing_from_row(row: dict[str, Any]) -> TokenPricing | None:
        if row["input_usd_per_million"] is None:
            return None
        return TokenPricing(
            input_usd_per_million=row["input_usd_per_million"],
            cached_input_usd_per_million=row["cached_input_usd_per_million"],
            output_usd_per_million=row["output_usd_per_million"],
            source=row["pricing_source"],
            as_of=row["pricing_as_of"],
        )

    @staticmethod
    def _score_from_row(row: dict[str, Any]) -> CaseScore:
        return CaseScore(
            case_id=row["case_id"],
            detection_correct=bool(row["detection_correct"]),
            category_correct=(
                bool(row["category_correct"]) if row["category_correct"] is not None else None
            ),
            file_correct=(bool(row["file_correct"]) if row["file_correct"] is not None else None),
            line_correct=(bool(row["line_correct"]) if row["line_correct"] is not None else None),
            false_positive=bool(row["false_positive"]),
            points_earned=row["points_earned"],
            points_possible=row["points_possible"],
            latency_ms=row["latency_ms"],
            input_tokens=row["input_tokens"],
            cached_input_tokens=row["cached_input_tokens"],
            output_tokens=row["output_tokens"],
            estimated_cost_usd=row["estimated_cost_usd"],
        )

    def _fetch_one(self, query: str, parameters: tuple[Any, ...]) -> dict[str, Any] | None:
        cursor = self._connection.execute(query, parameters)
        row = cursor.fetchone()
        return self._as_dict(cursor, row) if row is not None else None

    def _fetch_all(self, query: str, parameters: tuple[Any, ...]) -> list[dict[str, Any]]:
        cursor = self._connection.execute(query, parameters)
        return [self._as_dict(cursor, row) for row in cursor.fetchall()]

    @staticmethod
    def _as_dict(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
        return {description[0]: value for description, value in zip(cursor.description, row)}
