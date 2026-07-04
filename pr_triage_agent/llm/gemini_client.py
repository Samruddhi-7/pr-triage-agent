import os
import random
import time
import logging
from typing import Any, Optional

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from pr_triage_agent.storage.db import Database

logger = logging.getLogger(__name__)

# Gemini free tier rate limit (requests per minute)
REQUESTS_PER_MINUTE = 15

# Gemini 2.5 Flash pricing (USD per token)
# Published rates: $0.075/1M input, $0.30/1M output
PRICING: dict[str, dict[str, float]] = {
    "gemini-2.5-flash": {
        "input": 0.075 / 1_000_000,
        "output": 0.30 / 1_000_000,
    },
    "gemini-2.5-flash-lite": {
        "input": 0.03 / 1_000_000,
        "output": 0.15 / 1_000_000,
    },
}

DEFAULT_PRICING = {"input": 0.075 / 1_000_000, "output": 0.30 / 1_000_000}

# Retry configuration
MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 1.0
RETRYABLE_EXCEPTIONS = (
    google_exceptions.ResourceExhausted,
    google_exceptions.InternalServerError,
    google_exceptions.ServiceUnavailable,
    google_exceptions.GatewayTimeout,
)


class RateLimiter:
    def __init__(self, requests_per_minute: float = REQUESTS_PER_MINUTE):
        self.min_interval = 60.0 / requests_per_minute
        self._last_call = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call = time.monotonic()


class GeminiClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-2.5-flash",
        db: Optional[Database] = None,
    ):
        if api_key is None:
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                raise ValueError(
                    "GEMINI_API_KEY must be provided or set in .env"
                )
        genai.configure(api_key=api_key)
        self.model_name = model
        self._model = genai.GenerativeModel(model)
        self.rate_limiter = RateLimiter()
        self.db = db

    def _model_for(self, *, system_instruction: Optional[str] = None):
        if system_instruction:
            return genai.GenerativeModel(
                self.model_name,
                system_instruction=system_instruction,
            )
        return self._model

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
    ) -> Optional[str]:
        model = self._model_for(system_instruction=system_instruction)
        response = self._call_with_retry(model.generate_content, prompt)
        if response is None:
            return None
        self._log_usage(response, "generate")
        return response.text

    def generate_with_tools(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        system_instruction: Optional[str] = None,
    ) -> Optional[Any]:
        model = self._model_for(system_instruction=system_instruction)
        response = self._call_with_retry(
            model.generate_content, prompt, tools=tools
        )
        if response is None:
            return None
        self._log_usage(response, "generate_with_tools")
        return response

    def generate_with_contents(
        self,
        contents: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
    ) -> Optional[Any]:
        model = self._model_for(system_instruction=system_instruction)
        kwargs: dict[str, Any] = {}
        if tools:
            kwargs["tools"] = tools
        response = self._call_with_retry(
            model.generate_content, contents, **kwargs
        )
        if response is None:
            return None
        self._log_usage(response, "generate_with_contents")
        return response

    def _call_with_retry(self, fn, *args, **kwargs) -> Optional[Any]:
        for attempt in range(MAX_RETRIES + 1):
            try:
                self.rate_limiter.wait()
                return fn(*args, **kwargs)
            except RETRYABLE_EXCEPTIONS as e:
                if attempt == MAX_RETRIES:
                    logger.error(
                        "%s after %d retries: %s",
                        type(e).__name__,
                        MAX_RETRIES,
                        e,
                    )
                    return None
                delay = BASE_BACKOFF_SECONDS * (2 ** attempt)
                delay += random.uniform(0, delay * 0.1)
                logger.warning(
                    "%s (attempt %d/%d), retrying in %.2fs",
                    type(e).__name__,
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                time.sleep(delay)
            except Exception as e:
                logger.exception("Unexpected Gemini API error: %s", e)
                return None
        return None

    def _log_usage(self, response: Any, endpoint: str) -> None:
        if self.db is None:
            return
        try:
            usage = response.usage_metadata
            prompt_tokens = usage.prompt_token_count or 0
            completion_tokens = usage.candidates_token_count or 0
            total_tokens = usage.total_token_count or 0

            pricing = PRICING.get(self.model_name, DEFAULT_PRICING)
            cost = (
                prompt_tokens * pricing["input"]
                + completion_tokens * pricing["output"]
            )

            self.db.log_cost(
                model=self.model_name,
                endpoint=endpoint,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=cost,
            )
        except Exception as e:
            logger.warning("Failed to log usage: %s", e)
