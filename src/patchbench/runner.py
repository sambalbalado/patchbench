import argparse
from pathlib import Path

from patchbench.evaluator import score_case, summarize
from patchbench.loader import load_cases, load_predictions
from patchbench.schemas import ReviewResult


def run(benchmark_dir: Path, predictions_path: Path):
    cases = load_cases(benchmark_dir)
    predictions = load_predictions(predictions_path)
    scores = []
    for case in cases:
        if case.case_id not in predictions:
            raise ValueError(f"Missing prediction for case: {case.case_id}")
        review = ReviewResult.model_validate(predictions[case.case_id])
        scores.append(score_case(case, review))
    return summarize(scores)


def main() -> None:
    parser = argparse.ArgumentParser(description="Score AI code-review predictions")
    parser.add_argument("--benchmark", type=Path, default=Path("benchmark"))
    parser.add_argument("--predictions", type=Path, default=Path("examples/predictions.json"))
    args = parser.parse_args()
    summary = run(args.benchmark, args.predictions)
    print(summary.model_dump_json(indent=2))


if __name__ == "__main__":
    main()

