from pathlib import Path

from patchbench.runner import run


def test_example_benchmark_scores_perfectly() -> None:
    root = Path(__file__).parents[1]
    summary = run(root / "benchmark", root / "examples" / "predictions.json")
    assert summary.detection_accuracy == 1.0
    assert summary.false_positive_rate == 0.0
    assert summary.total_accuracy == 1.0

