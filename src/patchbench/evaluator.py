from patchbench.schemas import (
    BenchmarkCase,
    BenchmarkSummary,
    CaseScore,
    ReviewResult,
    TokenPricing,
)


def score_case(
    case: BenchmarkCase,
    review: ReviewResult,
    line_tolerance: int = 2,
    latency_ms: float | None = None,
    input_tokens: int | None = None,
    cached_input_tokens: int | None = None,
    output_tokens: int | None = None,
    estimated_cost_usd: float | None = None,
) -> CaseScore:
    expected = case.expected
    detection_correct = review.bug_found == expected.bug_present
    false_positive = review.bug_found and not expected.bug_present

    checks: list[bool] = [detection_correct]
    category_correct = file_correct = line_correct = None

    if expected.bug_present:
        category_correct = detection_correct and review.category == expected.category
        file_correct = detection_correct and review.file == expected.file
        line_correct = detection_correct and (
            review.line is not None and abs(review.line - expected.line) <= line_tolerance
        )
        checks.extend((category_correct, file_correct, line_correct))

    return CaseScore(
        case_id=case.case_id,
        detection_correct=detection_correct,
        category_correct=category_correct,
        file_correct=file_correct,
        line_correct=line_correct,
        false_positive=false_positive,
        points_earned=sum(checks),
        points_possible=len(checks),
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=estimated_cost_usd,
    )


def summarize(
    scores: list[CaseScore],
    *,
    model: str | None = None,
    prompt_version: str | None = None,
    pricing: TokenPricing | None = None,
) -> BenchmarkSummary:
    if not scores:
        raise ValueError("At least one score is required")
    safe_cases = [score for score in scores if score.points_possible == 1]
    latencies = [score.latency_ms for score in scores if score.latency_ms is not None]
    usage_scores = [
        score
        for score in scores
        if score.input_tokens is not None and score.output_tokens is not None
    ]
    costs = [score.estimated_cost_usd for score in scores if score.estimated_cost_usd is not None]
    return BenchmarkSummary(
        cases=scores,
        detection_accuracy=sum(score.detection_correct for score in scores) / len(scores),
        false_positive_rate=(
            sum(score.false_positive for score in safe_cases) / len(safe_cases)
            if safe_cases
            else 0.0
        ),
        total_accuracy=sum(score.points_earned for score in scores)
        / sum(score.points_possible for score in scores),
        model=model,
        prompt_version=prompt_version,
        pricing=pricing,
        average_latency_ms=sum(latencies) / len(latencies) if latencies else None,
        total_input_tokens=(
            sum(score.input_tokens or 0 for score in usage_scores) if usage_scores else None
        ),
        total_cached_input_tokens=(
            sum(score.cached_input_tokens or 0 for score in usage_scores) if usage_scores else None
        ),
        total_output_tokens=(
            sum(score.output_tokens or 0 for score in usage_scores) if usage_scores else None
        ),
        total_estimated_cost_usd=sum(costs) if costs else None,
        usage_available_cases=len(usage_scores),
        cost_estimated_cases=len(costs),
    )
