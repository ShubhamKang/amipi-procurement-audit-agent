"""Configuration: audit rules come from config/policy.yaml, runtime/LLM settings from env."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_DOWN, ROUND_UP, Decimal
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = ROOT / "config" / "policy.yaml"

ROUNDING_MODES = {
    "ROUND_HALF_UP": ROUND_HALF_UP,
    "ROUND_HALF_EVEN": ROUND_HALF_EVEN,
    "ROUND_UP": ROUND_UP,
    "ROUND_DOWN": ROUND_DOWN,
}


@dataclass(frozen=True)
class Settings:
    """Audit rule settings (mirrors the binding procurement policy)."""

    tolerance: Decimal
    rounding_mode: str
    money_places: int
    round_each_component: bool
    rate_selection_date: str
    rhodium_values: tuple[str, ...]
    pair_categories: tuple[str, ...]
    piece_units: tuple[str, ...]
    pair_units: tuple[str, ...]
    auto_accept_score: float
    min_margin: float
    llm_min_confidence: float
    p1_abs_variance: Decimal
    p2_abs_variance: Decimal
    injection_patterns: tuple[str, ...]
    config_hash: str

    @property
    def rounding(self) -> str:
        return ROUNDING_MODES[self.rounding_mode]

    @property
    def quantum(self) -> Decimal:
        return Decimal(1).scaleb(-self.money_places)


def _lower_tuple(values: Any) -> tuple[str, ...]:
    return tuple(str(v).strip().lower() for v in (values or []))


def settings_from_dict(raw: dict[str, Any]) -> Settings:
    mode = str(raw.get("rounding_mode", "ROUND_HALF_UP")).upper()
    if mode not in ROUNDING_MODES:
        raise ValueError(f"Unsupported rounding_mode {mode!r}; use one of {sorted(ROUNDING_MODES)}")
    sel = str(raw.get("rate_selection_date", "quote_date"))
    if sel not in {"quote_date", "po_due_date"}:
        raise ValueError("rate_selection_date must be 'quote_date' or 'po_due_date'")
    finish = raw.get("finish", {}) or {}
    units = raw.get("units", {}) or {}
    matching = raw.get("matching", {}) or {}
    prio = raw.get("priority", {}) or {}
    sec = raw.get("security", {}) or {}
    digest = hashlib.sha256(yaml.safe_dump(raw, sort_keys=True).encode()).hexdigest()[:12]
    return Settings(
        tolerance=Decimal(str(raw.get("tolerance_usd", "0.01"))),
        rounding_mode=mode,
        money_places=int(raw.get("money_places", 2)),
        round_each_component=bool(raw.get("round_each_component", True)),
        rate_selection_date=sel,
        rhodium_values=_lower_tuple(finish.get("rhodium_values", ["rhodium"])),
        pair_categories=_lower_tuple(units.get("pair_categories", ["earrings"])),
        piece_units=_lower_tuple(units.get("piece_units", ["piece", "pcs", "pc", "unit", "each"])),
        pair_units=_lower_tuple(units.get("pair_units", ["pair", "pairs"])),
        auto_accept_score=float(matching.get("auto_accept_score", 0.8)),
        min_margin=float(matching.get("min_margin", 0.1)),
        llm_min_confidence=float(matching.get("llm_min_confidence", 0.7)),
        p1_abs_variance=Decimal(str(prio.get("p1_abs_variance_usd", "50"))),
        p2_abs_variance=Decimal(str(prio.get("p2_abs_variance_usd", "0.01"))),
        injection_patterns=tuple(sec.get("injection_patterns", []) or []),
        config_hash=digest,
    )


def load_settings(path: str | Path | None = None, overrides: dict[str, Any] | None = None) -> Settings:
    """Load audit settings from YAML, optionally applying top-level overrides (used by UI/tests)."""
    p = Path(path) if path else DEFAULT_POLICY_PATH
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if overrides:
        raw = {**raw, **overrides}
    return settings_from_dict(raw)


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    api_key: str | None
    model: str
    timeout_s: float
    max_retries: int
    min_interval_s: float
    cache_path: Path | None
    explain: bool

    @property
    def remote_enabled(self) -> bool:
        return self.provider == "gemini" and bool(self.api_key)


def load_llm_settings(provider_override: str | None = None) -> LLMSettings:
    load_dotenv(ROOT / ".env", override=False)
    provider = (provider_override or os.getenv("LLM_PROVIDER", "mock")).strip().lower()
    cache = os.getenv("LLM_CACHE_PATH", str(ROOT / "runs" / "llm_cache.json"))
    return LLMSettings(
        provider=provider,
        api_key=os.getenv("GEMINI_API_KEY") or None,
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite"),
        timeout_s=float(os.getenv("LLM_TIMEOUT_S", "30")),
        max_retries=int(os.getenv("LLM_MAX_RETRIES", "3")),
        min_interval_s=float(os.getenv("LLM_MIN_INTERVAL_S", "4.5")),
        cache_path=Path(cache) if cache else None,
        explain=os.getenv("LLM_EXPLAIN", "1") not in {"0", "false", "False"},
    )


def default_data_dir() -> Path:
    load_dotenv(ROOT / ".env", override=False)
    d = Path(os.getenv("DATA_DIR", "Data"))
    return d if d.is_absolute() else ROOT / d


def default_db_path() -> Path:
    load_dotenv(ROOT / ".env", override=False)
    d = Path(os.getenv("DB_PATH", "runs/audit.db"))
    return d if d.is_absolute() else ROOT / d
