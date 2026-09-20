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
    def __init__(self, output_parsed=None, error: Exception | None = None, usage=None) -> None:
        self.output_parsed = output_parsed
        self.error = error
        self.usage = usage
        self.arguments = {}
        self.calls = 0

    def parse(self, **kwargs):
        self.calls += 1
        self.arguments = kwargs
        if self.error:
            raise self.error
        return SimpleNamespace(output_parsed=self.output_parsed, usage=self.usage)


def reviewer_with(
    responses: FakeResponses,
    times=(10.0, 10.25),
    model: str = "test-model",
) -> OpenAIReviewer:
    clock_values = iter(times)
    client = SimpleNamespace(responses=responses)
    return OpenAIReviewer(
        model=model,
        api_key="test-key",
        max_retries=0,
        client=client,
        clock=lambda: next(clock_values),
    )


def valid_response_payload() -> dict:
    return {
        "id": "resp_test",
        "created_at": 0.0,
        "model": "gpt-5-mini",
        "object": "response",
        "output": [
            {
                "id": "msg_test",
                "content": [
                    {
                        "annotations": [],
                        "text": valid_review().model_dump_json(),
                        "type": "output_text",
                    }
                ],
                "role": "assistant",
                "status": "completed",
                "type": "message",
            }
        ],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
    }


def client_with_transport(handler, *, max_retries: int = 1) -> openai.OpenAI:
    return openai.OpenAI(
        api_key="test-key",
        base_url="https://example.test/v1",
        max_retries=max_retries,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_requests_and_validates_structured_review_with_latency() -> None:
    responses = FakeResponses(output_parsed=valid_review())
    reviewer = reviewer_with(responses)

    result = reviewer.review_patch("diff --git a/a.py b/a.py")

    assert result.review == valid_review()
    assert result.latency_ms == pytest.approx(250)
    assert responses.arguments["model"] == "test-model"
    assert responses.arguments["store"] is False
    assert responses.arguments["text_format"] is ReviewResult
    assert responses.arguments["input"].startswith("diff --git")
    assert reviewer.prompt_version == "review-v2"


def test_records_usage_and_estimates_known_model_cost() -> None:
    usage = SimpleNamespace(
        input_tokens=100,
        input_tokens_details=SimpleNamespace(cached_tokens=20),
        output_tokens=25,
    )
    responses = FakeResponses(output_parsed=valid_review(), usage=usage)

    result = reviewer_with(responses, model="gpt-5-mini").review_patch("patch")

    assert result.input_tokens == 100
    assert result.cached_input_tokens == 20
    assert result.output_tokens == 25
    assert result.estimated_cost_usd == pytest.approx(0.0000705)


def test_handles_missing_usage_and_unknown_pricing_explicitly() -> None:
    no_usage = reviewer_with(FakeResponses(output_parsed=valid_review())).review_patch("patch")
    unknown_pricing = reviewer_with(
        FakeResponses(
            output_parsed=valid_review(),
            usage=SimpleNamespace(
                input_tokens=100,
                input_tokens_details=SimpleNamespace(cached_tokens=0),
                output_tokens=25,
            ),
        )
    ).review_patch("patch")

    assert (no_usage.input_tokens, no_usage.output_tokens) == (None, None)
    assert no_usage.estimated_cost_usd is None
    assert unknown_pricing.estimated_cost_usd is None


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
    responses = FakeResponses(error=openai.OpenAIError("truncated"))

    with pytest.raises(InvalidModelResponse, match="could not be parsed"):
        reviewer_with(responses).review_patch("patch")

    assert responses.calls == 1


def test_retries_rate_limit_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"retry-after-ms": "1"},
                json={"error": {"message": "Slow down", "type": "rate_limit_error"}},
            )
        return httpx.Response(200, json=valid_response_payload())

    with client_with_transport(handler) as client:
        result = OpenAIReviewer(model="gpt-5-mini", api_key="test-key", client=client).review_patch(
            "patch"
        )

    assert result.review == valid_review()
    assert calls == 2


def test_reports_retryable_error_after_retry_exhaustion() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            500,
            headers={"retry-after-ms": "1"},
            json={"error": {"message": "Try again", "type": "server_error"}},
        )

    with (
        client_with_transport(handler, max_retries=2) as client,
        pytest.raises(ModelAPIError, match="Try again"),
    ):
        OpenAIReviewer(
            model="gpt-5-mini", api_key="test-key", max_retries=2, client=client
        ).review_patch("patch")

    assert calls == 3


def test_does_not_retry_non_retryable_bad_request() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            400,
            json={"error": {"message": "Invalid request", "type": "invalid_request_error"}},
        )

    with (
        client_with_transport(handler) as client,
        pytest.raises(ModelAPIError, match="Invalid request"),
    ):
        OpenAIReviewer(model="gpt-5-mini", api_key="test-key", client=client).review_patch("patch")

    assert calls == 1


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


@pytest.mark.parametrize("max_retries", [-1, 3])
def test_rejects_unsafe_retry_limits(max_retries: int) -> None:
    with pytest.raises(ValueError, match="between 0 and 2"):
        OpenAIReviewer(model="model", api_key="key", max_retries=max_retries)


def test_configures_timeout_and_conservative_sdk_retries(monkeypatch) -> None:
    arguments = {}

    def fake_openai(**kwargs):
        arguments.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(openai, "OpenAI", fake_openai)

    reviewer = OpenAIReviewer(model="test-model", api_key="test-key", timeout_seconds=7.5)

    assert arguments == {"api_key": "test-key", "timeout": 7.5, "max_retries": 1}
    assert reviewer.timeout_seconds == 7.5
    assert reviewer.max_retries == 1
