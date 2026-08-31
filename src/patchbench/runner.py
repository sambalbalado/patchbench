import argparse
import os
from pathlib import Path

from patchbench.evaluator import score_case, summarize
from patchbench.loader import load_cases, load_predictions
from patchbench.openai_reviewer import ModelReviewError, OpenAIReviewer
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


def run_openai(benchmark_dir: Path, reviewer: OpenAIReviewer):
    cases = load_cases(benchmark_dir)
    scores = []
    for case in cases:
        try:
            timed_review = reviewer.review_patch(case.patch_path.read_text())
        except ModelReviewError as exc:
            raise type(exc)(f"Case {case.case_id}: {exc.detail}", exc.latency_ms) from exc
        scores.append(
            score_case(case, timed_review.review, latency_ms=timed_review.latency_ms)
        )
    return summarize(scores)


def main() -> None:
    parser = argparse.ArgumentParser(description="Score AI code-review predictions")
    parser.add_argument("--benchmark", type=Path, default=Path("benchmark"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--predictions", type=Path, help="Read offline predictions from JSON")
    mode.add_argument("--openai", action="store_true", help="Request live OpenAI reviews")
    args = parser.parse_args()
    if args.openai:
        model = os.environ.get("PATCHBENCH_MODEL", "")
        api_key = os.environ.get("OPENAI_API_KEY", "")
        try:
            summary = run_openai(args.benchmark, OpenAIReviewer(model=model, api_key=api_key))
        except (ValueError, ModelReviewError) as exc:
            parser.error(str(exc))
    else:
        predictions = args.predictions or Path("examples/predictions.json")
        summary = run(args.benchmark, predictions)
    print(summary.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
