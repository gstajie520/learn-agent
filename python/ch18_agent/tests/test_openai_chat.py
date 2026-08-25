"""OpenAI 兼容适配器的供应商错误归一化测试。"""

from types import SimpleNamespace

from agent_ch18.adapters.openai_chat import (
    _map_api_status_error,
    _structured_error_identifier,
)
from agent_ch18.core.model import (
    ModelOverloadedError,
    ModelPromptTooLongError,
    ModelRateLimitError,
)


def _fake_error(status: int, body: object, *, retry_after: str | None = None) -> object:
    headers = {} if retry_after is None else {"retry-after": retry_after}
    return SimpleNamespace(
        status_code=status,
        body=body,
        request_id="req-test",
        response=SimpleNamespace(headers=headers),
    )


def test_structured_error_identifier_supports_nested_provider_body() -> None:
    assert _structured_error_identifier({"error": {"code": "context_length_exceeded"}}) == (
        "context_length_exceeded"
    )
    assert _structured_error_identifier({"type": "rate_limit"}) == "rate_limit"
    assert _structured_error_identifier({"message": "仅有文本"}) is None


def test_maps_rate_limit_with_retry_after_to_typed_error() -> None:
    mapped = _map_api_status_error(
        _fake_error(429, {"error": {"code": "rate_limit"}}, retry_after="2")
    )  # type: ignore[arg-type]
    assert isinstance(mapped, ModelRateLimitError)
    assert mapped.retry_after == "2"
    assert mapped.request_id == "req-test"


def test_maps_overload_and_prompt_too_long_errors() -> None:
    overload = _map_api_status_error(_fake_error(529, {"error": {"type": "overloaded"}}))  # type: ignore[arg-type]
    too_long = _map_api_status_error(
        _fake_error(400, {"error": {"code": "context_length_exceeded"}})
    )  # type: ignore[arg-type]
    assert isinstance(overload, ModelOverloadedError)
    assert isinstance(too_long, ModelPromptTooLongError)


def test_unknown_status_is_left_for_caller_to_handle() -> None:
    assert _map_api_status_error(_fake_error(500, {"error": {"code": "server_error"}})) is None  # type: ignore[arg-type]
