"""Deterministic cost engine. The ONLY source of expected monetary values (no AI involved)."""
from __future__ import annotations

from decimal import Decimal

from .config import Settings
from .models import CostBreakdown, POLine, RateCard


def money(x: Decimal, s: Settings) -> Decimal:
    return x.quantize(s.quantum, rounding=s.rounding)


def is_rhodium(finish: str | None, s: Settings) -> bool:
    return (finish or "").strip().lower() in s.rhodium_values


def compute_expected(
    po: POLine,
    rate: RateCard,
    s: Settings,
    *,
    qty: Decimal | None = None,
    set_pcs: Decimal | None = None,
    labor_multiplier: Decimal = Decimal(1),
    force_finish: bool | None = None,
) -> CostBreakdown:
    """Expected line total per policy Rules 2-7.

    Per finished unit (a pair of earrings is ONE unit):
      metal    = metal_g x MetalUSDperGram
      setting  = set_pcs x SettingUSDperStone
      labor    = LaborUSDperUnit
      subtotal = metal + setting + labor
      handling = round(subtotal x HandlingRate)
      finish   = Rhodium fee only if PO finish is Rhodium
      unit     = round(subtotal + handling + finish)
      total    = round(unit x qty)
    Keyword overrides exist only for what-if diagnostics, never for the audited value.
    """
    q = po.qty if qty is None else qty
    pcs = po.set_pcs if set_pcs is None else set_pcs
    r = (lambda v: money(v, s)) if s.round_each_component else (lambda v: v)
    metal = r(po.metal_g * rate.metal_usd_per_gram)
    setting = r(pcs * rate.setting_usd_per_stone)
    labor = r(rate.labor_usd_per_unit * labor_multiplier)
    subtotal = metal + setting + labor
    handling = money(subtotal * rate.handling_rate, s)
    apply_finish = is_rhodium(po.finish, s) if force_finish is None else force_finish
    finish = money(rate.finish_rhodium_usd_per_unit, s) if apply_finish else Decimal("0.00")
    unit = money(subtotal + handling + finish, s)
    total = money(unit * q, s)
    return CostBreakdown(
        rate_id=rate.rate_id, metal=money(metal, s), setting=money(setting, s), labor=money(labor, s),
        subtotal=money(subtotal, s), handling=handling, finish=finish, unit_cost=unit, qty=q, total=total,
        inputs={
            "metal_g": str(po.metal_g), "metal_usd_per_gram": str(rate.metal_usd_per_gram),
            "set_pcs": str(pcs), "setting_usd_per_stone": str(rate.setting_usd_per_stone),
            "labor_usd_per_unit": str(rate.labor_usd_per_unit), "handling_rate": str(rate.handling_rate),
            "finish": po.finish, "rhodium_usd_per_unit": str(rate.finish_rhodium_usd_per_unit),
            "qty": str(q), "rounding": f"{s.rounding_mode} @ {s.money_places}dp",
        },
    )


def variance(quoted: Decimal, expected: Decimal, s: Settings) -> Decimal:
    """Positive = overquote (supplier asks more than policy price)."""
    return money(quoted - expected, s)


def exceeds_tolerance(var: Decimal, s: Settings) -> bool:
    return abs(var) > s.tolerance
