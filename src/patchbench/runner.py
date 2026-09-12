import argparse
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from patchbench.evaluator import score_case, summarize
from patchbench.loader import load_cases, load_predictions
from patchbench.openai_reviewer import ModelReviewError, OpenAIReviewer
from patchbench.schemas import BenchmarkCase, BenchmarkRun, CaseFailure, CaseScore, ReviewResult

DEFAULT_MAX_CONCURRENCY = 4
MAX_CONCURRENCY = 8


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


def _review_case(case: BenchmarkCase, reviewer: OpenAIReviewer) -> CaseScore | CaseFailure:
    try:
        timed_review = reviewer.review_patch(case.patch_path.read_text())
        return score_case(
            case,
            timed_review.review,
            latency_ms=timed_review.latency_ms,
            input_tokens=timed_review.input_tokens,
            cached_input_tokens=timed_review.cached_input_tokens,
            output_tokens=timed_review.output_tokens,
            estimated_cost_usd=timed_review.estimated_cost_usd,
        )
    except ModelReviewError as exc:
        return CaseFailure(
            case_id=case.case_id,
            error_type=type(exc).__name__,
            message=exc.detail,
            latency_ms=exc.latency_ms,
        )
    except Exception as exc:  # noqa: BLE001 - isolate every individual worker failure
        return CaseFailure(
            case_id=case.case_id,
            error_type=type(exc).__name__,
            message=str(exc) or "Model review failed without an error message",
        )


def run_openai(
    benchmark_dir: Path,
    reviewer: OpenAIReviewer,
    *,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
) -> BenchmarkRun:
    if not 1 <= max_concurrency <= MAX_CONCURRENCY:
        raise ValueError(f"max_concurrency must be between 1 and {MAX_CONCURRENCY}")

    cases = load_cases(benchmark_dir)
    outcomes: dict[str, CaseScore | CaseFailure] = {}
    with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
        futures = {executor.submit(_review_case, case, reviewer): case for case in cases}
        for future in as_completed(futures):
            case = futures[future]
            outcomes[case.case_id] = future.result()

    scores = [outcome for case in cases if isinstance(outcome := outcomes[case.case_id], CaseScore)]
    failures = [
        outcome for case in cases if isinstance(outcome := outcomes[case.case_id], CaseFailure)
    ]
    summary = (
        summarize(
            scores,
            model=getattr(reviewer, "model", None),
            prompt_version=getattr(reviewer, "prompt_version", None),
            pricing=getattr(reviewer, "pricing", None),
        )
        if scores
        else None
    )
    return BenchmarkRun(
        case_order=[case.case_id for case in cases],
        requested_cases=len(cases),
        completed_cases=len(scores),
        failed_cases=len(failures),
        skipped_cases=0,
        failures=failures,
        skipped_case_ids=[],
        summary=summary,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Score AI code-review predictions")
    parser.add_argument("--benchmark", type=Path, default=Path("benchmark"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--predictions", type=Path, help="Read offline predictions from JSON")
    mode.add_argument("--openai", action="store_true", help="Request live OpenAI reviews")
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=DEFAULT_MAX_CONCURRENCY,
        help=f"Maximum simultaneous live requests (1-{MAX_CONCURRENCY}, default: %(default)s)",
    )
    args = parser.parse_args()
    if args.openai:
        model = os.environ.get("PATCHBENCH_MODEL", "")
        api_key = os.environ.get("OPENAI_API_KEY", "")
        try:
            result = run_openai(
                args.benchmark,
                OpenAIReviewer(model=model, api_key=api_key),
                max_concurrency=args.max_concurrency,
            )
        except (ValueError, ModelReviewError) as exc:
            parser.error(str(exc))
    else:
        predictions = args.predictions or Path("examples/predictions.json")
        result = run(args.benchmark, predictions)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
