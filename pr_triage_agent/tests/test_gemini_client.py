import time
from unittest.mock import MagicMock, patch

import pytest

from pr_triage_agent.llm.gemini_client import (
    GeminiClient,
    RateLimiter,
    REQUESTS_PER_MINUTE,
    MAX_RETRIES,
    BASE_BACKOFF_SECONDS,
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


class FakeUsageMetadata:
    prompt_token_count = 50
    candidates_token_count = 30
    total_token_count = 80


class FakeResponse:
    text = "fake response"
    usage_metadata = FakeUsageMetadata()


@pytest.fixture
def mock_db():
    db = MagicMock()
    return db


@pytest.fixture
def mock_genai():
    with patch("pr_triage_agent.llm.gemini_client.genai") as mock:
        yield mock


class TestGeminiClient:
    def test_generate_success(self, mock_genai, mock_db) -> None:
        mock_model = MagicMock()
        mock_model.generate_content.return_value = FakeResponse()
        mock_genai.GenerativeModel.return_value = mock_model

        client = GeminiClient(api_key="test-key", db=mock_db)
        result = client.generate("hello")

        assert result == "fake response"
        mock_model.generate_content.assert_called_once_with("hello")
        mock_db.log_cost.assert_called_once()

    def test_generate_missing_api_key(self) -> None:
        with patch.dict("os.environ", clear=True):
            with pytest.raises(ValueError, match="GEMINI_API_KEY"):
                GeminiClient()

    def test_generate_with_tools(self, mock_genai, mock_db) -> None:
        mock_model = MagicMock()
        mock_model.generate_content.return_value = FakeResponse()
        mock_genai.GenerativeModel.return_value = mock_model

        tools = [{"function_declarations": [{"name": "test_fn"}]}]
        client = GeminiClient(api_key="test-key", db=mock_db)
        result = client.generate_with_tools("hello", tools=tools)

        assert result.text == "fake response"
        mock_model.generate_content.assert_called_once_with(
            "hello", tools=tools
        )

    @patch("pr_triage_agent.llm.gemini_client.time.sleep")
    def test_retry_on_429_then_succeeds(
        self, mock_sleep, mock_genai, mock_db
    ) -> None:
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        exc = __import__(
            "google.api_core.exceptions", fromlist=["ResourceExhausted"]
        ).ResourceExhausted("429")

        mock_model.generate_content.side_effect = [exc, exc, FakeResponse()]

        client = GeminiClient(api_key="test-key", db=mock_db)
        result = client.generate("hello")

        assert result == "fake response"
        assert mock_model.generate_content.call_count == 3

    @patch("pr_triage_agent.llm.gemini_client.time.sleep")
    def test_retry_on_429_exhausted(
        self, mock_sleep, mock_genai, mock_db
    ) -> None:
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        exc = __import__(
            "google.api_core.exceptions", fromlist=["ResourceExhausted"]
        ).ResourceExhausted("429")

        mock_model.generate_content.side_effect = [exc] * (MAX_RETRIES + 1)

        client = GeminiClient(api_key="test-key", db=mock_db)
        result = client.generate("hello")

        assert result is None
        assert mock_model.generate_content.call_count == MAX_RETRIES + 1

    @patch("pr_triage_agent.llm.gemini_client.time.sleep")
    def test_exponential_backoff_used(
        self, mock_sleep, mock_genai, mock_db
    ) -> None:
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        exc = __import__(
            "google.api_core.exceptions", fromlist=["ResourceExhausted"]
        ).ResourceExhausted("429")

        mock_model.generate_content.side_effect = [exc, exc, FakeResponse()]

        client = GeminiClient(api_key="test-key", db=mock_db)
        client.generate("hello")

        backoff_sleeps = [
            args[0][0]
            for args in mock_sleep.call_args_list
            if args[0][0] < 3.0
        ]
        assert len(backoff_sleeps) == 2
        assert backoff_sleeps[1] > backoff_sleeps[0]
        assert BASE_BACKOFF_SECONDS <= backoff_sleeps[0] <= BASE_BACKOFF_SECONDS * 2
        assert BASE_BACKOFF_SECONDS * 2 <= backoff_sleeps[1] <= BASE_BACKOFF_SECONDS * 4

    def test_system_instruction_creates_new_model(
        self, mock_genai, mock_db
    ) -> None:
        default_model = MagicMock()
        instructed_model = MagicMock()
        mock_genai.GenerativeModel.side_effect = [
            default_model,
            instructed_model,
        ]

        client = GeminiClient(api_key="test-key", db=mock_db)
        model = client._model_for(system_instruction="Be concise")
        assert model is instructed_model
        assert model is not client._model
        mock_genai.GenerativeModel.assert_called_with(
            "gemini-2.5-flash", system_instruction="Be concise"
        )

    def test_logs_cost_to_db(self, mock_genai, mock_db) -> None:
        mock_model = MagicMock()
        mock_model.generate_content.return_value = FakeResponse()
        mock_genai.GenerativeModel.return_value = mock_model

        client = GeminiClient(api_key="test-key", db=mock_db)
        client.generate("hello")

        mock_db.log_cost.assert_called_once_with(
            model="gemini-2.5-flash",
            endpoint="generate",
            prompt_tokens=50,
            completion_tokens=30,
            total_tokens=80,
            estimated_cost_usd=(
                50 * 0.075 / 1_000_000 + 30 * 0.30 / 1_000_000
            ),
        )
