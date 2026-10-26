"""Phase 6: Nova 18K bracelet per-unit surcharge — boundary, alias, quantity,
read-only-total and unmatched-PO tests over the 12 live-test lines.

Covers requirements.md AC-1..AC-13. The surcharge engine wiring lives in
calc.py (amount) and the pure predicate in surcharge.py; the focused CSV adapter
joins and assembles per-line audit records.
"""
from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from audit_agent.calc import compute_expected
from audit_agent.config import load_settings
from audit_agent.surcharge import is_eligible, surcharge_amount
from audit_agent.surcharge_adapter import (
    QuoteRow, audit_report, evaluate_line, load_po_rows, run_surcharge_audit, _index_pos,
)
from audit_agent.models import Evidence

from conftest import po, rate

FIX = Path(__file__).resolve().parent / "fixtures" / "nova_live"
EV = Evidence(source_file="t", sheet_or_page="Quote", row_or_line="row 1", quote="t")


@pytest.fixture
def s():
    return load_settings()


@pytest.fixture
def lines(s):
    return {l.quote_line_id: l for l in run_surcharge_audit(FIX, s)}


# --- expected truth table over all 12 lines (requirements.md worked table) ---
EXPECTED = {
    "L01": (True, "30.00"), "L02": (False, "0.00"), "L03": (False, "0.00"),
    "L04": (True, "60.00"), "L05": (False, "0.00"), "L06": (False, "0.00"),
    "L07": (True, "75.00"), "L08": (True, "15.00"), "L09": (False, "0.00"),
    "L10": (False, "0.00"), "L11": (True, "15.00"), "L12": (False, "0.00"),
}


@pytest.mark.parametrize("lid,expected", EXPECTED.items())
def test_all_twelve_lines(lines, lid, expected):
    exp_elig, exp_amt = expected
    L = lines[lid]
    assert L.eligible is exp_elig, f"{lid} eligibility {L.eligible} != {exp_elig} ({L.reason})"
    assert str(L.surcharge_usd) == exp_amt, f"{lid} surcharge {L.surcharge_usd} != {exp_amt}"


def test_eligible_set_is_exactly_expected(lines):
    elig = sorted(k for k, v in lines.items() if v.eligible)
    assert elig == ["L01", "L04", "L07", "L08", "L11"]


# --- AC-4: inclusive boundary, both dates on the 15th ---
def test_boundary_L04_both_dates_on_the_15th_qualifies(lines):
    L = lines["L04"]
    assert L.po_date == date(2026, 10, 15) and L.quotation_date == date(2026, 10, 15)
    assert L.eligible and str(L.surcharge_usd) == "60.00"


def test_boundary_inclusive_direct(s):
    d = is_eligible("18K", "Bracelet", date(2026, 10, 15), date(2026, 10, 15), s)
    assert d.eligible


# --- AC-2: early PO excluded even if quoted later (L02, L10) ---
@pytest.mark.parametrize("lid", ["L02", "L10"])
def test_early_po_excluded(lines, lid):
    L = lines[lid]
    assert L.po_date < date(2026, 10, 15)
    assert not L.eligible and str(L.surcharge_usd) == "0.00"
    assert "PO date" in L.reason and "before effective" in L.reason


# --- AC-3: early quote excluded (L03) ---
def test_early_quote_excluded_L03(lines):
    L = lines["L03"]
    assert L.quotation_date < date(2026, 10, 15) <= L.po_date
    assert not L.eligible
    assert "quote date" in L.reason and "before effective" in L.reason


# --- AC-5 / AC-6: metal aliases qualify ---
def test_alias_18KT_L07(lines):
    L = lines["L07"]
    assert L.product_material == "18KT" and L.product_category == "Tennis Bracelet"
    assert L.eligible and str(L.surcharge_usd) == "75.00"


def test_alias_18K_yellow_gold_bangle_L08(lines):
    L = lines["L08"]
    assert L.product_material == "18K Yellow Gold" and L.product_category == "Bangle Bracelet"
    assert L.eligible and str(L.surcharge_usd) == "15.00"


# --- AC-7: non-qualifying metals excluded ---
@pytest.mark.parametrize("lid", ["L05", "L09"])  # 14K, Platinum
def test_non_qualifying_metal(lines, lid):
    assert not lines[lid].eligible
    assert "not 18K gold" in lines[lid].reason


# --- AC-9: non-bracelet categories excluded ---
@pytest.mark.parametrize("lid", ["L06", "L12"])  # Necklace, Ring
def test_non_bracelet_category(lines, lid):
    assert not lines[lid].eligible
    assert "bracelet family" in lines[lid].reason


# --- AC-10: per-unit multiplied by quantity (L01 = 15 x 2 = 30) ---
def test_quantity_L01_fifteen_times_two(lines, s):
    L = lines["L01"]
    assert L.quantity == Decimal("2")
    assert L.surcharge_usd == Decimal("15.00") * Decimal("2") == Decimal("30.00")


def test_quantity_L07_fifteen_times_five(lines):
    assert lines["L07"].surcharge_usd == Decimal("15.00") * Decimal("5") == Decimal("75.00")


# --- AC-11: quoted total never changed ---
def test_quoted_total_never_changed(lines):
    raw = {}
    with (FIX / "Supplier_Quotations_Live_Test.csv").open() as fh:
        for r in csv.DictReader(fh):
            raw[r["quote_line_id"]] = r["quoted_total_usd"]
    for lid, L in lines.items():
        assert str(L.quoted_total_usd) == raw[lid], f"{lid} quoted total mutated"


def test_adjusted_is_quoted_plus_surcharge(lines):
    for L in lines.values():
        if L.quoted_total_usd is not None:
            assert L.adjusted_expected_usd == L.quoted_total_usd + L.surcharge_usd


def test_finding_shows_four_required_fields(s):
    rep = audit_report(FIX, s)
    f = next(x for x in rep["findings"] if x["quote_line_id"] == "L01")
    assert f["original_quoted_total_usd"] == "620.00"
    assert f["surcharge_usd"] == "30.00"
    assert f["adjusted_expected_usd"] == "650.00"
    assert f["supporting_rule"]


# --- AC-12 negative test: unmatched PO -> NEEDS_REVIEW, no guessed eligibility ---
def test_unmatched_po_goes_to_needs_review(s):
    po_by = _index_pos(load_po_rows(FIX / "Purchase_Orders_Live_Test.csv"))
    q = QuoteRow("L99", "PO-DOES-NOT-EXIST", date(2026, 10, 20),
                 "Fictional Nova Manufacturing", Decimal("500.00"), "USD", EV)
    res = evaluate_line(q, po_by.get(q.po_reference), s)
    assert res.matched is False
    assert res.status == "NEEDS_REVIEW"
    assert res.eligible is False
    assert res.surcharge_usd == Decimal("0.00")
    assert res.adjusted_expected_usd is None
    assert "not found" in res.reason and "manual review" in res.reason


# --- AC-13: engine stays the money source; surcharge never alters policy total ---
def test_calc_adjusted_total_adds_surcharge_without_touching_total(s):
    base = compute_expected(po(qty="2", g="4", pcs="1"), rate(), s)
    withs = compute_expected(po(qty="2", g="4", pcs="1"), rate(), s, surcharge=Decimal("30"))
    assert base.total == withs.total                       # policy total unchanged
    assert base.surcharge == Decimal("0.00") and base.adjusted_total == base.total
    assert withs.surcharge == Decimal("30.00")
    assert withs.adjusted_total == withs.total + Decimal("30.00")


def test_surcharge_disabled_yields_zero(s):
    disabled = load_settings(overrides={"surcharge": {"enabled": False, "amount_usd": "15.00",
                                                       "effective_date": "2026-10-15",
                                                       "metal_prefixes": ["18K", "18KT"],
                                                       "bracelet_categories": ["Bracelet"]}})
    d = is_eligible("18K", "Bracelet", date(2026, 10, 20), date(2026, 10, 20), disabled)
    assert not d.eligible
    assert surcharge_amount(d, Decimal("3"), disabled) == Decimal("0.00")


# ----------------------------- robustness hardening -----------------------------

GATE = (date(2026, 10, 20), date(2026, 10, 20))  # both dates pass the gate


@pytest.mark.parametrize("material,expected", [
    ("18K", True),
    ("18KT", True),
    ("18K Yellow Gold", True),
    ("18k yellow gold", True),
    ("18KT White Gold", True),     # 18KT + finish
    ("18K-White", True),           # hyphen separator
    ("  18K  ", True),             # padding
    ("14K", False),
    ("Platinum", False),
    ("18KARAT", False),            # run-on token must NOT match prefix 18K
    ("18KT9", False),              # 18KT followed by non-separator
    ("180K", False),              # different karat, not a boundary match
    ("", False),
    (None, False),
])
def test_prefix_boundary_matching(s, material, expected):
    d = is_eligible(material, "Bracelet", GATE[0], GATE[1], s)
    assert d.eligible is expected, f"{material!r} -> {d.eligible} (expected {expected}): {d.reason}"


def test_duplicate_po_number_goes_to_review(s, tmp_path):
    # Two PO rows share PO-900 -> any quote referencing it is ambiguous.
    (tmp_path / "Purchase_Orders_Live_Test.csv").write_text(
        "line_id,po_number,po_date,product_material,product_category,quantity\n"
        "L01,PO-900,2026-10-17,18K,Bracelet,2\n"
        "L02,PO-900,2026-10-18,18K,Bracelet,3\n", encoding="utf-8")
    (tmp_path / "Supplier_Quotations_Live_Test.csv").write_text(
        "quote_line_id,po_reference,quotation_date,vendor,base_unit_cost_usd,quoted_total_usd,currency\n"
        "Q1,PO-900,2026-10-20,Fictional Nova Manufacturing,310.00,620.00,USD\n", encoding="utf-8")
    res = run_surcharge_audit(tmp_path, s)
    assert len(res) == 1
    assert res[0].status == "NEEDS_REVIEW" and not res[0].eligible
    assert res[0].surcharge_usd == Decimal("0.00")
    assert "multiple PO rows" in res[0].reason


def test_malformed_quantity_goes_to_review(s, tmp_path):
    (tmp_path / "Purchase_Orders_Live_Test.csv").write_text(
        "line_id,po_number,po_date,product_material,product_category,quantity\n"
        "L01,PO-901,2026-10-17,18K,Bracelet,abc\n", encoding="utf-8")
    (tmp_path / "Supplier_Quotations_Live_Test.csv").write_text(
        "quote_line_id,po_reference,quotation_date,vendor,base_unit_cost_usd,quoted_total_usd,currency\n"
        "Q1,PO-901,2026-10-20,Fictional Nova Manufacturing,310.00,620.00,USD\n", encoding="utf-8")
    res = run_surcharge_audit(tmp_path, s)
    assert res[0].status == "NEEDS_REVIEW" and not res[0].eligible
    assert "quantity" in res[0].reason


def test_malformed_dates_go_to_review(s, tmp_path):
    (tmp_path / "Purchase_Orders_Live_Test.csv").write_text(
        "line_id,po_number,po_date,product_material,product_category,quantity\n"
        "L01,PO-902,not-a-date,18K,Bracelet,2\n", encoding="utf-8")
    (tmp_path / "Supplier_Quotations_Live_Test.csv").write_text(
        "quote_line_id,po_reference,quotation_date,vendor,base_unit_cost_usd,quoted_total_usd,currency\n"
        "Q1,PO-902,2026-10-20,Fictional Nova Manufacturing,310.00,620.00,USD\n", encoding="utf-8")
    res = run_surcharge_audit(tmp_path, s)
    assert res[0].status == "NEEDS_REVIEW" and not res[0].eligible
    assert "date" in res[0].reason


def test_hardening_did_not_change_the_twelve_line_result(s):
    # Regression guard: the real dataset must still produce exactly 5 qualifiers / $195.
    rep = audit_report(FIX, s)
    assert rep["metrics"]["eligible_line_ids"] == ["L01", "L04", "L07", "L08", "L11"]
    assert rep["metrics"]["total_surcharge_usd"] == "195.00"
    assert rep["metrics"]["needs_review"] == 0
