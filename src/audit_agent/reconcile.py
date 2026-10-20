"""Reconcile PDF (primary) and CSV register (secondary) views into ONE business quotation per quote_id.

Rules:
* PDF and register rows with the same quote_id are the same quotation -> never double-counted.
* PDF values win; register values only fill blanks (recorded in `filled_from_secondary`).
* Any disagreement is recorded as a FieldConflict; conflicts on monetary/identity fields are critical
  and force NEEDS_REVIEW downstream.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from .models import FieldConflict, IngestionIssue, Quote, QuoteRecord, Severity
from .normalize import fold, norm_vendor

FIELDS = ["vendor", "quote_date", "po_id", "supplier_line", "vendor_sku", "description", "qty", "unit", "quoted_total", "currency"]
CRITICAL = {"vendor", "quote_date", "po_id", "qty", "unit", "quoted_total", "currency", "vendor_sku"}
ORIGIN_RANK = {"pdf": 0, "llm_pdf": 1, "csv": 2}


def _norm(field: str, v: object) -> str | None:
    if v is None:
        return None
    if field == "vendor":
        return norm_vendor(str(v))
    if field == "description":
        return fold(str(v))
    if field in {"qty", "quoted_total"}:
        return str(Decimal(v).normalize())
    if field == "unit":
        u = str(v).lower().rstrip("s")
        return {"pc": "piece", "pcs": "piece", "pr": "pair"}.get(u, u)
    return str(v).strip().upper()


def reconcile(records: list[QuoteRecord], issues: list[IngestionIssue]) -> list[Quote]:
    groups: dict[str, list[QuoteRecord]] = defaultdict(list)
    for r in records:
        groups[r.quote_id.strip().upper()].append(r)

    out: list[Quote] = []
    for qid in sorted(groups):
        recs = sorted(groups[qid], key=lambda r: ORIGIN_RANK[r.origin])
        per_origin: dict[str, list[QuoteRecord]] = defaultdict(list)
        for r in recs:
            per_origin[r.origin].append(r)
        for origin, rs in per_origin.items():
            if len(rs) > 1:
                issues.append(IngestionIssue(code="DUPLICATE_QUOTE_RECORD", severity=Severity.WARNING,
                                             source_file=rs[1].evidence.source_file, location=rs[1].evidence.ref(),
                                             message=f"{qid} appears {len(rs)} times in {origin} sources; treated as one quotation"))
        primary = recs[0]
        merged: dict[str, object] = {}
        filled: list[str] = []
        conflicts: list[FieldConflict] = []
        for f in FIELDS:
            vals = {f"{r.origin}:{r.evidence.source_file}:{r.evidence.row_or_line}": getattr(r, f) for r in recs}
            present = {k: v for k, v in vals.items() if v is not None}
            pv = getattr(primary, f)
            if pv is None and present:
                k0 = next(iter(present))
                merged[f] = present[k0]
                filled.append(f"{f} (from {k0.split(':')[0]})")
            else:
                merged[f] = pv
            normed = {_norm(f, v) for v in present.values()}
            if len(normed) > 1:
                conflicts.append(FieldConflict(field=f, values={k: str(v) for k, v in present.items()}, critical=f in CRITICAL))
        errs = [e for r in recs for e in r.parse_errors]
        # A field that failed to parse in one source but parsed in another is recoverable; keep the note.
        out.append(Quote(
            quote_id=qid, origins=[r.origin for r in recs], evidence=[r.evidence for r in recs], conflicts=conflicts,
            parse_errors=errs, filled_from_secondary=filled, **merged,  # type: ignore[arg-type]
        ))
    return out
