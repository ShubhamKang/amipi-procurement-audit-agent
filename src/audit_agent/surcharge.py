"""Pure surcharge rule: Nova 18K-gold bracelet-family per-unit surcharge.

AI-independent and IO-free. Takes normalized primitives + Settings only; no
pipeline, no file access, no network. Mirrors the `is_rhodium` predicate style.

Rule (see docs/surcharge-change/requirements.md):
  A flat per-unit surcharge applies to 18K-gold products in the bracelet family,
  effective `surcharge_effective_date` (inclusive), ONLY when BOTH the quotation
  date AND the linked PO date are on or after the effective date.
  Surcharge total = amount_usd * quantity when eligible, else 0.00.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .config import Settings


@dataclass(frozen=True)
class SurchargeDecision:
    """Structured, evidence-bearing eligibility result (no AI involved)."""

    eligible: bool
    reason: str


def _norm_metal(material: str | None) -> str:
    """Upper-case and collapse surrounding whitespace for prefix comparison."""
    return " ".join((material or "").strip().upper().split())


def _metal_qualifies(material: str | None, s: Settings) -> bool:
    """True if the normalized metal matches any configured prefix at a boundary.

    Prefixes are configured lower-case (e.g. '18k', '18kt'); we compare on an
    upper-cased designation. A match requires the designation to be either:
      * exactly the prefix (e.g. '18K', '18KT'), or
      * the prefix followed by a space/hyphen then a color/finish
        (e.g. '18K YELLOW GOLD', '18K-WHITE'), or
      * the prefix immediately followed by 'T' karat marker (so prefix '18K'
        still accepts '18KT' / '18KT YELLOW GOLD').
    This intentionally rejects run-on tokens like '18KARAT' or '180K' that merely
    start with the prefix characters, while still covering the 18K + finish family
    without enumerating every finish.
    """
    norm = _norm_metal(material)
    if not norm:
        return False
    for raw in s.surcharge_metal_prefixes:
        p = raw.strip().upper()
        if not p or not norm.startswith(p):
            continue
        rest = norm[len(p):]
        if rest == "":
            return True                      # exact prefix, e.g. '18K' / '18KT'
        if rest[0] in (" ", "-"):
            return True                      # prefix + separator + finish
        if rest[0] == "T" and (len(rest) == 1 or rest[1] in (" ", "-")):
            return True                      # '18K' -> '18KT' / '18KT WHITE'
    return False


def _category_qualifies(category: str | None, s: Settings) -> bool:
    """Case-insensitive membership in the configured bracelet family."""
    return (category or "").strip().lower() in s.surcharge_bracelet_categories


def _date_gate_ok(po_date: date | None, quote_date: date | None, s: Settings) -> bool:
    """BOTH dates must be present and >= the inclusive effective date."""
    eff = s.surcharge_effective_date
    if eff is None or po_date is None or quote_date is None:
        return False
    return po_date >= eff and quote_date >= eff


def is_eligible(
    material: str | None,
    category: str | None,
    po_date: date | None,
    quote_date: date | None,
    s: Settings,
) -> SurchargeDecision:
    """Pure eligibility predicate. Returns a decision with a human-readable reason.

    Order of checks is chosen to produce the most specific reason. Caller is
    responsible for only invoking this when a trustworthy PO match exists;
    unmatched POs must be routed to manual review, not passed here with guesses.
    """
    if not s.surcharge_enabled:
        return SurchargeDecision(False, "surcharge rule disabled in policy")
    if s.surcharge_effective_date is None:
        return SurchargeDecision(False, "no effective_date configured for surcharge")

    metal_ok = _metal_qualifies(material, s)
    cat_ok = _category_qualifies(category, s)
    norm_metal = _norm_metal(material) or "(missing)"

    if not metal_ok:
        return SurchargeDecision(False, f"metal '{norm_metal}' is not 18K gold (no configured prefix match)")
    if not cat_ok:
        return SurchargeDecision(False, f"category '{(category or '').strip() or '(missing)'}' is not in the bracelet family")

    eff = s.surcharge_effective_date
    if po_date is None or quote_date is None:
        return SurchargeDecision(False, "missing PO date or quote date; cannot evaluate date gate")
    if po_date < eff:
        return SurchargeDecision(False, f"PO date {po_date} is before effective date {eff} (earlier PO retains prior rate)")
    if quote_date < eff:
        return SurchargeDecision(False, f"quote date {quote_date} is before effective date {eff}")

    return SurchargeDecision(
        True,
        f"18K-gold bracelet-family item; PO {po_date} and quote {quote_date} both on/after {eff}",
    )


def surcharge_amount(decision: SurchargeDecision, quantity: Decimal, s: Settings) -> Decimal:
    """Deterministic amount = unit surcharge * quantity when eligible, else 0.00.

    Quantized to the policy's money places. Negative/None quantities yield 0.00.
    """
    places = Decimal(1).scaleb(-s.money_places)
    if not decision.eligible:
        return Decimal("0").quantize(places)
    if quantity is None or quantity <= 0:
        return Decimal("0").quantize(places)
    return (s.surcharge_amount_usd * quantity).quantize(places, rounding=s.rounding)
