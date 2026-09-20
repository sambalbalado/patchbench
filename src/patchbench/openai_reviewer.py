from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import openai
from pydantic import ValidationError

from patchbench.schemas import ReviewResult, TokenPricing

REVIEW_PROMPT_VERSION = "review-v2"
DEFAULT_MAX_RETRIES = 1
MAX_RETRIES = 2
REVIEW_INSTRUCTIONS = """You are a careful code reviewer. Review only the supplied patch.
Report a bug only when the patch introduces a concrete defect. Use the path and new-file line
number from the diff. Select the most specific category allowed by the response schema, using
other only when none applies. If the patch is safe, set bug_found to false and leave category,
file, and line null. Explain the decision and suggest a focused test when useful.
"""

OPENAI_PRICING = {
    model: TokenPricing(
        input_usd_per_million=0.25,
        cached_input_usd_per_million=0.025,
        output_usd_per_million=2.00,
        source="https://developers.openai.com/api/docs/models/gpt-5-mini",
        as_of="2026-09-10",
    )
    for model in ("gpt-5-mini", "gpt-5-mini-2025-08-07")
}


@dataclass(frozen=True)
class TimedReview:
    review: ReviewResult
    latency_ms: float
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None


class ModelReviewError(RuntimeError):
    """Base error for a failed model review, including elapsed request time."""

    def __init__(self, message: str, latency_ms: float) -> None:
        self.detail = message
        self.latency_ms = latency_ms
        super().__init__(f"{message} (after {latency_ms:.1f} ms)")


class ModelReviewTimeout(ModelReviewError):
    """The model request exceeded its configured timeout."""


class InvalidModelResponse(ModelReviewError):
    """The model did not return a valid ReviewResult."""


class ModelAPIError(ModelReviewError):
    """The OpenAI API rejected or could not complete the request."""


class OpenAIReviewer:
    def __init__(
        self,
        model: str,
        api_key: str,
        timeout_seconds: float = 60.0,
        max_retries: int = DEFAULT_MAX_RETRIES,
        *,
        client: Any | None = None,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        if not model:
            raise ValueError("PATCHBENCH_MODEL must be set for --openai mode")
        if not api_key:
            raise ValueError("OPENAI_API_KEY must be set for --openai mode")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not 0 <= max_retries <= MAX_RETRIES:
            raise ValueError(f"max_retries must be between 0 and {MAX_RETRIES}")

        self.model = model
        self.prompt_version = REVIEW_PROMPT_VERSION
        self.pricing = OPENAI_PRICING.get(model)
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._clock = clock
        self._client = client or openai.OpenAI(
            api_key=api_key, timeout=timeout_seconds, max_retries=max_retries
        )

    def review_patch(self, patch: str) -> TimedReview:
        started_at = self._clock()
        try:
            response = self._client.responses.parse(
                model=self.model,
                instructions=REVIEW_INSTRUCTIONS,
                input=patch,
                store=False,
                text_format=ReviewResult,
            )
            if response.output_parsed is None:
                raise InvalidModelResponse(
                    "OpenAI returned no structured ReviewResult", self._elapsed_ms(started_at)
                )
            review = ReviewResult.model_validate(response.output_parsed)
        except openai.APITimeoutError as exc:
            raise ModelReviewTimeout(
                "OpenAI request timed out", self._elapsed_ms(started_at)
            ) from exc
        except openai.APIError as exc:
            raise ModelAPIError(
                f"OpenAI API request failed: {exc}", self._elapsed_ms(started_at)
            ) from exc
        except openai.OpenAIError as exc:
            raise InvalidModelResponse(
                f"OpenAI response could not be parsed: {exc}", self._elapsed_ms(started_at)
            ) from exc
        except ValidationError as exc:
            raise InvalidModelResponse(
                "OpenAI response did not match ReviewResult", self._elapsed_ms(started_at)
            ) from exc

        input_tokens, cached_input_tokens, output_tokens = self._extract_usage(response)
        estimated_cost_usd = None
        if self.pricing is not None and input_tokens is not None and output_tokens is not None:
            estimated_cost_usd = self.pricing.estimate_cost(
                input_tokens=input_tokens,
                cached_input_tokens=cached_input_tokens or 0,
                output_tokens=output_tokens,
            )

        return TimedReview(
            review=review,
            latency_ms=self._elapsed_ms(started_at),
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimated_cost_usd,
        )

    @staticmethod
    def _extract_usage(response: Any) -> tuple[int | None, int | None, int | None]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None, None, None

        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        input_details = getattr(usage, "input_tokens_details", None)
        cached_input_tokens = getattr(input_details, "cached_tokens", 0)
        return input_tokens, cached_input_tokens, output_tokens

    def _elapsed_ms(self, started_at: float) -> float:
        return (self._clock() - started_at) * 1000
