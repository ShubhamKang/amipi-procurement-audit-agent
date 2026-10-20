"""AMIPI Quotation Audit — Streamlit web interface.

Run:  streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
sys.path[:0] = [str(APP_DIR), str(ROOT / "src")]

from audit_agent.config import default_data_dir, default_db_path, load_llm_settings, load_settings  # noqa: E402
from audit_agent.export import findings_frame, to_csv, to_json, to_xlsx  # noqa: E402
from audit_agent.pipeline import run_audit  # noqa: E402
from audit_agent.store import DECISIONS, ReviewError, ReviewStore  # noqa: E402

import views as V  # noqa: E402
from theme import CSS, EMERALD, RUBY, SAPPHIRE, TOPAZ, diamond, esc  # noqa: E402

st.set_page_config(page_title="AMIPI · Quotation Audit Atelier", page_icon="💎", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)


# ----------------------------------------------------------------------------- state
@st.cache_resource
def store() -> ReviewStore:
    return ReviewStore(default_db_path())


def save_uploads(files) -> Path:
    d = Path(tempfile.mkdtemp(prefix="amipi_upload_"))
    for f in files:
        name = Path(f.name).name  # strip any path components
        sub = d / ("Contracts" if "policy" in name.lower() or "contract" in name.lower() else "Quotations" if name.lower().endswith(".pdf") else "")
        sub.mkdir(parents=True, exist_ok=True)
        (sub / name).write_bytes(f.getbuffer())
    return d


def execute(data_dir: Path, provider: str, overrides: dict, explain: bool):
    s = load_settings(overrides=overrides or None)
    with st.spinner("Assaying quotations… ingesting, matching, pricing and explaining"):
        run = run_audit(data_dir, s, load_llm_settings(provider), explain=explain)
    store().save_run(run)
    st.session_state.run = run
    st.session_state.selected = run.findings[0].quote_id if run.findings else None


# ----------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown(f'<div style="display:flex;gap:10px;align-items:center">{diamond(34, "s")}'
                '<div><div class="wordmark">AMIPI</div>'
                '<div style="font-size:.72rem;letter-spacing:2px">AUDIT ATELIER</div></div></div>', unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("### Audit run")
    llm_env = load_llm_settings()
    options = ["gemini", "mock", "none"]
    provider = st.selectbox("AI provider", options, index=options.index(llm_env.provider) if llm_env.provider in options else 1,
                            help="gemini = Google Gemini API · mock = offline deterministic stand-in · none = rules only")
    if provider == "gemini" and not llm_env.api_key:
        st.warning("GEMINI_API_KEY not set in .env — the run will fall back to the offline mock provider.")
    explain = st.toggle("AI explanations", value=True, help="Narrative only; validated against computed numbers")
    source = st.radio("Documents", ["Supplied sample package", "Upload files"], horizontal=False)
    uploads = None
    if source == "Upload files":
        uploads = st.file_uploader("XLSX / CSV / PDF", type=["xlsx", "csv", "pdf"], accept_multiple_files=True)

    with st.expander("Live rule changes"):
        base = load_settings()
        tol = st.number_input("Tolerance (USD)", value=float(base.tolerance), min_value=0.0, step=0.01, format="%.2f")
        rounding = st.selectbox("Rounding", ["ROUND_HALF_UP", "ROUND_HALF_EVEN", "ROUND_UP", "ROUND_DOWN"])
        sel_date = st.selectbox("Rate applicability date", ["quote_date", "po_due_date"])
        overrides = {}
        if abs(tol - float(base.tolerance)) > 1e-9:
            overrides["tolerance_usd"] = f"{tol:.2f}"
        if rounding != base.rounding_mode:
            overrides["rounding_mode"] = rounding
        if sel_date != base.rate_selection_date:
            overrides["rate_selection_date"] = sel_date
        if overrides:
            st.caption(f"Overrides: {overrides}")

    if st.button("✦ Run audit", type="primary"):
        if source == "Upload files" and not uploads:
            st.error("Upload at least one file.")
        else:
            execute(save_uploads(uploads) if uploads else default_data_dir(), provider, overrides, explain)
    st.markdown("---")
    st.caption("Supplier documents are treated as untrusted data. No quotation is ever approved automatically.")

if "run" not in st.session_state:
    execute(default_data_dir(), provider, {}, explain)

run = st.session_state.run
store().apply(run.findings)
M = run.metrics

# ----------------------------------------------------------------------------- hero
st.markdown(f"""
<div class="hero"><div class="row">
  {diamond(50, "h")}
  <div><div class="eyebrow">AMIPI · Procurement Audit · Fine Jewellery</div><h1>Quotation Audit Atelier</h1>
  <div class="tag">Every carat, gram and setting — reconciled against policy, with evidence you can trace.</div></div>
  <div class="meta">Run <b>{esc(run.run_id)}</b><br>AI provider <b>{esc(run.provider)}</b><br>
  Rules <b>{esc(run.config_hash)}</b> · tolerance <b>${run.settings.tolerance}</b> · {esc(run.settings.rounding_mode)}</div>
</div></div>""", unsafe_allow_html=True)

pending = sum(f.human_review.decision == "pending" for f in run.findings)
st.markdown(V.kpi_row([
    V.kpi("Quotations", str(M["quotations"]), f"from {M['source_records']} records, de-duplicated"),
    V.kpi("Flagged", str(M["flag"]), "ruby · above tolerance", RUBY),
    V.kpi("Needs review", str(M["needs_review"]), "topaz · insufficient evidence", TOPAZ),
    V.kpi("Within tolerance", str(M["within_tolerance"]), "emerald · awaiting sign-off", EMERALD),
    V.kpi("Net overquote", f"${M['overquote_usd']:,.2f}", f"underquotes −${abs(M['underquote_usd']):,.2f}", RUBY),
    V.kpi("Pending review", str(pending), f"auto-approved: {M['auto_approved']}", SAPPHIRE),
]), unsafe_allow_html=True)

if M["injections_detected"]:
    st.markdown(f'<div class="ev warn"><div class="src">Security</div><div class="q">{M["injections_detected"]} vendor note(s) contained embedded instructions. '
                'They were quarantined, never sent to the model, and had no effect on rates, totals or status.</div></div>', unsafe_allow_html=True)

tab_f, tab_r, tab_n, tab_s, tab_x = st.tabs(["Findings", "Review ledger", "Vendor notes & security", "Sources & AI log", "Export"])

# ----------------------------------------------------------------------------- findings
with tab_f:
    df = findings_frame(run.findings)
    c1, c2, c3, c4 = st.columns([2.2, 1.4, 1.4, 1.4])
    q = c1.text_input("Search", placeholder="quote, vendor, item, issue code…", label_visibility="collapsed")
    st_f = c2.multiselect("Status", ["FLAG", "NEEDS_REVIEW", "WITHIN_TOLERANCE"], placeholder="All statuses")
    pr_f = c3.multiselect("Priority", ["P1", "P2", "P3"], placeholder="All priorities")
    vn_f = c4.multiselect("Vendor", sorted(df["vendor"].dropna().unique()), placeholder="All vendors")
    view = df
    if q:
        mask = view.apply(lambda r: q.lower() in " ".join(str(v) for v in r.values).lower(), axis=1)
        view = view[mask]
    if st_f:
        view = view[view["status"].isin(st_f)]
    if pr_f:
        view = view[view["priority"].isin(pr_f)]
    if vn_f:
        view = view[view["vendor"].isin(vn_f)]
    gem = {"FLAG": "♦ Ruby · FLAG", "NEEDS_REVIEW": "♦ Topaz · NEEDS REVIEW", "WITHIN_TOLERANCE": "♦ Emerald · OK"}
    table = view[["priority", "status", "quote_id", "vendor", "po_line_id", "description", "quoted_total_usd",
                  "expected_total_usd", "variance_usd", "matched_rate_id", "issue_codes", "review_decision"]].copy()
    table["status"] = table["status"].map(gem)
    sel = st.dataframe(
        table, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", height=min(460, 38 + 35 * len(table)),
        column_config={
            "priority": st.column_config.TextColumn("Pri", width="small"),
            "status": st.column_config.TextColumn("Status"),
            "quote_id": "Quote", "vendor": "Vendor", "po_line_id": st.column_config.TextColumn("PO line", width="small"),
            "description": st.column_config.TextColumn("Item", width="medium"),
            "quoted_total_usd": st.column_config.NumberColumn("Quoted", format="$%.2f"),
            "expected_total_usd": st.column_config.NumberColumn("Expected", format="$%.2f"),
            "variance_usd": st.column_config.NumberColumn("Variance", format="$%+.2f"),
            "matched_rate_id": "Rate", "issue_codes": st.column_config.TextColumn("Issues", width="medium"),
            "review_decision": "Review",
        })
    rows = sel.selection.rows if sel and sel.selection else []
    if rows:
        st.session_state.selected = table.iloc[rows[0]]["quote_id"]
    ids = [f.quote_id for f in run.findings]
    cur = st.session_state.get("selected") or (ids[0] if ids else None)
    if cur:
        cur = st.selectbox("Inspect quotation", ids, index=ids.index(cur) if cur in ids else 0)
        f = run.finding(cur)
        st.markdown('<div class="ornament">◆ ◇ ◆</div>', unsafe_allow_html=True)
        st.markdown(V.header_panel(f), unsafe_allow_html=True)
        st.markdown(V.explanation_html(f), unsafe_allow_html=True)
        st.write("")
        a, b = st.columns([1, 1])
        with a:
            st.markdown(V.calc_panel(f), unsafe_allow_html=True)
            st.markdown(V.facts_panel(f), unsafe_allow_html=True)
        with b:
            st.markdown(V.issues_html(f), unsafe_allow_html=True)
            st.markdown(V.citations_html(f), unsafe_allow_html=True)
        st.markdown(V.evidence_html(f), unsafe_allow_html=True)

        # ---------------- review form
        st.markdown('<div class="panel"><h3>Reviewer decision</h3><div class="muted">Decisions are appended to a persistent ledger. '
                    'Calculated values are never modified; an optional override is stored separately.</div></div>', unsafe_allow_html=True)
        with st.form(f"review_{f.quote_id}", clear_on_submit=True):
            r1, r2 = st.columns([1, 1])
            decision = r1.selectbox("Decision", DECISIONS, format_func=lambda d: d.replace("_", " ").title())
            reviewer = r2.text_input("Reviewer name")
            reason = st.text_area("Justification", placeholder="Why is this decision appropriate? Reference evidence or rules.")
            ov = st.checkbox("Record a human override of the expected total")
            override = st.number_input("Override expected total (USD)", min_value=0.0, step=0.01, format="%.2f") if ov else None
            if st.form_submit_button("Record decision"):
                try:
                    hr = store().record(f, decision, reviewer, reason, run.run_id, override)
                    st.success(f"Recorded '{hr.decision}' for {f.quote_id} by {hr.reviewer} at {hr.timestamp}")
                    st.rerun()
                except ReviewError as e:
                    st.error(str(e))
        hist = store().history(f.quote_id)
        if hist:
            st.dataframe(pd.DataFrame(hist)[["timestamp", "decision", "reviewer", "reason", "override_expected_total_usd", "status_at_review"]],
                         hide_index=True, width="stretch")

# ----------------------------------------------------------------------------- ledger
with tab_r:
    hist = store().history()
    st.markdown(f'<div class="panel"><h3>Review ledger</h3><div class="muted">{len(hist)} decision(s) recorded · append-only · '
                'stale decisions (inputs or rules changed since review) revert the finding to pending.</div></div>', unsafe_allow_html=True)
    if hist:
        st.dataframe(pd.DataFrame(hist), hide_index=True, width="stretch")
    else:
        st.info("No decisions recorded yet. Select a finding and record a decision.")

# ----------------------------------------------------------------------------- notes
with tab_n:
    for n in run.notes:
        warn = n.injection_detected
        body = ("[QUARANTINED — embedded instructions detected: " + esc(", ".join(n.injection_matches)) + "] ") if warn else ""
        st.markdown(f'<div class="ev {"warn" if warn else ""}"><div class="src">{esc(n.note_id)} · {esc(n.vendor)} · {esc(n.note_date)} · '
                    f'{esc(n.po_id)}/{esc(n.line_id)} · {esc(n.kind)} · {esc(n.evidence.ref())}</div>'
                    f'<div class="q">{body}“{esc(n.text)}”</div></div>', unsafe_allow_html=True)
    st.markdown("""<div class="panel"><h3>How vendor content is isolated</h3><ol style="font-size:.9rem">
<li><b>Detection</b> — configurable patterns flag imperative or approval-manipulating text.</li>
<li><b>Quarantine</b> — flagged text is never sent to the model.</li>
<li><b>Spotlighting</b> — other document text is wrapped in &lt;untrusted_document&gt; tags; the system prompt declares it data only.</li>
<li><b>No capability</b> — model output schemas have no status, price or approval fields; only humans approve.</li>
<li><b>Output checks</b> — explanations quoting amounts not in the computed facts, or asserting approval, are rejected.</li></ol></div>""",
                unsafe_allow_html=True)

# ----------------------------------------------------------------------------- sources
with tab_s:
    a, b = st.columns(2)
    with a:
        st.markdown("#### Ingestion report")
        if run.ingestion_issues:
            st.dataframe(pd.DataFrame([i.model_dump(mode="json") for i in run.ingestion_issues]), hide_index=True, width="stretch")
        else:
            st.success("All documents ingested without errors.")
        st.markdown("#### Files (SHA-256 prefix)")
        st.dataframe(pd.DataFrame([{"file": k, "sha256": v} for k, v in run.file_hashes.items()]), hide_index=True, width="stretch")
        if run.unquoted_po_lines:
            st.warning("PO lines without a trustworthy quotation: " + ", ".join(run.unquoted_po_lines))
    with b:
        st.markdown("#### AI activity")
        if run.ai_events:
            st.dataframe(pd.DataFrame([e.__dict__ for e in run.ai_events]), hide_index=True, width="stretch")
        st.markdown("#### Rate cards")
        st.dataframe(pd.DataFrame([{k: str(v) for k, v in r.model_dump(exclude={"evidence"}).items()} for r in run.rates]),
                     hide_index=True, width="stretch")

# ----------------------------------------------------------------------------- export
with tab_x:
    st.markdown('<div class="panel"><h3>Download the audit dossier</h3><div class="muted">Exports include variance, applicable rate, '
                'issue codes, source evidence, policy citations and the latest reviewer decision.</div></div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.download_button("⬇ Excel workbook", to_xlsx(run, store().history()), f"amipi_audit_{run.run_id}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    c2.download_button("⬇ CSV findings", to_csv(run), f"amipi_audit_{run.run_id}.csv", "text/csv")
    c3.download_button("⬇ JSON report", to_json(run), f"amipi_audit_{run.run_id}.json", "application/json")

st.markdown('<div class="footer">◆ AMIPI Audit Atelier · fictional assessment data · deterministic pricing, AI-assisted reconciliation, human approval ◆</div>',
            unsafe_allow_html=True)
