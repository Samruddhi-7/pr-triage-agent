import json
import logging
import os
import random
import time
from typing import Any, Optional

from openai import OpenAI

from pr_triage_agent.storage.db import Database

logger = logging.getLogger(__name__)

REQUESTS_PER_MINUTE = 25

# Llama 3.3 70B Versatile pricing (USD per million tokens)
PRICING: dict[str, dict[str, float]] = {
    "llama-3.3-70b-versatile": {
        "input": 0.59 / 1_000_000,
        "output": 0.79 / 1_000_000,
    },
}

DEFAULT_PRICING = {"input": 0.59 / 1_000_000, "output": 0.79 / 1_000_000}

MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 1.0


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


def _to_openai_messages(
    contents: list[dict],
    system_instruction: Optional[str] = None,
) -> list[dict]:
    messages: list[dict] = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})

    # If first message lacks "parts", assume already OpenAI format
    if contents and "parts" not in contents[0]:
        messages.extend(contents)
        return messages

    call_id_queue: list[str] = []

    for msg in contents:
        role = msg.get("role", "")
        parts = msg.get("parts", [])

        if role == "model":
            role = "assistant"

        if role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict] = []
            for part in parts:
                if "function_call" in part:
                    fc = part["function_call"]
                    call_id = f"call_{len(call_id_queue) + 1}"
                    call_id_queue.append(call_id)
                    tool_calls.append({
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": fc["name"],
                            "arguments": json.dumps(fc.get("args", {})),
                        },
                    })
                elif "text" in part:
                    text_parts.append(part["text"])
            entry: dict[str, Any] = {"role": "assistant"}
            entry["content"] = "\n".join(text_parts) if text_parts else None
            if tool_calls:
                entry["tool_calls"] = tool_calls
            messages.append(entry)

        elif role == "user":
            tool_msgs: list[dict] = []
            text_parts = []
            for part in parts:
                if "function_response" in part:
                    fr = part["function_response"]
                    call_id = (
                        call_id_queue.pop(0)
                        if call_id_queue
                        else f"call_{int(time.time() * 1000)}"
                    )
                    tool_msgs.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(fr.get("response", {})),
                    })
                elif "text" in part:
                    text_parts.append(part["text"])
            messages.extend(tool_msgs)
            if text_parts:
                messages.append({"role": "user", "content": "\n".join(text_parts)})

        else:
            text_parts = [p["text"] for p in parts if "text" in p]
            if text_parts:
                messages.append({"role": role, "content": "\n".join(text_parts)})

    return messages


def _convert_tools(tools: list[dict]) -> list[dict]:
    if not tools:
        return []
    result: list[dict] = []
    for entry in tools:
        fds = entry.get("function_declarations", [])
        for fd in fds:
            result.append({
                "type": "function",
                "function": {
                    "name": fd["name"],
                    "description": fd.get("description", ""),
                    "parameters": fd.get("parameters", {}),
                },
            })
    return result


class GroqClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "llama-3.3-70b-versatile",
        db: Optional[Database] = None,
    ):
        if api_key is None:
            api_key = os.environ.get("GROQ_API_KEY")
            if not api_key:
                raise ValueError(
                    "GROQ_API_KEY must be provided or set in .env"
                )
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        self.model_name = model
        self.rate_limiter = RateLimiter()
        self.db = db

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
    ) -> Optional[str]:
        messages: list[dict] = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        response = self._call_with_retry(
            self.client.chat.completions.create,
            model=self.model_name,
            messages=messages,
        )
        if response is None:
            return None
        self._log_usage(response, "generate")
        return response.choices[0].message.content

    def generate_with_tools(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        system_instruction: Optional[str] = None,
    ) -> Optional[Any]:
        messages: list[dict] = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        groq_tools = _convert_tools(tools)

        response = self._call_with_retry(
            self.client.chat.completions.create,
            model=self.model_name,
            messages=messages,
            tools=groq_tools if groq_tools else None,
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
        messages = _to_openai_messages(contents, system_instruction)
        groq_tools = _convert_tools(tools) if tools else None

        response = self._call_with_retry(
            self.client.chat.completions.create,
            model=self.model_name,
            messages=messages,
            tools=groq_tools if groq_tools else None,
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
            except Exception as e:
                status = getattr(e, "status_code", None) or getattr(
                    getattr(e, "response", None), "status_code", None
                )
                retryable = status is None or status in (429, 500, 502, 503, 504)

                if not retryable or attempt == MAX_RETRIES:
                    logger.error(
                        "%s after %d retries: %s",
                        type(e).__name__,
                        MAX_RETRIES,
                        e,
                    )
                    return None

                delay = BASE_BACKOFF_SECONDS * (2**attempt)
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
                logger.exception("Unexpected Groq API error: %s", e)
                return None
        return None

    def _log_usage(self, response: Any, endpoint: str) -> None:
        if self.db is None:
            return
        try:
            usage = response.usage
            prompt_tokens = usage.prompt_tokens or 0
            completion_tokens = usage.completion_tokens or 0
            total_tokens = usage.total_tokens or 0

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
