"""Unit tests: deterministic calculation (policy Rules 2-8)."""
from decimal import Decimal

from audit_agent.calc import compute_expected, exceeds_tolerance, variance
from audit_agent.config import load_settings

from conftest import po, rate


def test_q001_reference_calculation(settings):
    # 4g x 38 = 152; 1 x 2.5; labor 35 -> 189.50; handling 8% = 15.16; unit 204.66; x2 = 409.32
    b = compute_expected(po(qty="2", g="4", pcs="1"), rate(), settings)
    assert (b.metal, b.setting, b.labor, b.subtotal) == (Decimal("152.00"), Decimal("2.50"), Decimal("35.00"), Decimal("189.50"))
    assert b.handling == Decimal("15.16")
    assert b.unit_cost == Decimal("204.66")
    assert b.total == Decimal("409.32")


def test_rhodium_applies_once_per_unit_only_when_po_specifies(settings):
    std = compute_expected(po(qty="3", finish="Standard"), rate(), settings)
    rh = compute_expected(po(qty="3", finish="Rhodium"), rate(), settings)
    assert rh.finish == Decimal("12.00") and std.finish == Decimal("0.00")
    assert rh.total - std.total == Decimal("36.00")  # 12 per unit x 3 units, not taxed by handling


def test_rhodium_case_insensitive(settings):
    assert compute_expected(po(finish=" rhodium "), rate(), settings).finish == Decimal("12.00")


def test_handling_excludes_finish(settings):
    b = compute_expected(po(finish="Rhodium"), rate(h="0.10"), settings)
    assert b.handling == (b.subtotal * Decimal("0.10")).quantize(Decimal("0.01"))


def test_round_half_up_on_handling(settings):
    # subtotal 100.05 x 0.05 = 5.0025 -> 5.00 ; 100.10 x 0.05 = 5.005 -> 5.01 (HALF_UP, not banker's)
    b = compute_expected(po(g="1", pcs="0"), rate(g="65.10", lab="35", h="0.05"), settings)
    assert b.subtotal == Decimal("100.10") and b.handling == Decimal("5.01")


def test_half_even_would_differ_config_driven():
    s = load_settings(overrides={"rounding_mode": "ROUND_HALF_EVEN"})
    b = compute_expected(po(g="1", pcs="0"), rate(g="65.10", lab="35", h="0.05"), s)
    assert b.handling == Decimal("5.00")


def test_component_rounding_metal(settings):
    # 3.33 g x 41.15 = 137.0295 -> 137.03 when components are rounded
    b = compute_expected(po(g="3.33", pcs="0"), rate(g="41.15", lab="0", h="0"), settings)
    assert b.metal == Decimal("137.03") and b.total == Decimal("137.03")


def test_earrings_pair_is_one_unit_labor_once(settings):
    # 3 pairs: labor charged 3 times (once per pair), not 6
    b = compute_expected(po(qty="3", g="3", pcs="2", category="Earrings"), rate(vendor="Blue Peak Metals", g="41", s="2.75", lab="38", h="0.09"), settings)
    assert b.labor == Decimal("38.00")
    assert b.total == Decimal("544.47")


def test_zero_settings(settings):
    assert compute_expected(po(pcs="0"), rate(), settings).setting == Decimal("0.00")


def test_variance_sign_and_tolerance(settings):
    assert variance(Decimal("100.00"), Decimal("100.01"), settings) == Decimal("-0.01")
    assert not exceeds_tolerance(Decimal("0.01"), settings)
    assert not exceeds_tolerance(Decimal("-0.01"), settings)
    assert exceeds_tolerance(Decimal("0.02"), settings)
    assert exceeds_tolerance(Decimal("-20.00"), settings)  # underquote is flagged too


def test_tolerance_is_configurable():
    s = load_settings(overrides={"tolerance_usd": "1.00"})
    assert not exceeds_tolerance(Decimal("0.99"), s) and exceeds_tolerance(Decimal("1.01"), s)


def test_no_float_contamination(settings):
    b = compute_expected(po(qty="7", g="2.2", pcs="3"), rate(g="0.1", s="0.2", lab="0.3", h="0.07000000000000001"), settings)
    assert isinstance(b.total, Decimal) and b.total.as_tuple().exponent == -2
