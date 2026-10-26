# Tasks — Nova 18K Bracelet Per-Unit Surcharge

Ordered checklist. Status: ALL PHASES COMPLETE (1-8).
Verified: full suite 141 passed (91 existing + 50 surcharge); live dataset yields
exactly 5 qualifiers [L01, L04, L07, L08, L11] with total surcharge $195.00.

## 1. Configuration
- [x] Add a `surcharge` block to `config/policy.yaml`: effective date,
      unit amount, qualifying metal aliases, bracelet-family categories.
- [x] Extend the `Settings` dataclass + `settings_from_dict` to parse it with
      backward-compatible safe defaults (so existing configs still load).
- [x] Confirm the new parameters are included in the per-run `config_hash`.

## 2. Eligibility predicate (pure, AI-independent)
- [x] Add a pure function (sibling to `is_rhodium`) that takes metal
      designation, category, PO date, quote date, and `Settings` and returns a
      structured decision (qualifies + reason + checked facts). -> surcharge.py:is_eligible
- [x] Implement metal alias matching (`18K`, `18KT`, `18K <color/finish>`).
- [x] Implement bracelet-family matching (Bracelet / Tennis / Bangle).
- [x] Implement the inclusive dual date gate.

## 3. Surcharge amount (deterministic, in `calc.py`)
- [x] Add a pure surcharge function returning `unit_amount * qty` as a distinct
      component; `0.00` when not qualifying. -> surcharge.py:surcharge_amount + calc.compute_expected(surcharge=...)
- [x] Ensure the existing cost formula and rounding are untouched for
      non-qualifying lines.
- [x] Produce adjusted expected total without mutating the quoted total. -> CostBreakdown.adjusted_total

## 4. Adapter (CSV → models)
- [x] Focused adapter to ingest the two live-test CSVs per data-mapping.md. -> surcharge_adapter.py
- [x] Carry `po_date` and `product_material` explicitly (gaps #1, #2).
- [x] Attach `Evidence` to every adapted record.
- [x] Join quote→PO; implement the unmatched → manual-review path.

## 5. Finding assembly / orchestration
- [x] At the layer where `Quote` + matched `POLine` coexist, call the predicate,
      then the surcharge function. -> surcharge_adapter.evaluate_line / audit_report
      (live CSVs have no rate card/metal grams, so the main _build_finding path
      cannot run on them without fabricating values forbidden by data-mapping #3;
      the focused adapter assembles the finding instead.)
- [x] Record original quoted, surcharge, adjusted expected, and rule reference
      on each finding (AC-11). -> finding_record
- [x] Route unmatched POs to `NEEDS_REVIEW` (AC-12).

## 6. Tests (boundary + dimensions)  -> tests/test_surcharge.py (32 tests)
- [x] Dual date gate: both-on/after (AC-1), early PO (AC-2), early quote (AC-3).
- [x] Inclusive boundary at 2026-10-15 (AC-4).
- [x] Metal aliases: 18KT (AC-5), 18K Yellow Gold (AC-6); non-qualifying metals
      14K / Platinum (AC-7).
- [x] Bracelet variants (AC-8); non-bracelet Necklace / Ring (AC-9).
- [x] Quantity multiplication: Q=2, Q=5 (AC-10).
- [x] Quoted total never overwritten; finding shows all four fields (AC-11).
- [x] Unmatched PO → manual review (AC-12).
- [x] Config-driven + deterministic, no AI in money/eligibility (AC-13).
- [x] End-to-end over the 12 live-test lines matches the worked table
      (qualifiers L01, L04, L07, L08, L11).

## 7. Audit export + walkthrough
- [x] Export the per-line audit (original, surcharge, adjusted, rule evidence).
      -> surcharge_adapter.write_audit / audit_report (JSON, 4 required fields + evidence)
- [x] Confirm existing engine behavior/tests still pass (no regressions).
      -> full suite 141 passed (91 existing + 50 surcharge)
- [x] Prepare the architectural narration: why calc.py + config, how eligibility
      stays AI-independent, and the match-failure behavior. -> docs/surcharge-change/design.md

## 8. Robustness hardening (post-review)
- [x] Prefix match tightened to boundary semantics: '18K'/'18KT'/'18K <finish>'
      qualify; run-on tokens '18KARAT'/'180K'/'18KT9' rejected (surcharge.py).
- [x] Duplicate PO number -> NEEDS_REVIEW (ambiguous match, no guess).
- [x] Malformed/invalid quantity -> NEEDS_REVIEW.
- [x] Missing/malformed PO or quote date -> NEEDS_REVIEW (date gate fails closed).
- [x] Regression guard: real dataset still yields exactly 5 qualifiers / $195.00.
