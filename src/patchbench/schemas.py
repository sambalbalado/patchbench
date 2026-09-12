from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExpectedFinding(BaseModel):
    bug_present: bool
    category: str | None = None
    file: str | None = None
    line: int | None = Field(default=None, ge=1)
    explanation: str

    @model_validator(mode="after")
    def require_bug_details(self) -> "ExpectedFinding":
        if self.bug_present and not all((self.category, self.file, self.line)):
            raise ValueError("Bug cases require category, file, and line")
        if not self.bug_present and any(
            value is not None for value in (self.category, self.file, self.line)
        ):
            raise ValueError("Safe cases cannot specify category, file, or line")
        return self


class ReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bug_found: bool
    category: str | None = None
    file: str | None = None
    line: int | None = Field(default=None, ge=1)
    explanation: str
    suggested_test: str | None = None
    confidence: float = Field(ge=0, le=1)


class BenchmarkCase(BaseModel):
    case_id: str
    patch_path: Path
    expected: ExpectedFinding


class TokenPricing(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_usd_per_million: float = Field(ge=0)
    cached_input_usd_per_million: float = Field(ge=0)
    output_usd_per_million: float = Field(ge=0)
    source: str
    as_of: str

    def estimate_cost(
        self,
        *,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
    ) -> float:
        uncached_input_tokens = input_tokens - cached_input_tokens
        return (
            uncached_input_tokens * self.input_usd_per_million
            + cached_input_tokens * self.cached_input_usd_per_million
            + output_tokens * self.output_usd_per_million
        ) / 1_000_000


class CaseScore(BaseModel):
    case_id: str
    detection_correct: bool
    category_correct: bool | None
    file_correct: bool | None
    line_correct: bool | None
    false_positive: bool
    points_earned: int
    points_possible: int
    latency_ms: float | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)

    @property
    def accuracy(self) -> float:
        return self.points_earned / self.points_possible


class BenchmarkSummary(BaseModel):
    cases: list[CaseScore]
    detection_accuracy: float
    false_positive_rate: float
    total_accuracy: float
    model: str | None = None
    prompt_version: str | None = None
    pricing: TokenPricing | None = None
    average_latency_ms: float | None = Field(default=None, ge=0)
    total_input_tokens: int | None = Field(default=None, ge=0)
    total_cached_input_tokens: int | None = Field(default=None, ge=0)
    total_output_tokens: int | None = Field(default=None, ge=0)
    total_estimated_cost_usd: float | None = Field(default=None, ge=0)
    usage_available_cases: int = Field(default=0, ge=0)
    cost_estimated_cases: int = Field(default=0, ge=0)


class CaseFailure(BaseModel):
    case_id: str
    error_type: str
    message: str
    latency_ms: float | None = Field(default=None, ge=0)


class BenchmarkRun(BaseModel):
    case_order: list[str]
    requested_cases: int = Field(ge=0)
    completed_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)
    skipped_cases: int = Field(ge=0)
    failures: list[CaseFailure]
    skipped_case_ids: list[str]
    summary: BenchmarkSummary | None

    @model_validator(mode="after")
    def validate_case_accounting(self) -> "BenchmarkRun":
        completed_ids = [score.case_id for score in self.summary.cases] if self.summary else []
        failed_ids = [failure.case_id for failure in self.failures]
        reported_ids = completed_ids + failed_ids + self.skipped_case_ids

        expected_counts = (
            len(self.case_order),
            len(completed_ids),
            len(failed_ids),
            len(self.skipped_case_ids),
        )
        actual_counts = (
            self.requested_cases,
            self.completed_cases,
            self.failed_cases,
            self.skipped_cases,
        )
        if actual_counts != expected_counts:
            raise ValueError("Benchmark run counts must match their case collections")
        if len(set(self.case_order)) != len(self.case_order):
            raise ValueError("Benchmark case order cannot contain duplicates")
        if len(reported_ids) != len(set(reported_ids)) or set(reported_ids) != set(self.case_order):
            raise ValueError("Every requested case must be completed, failed, or skipped once")

        position = {case_id: index for index, case_id in enumerate(self.case_order)}
        for group in (completed_ids, failed_ids, self.skipped_case_ids):
            if group != sorted(group, key=position.__getitem__):
                raise ValueError("Case collections must preserve benchmark order")
        return self
