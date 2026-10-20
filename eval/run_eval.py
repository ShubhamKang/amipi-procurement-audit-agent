"""Evaluation: extraction / matching precision & recall, calculation accuracy, status accuracy, safety gates.

Usage:  python eval/run_eval.py [--provider mock|none|gemini] [--n 120]
Writes eval/results.json and prints a markdown summary.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "eval")]

from audit_agent.config import load_llm_settings, load_settings  # noqa: E402
from audit_agent.ingest import load_bundle  # noqa: E402
from audit_agent.pipeline import run_audit  # noqa: E402

import synth  # noqa: E402

SUPPLIED_GOLD = json.loads((ROOT / "tests" / "gold" / "supplied_gold.json").read_text())
FIELDS = ["quote_date", "po_id", "vendor_sku", "qty", "unit", "total"]


def _pr(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return {"precision": round(p, 4), "recall": round(r, 4), "tp": tp, "fp": fp, "fn": fn}


def _norm(field, v):
    if v in (None, ""):
        return None
    if field in ("qty", "total"):
        return str(Decimal(str(v)).normalize())
    return str(v).strip().upper()


def extraction_metrics(data_dir: Path, gold: dict) -> dict:
    """PDF extraction vs gold fields (register is NOT used as truth for PDFs)."""
    b = load_bundle(data_dir)
    pdf = {q.quote_id: q for q in b.pdf_quotes}
    tp = fp = fn = 0
    errors = []
    for qid, g in gold.items():
        q = pdf.get(qid)
        for f in FIELDS:
            gv = _norm(f, g["fields"].get(f))
            pv = None if q is None else _norm(f, getattr(q, "quoted_total" if f == "total" else f))
            if pv is not None and pv == gv:
                tp += 1
            elif pv is not None and gv is not None:
                fp += 1; fn += 1; errors.append(f"{qid}.{f}: got {pv} want {gv}")
            elif pv is not None:
                fp += 1; errors.append(f"{qid}.{f}: spurious {pv}")
            elif gv is not None:
                fn += 1; errors.append(f"{qid}.{f}: missing")
    spurious = [qid for qid in pdf if qid not in gold]
    fp += len(spurious)
    return {**_pr(tp, fp, fn), "quotes_found": len(pdf), "quotes_expected": len(gold), "spurious_quotes": spurious, "errors": errors[:10]}


def audit_metrics(run, gold: dict) -> dict:
    mtp = mfp = mfn = 0
    calc_ok = calc_n = status_ok = 0
    unsafe, wrong_match, abstained, calc_err, status_err = [], [], [], [], []
    for qid, g in gold.items():
        f = run.finding(qid)
        if f is None:
            mfn += 1; continue
        pred = f.match.po_line_key if f.match.trustworthy else None
        if pred == g["po_line"]:
            mtp += 1
        elif pred is None:
            mfn += 1; abstained.append(qid)
        else:
            mfp += 1; mfn += 1; wrong_match.append(f"{qid}: {pred} != {g['po_line']}")
        if g["expected"] is not None and f.expected_total_usd is not None:
            calc_n += 1
            if Decimal(str(f.expected_total_usd)) == Decimal(g["expected"]):
                calc_ok += 1
            else:
                calc_err.append(f"{qid}: {f.expected_total_usd} != {g['expected']}")
        if f.status == g["status"]:
            status_ok += 1
        else:
            status_err.append(f"{qid}: {f.status} != {g['status']} ({g.get('scenario', '')})")
            if f.status == "WITHIN_TOLERANCE":
                unsafe.append(qid)  # a real discrepancy/uncertainty shown as clean = critical
    n = len(gold)
    gold_calc = sum(1 for g in gold.values() if g["expected"] is not None)
    return {
        "matching": _pr(mtp, mfp, mfn) | {"abstained": abstained[:10], "wrong": wrong_match[:10]},
        "calculation": {"accuracy_on_computed": round(calc_ok / calc_n, 4) if calc_n else None, "computed": calc_n,
                        "gold_computable": gold_calc, "coverage": round(calc_n / gold_calc, 4) if gold_calc else None, "errors": calc_err[:10]},
        "status_accuracy": round(status_ok / n, 4), "status_errors": status_err[:10],
        "unsafe_within_tolerance": unsafe, "auto_approved": run.metrics["auto_approved"],
        "injections_detected": run.metrics["injections_detected"], "ai_events": {
            s: sum(e.status == s for e in run.ai_events) for s in ("ok", "rejected", "error", "fallback", "disabled")},
    }


def evaluate(provider: str, n: int) -> dict:
    s = load_settings()
    res = {"provider": provider}
    t = time.time()
    run = run_audit(ROOT / "Data", s, load_llm_settings(provider))
    res["supplied"] = {"extraction": extraction_metrics(ROOT / "Data", SUPPLIED_GOLD), **audit_metrics(run, SUPPLIED_GOLD),
                       "seconds": round(time.time() - t, 2)}
    syn_dir = ROOT / "runs" / "synth"
    gold = synth.generate(n, syn_dir, seed=7)
    t = time.time()
    run = run_audit(syn_dir, s, load_llm_settings(provider), explain=False)
    res["synthetic"] = {"records": n, "extraction": extraction_metrics(syn_dir, gold), **audit_metrics(run, gold),
                        "seconds": round(time.time() - t, 2)}
    return res


def table(res: dict) -> str:
    rows = ["| Metric | Supplied (12) | Synthetic |", "|---|---|---|"]
    for name, key in [("Extraction precision", ("extraction", "precision")), ("Extraction recall", ("extraction", "recall")),
                      ("Matching precision", ("matching", "precision")), ("Matching recall", ("matching", "recall")),
                      ("Calc accuracy (computed)", ("calculation", "accuracy_on_computed")), ("Calc coverage", ("calculation", "coverage")),
                      ("Status accuracy", ("status_accuracy",)), ("Unsafe WITHIN_TOLERANCE", ("unsafe_within_tolerance",)),
                      ("Auto-approved", ("auto_approved",)), ("Runtime (s)", ("seconds",))]:
        vals = []
        for part in ("supplied", "synthetic"):
            v = res[part]
            for k in key:
                v = v[k]
            vals.append(str(len(v)) if isinstance(v, list) else str(v))
        rows.append(f"| {name} | {vals[0]} | {vals[1]} |")
    return "\n".join(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="mock")
    ap.add_argument("--n", type=int, default=120)
    a = ap.parse_args()
    r = evaluate(a.provider, a.n)
    out = ROOT / "eval" / f"results_{a.provider}.json"
    out.write_text(json.dumps(r, indent=2))
    print(f"## Evaluation ({a.provider})\n")
    print(table(r))
    for part in ("supplied", "synthetic"):
        for k in ("status_errors",):
            if r[part][k]:
                print(f"\n{part} {k}: {r[part][k]}")
        if r[part]["matching"]["abstained"]:
            print(f"{part} abstained: {r[part]['matching']['abstained']}")
        if r[part]["matching"]["wrong"]:
            print(f"{part} wrong matches: {r[part]['matching']['wrong']}")
    print(f"\nwrote {out}")
