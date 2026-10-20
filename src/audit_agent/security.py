"""Isolation of untrusted vendor content.

Defence in depth against instructions embedded in supplier documents:
1. Detection   - regex patterns from config flag imperative/approval-manipulation phrases.
2. Quarantine  - flagged text is never sent to the LLM; prompts get a neutral placeholder.
3. Spotlighting- all other document text is wrapped in <untrusted_document> tags with tag-breaking
                 characters neutralised, and the system prompt declares it as data only.
4. Capability  - LLM output schemas contain no status/approval/price fields, and the
                 deterministic pipeline is the only writer of statuses. Approval only happens
                 through the human review store.
"""
from __future__ import annotations

import re
import unicodedata

from .config import Settings

_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")


def canonical(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = _ZERO_WIDTH.sub("", t)
    return re.sub(r"\s+", " ", t)


def detect_injection(text: str, s: Settings) -> list[str]:
    """Return matched suspicious phrases (empty list if clean)."""
    t = canonical(text).lower()
    hits: list[str] = []
    for pat in s.injection_patterns:
        for m in re.finditer(pat, t, flags=re.I):
            hits.append(m.group(0).strip())
    return sorted(set(hits))


def neutralise(text: str, limit: int = 4000) -> str:
    """Make document text safe to embed inside prompt delimiters."""
    t = canonical(text)
    t = t.replace("<", "‹").replace(">", "›")  # cannot close/open our tags
    t = t.replace("```", "'''")
    return t[:limit]


def wrap_untrusted(text: str, source: str, s: Settings) -> str:
    hits = detect_injection(text, s)
    if hits:
        return f'<untrusted_document source="{source}">[QUARANTINED: {len(hits)} embedded instruction pattern(s) removed]</untrusted_document>'
    return f'<untrusted_document source="{source}">\n{neutralise(text)}\n</untrusted_document>'


_NEGATED_APPROVAL = re.compile(
    r"\b(not|never|no|cannot|can't|must not|without)\b[\w\s-]{0,30}?\bapprov\w*|\bpending\b[\w\s]{0,20}approv\w*|approv\w*\s+(is|remains)\s+(pending|required)", re.I)


def output_claims_approval(text: str) -> bool:
    """Detect LLM output that asserts approval (the model must never decide approval)."""
    t = _NEGATED_APPROVAL.sub(" ", canonical(text))
    return bool(re.search(r"\b(approved|approve|auto-?approv\w*)\b", t, re.I))
