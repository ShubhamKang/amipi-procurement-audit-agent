"""AI service: the only place the pipeline talks to a model. Every output is validated before use.

Validation layers
* schema      - pydantic structured output (provider level)
* match       - chosen key must be one of the offered candidates; confidence threshold
* extraction  - every extracted value must appear verbatim in the source page (grounding)
* explanation - every money amount must come from the computed facts; no approval claims
Failures are recorded as events and the deterministic fallback is used (graceful degradation).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from ..config import LLMSettings, Settings
from ..ingest.parsing import to_date, to_decimal, to_text
from ..ingest.pdf import PageText
from ..models import Evidence, Quote, QuoteRecord
from ..security import canonical, detect_injection, output_claims_approval, wrap_untrusted
from . import prompts
from .providers import LLMError, LLMUnavailable, Provider, make_provider
from .schemas import ExplanationBatch, ExtractionResult, MatchDecision

_MONEY = re.compile(r"(?<![\w.])-?\$?\d{1,3}(?:,\d{3})*\.\d{2}(?!\d)|(?<![\w.])-?\$?\d+\.\d{2}(?!\d)")


@dataclass
class AIEvent:
    task: str
    status: str  # ok | fallback | rejected | error | disabled
    detail: str
    ref: str = ""
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


class AIService:
    def __init__(self, llm: LLMSettings, settings: Settings, provider: Provider | None = None, max_failures: int = 3):
        self.llm, self.settings = llm, settings
        warn = None
        self.provider, warn = (provider, None) if provider else make_provider(llm)
        self.events: list[AIEvent] = []
        if warn:
            self.events.append(AIEvent("init", "fallback", warn))
        self._failures = 0
        self._max_failures = max_failures
        self._tripped = False

    # ------------------------------------------------------------------ infra
    @property
    def name(self) -> str:
        return self.provider.name

    @property
    def enabled(self) -> bool:
        return self.provider.name != "disabled" and not self._tripped

    def _call(self, task: str, system: str, user: str, schema, payload: dict[str, Any], ref: str):
        if not self.enabled:
            self.events.append(AIEvent(task, "disabled", "LLM disabled or circuit open; deterministic fallback used", ref))
            return None
        try:
            out = self.provider.generate(task, system, user, schema, payload)
            self._failures = 0
            return out
        except LLMUnavailable as e:
            self._tripped = True
            self.events.append(AIEvent(task, "error", f"{e} (LLM disabled for rest of run)", ref))
        except LLMError as e:
            self._failures += 1
            self.events.append(AIEvent(task, "error", str(e), ref))
            if self._failures >= self._max_failures:
                self._tripped = True
                self.events.append(AIEvent(task, "error", f"circuit opened after {self._failures} consecutive failures", ref))
        except Exception as e:  # never let model problems crash an audit
            self._failures += 1
            self.events.append(AIEvent(task, "error", f"{type(e).__name__}: {str(e)[:200]}", ref))
        return None

    # ------------------------------------------------------------------ match
    def match(self, q: Quote, candidates: list[dict]) -> MatchDecision | None:
        quote_text = f"Quote {q.quote_id} | vendor {q.vendor} | PO {q.po_id} | line {q.supplier_line} | SKU {q.vendor_sku or 'not provided'} | item: {q.description} | qty {q.qty} {q.unit}"
        cand_txt = "\n".join(f"- {c['po_line_key']}: {c['description']} (category {c.get('category')}, SKU {c.get('product_id')})" for c in candidates)
        user = prompts.MATCH_USER.format(quote_block=wrap_untrusted(quote_text, q.quote_id, self.settings), candidates=cand_txt)
        payload = {"quote_description": q.description or "", "candidates": candidates}
        out = self._call("match", prompts.MATCH_SYSTEM, user, MatchDecision, payload, q.quote_id)
        if out is None:
            return None
        keys = {c["po_line_key"] for c in candidates}
        if out.po_line_key is not None and out.po_line_key not in keys:
            self.events.append(AIEvent("match", "rejected", f"model returned unknown key {out.po_line_key!r}", q.quote_id))
            return MatchDecision(po_line_key=None, confidence=0.0, rationale="rejected: key not among candidates")
        self.events.append(AIEvent("match", "ok", f"{out.po_line_key} @ {out.confidence:.2f}", q.quote_id))
        return out

    # ------------------------------------------------------------------ extract
    def extract(self, page: PageText) -> list[QuoteRecord]:
        text = "\n".join(page.lines)
        ref = f"{page.source_file} p{page.page}"
        if detect_injection(text, self.settings):
            self.events.append(AIEvent("extract", "rejected", "page contains embedded instructions; quarantined, not sent to model", ref))
            return []
        user = prompts.EXTRACT_USER.format(page_block=wrap_untrusted(text, ref, self.settings))
        out: ExtractionResult | None = self._call("extract", prompts.EXTRACT_SYSTEM, user, ExtractionResult, {"text": text}, ref)
        if out is None:
            return []
        haystack = canonical(text).lower()
        recs: list[QuoteRecord] = []
        for ln in out.lines:
            rec, dropped = self._ground(ln.model_dump(), haystack, page)
            if rec is None:
                self.events.append(AIEvent("extract", "rejected", f"ungrounded quote_id {ln.quote_id!r} (hallucination)", ref))
                continue
            if dropped:
                self.events.append(AIEvent("extract", "rejected", f"{rec.quote_id}: dropped ungrounded fields {dropped}", ref))
            recs.append(rec)
        self.events.append(AIEvent("extract", "ok", f"{len(recs)} grounded line(s) of {len(out.lines)}", ref))
        return recs

    @staticmethod
    def _grounded(value: str | None, haystack: str) -> bool:
        if value is None:
            return True
        v = canonical(str(value)).lower().strip()
        if not v:
            return True
        return v in haystack or v.replace(",", "") in haystack.replace(",", "")

    def _ground(self, d: dict, haystack: str, page: PageText) -> tuple[QuoteRecord | None, list[str]]:
        if not d.get("quote_id") or not self._grounded(d["quote_id"], haystack):
            return None, []
        dropped = [k for k, v in d.items() if k != "quote_id" and v is not None and not self._grounded(v, haystack)]
        for k in dropped:
            d[k] = None
        errors: list[str] = [f"{k}: not found verbatim in source (AI output discarded)" for k in dropped]

        def soft(fn, v, name):
            if v is None:
                return None
            try:
                return fn(v, name)
            except ValueError as e:
                errors.append(str(e))
                return None

        if d.get("total") is None:
            errors.append("quoted_total: not extracted")
        return QuoteRecord(
            origin="llm_pdf", quote_id=d["quote_id"].upper(), vendor=None, quote_date=soft(to_date, d.get("quote_date"), "quote_date"),
            po_id=to_text(d.get("po_id")), supplier_line=to_text(d.get("supplier_line")), vendor_sku=to_text(d.get("sku")),
            description=to_text(d.get("description")), qty=soft(to_decimal, d.get("qty"), "qty"),
            unit=(to_text(d.get("unit")) or "").lower() or None, quoted_total=soft(to_decimal, d.get("total"), "quoted_total"),
            currency=(to_text(d.get("currency")) or "USD").upper(), parse_errors=errors,
            evidence=Evidence(source_file=page.source_file, sheet_or_page=f"page {page.page}", row_or_line="AI-extracted (grounded)",
                              quote=f"{d['quote_id']} ... total {d.get('total')}"),
        ), dropped

    # ------------------------------------------------------------------ explain
    def explain(self, facts: list[dict[str, Any]], clauses_text: str) -> dict[str, tuple[str, str]]:
        """Return {quote_id: (text, source)}. Falls back to the deterministic template per finding."""
        result = {f["quote_id"]: (f["template"], "template") for f in facts}
        if not facts:
            return result
        for i in range(0, len(facts), 15):
            chunk = facts[i:i + 15]
            slim = [{k: v for k, v in f.items() if k not in {"template", "allowed_amounts"}} for f in chunk]
            user = prompts.EXPLAIN_USER.format(facts=json.dumps(slim, indent=1, default=str), clauses=clauses_text)
            out: ExplanationBatch | None = self._call("explain", prompts.EXPLAIN_SYSTEM, user, ExplanationBatch, {"facts": chunk}, f"batch {i // 15 + 1}")
            if out is None:
                continue
            by_id = {f["quote_id"]: f for f in chunk}
            for item in out.items:
                f = by_id.get(item.quote_id)
                if not f:
                    continue
                ok, why = self.validate_explanation(item.text, f["allowed_amounts"])
                if ok:
                    src = "template (mock provider)" if self.provider.name == "mock" else self.provider.name
                    result[item.quote_id] = (item.text.strip(), src)
                else:
                    self.events.append(AIEvent("explain", "rejected", why, item.quote_id))
        n_ai = sum(1 for v in result.values() if v[1] != "template")
        self.events.append(AIEvent("explain", "ok" if n_ai else "fallback", f"{n_ai}/{len(facts)} AI explanations accepted"))
        return result

    @staticmethod
    def validate_explanation(text: str, allowed: set[Decimal]) -> tuple[bool, str]:
        if output_claims_approval(text):
            return False, "explanation asserts approval (not permitted)"
        for m in _MONEY.findall(text):
            v = Decimal(m.replace("$", "").replace(",", ""))
            if abs(v) not in allowed:
                return False, f"hallucinated amount {m} not present in computed facts"
        return True, ""
