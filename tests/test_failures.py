"""Failure tests: missing files, malformed amounts, ambiguous units, corrupt documents, LLM outages."""
import csv
import shutil
from decimal import Decimal

import pytest

from audit_agent.config import load_llm_settings, load_settings
from audit_agent.ingest.parsing import to_date, to_decimal
from audit_agent.llm import AIService
from audit_agent.llm.providers import LLMError, LLMUnavailable
from audit_agent.pipeline import run_audit

from conftest import DATA


@pytest.fixture
def data_copy(tmp_path):
    d = tmp_path / "Data"
    shutil.copytree(DATA, d)
    return d


def _edit_register(d, qid, **changes):
    p = d / "Quote_Register.csv"
    rows = list(csv.DictReader(p.open()))
    for r in rows:
        if r["quote_id"] == qid:
            r.update(changes)
    with p.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)


@pytest.mark.parametrize("raw,exp", [("USD 1,110.00", "1110.00"), ("$409.32", "409.32"), (604.4400000000001, "604.44"), ("0.07", "0.07"), (2, "2")])
def test_parse_amounts(raw, exp):
    assert to_decimal(raw, "x") == Decimal(exp)


@pytest.mark.parametrize("raw", ["abc", "12,34", "1.2.3", "", None, "USD", float("nan"), True])
def test_malformed_amounts_rejected(raw):
    with pytest.raises(ValueError):
        to_decimal(raw, "x")


def test_ambiguous_date_rejected():
    with pytest.raises(ValueError):
        to_date("05/06/2026", "d")
    assert str(to_date("25/10/2026", "d")) == "2026-10-25"


def test_missing_data_dir(tmp_path):
    r = run_audit(tmp_path / "nope", load_settings(), load_llm_settings("mock"))
    assert r.findings == [] and any(i.code == "DATA_DIR_MISSING" for i in r.ingestion_issues)


def test_missing_rate_cards_gives_needs_review(data_copy):
    (data_copy / "Vendor_Rate_Cards.xlsx").unlink()
    r = run_audit(data_copy, load_settings(), load_llm_settings("mock"), explain=False)
    assert any(i.code == "FILE_MISSING" for i in r.ingestion_issues)
    assert all(f.status == "NEEDS_REVIEW" and f.expected_total_usd is None for f in r.findings)


def test_missing_register_still_audits_from_pdfs(data_copy):
    (data_copy / "Quote_Register.csv").unlink()
    r = run_audit(data_copy, load_settings(), load_llm_settings("mock"), explain=False)
    assert len(r.findings) == 12 and r.finding("Q-003").variance_usd == 120.0
    assert "NOT_IN_REGISTER" in r.finding("Q-003").issue_codes


def test_corrupt_pdf_reported(data_copy):
    (data_copy / "Quotations" / "Supplier_Crestline_Gems.pdf").write_bytes(b"not a pdf")
    r = run_audit(data_copy, load_settings(), load_llm_settings("mock"), explain=False)
    assert any(i.code == "FILE_UNREADABLE" for i in r.ingestion_issues)
    assert "NO_PRIMARY_DOCUMENT" in r.finding("Q-003").issue_codes  # register-only, still audited


def test_malformed_register_amount_conflict(data_copy):
    _edit_register(data_copy, "Q-004", quoted_total_usd="six hundred")
    r = run_audit(data_copy, load_settings(), load_llm_settings("mock"), explain=False)
    assert any(i.code == "FIELD_INVALID" for i in r.ingestion_issues)
    assert r.finding("Q-004").quoted_total_usd == 687.96  # PDF primary value still present


def test_source_conflict_forces_review(data_copy):
    _edit_register(data_copy, "Q-008", quoted_total_usd="900.00")
    f = run_audit(data_copy, load_settings(), load_llm_settings("mock"), explain=False).finding("Q-008")
    assert f.status == "NEEDS_REVIEW" and "SOURCE_CONFLICT" in f.issue_codes


def test_ambiguous_unit_forces_review(data_copy):
    _edit_register(data_copy, "Q-002", unit="piece")
    f = run_audit(data_copy, load_settings(), load_llm_settings("mock"), explain=False).finding("Q-002")
    assert f.status == "NEEDS_REVIEW" and "SOURCE_CONFLICT" in f.issue_codes


def test_qty_mismatch_forces_review(data_copy):
    _edit_register(data_copy, "Q-011", qty="3")
    f = run_audit(data_copy, load_settings(), load_llm_settings("mock"), explain=False).finding("Q-011")
    assert f.status == "NEEDS_REVIEW"


def test_quote_outside_rate_period(data_copy):
    _edit_register(data_copy, "Q-012", quote_date="2027-02-01")
    f = run_audit(data_copy, load_settings(), load_llm_settings("mock"), explain=False).finding("Q-012")
    assert f.status == "NEEDS_REVIEW"


class Boom:
    name, remote = "boom", True

    def __init__(self, exc):
        self.exc, self.calls = exc, 0

    def generate(self, *a, **k):
        self.calls += 1
        raise self.exc


@pytest.mark.parametrize("exc", [LLMError("429 quota"), LLMUnavailable("bad key"), TimeoutError("slow")])
def test_llm_outage_degrades_gracefully(exc):
    s = load_settings()
    p = Boom(exc)
    ai = AIService(load_llm_settings("mock"), s, provider=p)
    r = run_audit(DATA, s, ai=ai)
    assert len(r.findings) == 12
    assert r.finding("Q-006").status == "NEEDS_REVIEW"  # no AI -> abstain
    assert r.finding("Q-003").status == "FLAG"
    assert r.metrics["ai_errors"] >= 1 and p.calls <= 4  # circuit breaker stops hammering


def test_gemini_without_key_falls_back(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    ai = AIService(load_llm_settings("gemini"), load_settings())
    assert ai.name == "mock" and ai.events[0].status == "fallback"
