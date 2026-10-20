"""Audit report exports: JSON (schema-compatible), CSV and multi-sheet XLSX."""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .models import Finding


def finding_record(f: Finding) -> dict[str, Any]:
    """Flat dict following Expected_Output_Schema.json plus documented extensions."""
    return {
        "quote_id": f.quote_id,
        "po_line_id": f.po_line_id,
        "status": f.status,
        "quoted_total_usd": f.quoted_total_usd,
        "expected_total_usd": f.expected_total_usd,
        "variance_usd": f.variance_usd,
        "matched_rate_id": f.matched_rate_id,
        "issue_codes": f.issue_codes,
        "evidence": [e.model_dump() for e in f.evidence],
        "ai_explanation": f.ai_explanation,
        "human_review": {k: v for k, v in f.human_review.model_dump().items() if k in ("decision", "reviewer", "reason", "timestamp")},
        # --- extensions (documented in README "Output schema deviations")
        "po_id": f.po_id,
        "vendor": f.vendor,
        "quote_date": f.quote_date,
        "priority": f.priority,
        "variance_pct": f.variance_pct,
        "explanation_source": f.explanation_source,
        "match": {"method": f.match.method, "confidence": f.match.confidence, "trustworthy": f.match.trustworthy,
                  "proposed_po_line_key": f.match.proposed_po_line_key, "rationale": f.match.rationale},
        "calculation": json.loads(f.calculation.model_dump_json()) if f.calculation else None,
        "hypotheses": f.hypotheses,
        "policy_citations": [c.model_dump(exclude={"score"}) for c in f.policy_citations],
        "issues": [i.model_dump() for i in f.issues],
        "human_override_expected_total_usd": f.human_review.override_expected_total_usd,
        "review_stale": f.human_review.stale,
        "fingerprint": f.fingerprint,
    }


def to_json(run) -> str:
    payload = {
        "run": {"run_id": run.run_id, "started_at": run.started_at, "finished_at": run.finished_at, "provider": run.provider,
                "config_hash": run.config_hash, "data_dir": run.data_dir, "file_hashes": run.file_hashes,
                "metrics": run.metrics, "unquoted_po_lines": run.unquoted_po_lines},
        "findings": [finding_record(f) for f in run.findings],
        "supplementary_notes": [n.model_dump(mode="json") for n in run.notes],
        "ingestion_issues": [i.model_dump(mode="json") for i in run.ingestion_issues],
        "ai_events": [e.__dict__ for e in run.ai_events],
    }
    return json.dumps(payload, indent=2, default=str)


def findings_frame(findings: list[Finding]) -> pd.DataFrame:
    rows = []
    for f in findings:
        c = f.calculation
        rows.append({
            "priority": f.priority, "status": f.status, "quote_id": f.quote_id, "vendor": f.vendor, "quote_date": f.quote_date,
            "po_id": f.po_id, "po_line_id": f.po_line_id, "description": f.description,
            "quoted_total_usd": f.quoted_total_usd, "expected_total_usd": f.expected_total_usd, "variance_usd": f.variance_usd,
            "variance_pct": f.variance_pct, "matched_rate_id": f.matched_rate_id, "issue_codes": "; ".join(f.issue_codes),
            "match_method": f.match.method, "match_confidence": f.match.confidence,
            "metal_usd": float(c.metal) if c else None, "setting_usd": float(c.setting) if c else None,
            "labor_usd": float(c.labor) if c else None, "handling_usd": float(c.handling) if c else None,
            "finish_usd": float(c.finish) if c else None, "unit_cost_usd": float(c.unit_cost) if c else None,
            "hypotheses": " | ".join(f.hypotheses),
            "evidence": " || ".join(e.ref() for e in f.evidence),
            "policy_citations": "; ".join(f"{c.source_file} p.{c.page} {c.rule_id}" for c in f.policy_citations),
            "ai_explanation": f.ai_explanation, "explanation_source": f.explanation_source,
            "review_decision": f.human_review.decision, "reviewer": f.human_review.reviewer, "review_reason": f.human_review.reason,
            "review_timestamp": f.human_review.timestamp, "override_expected_total_usd": f.human_review.override_expected_total_usd,
            "review_stale": f.human_review.stale,
        })
    return pd.DataFrame(rows)


def to_csv(run) -> bytes:
    return findings_frame(run.findings).to_csv(index=False).encode("utf-8")


def to_xlsx(run, review_history: list[dict] | None = None) -> bytes:
    buf = io.BytesIO()
    summary = pd.DataFrame([{"metric": k, "value": v} for k, v in {
        "run_id": run.run_id, "started_at": run.started_at, "provider": run.provider, "config_hash": run.config_hash, **run.metrics}.items()])
    evidence = pd.DataFrame([{"quote_id": f.quote_id, **e.model_dump()} for f in run.findings for e in f.evidence])
    issues = pd.DataFrame([{"quote_id": f.quote_id, **i.model_dump()} for f in run.findings for i in f.issues])
    notes = pd.DataFrame([{**n.model_dump(exclude={"evidence"}, mode="json"), "evidence": n.evidence.ref()} for n in run.notes])
    ing = pd.DataFrame([i.model_dump(mode="json") for i in run.ingestion_issues]) if run.ingestion_issues else pd.DataFrame([{"message": "no ingestion issues"}])
    with pd.ExcelWriter(buf, engine="xlsxwriter") as xw:
        summary.to_excel(xw, sheet_name="Summary", index=False)
        findings_frame(run.findings).to_excel(xw, sheet_name="Findings", index=False)
        issues.to_excel(xw, sheet_name="Issues", index=False)
        evidence.to_excel(xw, sheet_name="Evidence", index=False)
        notes.to_excel(xw, sheet_name="Vendor_Notes", index=False)
        ing.to_excel(xw, sheet_name="Ingestion", index=False)
        pd.DataFrame(review_history or [{"message": "no reviews recorded"}]).to_excel(xw, sheet_name="Review_Log", index=False)
        for name, ws in xw.sheets.items():
            ws.freeze_panes(1, 0)
            ws.set_column(0, 40, 18)
    return buf.getvalue()


def write_all(run, out_dir: Path, review_history: list[dict] | None = None) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"json": out_dir / "audit_report.json", "csv": out_dir / "audit_findings.csv", "xlsx": out_dir / "audit_report.xlsx"}
    paths["json"].write_text(to_json(run), encoding="utf-8")
    paths["csv"].write_bytes(to_csv(run))
    paths["xlsx"].write_bytes(to_xlsx(run, review_history))
    return paths
