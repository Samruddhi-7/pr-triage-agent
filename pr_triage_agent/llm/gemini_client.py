import time
from typing import Optional

import google.generativeai as genai


class RateLimiter:
    def __init__(self, requests_per_minute: int = 10):
        self.rpm = requests_per_minute
        self.min_interval = 60.0 / self.rpm
        self._last_call: float = 0.0

    def wait(self) -> None:
        elapsed = time.time() - self._last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call = time.time()


class GeminiClient:
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model)
        self.rate_limiter = RateLimiter()

    def generate(self, prompt: str, max_retries: int = 3) -> Optional[str]:
        raise NotImplementedError("Phase 1")

    def generate_cheap(self, prompt: str) -> Optional[str]:
        raise NotImplementedError("Phase 1")
