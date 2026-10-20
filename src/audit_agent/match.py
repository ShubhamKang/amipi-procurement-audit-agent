"""Deterministic candidate scoring for quote -> PO line matching.

The rules score is explainable (each signal is listed). Hard attribute conflicts (metal grade,
gold colour, category, gemstone) make a candidate untrustworthy regardless of score.
Low-confidence cases are delegated to the AI matcher (see pipeline) or sent to NEEDS_REVIEW.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz

from .models import POLine, Quote
from .normalize import attributes, line_number


@dataclass
class Candidate:
    po: POLine
    score: float
    signals: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"po_line_key": self.po.key, "score": round(self.score, 3), "signals": self.signals,
                "conflicts": self.conflicts, "description": self.po.description, "product_id": self.po.product_id}


def _attr_conflicts(q_desc: str | None, po: POLine) -> tuple[list[str], list[str], float]:
    qa = attributes(q_desc)
    pa = attributes(po.description, po.category)
    conflicts, agree = [], []
    checks = 0
    for name, qv, pv in (("grade", qa.grade, pa.grade), ("colour", qa.color, pa.color), ("category", qa.category, pa.category)):
        if qv and pv:
            checks += 1
            if qv != pv:
                conflicts.append(f"{name} {qv} vs PO {pv}")
            else:
                agree.append(f"{name} {qv}")
    if qa.stones and pa.stones:
        checks += 1
        if qa.stones.isdisjoint(pa.stones):
            conflicts.append(f"stone {sorted(qa.stones)} vs PO {sorted(pa.stones)}")
        else:
            agree.append(f"stone {sorted(qa.stones & pa.stones)}")
    frac = (len(agree) / checks) if checks else 0.0
    return conflicts, agree, frac


def score_candidates(q: Quote, po_lines: list[POLine]) -> list[Candidate]:
    out: list[Candidate] = []
    q_line = line_number(q.supplier_line)
    q_desc = attributes(q.description).normalized
    for po in po_lines:
        sig: list[str] = []
        s = 0.0
        sku_hit = bool(q.vendor_sku and po.product_id and q.vendor_sku.strip().upper() == po.product_id.strip().upper())
        if sku_hit:
            s += 0.40
            sig.append(f"SKU {po.product_id} exact")
        same_po = bool(q.po_id and q.po_id.upper() == po.po_id.upper())
        if same_po:
            s += 0.15
            sig.append(f"PO {po.po_id}")
        if same_po and q_line is not None and q_line == line_number(po.line_id):
            s += 0.10
            sig.append(f"supplier line {q.supplier_line} ~ {po.line_id}")
        sim = fuzz.token_set_ratio(q_desc, attributes(po.description).normalized) / 100.0
        conflicts, agree, frac = _attr_conflicts(q.description, po)
        s += 0.35 * (0.5 * sim + 0.5 * frac)
        sig.append(f"description similarity {sim:.2f}")
        if agree:
            sig.append("attributes agree: " + ", ".join(agree))
        if q.po_id and not same_po:
            conflicts.append(f"quote PO {q.po_id} vs {po.po_id}")
        if q.vendor_sku and po.product_id and not sku_hit:
            conflicts.append(f"SKU {q.vendor_sku} vs PO {po.product_id}")
        out.append(Candidate(po, min(s, 1.0), sig, conflicts))
    out.sort(key=lambda c: (-c.score, c.po.key))
    return out
