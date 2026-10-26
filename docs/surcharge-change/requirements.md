# Requirements — Nova 18K Bracelet Per-Unit Surcharge

## Context

Live rule change from Fictional Nova Manufacturing. A flat **$15.00 per-unit**
surcharge applies to **18-karat gold** products in the **bracelet family**,
**effective 2026-10-15 (inclusive)**, gated by **both** the quotation date and
the linked purchase-order date.

The surcharge is an **internal audit adjustment** to the *expected* amount. It
does **not** modify or imply fault with the supplier's quoted total.

## Scope

- In scope: computing an adjusted expected total for qualifying lines and
  surfacing supporting evidence per line.
- Out of scope: taxes, discounts, exchange rates, percentage adjustments, or any
  change to the existing cost engine formula for non-qualifying lines.

## Definitions

- **Effective date**: `2026-10-15`, inclusive.
- **Qualifying metal (18K gold)**: designation is one of
  - `18K`
  - `18KT`
  - `18K` followed by a color/finish (e.g. `18K Yellow Gold`, `18K White Gold`).
  - Matching is case-insensitive and whitespace-tolerant.
- **Bracelet family**: `Bracelet`, `Tennis Bracelet`, `Bangle Bracelet`
  (case-insensitive).
- **Surcharge unit amount**: `$15.00`.
- **Dual date gate**: BOTH `quotation_date` AND linked `po_date` must be
  `>= 2026-10-15`.

## Acceptance Criteria (Given / When / Then)

### AC-1 — Dual date gate (both dates on/after effective)
- **Given** a line with qualifying metal and category
- **And** the PO date is `>= 2026-10-15`
- **And** the quotation date is `>= 2026-10-15`
- **When** the surcharge rule is evaluated
- **Then** the line qualifies and a surcharge is applied.

### AC-2 — Early PO blocks surcharge even if quoted later
- **Given** a qualifying metal + category line
- **And** the PO date is `< 2026-10-15` (e.g. `2026-10-10`)
- **And** the quotation date is `>= 2026-10-15` (e.g. `2026-10-20`)
- **When** the rule is evaluated
- **Then** the line does **not** qualify (earlier POs retain their previous rate).

### AC-3 — Early quote blocks surcharge even if PO is on/after
- **Given** a qualifying metal + category line
- **And** the PO date is `>= 2026-10-15`
- **And** the quotation date is `< 2026-10-15`
- **When** the rule is evaluated
- **Then** the line does **not** qualify.

### AC-4 — Inclusive boundary
- **Given** a qualifying metal + category line
- **And** both the PO date and the quotation date equal `2026-10-15`
- **When** the rule is evaluated
- **Then** the line qualifies (boundary is inclusive).

### AC-5 — Metal alias: 18KT
- **Given** a bracelet-family line with material `18KT`
- **And** the dual date gate passes
- **When** the rule is evaluated
- **Then** the line qualifies (treated as 18K gold).

### AC-6 — Metal alias: 18K + color/finish
- **Given** a bracelet-family line with material `18K Yellow Gold`
- **And** the dual date gate passes
- **When** the rule is evaluated
- **Then** the line qualifies (treated as 18K gold).

### AC-7 — Non-qualifying metal
- **Given** a bracelet-family line with material `14K` or `Platinum`
- **When** the rule is evaluated
- **Then** the line does **not** qualify.

### AC-8 — Bracelet variants qualify
- **Given** the dual date gate passes and metal is 18K gold
- **And** the category is `Bracelet`, `Tennis Bracelet`, or `Bangle Bracelet`
- **When** the rule is evaluated
- **Then** the line qualifies.

### AC-9 — Non-bracelet category
- **Given** an 18K gold line with the dual date gate passing
- **And** the category is e.g. `Necklace` or `Ring`
- **When** the rule is evaluated
- **Then** the line does **not** qualify.

### AC-10 — Per-unit multiplied by quantity
- **Given** a qualifying line with quantity `Q`
- **When** the surcharge is computed
- **Then** `surcharge_total = 15.00 * Q` (e.g. `Q=2 -> 30.00`, `Q=5 -> 75.00`).

### AC-11 — Never overwrite the supplier total
- **Given** any line (qualifying or not)
- **When** a finding is produced
- **Then** the original quoted total is preserved unchanged
- **And** the surcharge is reported as a separate internal adjustment
- **And** a qualifying finding shows: original quoted amount, surcharge amount,
  adjusted expected amount, and the supporting rule reference.

### AC-12 — Unmatched PO goes to manual review
- **Given** a quotation line whose linked PO cannot be matched
- **When** the rule is evaluated
- **Then** eligibility is **not** guessed
- **And** the line is flagged for manual review.

### AC-13 — Deterministic + config-driven
- **Given** the surcharge parameters live in `config/policy.yaml`
- **When** a run executes
- **Then** monetary values originate only from the deterministic engine (`calc.py`)
- **And** the config hash recorded for the run reflects the surcharge parameters
- **And** no AI/LLM layer contributes to the surcharge amount or eligibility.

## Worked expectations (from provided live-test CSVs)

| Line | Material         | Category         | PO date    | Quote date | Qty | Qualifies | Surcharge |
|------|------------------|------------------|------------|------------|-----|-----------|-----------|
| L01  | 18K              | Bracelet         | 2026-10-17 | 2026-10-18 | 2   | Yes       | $30.00    |
| L02  | 18K              | Bracelet         | 2026-10-10 | 2026-10-20 | 1   | No        | —         |
| L03  | 18K              | Bracelet         | 2026-10-16 | 2026-10-14 | 3   | No        | —         |
| L04  | 18K              | Bracelet         | 2026-10-15 | 2026-10-15 | 4   | Yes       | $60.00    |
| L05  | 14K              | Bracelet         | 2026-10-16 | 2026-10-19 | 2   | No        | —         |
| L06  | 18K              | Necklace         | 2026-10-16 | 2026-10-19 | 1   | No        | —         |
| L07  | 18KT             | Tennis Bracelet  | 2026-10-16 | 2026-10-19 | 5   | Yes       | $75.00    |
| L08  | 18K Yellow Gold  | Bangle Bracelet  | 2026-10-16 | 2026-10-19 | 1   | Yes       | $15.00    |
| L09  | Platinum         | Bracelet         | 2026-10-16 | 2026-10-19 | 2   | No        | —         |
| L10  | 18K              | Bracelet         | 2026-10-14 | 2026-10-19 | 2   | No        | —         |
| L11  | 18K              | Bracelet         | 2026-10-20 | 2026-10-20 | 1   | Yes       | $15.00    |
| L12  | 18K              | Ring             | 2026-10-17 | 2026-10-18 | 3   | No        | —         |

Qualifying lines: **L01, L04, L07, L08, L11**.
