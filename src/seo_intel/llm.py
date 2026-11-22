"""Gemini client with a disk cache and cost tracking."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Dict

import httpx

from seo_intel import config


class LLMError(Exception):
    pass


def load_key() -> str:
    """Key from the environment, else the .env file."""
    key = os.environ.get(config.LLM_API_KEY_ENV, "")
    env_file = Path(config.ENV_FILE_NAME)
    if not key and env_file.is_file():
        for line in env_file.read_text().splitlines():
            name, _sep, value = line.partition("=")
            if name.strip() == config.LLM_API_KEY_ENV:
                key = value.strip().strip("'\"")
    return key


class Gemini:
    def __init__(self, cache_dir: Path, seed: int):
        self.key = load_key()
        self.cache_dir = cache_dir
        self.seed = seed
        self.calls = 0
        self.cached_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.max_prompt_tokens = 0
        self.last_error = ""
        self.last_call = 0.0

    @property
    def cost(self) -> float:
        dollars = self.input_tokens * config.LLM_INPUT_PRICE
        dollars += self.output_tokens * config.LLM_OUTPUT_PRICE
        return dollars / 1_000_000

    def usage(self) -> Dict:
        return {
            "model": config.LLM_MODEL, "calls": self.calls, "cached_calls": self.cached_calls,
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "max_prompt_tokens": self.max_prompt_tokens, "cost_usd": round(self.cost, 6),
            "last_error": self.last_error,
        }

    def _post(self, body: Dict) -> Dict:
        url = config.LLM_URL.format(model=config.LLM_MODEL)
        last = "no attempt"
        for attempt in range(config.FETCH_RETRIES + 1):
            # Stay under the per minute call limit
            wait = self.last_call + config.LLM_MIN_GAP_SECONDS - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last_call = time.monotonic()
            try:
                response = httpx.post(
                    url, json=body, headers={"x-goog-api-key": self.key},
                    timeout=config.LLM_TIMEOUT_SECONDS,
                )
            except httpx.HTTPError as exc:
                last = type(exc).__name__
            else:
                if response.status_code == 200:
                    return response.json()
                last = f"HTTP {response.status_code}"
                if response.status_code not in (429, 500, 502, 503, 504):
                    break
            time.sleep(2.0 ** (attempt + 1))
        raise LLMError(last)

    def generate(self, body: Dict) -> Dict:
        """One model call, replayed from cache if seen."""
        body = dict(body)
        body["generationConfig"] = {
            "temperature": config.LLM_TEMPERATURE,
            "seed": self.seed,
            "maxOutputTokens": config.LLM_MAX_OUTPUT_TOKENS,
        }
        text = json.dumps(body, sort_keys=True, ensure_ascii=False)
        name = hashlib.sha256((config.LLM_MODEL + text).encode("utf-8")).hexdigest()
        path = self.cache_dir / f"{name}.json"
        if path.is_file():
            self.cached_calls += 1
            return json.loads(path.read_text(encoding="utf-8"))
        if not self.key:
            raise LLMError("no API key")
        if self.cost >= config.MAX_LLM_COST_USD:
            raise LLMError("cost limit reached")
        result = self._post(body)
        usage = result.get("usageMetadata", {})
        prompt_tokens = usage.get("promptTokenCount", 0)
        self.calls += 1
        self.input_tokens += prompt_tokens
        self.output_tokens += usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
        self.max_prompt_tokens = max(self.max_prompt_tokens, prompt_tokens)
        if prompt_tokens > config.MAX_LLM_INPUT_TOKENS:
            raise LLMError("prompt went over the token cap")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, sort_keys=True, ensure_ascii=False), encoding="utf-8")
        return result
