import json
import time
from unittest.mock import MagicMock, patch

import pytest

from pr_triage_agent.llm.groq_client import (
    GroqClient,
    RateLimiter,
    MAX_RETRIES,
    BASE_BACKOFF_SECONDS,
    _convert_tools,
    _to_openai_messages,
)


class TestRateLimiter:
    def test_respects_min_interval(self) -> None:
        limiter = RateLimiter(requests_per_minute=60)
        limiter._last_call = time.monotonic() - 2.0
        start = time.monotonic()
        limiter.wait()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1

    def test_waits_when_called_too_soon(self) -> None:
        limiter = RateLimiter(requests_per_minute=60)
        limiter.wait()
        start = time.monotonic()
        limiter.wait()
        elapsed = time.monotonic() - start
        assert 0.8 <= elapsed <= 1.2


class FakeUsage:
    prompt_tokens = 50
    completion_tokens = 30
    total_tokens = 80


class FakeChoiceMessage:
    content = "fake response"
    tool_calls = None


class FakeChoice:
    message = FakeChoiceMessage()


class FakeResponse:
    choices = [FakeChoice()]

    class Usage:
        prompt_tokens = 50
        completion_tokens = 30
        total_tokens = 80

    usage = Usage()


@pytest.fixture
def mock_db():
    db = MagicMock()
    return db


@pytest.fixture
def mock_openai():
    with patch("pr_triage_agent.llm.groq_client.OpenAI") as mock:
        client_instance = MagicMock()
        mock.return_value = client_instance
        yield client_instance


class TestGroqClient:
    def test_generate_success(self, mock_openai, mock_db) -> None:
        mock_openai.chat.completions.create.return_value = FakeResponse()

        client = GroqClient(api_key="test-key", db=mock_db)
        result = client.generate("hello")

        assert result == "fake response"
        mock_openai.chat.completions.create.assert_called_once()
        args, kwargs = mock_openai.chat.completions.create.call_args
        assert kwargs["model"] == "llama-3.3-70b-versatile"
        assert kwargs["messages"] == [
            {"role": "user", "content": "hello"}
        ]
        mock_db.log_cost.assert_called_once()

    def test_generate_missing_api_key(self) -> None:
        with patch.dict("os.environ", clear=True):
            with pytest.raises(ValueError, match="GROQ_API_KEY"):
                GroqClient()

    def test_generate_with_system_instruction(self, mock_openai, mock_db) -> None:
        mock_openai.chat.completions.create.return_value = FakeResponse()

        client = GroqClient(api_key="test-key", db=mock_db)
        result = client.generate("hello", system_instruction="Be concise")

        assert result == "fake response"
        args, kwargs = mock_openai.chat.completions.create.call_args
        assert kwargs["messages"] == [
            {"role": "system", "content": "Be concise"},
            {"role": "user", "content": "hello"},
        ]

    def test_generate_with_tools(self, mock_openai, mock_db) -> None:
        mock_openai.chat.completions.create.return_value = FakeResponse()

        tools = [{"function_declarations": [{"name": "test_fn"}]}]
        client = GroqClient(api_key="test-key", db=mock_db)
        result = client.generate_with_tools("hello", tools=tools)

        assert result.choices[0].message.content == "fake response"
        args, kwargs = mock_openai.chat.completions.create.call_args
        assert kwargs["tools"] == [
            {"type": "function", "function": {"name": "test_fn", "description": "", "parameters": {}}}
        ]

    def test_generate_with_contents(self, mock_openai, mock_db) -> None:
        mock_openai.chat.completions.create.return_value = FakeResponse()

        contents = [{"role": "user", "parts": [{"text": "hello"}]}]
        client = GroqClient(api_key="test-key", db=mock_db)
        result = client.generate_with_contents(contents=contents)

        assert result.choices[0].message.content == "fake response"
        args, kwargs = mock_openai.chat.completions.create.call_args
        assert len(kwargs["messages"]) == 1
        assert kwargs["messages"][0]["role"] == "user"
        assert kwargs["messages"][0]["content"] == "hello"

    @patch("pr_triage_agent.llm.groq_client.time.sleep")
    def test_retry_on_429_then_succeeds(
        self, mock_sleep, mock_openai, mock_db
    ) -> None:
        from openai import RateLimitError

        exc = RateLimitError(
            "429",
            response=MagicMock(status_code=429),
            body=None,
        )

        good_response = FakeResponse()
        mock_openai.chat.completions.create.side_effect = [
            exc, exc, good_response
        ]

        client = GroqClient(api_key="test-key", db=mock_db)
        result = client.generate("hello")

        assert result == "fake response"
        assert mock_openai.chat.completions.create.call_count == 3

    @patch("pr_triage_agent.llm.groq_client.time.sleep")
    def test_retry_on_429_exhausted(
        self, mock_sleep, mock_openai, mock_db
    ) -> None:
        from openai import RateLimitError

        exc = RateLimitError(
            "429",
            response=MagicMock(status_code=429),
            body=None,
        )

        mock_openai.chat.completions.create.side_effect = [
            exc
        ] * (MAX_RETRIES + 1)

        client = GroqClient(api_key="test-key", db=mock_db)
        result = client.generate("hello")

        assert result is None
        assert mock_openai.chat.completions.create.call_count == MAX_RETRIES + 1

    @patch("pr_triage_agent.llm.groq_client.time.sleep")
    def test_exponential_backoff_used(
        self, mock_sleep, mock_openai, mock_db
    ) -> None:
        from openai import RateLimitError

        exc = RateLimitError(
            "429",
            response=MagicMock(status_code=429),
            body=None,
        )

        mock_openai.chat.completions.create.side_effect = [
            exc, exc, FakeResponse()
        ]

        client = GroqClient(api_key="test-key", db=mock_db)
        client.generate("hello")

        sleep_values = [
            args[0][0] for args in mock_sleep.call_args_list
        ]
        # Backoff sleeps should be ~1s and ~2s (before rate limiter at ~2.4s)
        backoff_sleeps = [s for s in sleep_values if 0.8 <= s <= 2.3]
        assert len(backoff_sleeps) == 2
        assert backoff_sleeps[1] > backoff_sleeps[0]

    def test_logs_cost_to_db(self, mock_openai, mock_db) -> None:
        mock_openai.chat.completions.create.return_value = FakeResponse()

        client = GroqClient(api_key="test-key", db=mock_db)
        client.generate("hello")

        mock_db.log_cost.assert_called_once()
        args, kwargs = mock_db.log_cost.call_args
        assert kwargs["model"] == "llama-3.3-70b-versatile"
        assert kwargs["endpoint"] == "generate"
        assert kwargs["prompt_tokens"] == 50
        assert kwargs["completion_tokens"] == 30
        assert kwargs["total_tokens"] == 80
        expected = 50 * 0.59 / 1_000_000 + 30 * 0.79 / 1_000_000
        assert abs(kwargs["estimated_cost_usd"] - expected) < 1e-10


class TestConvertTools:
    def test_converts_gemini_to_openai_format(self) -> None:
        gemini_tools = [
            {
                "function_declarations": [
                    {
                        "name": "test_fn",
                        "description": "A test function",
                        "parameters": {
                            "type": "object",
                            "properties": {"arg1": {"type": "string"}},
                            "required": ["arg1"],
                        },
                    }
                ]
            }
        ]
        result = _convert_tools(gemini_tools)
        assert result == [
            {
                "type": "function",
                "function": {
                    "name": "test_fn",
                    "description": "A test function",
                    "parameters": {
                        "type": "object",
                        "properties": {"arg1": {"type": "string"}},
                        "required": ["arg1"],
                    },
                },
            }
        ]

    def test_returns_empty_for_no_tools(self) -> None:
        assert _convert_tools([]) == []
        assert _convert_tools(None) == []

    def test_converts_multiple_functions(self) -> None:
        gemini_tools = [
            {
                "function_declarations": [
                    {"name": "fn1", "description": "", "parameters": {"type": "object"}},
                    {"name": "fn2", "description": "", "parameters": {"type": "object"}},
                ]
            }
        ]
        result = _convert_tools(gemini_tools)
        assert len(result) == 2


class TestToOpenaiMessages:
    def test_converts_simple_user_message(self) -> None:
        contents = [{"role": "user", "parts": [{"text": "hello"}]}]
        result = _to_openai_messages(contents)
        assert result == [{"role": "user", "content": "hello"}]

    def test_prepends_system_instruction(self) -> None:
        contents = [{"role": "user", "parts": [{"text": "hi"}]}]
        result = _to_openai_messages(contents, system_instruction="Be concise")
        assert result == [
            {"role": "system", "content": "Be concise"},
            {"role": "user", "content": "hi"},
        ]

    def test_converts_model_role_to_assistant(self) -> None:
        contents = [
            {"role": "model", "parts": [{"text": "I think..."}]}
        ]
        result = _to_openai_messages(contents)
        assert result == [
            {"role": "assistant", "content": "I think..."}
        ]

    def test_converts_function_call_and_response(self) -> None:
        contents = [
            {
                "role": "model",
                "parts": [
                    {
                        "function_call": {
                            "name": "run_linter",
                            "args": {"paths": ["src/main.py"]},
                        }
                    }
                ],
            },
            {
                "role": "user",
                "parts": [
                    {
                        "function_response": {
                            "name": "run_linter",
                            "response": {"result": "ok"},
                        }
                    }
                ],
            },
        ]
        result = _to_openai_messages(contents)
        assert len(result) == 2
        assert result[0]["role"] == "assistant"
        assert result[0]["content"] is None
        assert len(result[0]["tool_calls"]) == 1
        assert result[0]["tool_calls"][0]["function"]["name"] == "run_linter"
        assert result[1]["role"] == "tool"
