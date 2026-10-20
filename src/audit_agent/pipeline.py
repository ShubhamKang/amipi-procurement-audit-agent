"""End-to-end audit pipeline: ingest -> reconcile -> match -> rate -> calculate -> findings -> explain."""
from __future__ import annotations

import hashlib
import re
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .calc import compute_expected, exceeds_tolerance, money, variance
from .config import LLMSettings, Settings, load_llm_settings, load_settings
from .diagnostics import explain_variance
from .ingest import Bundle, load_bundle
from .llm import AIEvent, AIService
from .match import Candidate, score_candidates
from .models import (
    CostBreakdown, Evidence, Finding, HistoryRecord, IngestionIssue, Issue, MatchResult, POLine, Quote, RateCard, ReviewNote,
)
from .normalize import grade_of, norm_vendor
from .notes import classify_notes, has_signed_exception
from .policy_rag import PolicyIndex
from .rates import select_rate
from .reconcile import reconcile


@dataclass
class AuditRun:
    run_id: str
    started_at: str
    finished_at: str
    data_dir: str
    provider: str
    config_hash: str
    settings: Settings
    file_hashes: dict[str, str]
    findings: list[Finding]
    notes: list[ReviewNote]
    ingestion_issues: list[IngestionIssue]
    ai_events: list[AIEvent]
    quotes: list[Quote]
    po_lines: list[POLine]
    rates: list[RateCard]
    unquoted_po_lines: list[str]
    metrics: dict[str, Any] = field(default_factory=dict)

    def finding(self, quote_id: str) -> Finding | None:
        return next((f for f in self.findings if f.quote_id == quote_id), None)


def _f(d: Decimal | None) -> float | None:
    return None if d is None else float(d)


def _iss(code: str, severity: str, message: str, blocking: bool = False) -> Issue:
    return Issue(code=code, severity=severity, message=message, blocking=blocking)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- matching
def _decide_match(q: Quote, po_lines: list[POLine], ai: AIService, s: Settings) -> tuple[MatchResult, POLine | None, list[Candidate]]:
    cands = score_candidates(q, po_lines)
    if not cands:
        return MatchResult(po_line_key=None, method="none", confidence=0.0, trustworthy=False, rationale="No PO lines loaded"), None, []
    top = cands[0]
    margin = top.score - (cands[1].score if len(cands) > 1 else 0.0)
    sku_hit = any(sig.startswith("SKU") for sig in top.signals)
    rules_ok = not top.conflicts and (
        (sku_hit and top.score >= 0.6) or (top.score >= s.auto_accept_score and margin >= s.min_margin))
    cdicts = [c.as_dict() | {"category": c.po.category} for c in cands[:5]]
    if rules_ok and sku_hit:
        return MatchResult(po_line_key=top.po.key, method="sku", confidence=round(top.score, 3), trustworthy=True,
                           rationale="; ".join(top.signals), candidates=cdicts), top.po, cands
    dec = ai.match(q, cdicts)
    if dec is None:
        if rules_ok:
            return MatchResult(po_line_key=top.po.key, method="rules", confidence=round(top.score, 3), trustworthy=True,
                               rationale="AI unavailable; rules-only: " + "; ".join(top.signals), candidates=cdicts), top.po, cands
        return MatchResult(po_line_key=None, proposed_po_line_key=top.po.key, method="rules", confidence=round(top.score, 3),
                           trustworthy=False, rationale=f"Rules score {top.score:.2f} below acceptance and AI matcher unavailable",
                           candidates=cdicts), top.po, cands
    by_key = {c.po.key: c for c in cands}
    chosen = by_key.get(dec.po_line_key) if dec.po_line_key else None
    rationale = f"AI ({ai.name}) chose {dec.po_line_key} @ {dec.confidence:.2f}: {dec.rationale} | rules top {top.po.key} @ {top.score:.2f}"
    if chosen is None or dec.confidence < s.llm_min_confidence:
        return MatchResult(po_line_key=None, proposed_po_line_key=(chosen or top).po.key, method="rules+llm", confidence=dec.confidence,
                           trustworthy=False, rationale=rationale, candidates=cdicts, llm_used=True), (chosen or top).po, cands
    if chosen.po.key != top.po.key:
        return MatchResult(po_line_key=None, proposed_po_line_key=chosen.po.key, method="rules+llm", confidence=dec.confidence,
                           trustworthy=False, rationale="Disagreement: " + rationale, candidates=cdicts, llm_used=True), chosen.po, cands
    if chosen.conflicts:
        return MatchResult(po_line_key=None, proposed_po_line_key=chosen.po.key, method="rules+llm", confidence=dec.confidence,
                           trustworthy=False, rationale=f"Attribute conflicts {chosen.conflicts}: " + rationale, candidates=cdicts,
                           llm_used=True), chosen.po, cands
    conf = round((top.score + dec.confidence) / 2, 3)
    return MatchResult(po_line_key=chosen.po.key, method="rules+llm", confidence=conf, trustworthy=True, rationale=rationale,
                       candidates=cdicts, llm_used=True), chosen.po, cands


# --------------------------------------------------------------------------- finding
def _unit_kind(unit: str | None, s: Settings) -> str | None:
    u = (unit or "").strip().lower()
    if u in s.pair_units:
        return "pair"
    if u in s.piece_units:
        return "piece"
    return None


def _priority(status: str, issues: list[Issue], var: Decimal | None, s: Settings) -> str:
    if status == "NEEDS_REVIEW" or any(i.severity == "critical" for i in issues):
        return "P1"
    if var is not None and abs(var) >= s.p1_abs_variance:
        return "P1"
    if status == "FLAG":
        return "P2"
    return "P3"


def _fingerprint(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, default=str, sort_keys=True).encode()).hexdigest()[:16]


def _template(f: dict[str, Any]) -> str:
    st, qid = f["status"], f["quote_id"]
    parts = []
    if f.get("expected") is not None and f.get("quoted") is not None:
        v = Decimal(f["variance"])
        kind = "overquote" if v > 0 else "underquote" if v < 0 else "exact match"
        parts.append(f"Quoted USD {f['quoted']} vs policy-expected USD {f['expected']} (variance {v:+.2f}, {kind}; tolerance {f['tolerance']}, Rule 8).")
    if f.get("rate"):
        parts.append(f"Rate {f['rate']} applies for quote date {f['quote_date']} (Rule 1).")
    if f.get("hypotheses"):
        parts.append("Hypothesis: " + " | ".join(f["hypotheses"]) + ".")
    blocking = [i for i in f["issues"] if i["blocking"]]
    if blocking:
        parts.append("Needs review: " + "; ".join(i["message"] for i in blocking[:3]) + " (Rule 9).")
    other = [i["code"] for i in f["issues"] if not i["blocking"] and i["code"] not in {"PRICE_VARIANCE", "OVERQUOTE", "UNDERQUOTE"}]
    if other:
        parts.append("Also noted: " + ", ".join(dict.fromkeys(other)) + ".")
    parts.append("No automatic approval; a human reviewer decision is required (Rule 10).")
    return f"{st} {qid}: " + " ".join(parts)


def _build_finding(q: Quote, m: MatchResult, po: POLine | None, b: Bundle, notes: list[ReviewNote],
                   hist: dict[str, HistoryRecord], dup_keys: set[str], idx: PolicyIndex, s: Settings) -> tuple[Finding, dict]:
    issues: list[Issue] = []
    evidence: list[Evidence] = list(q.evidence)
    note_lines: list[str] = []

    # --- source reconciliation
    if not ({"pdf", "llm_pdf"} & set(q.origins)):
        issues.append(_iss("NO_PRIMARY_DOCUMENT", "medium", "Only the register lists this quotation; no supplier PDF found"))
    if "csv" not in q.origins:
        issues.append(_iss("NOT_IN_REGISTER", "low", "Quotation found in PDF but not in Quote_Register.csv"))
    if "llm_pdf" in q.origins and "pdf" not in q.origins:
        issues.append(_iss("AI_EXTRACTED", "medium", "Line items extracted by AI from an unrecognised layout (grounded, verify)"))
    for c in q.conflicts:
        if c.critical:
            issues.append(_iss("SOURCE_CONFLICT", "critical", f"PDF and register disagree on {c.field}: {list(c.values.values())}", True))
        else:
            issues.append(_iss("DESCRIPTION_WORDING_DIFFERS", "info", f"Sources word the {c.field} differently"))
    for fsec in q.filled_from_secondary:
        issues.append(_iss("FILLED_FROM_REGISTER", "low", f"{fsec} missing in primary document"))
    if len(q.origins) > 1:
        note_lines.append(f"De-duplicated: {len(q.origins)} source records ({', '.join(q.origins)}) = 1 business quotation")
    if q.vendor_sku is None:
        issues.append(_iss("MISSING_SKU", "low", "Supplier did not provide a SKU; matched by description"))

    # --- matching
    if not m.trustworthy:
        code = "MATCH_DISAGREEMENT" if m.rationale.startswith("Disagreement") else "LOW_MATCH_CONFIDENCE" if m.proposed_po_line_key else "NO_PO_MATCH"
        issues.append(_iss(code, "high", f"No trustworthy PO line match (proposed {m.proposed_po_line_key}, confidence {m.confidence:.2f})", True))
    if po:
        evidence.append(po.evidence)
    if m.trustworthy and m.po_line_key in dup_keys:
        issues.append(_iss("POSSIBLE_DUPLICATE_QUOTE", "high", f"Another quotation from the same vendor matches {m.po_line_key}", True))

    # --- quantity / unit / amount checks
    unit_kind = _unit_kind(q.unit, s)
    if po:
        pair_cat = po.category.strip().lower() in s.pair_categories
        if q.unit is None:
            issues.append(_iss("UNIT_MISSING", "high", "Quotation unit not stated", True))
        elif unit_kind is None:
            issues.append(_iss("AMBIGUOUS_UNIT", "high", f"Unrecognised unit '{q.unit}'", True))
        elif pair_cat and unit_kind == "piece":
            issues.append(_iss("AMBIGUOUS_UNIT", "high", f"Earrings quoted in '{q.unit}' but policy measures earrings in pairs (Rule 4)", True))
        elif not pair_cat and unit_kind == "pair":
            issues.append(_iss("AMBIGUOUS_UNIT", "high", f"{po.category} quoted in pairs", True))
        if q.qty is None:
            issues.append(_iss("QTY_MISSING", "high", "Quoted quantity missing", True))
        elif q.qty != po.qty:
            issues.append(_iss("QTY_MISMATCH", "high", f"Quoted qty {q.qty} vs PO ordered qty {po.qty}", True))
    if q.quoted_total is None:
        issues.append(_iss("MISSING_QUOTED_TOTAL", "critical", "Quoted total missing or malformed", True))
    elif q.quoted_total <= 0:
        issues.append(_iss("INVALID_AMOUNT", "critical", f"Quoted total {q.quoted_total} is not positive", True))
    if (q.currency or "USD") != "USD":
        issues.append(_iss("CURRENCY_MISMATCH", "high", f"Currency {q.currency} (policy is USD); no FX conversion applied", True))
    for e in q.parse_errors:
        issues.append(_iss("FIELD_PARSE_ERROR", "medium", e))

    # --- rate + calculation
    calc: CostBreakdown | None = None
    rate: RateCard | None = None
    if po:
        on_date = q.quote_date if s.rate_selection_date == "quote_date" else po.due_date
        sel = select_rate(b.rates, q.vendor, grade_of(po.description), po.category, on_date)
        if sel.rate is None:
            issues.append(_iss(sel.code or "NO_ELIGIBLE_RATE", "high", sel.reason, True))
        else:
            rate = sel.rate
            evidence.append(rate.evidence.model_copy(update={"quote": f"{rate.rate_id} {rate.vendor} {rate.metal} effective {rate.effective_from}..{rate.effective_to}; {rate.notes}"[:240]}))
            calc = compute_expected(po, rate, s)

    trusted_calc = calc is not None and m.trustworthy
    expected = calc.total if trusted_calc else None
    var = variance(q.quoted_total, expected, s) if (expected is not None and q.quoted_total is not None) else None
    hyps: list[str] = []
    if calc is not None and not m.trustworthy:
        note_lines.append(f"Provisional (NOT authoritative) expected for proposed {m.proposed_po_line_key}: USD {calc.total}")
    if var is not None and exceeds_tolerance(var, s):
        sev = "high" if abs(var) >= s.p1_abs_variance else "medium"
        issues.append(_iss("PRICE_VARIANCE", sev, f"|variance| {abs(var)} exceeds tolerance {s.tolerance}"))
        issues.append(_iss("OVERQUOTE" if var > 0 else "UNDERQUOTE", sev,
                           "Supplier quoted above policy price" if var > 0 else "Supplier quoted below policy price (identify, do not auto-reject; Rule 8)"))
        if po and rate:
            related_amounts = [n for n in notes if n.po_id and po and f"{n.po_id}/{n.line_id}" == po.key]
            for h in explain_variance(po, rate, q.quoted_total, b.rates, q.vendor, related_amounts, s):
                hyps.append(h.text)
                for c in h.codes:
                    issues.append(_iss(c, "medium", f"Hypothesis: {h.text} (reproduces USD {h.total})"))
        if not hyps:
            issues.append(_iss("UNEXPLAINED_VARIANCE", "medium", "No single pricing error reproduces the quoted total; possible undisclosed charge"))

    # --- supplementary notes (untrusted)
    related = [n for n in notes if (po and n.po_id and f"{n.po_id}/{n.line_id}" == po.key) or q.quote_id in n.referenced_quote_ids]
    note_amounts: list[Decimal] = []
    for n in related:
        evidence.append(n.evidence)
        if norm_vendor(n.vendor) != norm_vendor(q.vendor):
            issues.append(_iss("NOTE_VENDOR_MISMATCH", "medium", f"{n.note_id} is from {n.vendor}, but {q.quote_id} was quoted by {q.vendor}"))
        if n.kind == "PROMPT_INJECTION":
            issues.append(_iss("PROMPT_INJECTION_DETECTED", "critical",
                               f"{n.note_id} contains embedded instructions ({', '.join(n.injection_matches)}); quarantined and ignored — no effect on rates or status"))
        elif n.kind == "SURCHARGE_CLAIM":
            note_amounts += n.amounts
            if not has_signed_exception(n):
                issues.append(_iss("UNAUTHORIZED_SURCHARGE", "high",
                                   f"{n.note_id} claims surcharge USD {', '.join(str(a) for a in n.amounts) or '?'} without signed exception; excluded from expected total"))
            else:
                issues.append(_iss("SURCHARGE_EXCEPTION_CLAIMED", "high", f"{n.note_id} cites a signed exception; verify document", True))
        elif n.kind == "DUPLICATE_NOTICE":
            issues.append(_iss("DUPLICATE_NOTICE", "info", f"{n.note_id} states duplicate/replacement of {', '.join(n.referenced_quote_ids) or 'a quote'}; not counted as an additional quotation"))
        elif n.kind == "RATE_CHANGE_NOTICE":
            issues.append(_iss("RATE_CHANGE_NOTICE_IGNORED", "info",
                               f"{n.note_id} ({n.note_date}) mentions a rate change; quote date {q.quote_date} governs (Rule 1)"))
        else:
            issues.append(_iss("VENDOR_NOTE", "low", f"{n.note_id} attached for reviewer context"))

    # --- history (context only, never a price authority)
    h = hist.get(q.quote_id)
    if h:
        evidence.append(h.evidence)
        if h.quoted_total is not None and q.quoted_total is not None and h.quoted_total != q.quoted_total:
            issues.append(_iss("HISTORY_MISMATCH", "low", f"Historical log shows USD {h.quoted_total} (context only)"))
        if (h.product_id or "").upper() == "UNMAPPED":
            issues.append(_iss("HISTORY_UNMAPPED", "info", "Historical log could not map this quote to a product"))

    # --- status
    blocking = any(i.blocking for i in issues)
    if blocking:
        status = "NEEDS_REVIEW"
    elif var is not None and exceeds_tolerance(var, s):
        status = "FLAG"
    else:
        status = "WITHIN_TOLERANCE"
    codes = list(dict.fromkeys(i.code for i in issues))
    if status == "WITHIN_TOLERANCE":
        codes = codes or ["WITHIN_TOLERANCE"]
    cites = idx.for_issues(codes + ([] if status != "WITHIN_TOLERANCE" else ["WITHIN_TOLERANCE"]))
    prio = _priority(status, issues, var, s)

    allowed: set[Decimal] = {s.tolerance}
    for v in [q.quoted_total, expected, var, *(note_amounts or [])]:
        if v is not None:
            allowed.add(abs(v))
    if calc:
        allowed |= {calc.metal, calc.setting, calc.labor, calc.subtotal, calc.handling, calc.finish, calc.unit_cost, calc.total}
    if rate:
        allowed |= {rate.metal_usd_per_gram, rate.setting_usd_per_stone, rate.labor_usd_per_unit, rate.finish_rhodium_usd_per_unit}
    for i in issues:
        for tok in re.findall(r"USD (\d+(?:\.\d+)?)", i.message):
            allowed.add(Decimal(tok))

    facts = {
        "quote_id": q.quote_id, "status": status, "priority": prio, "vendor": q.vendor, "quote_date": str(q.quote_date),
        "po_line": m.po_line_key or m.proposed_po_line_key, "po_product": po.description if po else None,
        "quoted": str(q.quoted_total) if q.quoted_total is not None else None, "expected": str(expected) if expected is not None else None,
        "variance": str(var) if var is not None else None, "tolerance": str(s.tolerance),
        "rate": (f"{rate.rate_id} ({rate.effective_from}..{rate.effective_to})" if rate else None),
        "calculation": ({k: str(v) for k, v in calc.model_dump(include={'metal', 'setting', 'labor', 'handling', 'finish', 'unit_cost', 'qty'}).items()} if calc else None),
        "hypotheses": hyps, "issues": [{"code": i.code, "message": i.message, "blocking": i.blocking} for i in issues],
        "match": {"method": m.method, "confidence": m.confidence, "trustworthy": m.trustworthy},
    }
    facts["template"] = _template(facts)
    facts["allowed_amounts"] = allowed

    fp = _fingerprint(q.model_dump(exclude={"evidence"}), po.model_dump(exclude={"evidence"}) if po else None,
                      rate.model_dump(exclude={"evidence"}) if rate else None, m.po_line_key, s.config_hash)
    finding = Finding(
        quote_id=q.quote_id, po_line_id=(po.line_id if (po and m.trustworthy) else None), po_id=q.po_id, vendor=q.vendor,
        quote_date=str(q.quote_date) if q.quote_date else None, description=q.description, status=status, priority=prio,  # type: ignore[arg-type]
        quoted_total_usd=_f(q.quoted_total), expected_total_usd=_f(expected), variance_usd=_f(var),
        variance_pct=(float(money(var / expected * 100, s)) if (var is not None and expected) else None),
        matched_rate_id=rate.rate_id if (rate and m.trustworthy) else None, issue_codes=codes, issues=issues,
        evidence=evidence, match=m, calculation=calc, hypotheses=hyps, policy_citations=cites, notes=note_lines,
        ai_explanation=facts["template"], explanation_source="template", fingerprint=fp,
    )
    return finding, facts


# --------------------------------------------------------------------------- run
def run_audit(data_dir: Path | str, settings: Settings | None = None, llm: LLMSettings | None = None,
              ai: AIService | None = None, explain: bool | None = None) -> AuditRun:
    started = datetime.now(timezone.utc)
    s = settings or load_settings()
    llm = llm or load_llm_settings()
    ai = ai or AIService(llm, s)
    data_dir = Path(data_dir)
    b = load_bundle(data_dir)
    notes = classify_notes(b.notes, s)

    # AI-assisted extraction for PDF pages the deterministic parser could not read
    llm_records = []
    for page in b.unparsed_pages:
        llm_records += ai.extract(page)
    issues = list(b.issues)
    quotes = reconcile(b.csv_quotes + b.pdf_quotes + llm_records, issues)

    idx = PolicyIndex(b.policy)
    hist = {h.quote_id: h for h in b.history}

    decided = {q.quote_id: _decide_match(q, b.po_lines, ai, s) for q in quotes}
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for q in quotes:
        m = decided[q.quote_id][0]
        if m.trustworthy and m.po_line_key:
            counts[(m.po_line_key, norm_vendor(q.vendor))] += 1
    dup_keys = {k for (k, _), n in counts.items() if n > 1}

    findings, facts = [], []
    for q in quotes:
        m, po, _ = decided[q.quote_id]
        f, fa = _build_finding(q, m, po, b, notes, hist, dup_keys, idx, s)
        findings.append(f)
        facts.append(fa)

    do_explain = llm.explain if explain is None else explain
    if do_explain and ai.enabled:
        clause_txt = "\n".join(f"{c.rule_id} | {c.title}: {c.text}" for c in b.policy)
        expl = ai.explain(facts, clause_txt)
        for f in findings:
            text, src = expl[f.quote_id]
            f.ai_explanation, f.explanation_source = text, src

    order = {"P1": 0, "P2": 1, "P3": 2}
    findings.sort(key=lambda f: (order[f.priority], -abs(f.variance_usd or 0), f.quote_id))
    matched = {f.match.po_line_key for f in findings if f.match.trustworthy}
    unquoted = [p.key for p in b.po_lines if p.key not in matched]

    run = AuditRun(
        run_id=started.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6], started_at=started.isoformat(timespec="seconds"),
        finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), data_dir=str(data_dir), provider=ai.name,
        config_hash=s.config_hash, settings=s, file_hashes=b.file_hashes, findings=findings, notes=notes,
        ingestion_issues=issues, ai_events=ai.events, quotes=quotes, po_lines=b.po_lines, rates=b.rates, unquoted_po_lines=unquoted,
    )
    run.metrics = compute_metrics(run, source_records=len(b.csv_quotes) + len(b.pdf_quotes) + len(llm_records))
    return run


def compute_metrics(run: AuditRun, source_records: int = 0) -> dict[str, Any]:
    fs = run.findings
    by_status: dict[str, int] = defaultdict(int)
    for f in fs:
        by_status[f.status] += 1
    over = sum((Decimal(str(f.variance_usd)) for f in fs if f.variance_usd and f.variance_usd > 0), Decimal(0))
    under = sum((Decimal(str(f.variance_usd)) for f in fs if f.variance_usd and f.variance_usd < 0), Decimal(0))
    return {
        "quotations": len(fs), "source_records": source_records,
        "flag": by_status["FLAG"], "needs_review": by_status["NEEDS_REVIEW"], "within_tolerance": by_status["WITHIN_TOLERANCE"],
        "p1": sum(f.priority == "P1" for f in fs),
        "quoted_total_usd": float(sum((Decimal(str(f.quoted_total_usd)) for f in fs if f.quoted_total_usd is not None), Decimal(0))),
        "expected_total_usd": float(sum((Decimal(str(f.expected_total_usd)) for f in fs if f.expected_total_usd is not None), Decimal(0))),
        "overquote_usd": float(over), "underquote_usd": float(under),
        "injections_detected": sum(n.injection_detected for n in run.notes), "notes": len(run.notes),
        "ingestion_errors": sum(i.severity.value == "error" for i in run.ingestion_issues),
        "ai_calls_ok": sum(e.status == "ok" for e in run.ai_events), "ai_errors": sum(e.status == "error" for e in run.ai_events),
        "ai_rejections": sum(e.status == "rejected" for e in run.ai_events),
        "auto_approved": 0,
    }
