"""LLM providers: Gemini (remote), Mock (offline deterministic) and Disabled."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError
from rapidfuzz import fuzz

from ..config import LLMSettings
from ..normalize import attributes
from .schemas import ExplanationBatch, Explanation, ExtractionResult, MatchDecision

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Any provider failure (network, quota, invalid output)."""


class LLMUnavailable(LLMError):
    pass


class Provider(Protocol):
    name: str
    remote: bool

    def generate(self, task: str, system: str, user: str, schema: type[T], payload: dict[str, Any]) -> T: ...


class DisabledProvider:
    name = "disabled"
    remote = False

    def generate(self, task, system, user, schema, payload):
        raise LLMUnavailable("LLM disabled (LLM_PROVIDER=none)")


class MockProvider:
    """Deterministic offline stand-in. Used for tests/CI and when no API key is configured.

    It never sees raw prompts semantics; it works from the structured payload, so results are
    reproducible. Outputs are clearly labelled 'mock' downstream.
    """

    name = "mock"
    remote = False

    def generate(self, task, system, user, schema, payload):
        if task == "match":
            q = attributes(payload["quote_description"])
            best, best_s = None, 0.0
            for c in payload["candidates"]:
                pa = attributes(c["description"])
                s = fuzz.token_set_ratio(q.normalized, pa.normalized) / 100.0
                if q.grade and pa.grade and q.grade != pa.grade:
                    s *= 0.3
                if q.category and pa.category and q.category != pa.category:
                    s *= 0.3
                if q.color and pa.color and q.color != pa.color:
                    s *= 0.5
                if s > best_s:
                    best, best_s = c["po_line_key"], s
            if best is None or best_s < 0.5:
                return schema(po_line_key=None, confidence=round(best_s, 2), rationale="mock: no candidate is similar enough")
            return schema(po_line_key=best, confidence=round(min(best_s, 0.95), 2),
                          rationale="mock: attribute and token similarity (grade, colour, type, stone)")
        if task == "extract":
            return ExtractionResult(lines=[])
        if task == "explain":
            return ExplanationBatch(items=[Explanation(quote_id=f["quote_id"], text=f["template"]) for f in payload["facts"]])
        raise LLMError(f"mock: unknown task {task}")


class GeminiProvider:
    remote = True

    def __init__(self, cfg: LLMSettings):
        if not cfg.api_key:
            raise LLMUnavailable("GEMINI_API_KEY not set")
        from google import genai  # imported lazily so the app runs without the SDK configured
        from google.genai import types

        self._types = types
        self.cfg = cfg
        self.name = f"gemini:{cfg.model}"
        self.client = genai.Client(api_key=cfg.api_key, http_options=types.HttpOptions(timeout=int(cfg.timeout_s * 1000)))
        self._lock = threading.Lock()
        self._last = 0.0

    def _throttle(self):
        with self._lock:
            wait = self.cfg.min_interval_s - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def generate(self, task, system, user, schema, payload):
        from google.genai import errors

        types = self._types
        delay = 2.0
        last_exc: Exception | None = None
        for attempt in range(1, self.cfg.max_retries + 1):
            self._throttle()
            try:
                resp = self.client.models.generate_content(
                    model=self.cfg.model, contents=user,
                    config=types.GenerateContentConfig(system_instruction=system, temperature=0.0,
                                                       response_mime_type="application/json", response_schema=schema))
                text = resp.text or ""
                return schema.model_validate_json(text)
            except ValidationError as e:
                last_exc = LLMError(f"schema validation failed: {e.errors()[:2]}")
            except errors.APIError as e:
                code = getattr(e, "code", None)
                if code in (400, 401, 403, 404):
                    raise LLMUnavailable(f"Gemini API error {code}: {str(e)[:200]}") from e
                last_exc = e  # 429 / 5xx -> retry with backoff
            except Exception as e:  # network / timeout
                last_exc = e
            if attempt < self.cfg.max_retries:
                time.sleep(delay)
                delay *= 2
        raise LLMError(f"Gemini failed after {self.cfg.max_retries} attempts: {str(last_exc)[:200]}")


class CachedProvider:
    """Wraps a remote provider with a response cache (saves free-tier quota, reproducible demos)."""

    def __init__(self, inner: Provider, path: Path | None):
        self.inner, self.path = inner, path
        self.name, self.remote = inner.name, inner.remote
        self._cache: dict[str, Any] = {}
        if path and path.exists():
            try:
                self._cache = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                self._cache = {}
        self.hits = 0

    def generate(self, task, system, user, schema, payload):
        key = hashlib.sha256(json.dumps([self.inner.name, task, system, user, schema.__name__]).encode()).hexdigest()
        if key in self._cache:
            try:
                self.hits += 1
                return schema.model_validate(self._cache[key])
            except ValidationError:
                pass
        out = self.inner.generate(task, system, user, schema, payload)
        self._cache[key] = out.model_dump()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._cache, indent=1))
        return out


def make_provider(cfg: LLMSettings) -> tuple[Provider, str | None]:
    """Return (provider, warning). Falls back to mock if Gemini is requested but unusable."""
    if cfg.provider in {"none", "disabled", "off"}:
        return DisabledProvider(), None
    if cfg.provider == "gemini":
        try:
            return CachedProvider(GeminiProvider(cfg), cfg.cache_path), None
        except LLMUnavailable as e:
            return MockProvider(), f"{e}; falling back to offline mock provider"
        except Exception as e:  # SDK missing / misconfigured
            return MockProvider(), f"Gemini init failed ({type(e).__name__}); falling back to mock"
    return MockProvider(), None


__all__ = ["LLMError", "LLMUnavailable", "MatchDecision", "make_provider", "MockProvider", "DisabledProvider", "GeminiProvider", "CachedProvider"]
