from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CoverageArea(StrEnum):
    LOGIC = "logic"
    VALIDATION = "validation"
    SECURITY = "security"
    RESOURCES = "resources"
    BOUNDARIES = "boundaries"


class CaseKind(StrEnum):
    BUGGY = "buggy"
    SAFE = "safe"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class FindingCategory(StrEnum):
    AUTHORIZATION_BYPASS = "authorization_bypass"
    CACHE_KEY_COLLISION = "cache_key_collision"
    DATA_LOSS = "data_loss"
    DIVISION_BY_ZERO = "division_by_zero"
    MISSING_AWAIT = "missing_await"
    MUTABLE_DEFAULT_ARGUMENT = "mutable_default_argument"
    OFF_BY_ONE = "off_by_one"
    PATH_TRAVERSAL = "path_traversal"
    SENSITIVE_DATA_EXPOSURE = "sensitive_data_exposure"
    SQL_INJECTION = "sql_injection"
    UNSAFE_DESERIALIZATION = "unsafe_deserialization"
    WEAK_RANDOMNESS = "weak_randomness"
    OTHER = "other"


class CoverageTargets(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_cases: int = Field(ge=1)
    safe_cases: int = Field(ge=1)
    coverage_areas: dict[CoverageArea, int]
    difficulty: dict[Difficulty, int]

    @model_validator(mode="after")
    def validate_target_totals(self) -> "CoverageTargets":
        if set(self.coverage_areas) != set(CoverageArea):
            raise ValueError("Coverage targets must define every coverage area exactly once")
        if set(self.difficulty) != set(Difficulty):
            raise ValueError("Difficulty targets must define every difficulty exactly once")
        if any(count < 1 for count in (*self.coverage_areas.values(), *self.difficulty.values())):
            raise ValueError("Coverage target counts must be positive")
        if sum(self.coverage_areas.values()) != self.total_cases:
            raise ValueError("Coverage-area targets must sum to total_cases")
        if sum(self.difficulty.values()) != self.total_cases:
            raise ValueError("Difficulty targets must sum to total_cases")
        if self.safe_cases > self.total_cases:
            raise ValueError("Safe-case target cannot exceed total_cases")
        return self


class CoverageEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    kind: CaseKind
    coverage_area: CoverageArea
    difficulty: Difficulty
    expected_finding: FindingCategory | None

    @model_validator(mode="after")
    def validate_expected_finding(self) -> "CoverageEntry":
        if self.kind is CaseKind.BUGGY and self.expected_finding in (None, FindingCategory.OTHER):
            raise ValueError("Buggy coverage entries require a specific expected finding")
        if self.kind is CaseKind.SAFE and self.expected_finding is not None:
            raise ValueError("Safe coverage entries cannot declare an expected finding")
        return self


class CoverageMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(ge=1)
    targets: CoverageTargets
    cases: list[CoverageEntry]

    @model_validator(mode="after")
    def validate_case_ids(self) -> "CoverageMatrix":
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Coverage matrix case IDs must be unique")
        return self


class ExpectedFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    bug_present: bool
    category: FindingCategory | None = None
    file: str | None = None
    line: int | None = Field(default=None, ge=1)
    explanation: str

    @model_validator(mode="after")
    def require_bug_details(self) -> "ExpectedFinding":
        if self.bug_present and not all((self.category, self.file, self.line)):
            raise ValueError("Bug cases require category, file, and line")
        if self.bug_present and self.category is FindingCategory.OTHER:
            raise ValueError("Ground truth requires a specific category")
        if not self.bug_present and any(
            value is not None for value in (self.category, self.file, self.line)
        ):
            raise ValueError("Safe cases cannot specify category, file, or line")
        return self


class ReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bug_found: bool
    category: FindingCategory | None = None
    file: str | None = None
    line: int | None = Field(default=None, ge=1)
    explanation: str
    suggested_test: str | None = None
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def require_consistent_bug_details(self) -> "ReviewResult":
        details = (self.category, self.file, self.line)
        if self.bug_found and not all(details):
            raise ValueError("Found bugs require category, file, and line")
        if not self.bug_found and any(value is not None for value in details):
            raise ValueError("Safe reviews cannot specify category, file, or line")
        return self


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
    max_concurrency: int = Field(ge=1)
    timeout_seconds: float | None = Field(default=None, gt=0)
    max_retries: int | None = Field(default=None, ge=0)
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
