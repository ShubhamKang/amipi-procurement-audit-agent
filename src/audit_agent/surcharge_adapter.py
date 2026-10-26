"""Focused adapter for the two Nova live-test CSVs.

Scope: ingest `Purchase_Orders_Live_Test.csv` + `Supplier_Quotations_Live_Test.csv`,
join quote `po_reference` -> PO `po_number`, and evaluate the pure surcharge
rule per line. This is a *focused* adapter (the live CSV schema differs from the
main app's inputs); it reuses the deterministic surcharge module and never
recomputes or overwrites supplier-quoted totals.

Policy / AC-12: if a quote's PO cannot be matched, eligibility is NOT guessed —
the line is flagged NEEDS_REVIEW for manual review.

Pure-ish: the only IO is reading the two CSV files. Monetary/eligibility logic
is delegated to `surcharge.py`; this module performs no AI calls.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .config import Settings
from .models import Evidence
from .surcharge import SurchargeDecision, is_eligible, surcharge_amount

PO_FILE = "Purchase_Orders_Live_Test.csv"
QUOTE_FILE = "Supplier_Quotations_Live_Test.csv"


@dataclass(frozen=True)
class PORow:
    line_id: str
    po_number: str
    po_date: date | None
    product_material: str
    product_category: str
    quantity: Decimal | None
    evidence: Evidence


@dataclass(frozen=True)
class QuoteRow:
    quote_line_id: str
    po_reference: str
    quotation_date: date | None
    vendor: str
    quoted_total_usd: Decimal | None  # read-only; never overwritten
    currency: str
    evidence: Evidence


@dataclass(frozen=True)
class SurchargeLine:
    """One audited quote line with the surcharge rule applied."""

    quote_line_id: str
    po_reference: str
    matched: bool
    status: str  # "AUDITED" | "NEEDS_REVIEW"
    vendor: str | None
    product_material: str | None
    product_category: str | None
    quantity: Decimal | None
    po_date: date | None
    quotation_date: date | None
    quoted_total_usd: Decimal | None  # original supplier total, unchanged
    eligible: bool
    surcharge_usd: Decimal
    adjusted_expected_usd: Decimal | None  # quoted + surcharge, internal audit view
    reason: str
    rule: str
    evidence: list[Evidence] = field(default_factory=list)


def _parse_date(raw: str | None) -> date | None:
    raw = (raw or "").strip()
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def _parse_decimal(raw: str | None) -> Decimal | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _verbatim(row: dict[str, str], fieldnames: list[str]) -> str:
    return ",".join((row.get(k) or "").strip() for k in fieldnames)


def load_po_rows(path: Path) -> list[PORow]:
    rows: list[PORow] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fns = reader.fieldnames or []
        for i, r in enumerate(reader, start=2):  # line 1 is the header
            ev = Evidence(source_file=path.name, sheet_or_page="PO", row_or_line=f"row {i}",
                          quote=_verbatim(r, fns))
            rows.append(PORow(
                line_id=(r.get("line_id") or "").strip(),
                po_number=(r.get("po_number") or "").strip(),
                po_date=_parse_date(r.get("po_date")),
                product_material=(r.get("product_material") or "").strip(),
                product_category=(r.get("product_category") or "").strip(),
                quantity=_parse_decimal(r.get("quantity")),
                evidence=ev,
            ))
    return rows


def load_quote_rows(path: Path) -> list[QuoteRow]:
    rows: list[QuoteRow] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fns = reader.fieldnames or []
        for i, r in enumerate(reader, start=2):
            ev = Evidence(source_file=path.name, sheet_or_page="Quote", row_or_line=f"row {i}",
                          quote=_verbatim(r, fns))
            rows.append(QuoteRow(
                quote_line_id=(r.get("quote_line_id") or "").strip(),
                po_reference=(r.get("po_reference") or "").strip(),
                quotation_date=_parse_date(r.get("quotation_date")),
                vendor=(r.get("vendor") or "").strip(),
                quoted_total_usd=_parse_decimal(r.get("quoted_total_usd")),
                currency=(r.get("currency") or "").strip() or "USD",
                evidence=ev,
            ))
    return rows


def _index_pos(po_rows: list[PORow]) -> dict[str, PORow]:
    """Join key: PO `po_number`. Convenience index (unique in the live dataset)."""
    return {p.po_number: p for p in po_rows if p.po_number}


def _duplicate_po_numbers(po_rows: list[PORow]) -> set[str]:
    """PO numbers that appear more than once; such a quote cannot be matched
    unambiguously and must go to manual review rather than guess a line."""
    seen: dict[str, int] = {}
    for p in po_rows:
        if p.po_number:
            seen[p.po_number] = seen.get(p.po_number, 0) + 1
    return {k for k, n in seen.items() if n > 1}


def evaluate_line(q: QuoteRow, po: PORow | None, s: Settings) -> SurchargeLine:
    """Apply the surcharge rule to one quote line.

    If `po` is None the PO could not be matched: per policy/AC-12 we do NOT guess
    eligibility — the line is flagged NEEDS_REVIEW.
    """
    rule = f"Nova 18K bracelet surcharge ${s.surcharge_amount_usd}/unit, effective {s.surcharge_effective_date} (inclusive, both dates)"

def _zero(s: Settings) -> Decimal:
    return Decimal("0").quantize(Decimal(1).scaleb(-s.money_places))


def _needs_review(q: QuoteRow, reason: str, rule: str, s: Settings) -> SurchargeLine:
    return SurchargeLine(
        quote_line_id=q.quote_line_id, po_reference=q.po_reference, matched=False,
        status="NEEDS_REVIEW", vendor=q.vendor, product_material=None, product_category=None,
        quantity=None, po_date=None, quotation_date=q.quotation_date,
        quoted_total_usd=q.quoted_total_usd, eligible=False, surcharge_usd=_zero(s),
        adjusted_expected_usd=None, reason=reason, rule=rule, evidence=[q.evidence],
    )


def evaluate_line(q: QuoteRow, po: PORow | None, s: Settings, *, ambiguous: bool = False) -> SurchargeLine:
    """Apply the surcharge rule to one quote line.

    Fail-closed review paths (eligibility is NOT guessed, AC-12):
      * PO not matched           -> NEEDS_REVIEW
      * PO number is ambiguous    -> NEEDS_REVIEW (duplicate po_number)
      * matched PO has no/invalid quantity or date -> NEEDS_REVIEW
    """
    rule = f"Nova 18K bracelet surcharge ${s.surcharge_amount_usd}/unit, effective {s.surcharge_effective_date} (inclusive, both dates)"

    if ambiguous:
        return _needs_review(q, f"PO '{q.po_reference}' matches multiple PO rows; cannot match unambiguously (manual review required)", rule, s)
    if po is None:
        return _needs_review(q, f"PO '{q.po_reference}' not found; eligibility not guessed (manual review required)", rule, s)
    if po.quantity is None or po.quantity <= 0:
        return _needs_review(q, f"PO '{q.po_reference}' has missing/invalid quantity; cannot compute per-unit surcharge (manual review required)", rule, s)
    if po.po_date is None or q.quotation_date is None:
        return _needs_review(q, f"PO '{q.po_reference}' has missing PO date or quote date; cannot evaluate date gate (manual review required)", rule, s)

    decision: SurchargeDecision = is_eligible(
        po.product_material, po.product_category, po.po_date, q.quotation_date, s)
    amount = surcharge_amount(decision, po.quantity, s)
    adjusted = None
    if q.quoted_total_usd is not None:
        adjusted = (q.quoted_total_usd + amount).quantize(Decimal(1).scaleb(-s.money_places), rounding=s.rounding)

    return SurchargeLine(
        quote_line_id=q.quote_line_id, po_reference=q.po_reference, matched=True,
        status="AUDITED", vendor=q.vendor, product_material=po.product_material,
        product_category=po.product_category, quantity=po.quantity, po_date=po.po_date,
        quotation_date=q.quotation_date, quoted_total_usd=q.quoted_total_usd,
        eligible=decision.eligible, surcharge_usd=amount, adjusted_expected_usd=adjusted,
        reason=decision.reason, rule=rule, evidence=[q.evidence, po.evidence],
    )


def run_surcharge_audit(data_dir: Path | str, s: Settings) -> list[SurchargeLine]:
    """Load both CSVs from `data_dir`, join on PO number, evaluate each quote line."""
    d = Path(data_dir)
    po_rows = load_po_rows(d / PO_FILE)
    quote_rows = load_quote_rows(d / QUOTE_FILE)
    po_by_number = _index_pos(po_rows)
    dups = _duplicate_po_numbers(po_rows)
    return [evaluate_line(q, po_by_number.get(q.po_reference), s, ambiguous=q.po_reference in dups)
            for q in quote_rows]


def finding_record(line: SurchargeLine) -> dict:
    """Per-line audit record. Shows the four policy-required fields:
    original quoted amount, surcharge, adjusted expected amount, supporting rule.

    The original quoted total is reported as-is and never overwritten; the
    surcharge is an internal audit adjustment, NOT evidence of overcharge.
    """
    return {
        "quote_line_id": line.quote_line_id,
        "po_reference": line.po_reference,
        "status": line.status,                       # AUDITED | NEEDS_REVIEW
        "matched": line.matched,
        "vendor": line.vendor,
        "product_material": line.product_material,
        "product_category": line.product_category,
        "quantity": None if line.quantity is None else str(line.quantity),
        "po_date": None if line.po_date is None else line.po_date.isoformat(),
        "quotation_date": None if line.quotation_date is None else line.quotation_date.isoformat(),
        "eligible": line.eligible,
        # --- the four required audit fields ---
        "original_quoted_total_usd": None if line.quoted_total_usd is None else str(line.quoted_total_usd),
        "surcharge_usd": str(line.surcharge_usd),
        "adjusted_expected_usd": None if line.adjusted_expected_usd is None else str(line.adjusted_expected_usd),
        "supporting_rule": line.rule,
        # --- provenance ---
        "reason": line.reason,
        "evidence": [e.model_dump() for e in line.evidence],
    }


def audit_report(data_dir: Path | str, s: Settings) -> dict:
    """Assemble a complete surcharge audit: per-line findings + summary metrics."""
    lines = run_surcharge_audit(data_dir, s)
    eligible = [l for l in lines if l.eligible]
    needs_review = [l for l in lines if l.status == "NEEDS_REVIEW"]
    total_surcharge = sum((l.surcharge_usd for l in lines), Decimal("0"))
    return {
        "config_hash": s.config_hash,
        "rule": lines[0].rule if lines else None,
        "metrics": {
            "lines": len(lines),
            "eligible": len(eligible),
            "needs_review": len(needs_review),
            "total_surcharge_usd": str(total_surcharge.quantize(Decimal(1).scaleb(-s.money_places))),
            "eligible_line_ids": [l.quote_line_id for l in eligible],
        },
        "findings": [finding_record(l) for l in lines],
    }


def write_audit(data_dir: Path | str, out_path: Path | str, s: Settings) -> Path:
    """Write the surcharge audit report to `out_path` as indented JSON."""
    import json

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(audit_report(data_dir, s), indent=2, default=str), encoding="utf-8")
    return out
