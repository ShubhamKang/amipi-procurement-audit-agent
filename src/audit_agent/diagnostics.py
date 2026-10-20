"""What-if diagnostics: deterministic search for a pricing error that exactly reproduces the quoted total.

Results are HYPOTHESES for the reviewer. They never change the expected value or status.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations

from .calc import compute_expected, is_rhodium
from .config import Settings
from .models import POLine, RateCard, ReviewNote
from .normalize import norm_vendor


@dataclass
class Hypothesis:
    codes: list[str]
    text: str
    total: Decimal


def explain_variance(po: POLine, rate: RateCard, quoted: Decimal, rates: list[RateCard], vendor: str | None,
                     notes: list[ReviewNote], s: Settings) -> list[Hypothesis]:
    base = compute_expected(po, rate, s)
    rh = is_rhodium(po.finish, s)
    is_pair_cat = po.category.strip().lower() in s.pair_categories
    # single deviations: (codes, description, kwargs)
    devs: list[tuple[str, str, dict]] = [
        ("FINISH_NOT_ON_PO" if not rh else "FINISH_OMITTED",
         "Rhodium finish charged although PO finish is " + po.finish if not rh else "Rhodium fee omitted although PO specifies Rhodium",
         {"force_finish": not rh}),
        ("SETTING_COUNT_MISMATCH",
         f"settings counted as {po.set_pcs * 2} instead of {po.set_pcs}" + (" (per earring instead of per pair)" if is_pair_cat else ""),
         {"set_pcs": po.set_pcs * 2}),
        ("LABOR_MULTIPLIED", "labor charged twice per unit" + (" (per earring)" if is_pair_cat else ""), {"labor_multiplier": Decimal(2)}),
    ]
    if is_pair_cat:
        devs.append(("UNIT_BASIS_MISMATCH", f"quantity priced as {po.qty * 2} single earrings instead of {po.qty} pairs", {"qty": po.qty * 2}))
    out: list[Hypothesis] = []

    def close(t: Decimal) -> bool:
        return abs(t - quoted) <= s.tolerance

    for n in (1, 2):
        for combo in combinations(devs, n):
            kw: dict = {}
            for _, _, k in combo:
                kw.update(k)
            t = compute_expected(po, rate, s, **kw).total
            if close(t):
                out.append(Hypothesis([c[0] for c in combo], "; ".join(c[1] for c in combo), t))
        if out:
            return out
    # wrong rate card (other period / other vendor) for the same grade
    for r in rates:
        if r.rate_id == rate.rate_id or r.metal != rate.metal:
            continue
        t = compute_expected(po, r, s).total
        if close(t):
            same_vendor = norm_vendor(r.vendor) == norm_vendor(vendor)
            code = "STALE_RATE_SUSPECTED" if same_vendor else "WRONG_VENDOR_RATE"
            out.append(Hypothesis([code], f"quote reproduces with rate {r.rate_id} ({r.effective_from}..{r.effective_to}) instead of {rate.rate_id}", t))
    # surcharge claimed in a note
    for nt in notes:
        for amt in nt.amounts:
            if close(base.total + amt) or close(base.total + amt * po.qty):
                out.append(Hypothesis(["SURCHARGE_INCLUDED"], f"variance equals the USD {amt} surcharge claimed in {nt.note_id}", base.total + amt))
    return out
