from patchbench.schemas import (
    BenchmarkCase,
    BenchmarkSummary,
    CaseScore,
    ReviewResult,
)


def score_case(
    case: BenchmarkCase,
    review: ReviewResult,
    line_tolerance: int = 2,
    latency_ms: float | None = None,
) -> CaseScore:
    expected = case.expected
    detection_correct = review.bug_found == expected.bug_present
    false_positive = review.bug_found and not expected.bug_present

    checks: list[bool] = [detection_correct]
    category_correct = file_correct = line_correct = None

    if expected.bug_present:
        category_correct = review.category == expected.category
        file_correct = review.file == expected.file
        line_correct = review.line is not None and abs(review.line - expected.line) <= line_tolerance
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
    )


def summarize(scores: list[CaseScore]) -> BenchmarkSummary:
    if not scores:
        raise ValueError("At least one score is required")
    safe_cases = [score for score in scores if score.points_possible == 1]
    return BenchmarkSummary(
        cases=scores,
        detection_accuracy=sum(score.detection_correct for score in scores) / len(scores),
        false_positive_rate=(
            sum(score.false_positive for score in safe_cases) / len(safe_cases) if safe_cases else 0.0
        ),
        total_accuracy=sum(score.points_earned for score in scores)
        / sum(score.points_possible for score in scores),
    )
