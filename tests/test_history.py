import sqlite3

import pytest

from patchbench.history import connect_history, initialize_history


def make_history() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    initialize_history(connection)
    return connection


def insert_run(connection: sqlite3.Connection, run_id: str = "run-1") -> None:
    connection.execute(
        """
        INSERT INTO runs (
            run_id, status, mode, benchmark_name, benchmark_version, source_commit,
            model, prompt_version, max_concurrency, timeout_seconds, max_retries,
            input_usd_per_million, cached_input_usd_per_million, output_usd_per_million,
            pricing_source, pricing_as_of, started_at, completed_at
        ) VALUES (?, 'completed', 'openai', 'default', 'coverage-v1', 'abc123',
            'gpt-5-mini', 'review-v2', 4, 60, 0, 0.25, 0.025, 2.0,
            'https://example.com/pricing', '2026-09-23',
            '2026-09-23T10:00:00Z', '2026-09-23T10:01:00Z')
        """,
        (run_id,),
    )


def test_initialization_applies_migrations_once() -> None:
    connection = sqlite3.connect(":memory:")

    assert initialize_history(connection) == 1
    assert initialize_history(connection) == 1

    migrations = connection.execute(
        "SELECT version, name FROM schema_migrations ORDER BY version"
    ).fetchall()
    assert migrations == [(1, "001_initial_history.sql")]
    assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)


def test_connect_history_creates_a_reusable_database(tmp_path) -> None:
    database_path = tmp_path / "history.sqlite3"

    with connect_history(database_path) as connection:
        insert_run(connection)

    with connect_history(database_path) as connection:
        assert connection.execute("SELECT run_id FROM runs").fetchone() == ("run-1",)
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone() == (1,)


def test_summary_metrics_are_derived_from_case_results() -> None:
    connection = make_history()
    insert_run(connection)
    connection.executemany(
        """
        INSERT INTO case_results (
            run_id, case_id, position, outcome, expected_bug_present,
            detection_correct, category_correct, file_correct, line_correct,
            false_positive, points_earned, points_possible, latency_ms,
            input_tokens, cached_input_tokens, output_tokens, estimated_cost_usd
        ) VALUES ('run-1', ?, ?, 'completed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("buggy", 0, 1, 1, 1, 1, 1, 0, 4, 4, 10.0, 100, 20, 25, 0.001),
            ("safe", 1, 0, 1, None, None, None, 0, 1, 1, 20.0, 80, 0, 20, 0.002),
            ("false-positive", 2, 0, 0, None, None, None, 1, 0, 1, 30.0, 90, 0, 30, 0.003),
        ],
    )

    connection.row_factory = sqlite3.Row
    summary = connection.execute("SELECT * FROM run_summaries WHERE run_id = 'run-1'").fetchone()

    assert summary is not None
    assert dict(summary) == {
        "run_id": "run-1",
        "requested_cases": 3,
        "completed_cases": 3,
        "failed_cases": 0,
        "skipped_cases": 0,
        "detection_accuracy": pytest.approx(2 / 3),
        "false_positive_rate": 0.5,
        "category_accuracy": 1.0,
        "file_accuracy": 1.0,
        "line_accuracy": 1.0,
        "total_accuracy": pytest.approx(5 / 6),
        "average_latency_ms": 20.0,
        "total_input_tokens": 270,
        "total_cached_input_tokens": 20,
        "total_output_tokens": 75,
        "total_estimated_cost_usd": 0.006,
        "usage_available_cases": 3,
        "cost_estimated_cases": 3,
    }


def test_run_delete_cascades_to_case_results() -> None:
    connection = make_history()
    insert_run(connection)
    connection.execute(
        """
        INSERT INTO case_results (
            run_id, case_id, position, outcome, expected_bug_present
        ) VALUES ('run-1', 'skipped', 0, 'skipped', 0)
        """
    )

    connection.execute("DELETE FROM runs WHERE run_id = 'run-1'")

    assert connection.execute("SELECT COUNT(*) FROM case_results").fetchone() == (0,)


def test_failure_and_skipped_outcomes_are_stored_without_affecting_scores() -> None:
    connection = make_history()
    insert_run(connection)
    connection.execute(
        """
        INSERT INTO case_results (
            run_id, case_id, position, outcome, expected_bug_present,
            latency_ms, error_type, error_message
        ) VALUES ('run-1', 'failed', 0, 'failed', 1, 5000, 'ModelAPIError', 'Unavailable')
        """
    )
    connection.execute(
        """
        INSERT INTO case_results (
            run_id, case_id, position, outcome, expected_bug_present
        ) VALUES ('run-1', 'skipped', 1, 'skipped', 0)
        """
    )

    summary = connection.execute(
        """
        SELECT requested_cases, completed_cases, failed_cases, skipped_cases,
            detection_accuracy, average_latency_ms
        FROM run_summaries WHERE run_id = 'run-1'
        """
    ).fetchone()

    assert summary == (2, 0, 1, 1, None, None)
    assert connection.execute(
        "SELECT error_type, error_message, latency_ms FROM case_results WHERE case_id = 'failed'"
    ).fetchone() == ("ModelAPIError", "Unavailable", 5000.0)


def test_case_outcome_constraints_reject_partial_completed_results() -> None:
    connection = make_history()
    insert_run(connection)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO case_results (
                run_id, case_id, position, outcome, expected_bug_present,
                detection_correct, false_positive
            ) VALUES ('run-1', 'partial', 0, 'completed', 0, 1, 0)
            """
        )
