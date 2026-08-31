from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import openai
from pydantic import ValidationError

from patchbench.schemas import ReviewResult

REVIEW_INSTRUCTIONS = """You are a careful code reviewer. Review only the supplied patch.
Report a bug only when the patch introduces a concrete defect. Use the path and new-file line
number from the diff. Use a concise snake_case category. If the patch is safe, set bug_found to
false and do not invent a finding. Explain the decision and suggest a focused test when useful.
"""


@dataclass(frozen=True)
class TimedReview:
    review: ReviewResult
    latency_ms: float


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

        self.model = model
        self._clock = clock
        self._client = client or openai.OpenAI(
            api_key=api_key, timeout=timeout_seconds, max_retries=0
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

        return TimedReview(review=review, latency_ms=self._elapsed_ms(started_at))

    def _elapsed_ms(self, started_at: float) -> float:
        return (self._clock() - started_at) * 1000
