"""Effective-date rate selection (policy Rule 1: quotation date governs)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .models import RateCard
from .normalize import norm_vendor


@dataclass
class RateSelection:
    rate: RateCard | None
    code: str | None  # None when exactly one eligible rate found
    reason: str
    considered: list[str]


def select_rate(rates: list[RateCard], vendor: str | None, grade: str | None, category: str | None,
                on_date: date | None) -> RateSelection:
    if on_date is None:
        return RateSelection(None, "MISSING_QUOTE_DATE", "Quote date unknown; rate applicability cannot be determined.", [])
    if not grade:
        return RateSelection(None, "METAL_GRADE_UNKNOWN", "Metal grade could not be determined from the PO line.", [])
    v = norm_vendor(vendor)
    vendor_rates = [r for r in rates if norm_vendor(r.vendor) == v]
    if not vendor_rates:
        return RateSelection(None, "NO_ELIGIBLE_RATE", f"No rate card for vendor '{vendor}'.", [])
    grade_rates = [r for r in vendor_rates if r.metal.upper() == grade.upper()]
    considered = [r.rate_id for r in grade_rates]
    if not grade_rates:
        return RateSelection(None, "NO_ELIGIBLE_RATE", f"No {grade} rate card for '{vendor}'.", considered)
    cat = (category or "").strip().lower()
    cat_rates = [r for r in grade_rates if r.category.strip().lower() in {"all", cat}]
    live = [r for r in cat_rates if r.effective_from <= on_date and (r.effective_to is None or on_date <= r.effective_to)]
    if not live:
        spans = ", ".join(f"{r.rate_id} {r.effective_from}..{r.effective_to or 'open'}" for r in cat_rates)
        return RateSelection(None, "NO_ELIGIBLE_RATE", f"No {grade} rate effective on {on_date} (cards: {spans}).", considered)
    specific = [r for r in live if r.category.strip().lower() == cat and cat]
    pool = specific or live
    if len(pool) > 1:
        return RateSelection(None, "AMBIGUOUS_RATE",
                             f"{len(pool)} overlapping rates effective on {on_date}: {[r.rate_id for r in pool]}.", considered)
    r = pool[0]
    return RateSelection(r, None, f"{r.rate_id} effective {r.effective_from}..{r.effective_to or 'open'} covers quote date {on_date}.", considered)
