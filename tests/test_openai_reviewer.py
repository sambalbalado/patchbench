from types import SimpleNamespace

import httpx
import openai
import pytest

from patchbench.openai_reviewer import (
    InvalidModelResponse,
    ModelAPIError,
    ModelReviewTimeout,
    OpenAIReviewer,
)
from patchbench.schemas import ReviewResult


def valid_review() -> ReviewResult:
    return ReviewResult(
        bug_found=True,
        category="division_by_zero",
        file="calculator.py",
        line=6,
        explanation="The zero guard was removed.",
        suggested_test="Call completion_rate with total=0.",
        confidence=0.95,
    )


class FakeResponses:
    def __init__(self, output_parsed=None, error: Exception | None = None) -> None:
        self.output_parsed = output_parsed
        self.error = error
        self.arguments = {}

    def parse(self, **kwargs):
        self.arguments = kwargs
        if self.error:
            raise self.error
        return SimpleNamespace(output_parsed=self.output_parsed)


def reviewer_with(responses: FakeResponses, times=(10.0, 10.25)) -> OpenAIReviewer:
    clock_values = iter(times)
    client = SimpleNamespace(responses=responses)
    return OpenAIReviewer(
        model="test-model",
        api_key="test-key",
        client=client,
        clock=lambda: next(clock_values),
    )


def test_requests_and_validates_structured_review_with_latency() -> None:
    responses = FakeResponses(output_parsed=valid_review())

    result = reviewer_with(responses).review_patch("diff --git a/a.py b/a.py")

    assert result.review == valid_review()
    assert result.latency_ms == pytest.approx(250)
    assert responses.arguments["model"] == "test-model"
    assert responses.arguments["store"] is False
    assert responses.arguments["text_format"] is ReviewResult
    assert responses.arguments["input"].startswith("diff --git")


def test_reports_timeout_with_elapsed_latency() -> None:
    timeout = openai.APITimeoutError(httpx.Request("POST", "https://api.openai.com"))

    with pytest.raises(ModelReviewTimeout, match=r"timed out \(after 250.0 ms\)") as caught:
        reviewer_with(FakeResponses(error=timeout)).review_patch("patch")

    assert caught.value.latency_ms == pytest.approx(250)


def test_reports_api_error_without_exposing_api_key() -> None:
    error = openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com"))

    with pytest.raises(ModelAPIError, match="OpenAI API request failed") as caught:
        reviewer_with(FakeResponses(error=error)).review_patch("patch")

    assert "test-key" not in str(caught.value)
    assert caught.value.latency_ms == pytest.approx(250)


def test_reports_sdk_parse_error_as_invalid_response() -> None:
    with pytest.raises(InvalidModelResponse, match="could not be parsed"):
        reviewer_with(FakeResponses(error=openai.OpenAIError("truncated"))).review_patch("patch")


@pytest.mark.parametrize(
    "output",
    [
        None,
        {
            "bug_found": True,
            "explanation": "Invalid confidence.",
            "confidence": 2,
        },
    ],
)
def test_rejects_missing_or_invalid_structured_response(output) -> None:
    with pytest.raises(InvalidModelResponse, match="ReviewResult"):
        reviewer_with(FakeResponses(output_parsed=output)).review_patch("patch")


@pytest.mark.parametrize(
    ("model", "api_key", "message"),
    [
        ("", "key", "PATCHBENCH_MODEL"),
        ("model", "", "OPENAI_API_KEY"),
    ],
)
def test_requires_environment_configuration(model: str, api_key: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        OpenAIReviewer(model=model, api_key=api_key)


def test_configures_timeout_and_disables_sdk_retries(monkeypatch) -> None:
    arguments = {}

    def fake_openai(**kwargs):
        arguments.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(openai, "OpenAI", fake_openai)

    OpenAIReviewer(model="test-model", api_key="test-key", timeout_seconds=7.5)

    assert arguments == {"api_key": "test-key", "timeout": 7.5, "max_retries": 0}
