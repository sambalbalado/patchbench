from pathlib import Path

from patchbench.demo import seed_demo_history
from patchbench.history import HistoryRepository, connect_history


def test_demo_seed_is_idempotent_and_reconstructs_both_baselines(tmp_path) -> None:
    root = Path(__file__).parents[1]
    database_path = tmp_path / "demo.sqlite3"

    assert seed_demo_history(database_path, root / "benchmark", root / "results") == 2
    assert seed_demo_history(database_path, root / "benchmark", root / "results") == 0

    with connect_history(database_path) as connection:
        repository = HistoryRepository(connection)
        records = repository.list_records()
        first = repository.get_run("baseline-review-v1-2026-09-11")
        second = repository.get_run("baseline-review-v2-2026-09-22")

    assert [record.metadata.run_id for record in records] == [
        "baseline-review-v2-2026-09-22",
        "baseline-review-v1-2026-09-11",
    ]
    assert first is not None
    assert first.benchmark_run.requested_cases == 24
    assert first.benchmark_run.summary is not None
    assert first.benchmark_run.summary.prompt_version == "review-v1"
    assert first.benchmark_run.summary.total_accuracy == 0.8333333333333334
    assert second is not None
    assert second.benchmark_run.requested_cases == 24
    assert second.benchmark_run.summary is not None
    assert second.benchmark_run.summary.prompt_version == "review-v2"
    assert second.benchmark_run.summary.total_accuracy == 0.9666666666666667
