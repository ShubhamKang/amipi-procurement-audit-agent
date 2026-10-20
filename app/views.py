"""Rendering helpers for the Streamlit UI (HTML snippets; all document text escaped)."""
from __future__ import annotations

from audit_agent.models import Finding

from theme import code_chip, decision_chip, esc, priority_chip, status_chip


def money(v: float | None) -> str:
    return "—" if v is None else f"${v:,.2f}"


def signed(v: float | None) -> str:
    return "—" if v is None else f"{'+' if v > 0 else '−' if v < 0 else '±'}${abs(v):,.2f}"


def var_class(v: float | None) -> str:
    if v is None:
        return ""
    return "var-pos" if v > 0.0 else "var-neg" if v < 0.0 else "var-zero"


def kpi(label: str, value: str, sub: str = "", accent: str = "#A8862F") -> str:
    return (f'<div class="kpi" style="--accent:{accent}"><div class="label">{esc(label)}</div>'
            f'<div class="value">{esc(value)}</div><div class="sub">{esc(sub)}</div></div>')


def kpi_row(cards: list[str]) -> str:
    return '<div class="kpis">' + "".join(cards) + "</div>"


def facet(label: str, value_html: str) -> str:
    return f'<div class="facet"><span>{esc(label)}</span><span>{value_html}</span></div>'


def header_panel(f: Finding) -> str:
    v = f.variance_usd
    return f"""
<div class="panel">
  <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
    <h3 style="margin:0">{esc(f.quote_id)} · {esc(f.vendor)}</h3>
    {status_chip(f.status)} {priority_chip(f.priority)} {decision_chip(f.human_review.decision, f.human_review.stale)}
  </div>
  <div class="muted" style="margin:6px 0 12px">{esc(f.description)}</div>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px">
    <div><div class="muted">Quoted total</div><div class="amount">{money(f.quoted_total_usd)}</div></div>
    <div><div class="muted">Policy-expected total</div><div class="amount">{money(f.expected_total_usd)}</div></div>
    <div><div class="muted">Variance</div><div class="amount {var_class(v)}">{signed(v)}
      <span class="muted" style="font-size:.85rem">{'' if f.variance_pct is None else f'({f.variance_pct:+.2f}%)'}</span></div></div>
  </div>
</div>"""


def facts_panel(f: Finding) -> str:
    m = f.match
    match_txt = esc(m.po_line_key or (f"proposed {m.proposed_po_line_key} (untrusted)" if m.proposed_po_line_key else "none"))
    return ('<div class="panel"><h3>Reconciliation</h3>'
            + facet("Purchase order", esc(f.po_id))
            + facet("Matched PO line", match_txt)
            + facet("Match method", esc(f"{m.method} · confidence {m.confidence:.2f}"))
            + facet("Applicable rate", esc(f.matched_rate_id or "—"))
            + facet("Quote date (governs rate)", esc(f.quote_date))
            + facet("Explanation source", esc(f.explanation_source))
            + f'<div class="muted" style="margin-top:8px">{esc(m.rationale)}</div></div>')


def calc_panel(f: Finding) -> str:
    c = f.calculation
    if not c:
        return '<div class="panel"><h3>Deterministic calculation</h3><div class="muted">No calculation: rate or PO line could not be determined. Status held at NEEDS_REVIEW; no value invented (Rule 9).</div></div>'
    i = c.inputs
    provisional = "" if f.expected_total_usd is not None else '<div class="ev warn"><div class="src">Provisional</div><div class="q">Match is not trustworthy; this breakdown is NOT used as the expected total.</div></div>'
    rows = [
        ("Metal", f"{i['metal_g']} g × ${i['metal_usd_per_gram']}/g", c.metal),
        ("Settings", f"{i['set_pcs']} stones × ${i['setting_usd_per_stone']}", c.setting),
        ("Labor", "once per finished unit", c.labor),
        ("Subtotal", "metal + settings + labor", c.subtotal),
        ("Handling", f"subtotal × {i['handling_rate']} ({i['rounding']})", c.handling),
        ("Rhodium finish", f"PO finish: {i['finish']}", c.finish),
        ("Unit cost", "per finished unit", c.unit_cost),
    ]
    body = "".join(f'<tr><td>{esc(a)}<div class="f">{esc(b)}</div></td><td>${float(v):,.2f}</td></tr>' for a, b, v in rows)
    body += f'<tr class="total"><td>Expected line total<div class="f">unit cost × qty {esc(i["qty"])}</div></td><td>${float(c.total):,.2f}</td></tr>'
    return f'<div class="panel"><h3>Deterministic calculation · {esc(c.rate_id)}</h3>{provisional}<table class="calc">{body}</table></div>'


def issues_html(f: Finding) -> str:
    chips = "".join(code_chip(i.code, i.severity) for i in f.issues) or code_chip("WITHIN_TOLERANCE")
    items = "".join(f'<li><b>{esc(i.code)}</b> — {esc(i.message)}{" <i>(blocking)</i>" if i.blocking else ""}</li>' for i in f.issues)
    hyp = "".join(f'<div class="ev"><div class="src">Hypothesis (reproduces quote exactly)</div><div class="q">{esc(h)}</div></div>' for h in f.hypotheses)
    notes = "".join(f'<li>{esc(n)}</li>' for n in f.notes)
    return (f'<div class="panel"><h3>Issues</h3><div>{chips}</div><ul style="margin-top:8px;font-size:.88rem">{items}</ul>{hyp}'
            + (f'<div class="muted"><ul>{notes}</ul></div>' if notes else "") + "</div>")


def evidence_html(f: Finding) -> str:
    out = []
    for e in f.evidence:
        cls = "ev warn" if "Additional_Review" in e.source_file else "ev"
        out.append(f'<div class="{cls}"><div class="src">{esc(e.source_file)} · {esc(e.sheet_or_page)} · {esc(e.row_or_line)}</div>'
                   f'<div class="q">“{esc(e.quote)}”</div></div>')
    return '<div class="panel"><h3>Source evidence</h3>' + "".join(out) + "</div>"


def citations_html(f: Finding) -> str:
    out = [f'<div class="ev cite"><div class="src">{esc(c.source_file)} · page {c.page} · {esc(c.rule_id)} — {esc(c.title)}</div>'
           f'<div class="q">{esc(c.excerpt)}</div></div>' for c in f.policy_citations]
    return '<div class="panel"><h3>Policy citations</h3>' + ("".join(out) or '<div class="muted">No clauses retrieved</div>') + "</div>"


def explanation_html(f: Finding) -> str:
    who = "AI explanation (validated)" if f.explanation_source not in ("template",) and "template" not in f.explanation_source else "Deterministic explanation"
    return (f'<div class="explain"><div class="who">{esc(who)} · {esc(f.explanation_source)}</div>{esc(f.ai_explanation)}'
            '<div class="muted" style="margin-top:6px;font-size:.78rem">Narrative only — amounts and status come from the deterministic engine.</div></div>')
