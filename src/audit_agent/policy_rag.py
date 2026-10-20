"""Targeted retrieval (BM25) of binding policy clauses for each finding.

Citations always resolve to a clause parsed from the actual policy PDF (file + page + rule id),
and the excerpt is the verbatim clause text.
"""
from __future__ import annotations

import re

from rank_bm25 import BM25Okapi

from .models import Citation, PolicyClause

ISSUE_QUERIES = {
    "PRICE_VARIANCE": "flag absolute total variance tolerance",
    "OVERQUOTE": "flag absolute total variance tolerance expected total",
    "UNDERQUOTE": "underquotes identified not automatically rejected",
    "FINISH_NOT_ON_PO": "rhodium finishing charge only when PO specifies rhodium",
    "FINISH_OMITTED": "rhodium finishing charge only when PO specifies rhodium",
    "SETTING_COUNT_MISMATCH": "setting rate charged for every stone setting finished unit",
    "UNIT_BASIS_MISMATCH": "earrings quantity measured in pairs one pair finished unit labor",
    "AMBIGUOUS_UNIT": "earrings quantity measured in pairs indeterminate units NEEDS_REVIEW",
    "UNIT_MISSING": "indeterminate units NEEDS_REVIEW do not invent value",
    "LABOR_MULTIPLIED": "labor applied once per finished unit",
    "STALE_RATE_SUSPECTED": "rate-card applicability determined by quotation date not PO date",
    "RATE_CHANGE_NOTICE_IGNORED": "rate-card applicability determined by quotation date not PO date delivery date",
    "NO_ELIGIBLE_RATE": "indeterminate rates NEEDS_REVIEW do not invent a value",
    "AMBIGUOUS_RATE": "indeterminate rates NEEDS_REVIEW do not invent a value",
    "MISSING_QUOTE_DATE": "rate-card applicability determined by quotation date indeterminate",
    "LOW_MATCH_CONFIDENCE": "matching indeterminate NEEDS_REVIEW",
    "MATCH_DISAGREEMENT": "matching indeterminate NEEDS_REVIEW",
    "NO_PO_MATCH": "matching indeterminate NEEDS_REVIEW",
    "SOURCE_CONFLICT": "missing evidence indeterminate NEEDS_REVIEW",
    "UNAUTHORIZED_SURCHARGE": "expected total per-unit cost ordered quantity metal setting labor handling",
    "PROMPT_INJECTION_DETECTED": "no quotation automatically approved reviewer decision",
    "WITHIN_TOLERANCE": "no quotation automatically approved reviewer decision justification",
}
CORE_CALC_QUERY = "metal cost grams grade setting labor handling total ROUND_HALF_UP"


def _tok(t: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", t.lower())


class PolicyIndex:
    def __init__(self, clauses: list[PolicyClause]):
        self.clauses = clauses
        self._bm25 = BM25Okapi([_tok(f"{c.title} {c.title} {c.text}") for c in clauses]) if clauses else None

    def search(self, query: str, k: int = 3) -> list[Citation]:
        if not self._bm25:
            return []
        scores = self._bm25.get_scores(_tok(query))
        ranked = sorted(range(len(self.clauses)), key=lambda i: -scores[i])[:k]
        return [self._cite(i, float(scores[i])) for i in ranked if scores[i] > 0]

    def _cite(self, i: int, score: float) -> Citation:
        c = self.clauses[i]
        return Citation(rule_id=c.rule_id, title=c.title, source_file=c.source_file, page=c.page, excerpt=c.text, score=round(score, 3))

    def for_issues(self, codes: list[str], k_per_code: int = 1, limit: int = 4) -> list[Citation]:
        seen: dict[str, Citation] = {}
        queries = [ISSUE_QUERIES[c] for c in codes if c in ISSUE_QUERIES] + [CORE_CALC_QUERY]
        for q in queries:
            for cit in self.search(q, k=k_per_code):
                if cit.rule_id not in seen:
                    seen[cit.rule_id] = cit
            if len(seen) >= limit:
                break
        return list(seen.values())
