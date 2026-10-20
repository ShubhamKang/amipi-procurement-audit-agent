"""Integration tests: full pipeline on the supplied package (mock + rules-only providers)."""
from decimal import Decimal

import pytest

from audit_agent.config import load_llm_settings, load_settings
from audit_agent.ingest import load_bundle
from audit_agent.pipeline import run_audit

from conftest import DATA

GOLD = {  # quote_id: (po_line, rate, expected, variance, status)
    "Q-001": ("L01", "A-OLD", 409.32, 0.00, "WITHIN_TOLERANCE"),
    "Q-002": ("L02", "B-14", 544.47, 59.97, "FLAG"),
    "Q-003": ("L03", "C-14", 594.92, 120.00, "FLAG"),
    "Q-004": ("L04", "A-OLD18", 687.96, 0.00, "WITHIN_TOLERANCE"),
    "Q-005": ("L05", "B-14", 309.83, 85.00, "FLAG"),
    "Q-006": ("L06", "C-18", 1070.00, 40.00, "FLAG"),
    "Q-007": ("L07", "A-NEW14", 728.90, 70.00, "FLAG"),
    "Q-008": ("L08", "B-18", 845.84, 0.00, "WITHIN_TOLERANCE"),
    "Q-009": ("L09", "C-14", 530.72, -20.00, "FLAG"),
    "Q-010": ("L10", "A-NEW14", 226.16, 15.00, "FLAG"),
    "Q-011": ("L11", "B-18", 681.80, 35.00, "FLAG"),
    "Q-012": ("L12", "C-14", 543.56, 50.00, "FLAG"),
}


@pytest.fixture(scope="module")
def mock_run():
    return run_audit(DATA, load_settings(), load_llm_settings("mock"))


def test_ingestion_counts_and_provenance():
    b = load_bundle(DATA)
    assert (len(b.po_lines), len(b.rates), len(b.csv_quotes), len(b.pdf_quotes), len(b.notes), len(b.policy)) == (12, 8, 12, 12, 4, 10)
    assert not [i for i in b.issues if i.severity.value == "error"]
    q = next(r for r in b.pdf_quotes if r.quote_id == "Q-006")
    assert q.quoted_total == Decimal("1110.00") and q.vendor_sku is None  # "1,110.00" and "[not provided]"
    assert q.evidence.source_file == "Supplier_Crestline_Gems.pdf" and q.evidence.sheet_or_page == "page 1"
    assert b.rates[6].handling_rate == Decimal("0.07")  # float noise removed
    assert b.po_lines[0].evidence.row_or_line == "row 2"


def test_no_double_counting(mock_run):
    assert mock_run.metrics["quotations"] == 12 and mock_run.metrics["source_records"] == 24
    assert len({f.quote_id for f in mock_run.findings}) == 12


@pytest.mark.parametrize("qid", sorted(GOLD))
def test_gold_findings(mock_run, qid):
    line, rate, exp, var, status = GOLD[qid]
    f = mock_run.finding(qid)
    assert (f.po_line_id, f.matched_rate_id, f.expected_total_usd, f.variance_usd, f.status) == (line, rate, exp, var, status)
    assert f.evidence and all(e.source_file for e in f.evidence)
    assert f.human_review.decision == "pending"


def test_never_auto_approved(mock_run):
    assert mock_run.metrics["auto_approved"] == 0
    assert all(f.human_review.decision == "pending" for f in mock_run.findings)


def test_effective_date_applied(mock_run):
    assert mock_run.finding("Q-001").matched_rate_id == "A-OLD"      # Sept quote: legacy card despite X-04 notice
    assert mock_run.finding("Q-007").matched_rate_id == "A-NEW14"    # Oct quote: new card
    assert "RATE_CHANGE_NOTICE_IGNORED" in mock_run.finding("Q-001").issue_codes


def test_special_notes(mock_run):
    assert "UNAUTHORIZED_SURCHARGE" in mock_run.finding("Q-005").issue_codes
    assert "DUPLICATE_NOTICE" in mock_run.finding("Q-006").issue_codes
    assert "PROMPT_INJECTION_DETECTED" in mock_run.finding("Q-007").issue_codes
    assert mock_run.finding("Q-007").status == "FLAG"


def test_hypotheses_and_underquote(mock_run):
    assert "FINISH_NOT_ON_PO" in mock_run.finding("Q-010").issue_codes
    assert {"SETTING_COUNT_MISMATCH", "FINISH_NOT_ON_PO"} <= set(mock_run.finding("Q-002").issue_codes)
    assert "UNDERQUOTE" in mock_run.finding("Q-009").issue_codes


def test_citations_resolve_to_policy(mock_run):
    rules = {c.rule_id for c in load_bundle(DATA).policy}
    for f in mock_run.findings:
        assert f.policy_citations
        for c in f.policy_citations:
            assert c.source_file == "Procurement_Policy_2026.pdf" and c.rule_id in rules and c.page == 1


def test_rules_only_abstains_on_skuless_quotes():
    r = run_audit(DATA, load_settings(), load_llm_settings("none"))
    for qid in ("Q-006", "Q-010"):
        f = r.finding(qid)
        assert f.status == "NEEDS_REVIEW" and f.expected_total_usd is None and "LOW_MATCH_CONFIDENCE" in f.issue_codes
    assert r.finding("Q-003").status == "FLAG"  # SKU-matched lines still audited


def test_live_rule_change_tolerance():
    r = run_audit(DATA, load_settings(overrides={"tolerance_usd": "100"}), load_llm_settings("mock"), explain=False)
    assert r.finding("Q-003").status == "FLAG" and r.finding("Q-005").status == "WITHIN_TOLERANCE"


def test_live_rule_change_rate_date_po_due():
    # Q-001 due 2026-09-20 -> unchanged; if rule switched to PO date the Sept quotes stay on legacy cards
    r = run_audit(DATA, load_settings(overrides={"rate_selection_date": "po_due_date"}), load_llm_settings("mock"), explain=False)
    assert r.finding("Q-001").matched_rate_id == "A-OLD"
    assert r.config_hash != load_settings().config_hash
