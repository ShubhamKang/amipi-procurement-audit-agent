"""Unit tests: effective-date precedence (policy Rule 1)."""
from datetime import date

from audit_agent.rates import select_rate

from conftest import rate

AURORA = [
    rate("A-OLD", frm="2026-01-01", to="2026-09-30", metal="14K"),
    rate("A-OLD18", frm="2026-01-01", to="2026-09-30", metal="18K"),
    rate("A-NEW14", frm="2026-10-01", to="2026-12-31", metal="14K", g="42"),
    rate("A-NEW18", frm="2026-10-01", to="2026-12-31", metal="18K", g="59"),
]


def pick(d, grade="14K", vendor="Aurora Craftworks", rates=AURORA, cat="Ring"):
    return select_rate(rates, vendor, grade, cat, date.fromisoformat(d) if d else None)


def test_quote_date_before_change_uses_old_rate():
    assert pick("2026-09-18").rate.rate_id == "A-OLD"


def test_boundary_last_day_inclusive():
    assert pick("2026-09-30").rate.rate_id == "A-OLD"


def test_boundary_first_day_inclusive():
    assert pick("2026-10-01").rate.rate_id == "A-NEW14"


def test_grade_selects_card():
    assert pick("2026-10-12", grade="18K").rate.rate_id == "A-NEW18"


def test_vendor_name_normalized():
    assert pick("2026-10-12", vendor="  aurora craftworks ").rate.rate_id == "A-NEW14"


def test_no_rate_after_expiry():
    sel = pick("2027-01-05")
    assert sel.rate is None and sel.code == "NO_ELIGIBLE_RATE"


def test_unknown_vendor():
    assert pick("2026-10-12", vendor="Unknown Co").code == "NO_ELIGIBLE_RATE"


def test_missing_date_and_grade():
    assert pick(None).code == "MISSING_QUOTE_DATE"
    assert pick("2026-10-12", grade=None).code == "METAL_GRADE_UNKNOWN"


def test_overlapping_rates_are_ambiguous_not_guessed():
    rs = AURORA + [rate("A-DUP", frm="2026-10-10", to="2026-10-31", metal="14K")]
    sel = pick("2026-10-12", rates=rs)
    assert sel.rate is None and sel.code == "AMBIGUOUS_RATE"


def test_category_specific_beats_all():
    rs = AURORA + [rate("A-RING", frm="2026-10-01", to="2026-12-31", metal="14K", category="Ring")]
    assert pick("2026-10-12", rates=rs).rate.rate_id == "A-RING"


def test_open_ended_rate():
    rs = [rate("Z", frm="2026-01-01", to=None)]
    assert pick("2030-01-01", rates=rs).rate.rate_id == "Z"
