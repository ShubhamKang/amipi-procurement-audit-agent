# AMIPI Procurement & Quotation Audit Agent

An auditable web tool that reconciles supplier quotations (PDF + register CSV) against purchase orders, vendor rate cards and the binding procurement policy. It computes the policy price exactly, explains every discrepancy with traceable evidence and policy citations, and records human review decisions. **Nothing is ever approved automatically.**

## 🔗 Live demo

**https://amipi-procurement-audit-agent-cjckcaeiqvvkjzmjbbmnmb.streamlit.app/**

Deployed on Streamlit Community Cloud. The app loads the supplied sample package and runs an audit automatically.
If a password prompt appears, use the `APP_PASSWORD` shared with the reviewer. (Streamlit free-tier apps sleep when
idle — the first load may take ~30s to wake. Review decisions are not persisted across restarts on the free tier;
see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).)


- Deterministic `Decimal` engine is the only source of monetary values.
- AI (Google Gemini) is used for semantic product matching, fallback PDF extraction and reviewer-facing explanations; every AI output is validated and can be disabled or mocked.
- Supplier text is treated as untrusted data; embedded instructions are detected and quarantined.

Architecture diagram and design notes: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quick start

Requires Python 3.11+ (developed on 3.13).

```bash
git clone https://github.com/ShubhamKang/amipi-procurement-audit-agent.git
cd amipi-procurement-audit-agent
python -m venv .venv && source .venv/bin/activate      # or: uv venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
cp .env.example .env                                     # then edit (see below)

streamlit run app/streamlit_app.py                       # web UI  -> http://localhost:8501
audit run --out sample_output                            # CLI batch run + JSON/CSV/XLSX reports
pytest                                                   # 91 tests, fully offline
python eval/run_eval.py --provider mock                  # evaluation report (supplied + 120 synthetic)
```

### Environment variables (`.env`, never committed)

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `mock` | `gemini` (remote), `mock` (offline deterministic stand-in), `none` (rules only, no AI) |
| `GEMINI_API_KEY` | – | Free key from https://aistudio.google.com → *Get API key* |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Any current free-tier Flash / Flash-Lite model id |
| `LLM_TIMEOUT_S` / `LLM_MAX_RETRIES` | `30` / `3` | Per-call timeout, retries with exponential backoff on 429/5xx |
| `LLM_MIN_INTERVAL_S` | `4.5` | Client-side throttle to respect free-tier RPM |
| `LLM_EXPLAIN` | `1` | Set `0` to skip AI explanations (deterministic templates only) |
| `LLM_CACHE_PATH` | `runs/llm_cache.json` | Response cache (saves quota, reproducible demos) |
| `DATA_DIR` / `DB_PATH` | `Data` / `runs/audit.db` | Input folder / SQLite review ledger |

If `LLM_PROVIDER=gemini` but the key is missing or invalid, the app logs a warning and falls back to the mock provider; if Gemini fails mid-run (quota, network) a circuit breaker switches to deterministic fallbacks and affected matches become `NEEDS_REVIEW`.

### CLI

```bash
audit run [--data DIR] [--provider gemini|mock|none] [--config alt_policy.yaml] [--no-explain] [--out DIR]
audit review Q-003 --decision rejected --reviewer "A. Shah" --reason "Overquote not justified by supplier"
audit history [--quote-id Q-003]
```

## What it does (workflow)

1. **Ingest** XLSX, CSV and PDFs with provenance (file · sheet/page · row/lines) and an ingestion failure report.
2. **Normalize & reconcile** PDF (primary) and register (secondary) records into one business quotation per `quote_id` — 24 source records → 12 quotations, no double counting. Disagreements on money/identity fields → `SOURCE_CONFLICT` → `NEEDS_REVIEW`.
3. **Match** quotation lines to PO lines: SKU/PO/line/attribute rules first; Gemini resolves SKU-less, shorthand descriptions (`14k YG emerald cut studs`, `18K RG huggies`). Disagreement or low confidence → `NEEDS_REVIEW`.
4. **Select rate** by vendor + metal grade + **quote date** (Rule 1); overlapping or missing rates → `NEEDS_REVIEW`.
5. **Compute** the expected total exactly (Rules 2-7, `ROUND_HALF_UP`, pair = one unit) and compare with tolerance (Rule 8).
6. **Diagnose** variances deterministically (e.g. *"Rhodium charged although PO finish is Standard; settings counted per earring"*) — hypotheses only.
7. **Retrieve** policy clauses (BM25 over parsed rules) and cite them by file/page/rule.
8. **Explain** (Gemini, validated) and **review**: reviewer, decision, justification and timestamp go to an append-only SQLite ledger; export CSV / XLSX / JSON.

### Results on the supplied package

| Quote | PO line | Rate | Quoted | Expected | Variance | Status | Key issues |
|---|---|---|---:|---:|---:|---|---|
| Q-001 | L01 | A-OLD | 409.32 | 409.32 | 0.00 | WITHIN_TOLERANCE | X-04 rate-change notice ignored (quote date governs) |
| Q-002 | L02 | B-14 | 604.44 | 544.47 | +59.97 | FLAG | Rhodium not on PO + settings counted per earring |
| Q-003 | L03 | C-14 | 714.92 | 594.92 | +120.00 | FLAG | Unexplained overquote |
| Q-004 | L04 | A-OLD18 | 687.96 | 687.96 | 0.00 | WITHIN_TOLERANCE | – |
| Q-005 | L05 | B-14 | 394.83 | 309.83 | +85.00 | FLAG | X-01 unsigned surcharge claim (excluded) |
| Q-006 | L06 | C-18 | 1110.00 | 1070.00 | +40.00 | FLAG | No SKU (AI match), X-02 duplicate notice (not counted) |
| Q-007 | L07 | A-NEW14 | 798.90 | 728.90 | +70.00 | FLAG | X-03 **prompt injection detected & quarantined** |
| Q-008 | L08 | B-18 | 845.84 | 845.84 | 0.00 | WITHIN_TOLERANCE | – |
| Q-009 | L09 | C-14 | 510.72 | 530.72 | −20.00 | FLAG | Underquote (identified, not rejected) |
| Q-010 | L10 | A-NEW14 | 241.16 | 226.16 | +15.00 | FLAG | No SKU (AI match), Rhodium charged but PO is Standard |
| Q-011 | L11 | B-18 | 716.80 | 681.80 | +35.00 | FLAG | Overquote |
| Q-012 | L12 | C-14 | 593.56 | 543.56 | +50.00 | FLAG | Overquote |

Full reports: [`sample_output/`](sample_output) (`audit_report.json`, `audit_findings.csv`, `audit_report.xlsx`). `WITHIN_TOLERANCE` items still require a human decision.

## Output schema & deviations from `Expected_Output_Schema.json`

All example fields are present with the same names and types. Deviations:

- `status` values are `FLAG`, `NEEDS_REVIEW`, `WITHIN_TOLERANCE` (the latter means "no discrepancy found — still pending human approval"; there is deliberately no `APPROVED` status from the system).
- `po_line_id` and `matched_rate_id` are `null` when the match is not trustworthy, and `expected_total_usd`/`variance_usd` are `null` when the value cannot be determined (Rule 9 — no invented value).
- Extensions: `po_id`, `vendor`, `quote_date`, `priority` (P1–P3), `variance_pct`, `match` (method/confidence/rationale), `calculation` (component breakdown + inputs), `hypotheses`, `policy_citations`, `issues` (code/severity/message/blocking), `explanation_source`, `human_override_expected_total_usd` (kept separate from the calculated value), `review_stale`, `fingerprint`.
- `human_review.decision` ∈ `pending | approved | rejected | escalated | needs_info`.

## Live rule changes

Rules live in [`config/policy.yaml`](config/policy.yaml) (tolerance, rounding mode, per-component rounding, rate date basis, Rhodium trigger values, unit vocabularies, matching thresholds, injection patterns). The UI sidebar also exposes tolerance, rounding and rate-date overrides. Each run records a hash of the effective rules; previous review decisions become *stale* when rules or inputs change. Rate cards and PO data are read from the spreadsheets, so editing a row and re-running is enough.

## AI model choice, data sent and cost

- **Model:** Gemini 3.5 Flash-Lite (configurable; `gemini-2.5-flash-lite` is no longer available to new keys). Chosen because it has a free tier (no billing needed for this assessment), supports JSON-schema structured output, low latency, and the tasks (short classification/extraction/summary) do not need a large model. Temperature 0.
- **Data transmitted** (only when `LLM_PROVIDER=gemini`): quotation line text (vendor, PO, SKU, description, qty) for SKU-less matches; PO line descriptions of candidate lines; policy clause text; computed finding facts for explanations; text of PDF pages the deterministic parser could not read. Pages containing detected injections are never sent. No API keys or reviewer data are sent. Note that Google may use free-tier prompts to improve its products — fine for this fictional data; use a paid tier or `mock`/`none` for real data.
- **Calls per run (supplied data):** 2 match calls + 1 batched explanation call (≈ 6–8k tokens total); cached on re-runs.
- **Approximate cost:** $0 on the free tier. On paid Flash-Lite pricing (~$0.10 / 1M input, ~$0.40 / 1M output tokens; check Google's pricing page) a 12-quote run is ≈ $0.001 and 1,000 quotations ≈ $0.10–0.30.

## Security & privacy

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#security). Summary: injection detection + quarantine, spotlighting in `<untrusted_document>` tags, output schemas with no status/price/approval fields, output validation (no unknown match keys, no ungrounded extracted values, no amounts absent from computed facts, no approval claims), HTML-escaping of all document text in the UI, secrets only in `.env` (git-ignored), uploads written to a temp folder with path components stripped. The UI has **no authentication** — run it locally or behind an authenticated proxy; reviewer names are self-declared.

## Testing & evaluation

`pytest` runs 91 offline tests: calculation and rounding, effective-date precedence (boundaries, overlaps, expiry), ingestion, de-duplication, gold results for all 12 supplied quotes, failure cases (missing files, corrupt PDF, malformed amounts, ambiguous dates/units, qty mismatch, source conflicts, LLM outages), prompt-injection and hostile-model simulations, review store persistence/staleness, exports, and a 100-record batch gate. Evaluation results and failure analysis: [docs/EVALUATION.md](docs/EVALUATION.md).

## Project layout

```
app/                 Streamlit UI (streamlit_app.py, views.py, theme.py)
config/policy.yaml   audit rules (live-editable)
src/audit_agent/     ingest/, reconcile, match, rates, calc, diagnostics, notes, security,
                     policy_rag, llm/ (providers, prompts, schemas, service), pipeline, store, export, cli
tests/               unit, integration, failure, security, batch tests + gold answers
eval/                synth.py (synthetic package generator), run_eval.py (metrics)
docs/                ARCHITECTURE.md, EVALUATION.md
sample_output/       reports produced from the supplied inputs
Data/                supplied fictional input package
```

## Limitations / not implemented

- No OCR: scanned PDFs without a text layer are reported (`NO_TEXT_LAYER`) and their lines would need manual entry.
- The deterministic PDF parser targets the supplied layout; other layouts rely on AI extraction (grounded but less certain, flagged `AI_EXTRACTED`).
- Live Gemini was evaluated on the supplied set and 120 synthetic records (see EVALUATION.md); quality on other models is not measured. Free-tier rate limits make large batches slow (~1 s/record incl. throttle; use `--no-explain` or `--provider none` for big batches).
- No authentication/role-based approval; single-user SQLite ledger (fine locally, not for concurrent multi-user use).
- No FX conversion (non-USD quotes → `NEEDS_REVIEW`), no multi-currency rate cards.
- Surcharge exceptions are detected from note text only; there is no signed-exception document registry.
- Policy retrieval is BM25 over 10 parsed rules (sufficient here; a larger corpus would merit embeddings).
