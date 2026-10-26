# Data Mapping — Live-Test CSVs to Domain Models

The two live-test CSVs are fictional and use a different schema from the
project's original inputs. This document maps their columns to the existing
domain models and names the gaps a focused adapter must fill. No source totals
are ever overwritten.

## Source files

- `Purchase_Orders_Live_Test.csv`
- `Supplier_Quotations_Live_Test.csv`

They share a join key: quote `po_reference` == PO `po_number`, and line identity
via `line_id` / `quote_line_id` (1:1 in this dataset).

## Purchase_Orders_Live_Test.csv → `POLine`

| CSV column         | Target                         | Notes |
|--------------------|--------------------------------|-------|
| `line_id`          | `POLine.line_id`               | e.g. `L01` |
| `po_number`        | `POLine.po_id`                 | join key |
| `po_date`          | **PO date for the date gate**  | NEW. Not the same as `POLine.due_date`; see "Gaps". |
| `product_material` | metal designation (surcharge)  | NEW. `POLine` has no metal-string field today (it carries `metal_g`). Needed for alias matching. |
| `product_category` | `POLine.category`              | drives bracelet-family check |
| `quantity`         | `POLine.qty`                   | drives per-unit × qty |

## Supplier_Quotations_Live_Test.csv → `QuoteRecord` / `Quote`

| CSV column         | Target                     | Notes |
|--------------------|----------------------------|-------|
| `quote_line_id`    | `QuoteRecord.supplier_line`| e.g. `L01` |
| `po_reference`     | `QuoteRecord.po_id`        | join key → PO `po_number` |
| `quotation_date`   | `QuoteRecord.quote_date`   | one side of the dual date gate |
| `vendor`           | `QuoteRecord.vendor`       | `Fictional Nova Manufacturing` |
| `base_unit_cost_usd` | (reference only)         | not used to recompute expected; engine owns expected |
| `quoted_total_usd` | `QuoteRecord.quoted_total` | **never overwritten** |
| `currency`         | `QuoteRecord.currency`     | `USD` |
| `quote_line_id`    | `QuoteRecord.quote_id`     | synthesize stable id, e.g. `{po_reference}:{quote_line_id}` |
| —                  | `QuoteRecord.origin`       | set to `csv` |
| —                  | `QuoteRecord.evidence`     | source file · row · verbatim line |

## Gaps the adapter must handle

1. **PO date vs due date.** The gate uses the PO's order date (`po_date`). The
   existing `POLine.due_date` is a different concept. The adapter must carry
   `po_date` explicitly (either populate a dedicated field or pass it alongside
   the line into eligibility). Do not reuse `due_date` as a proxy.
2. **Metal designation field.** `POLine` models grams (`metal_g`), not a metal
   string. `product_material` ("18K", "18KT", "18K Yellow Gold") is required for
   alias matching. The adapter must surface this designation to the eligibility
   predicate.
3. **Fields absent in the CSVs.** `metal_g`, `stone_ct`, `set_pcs`, `finish`,
   `product_id`, `description` are not present. For the surcharge audit these
   are not needed; the adapter should use explicit, documented defaults/None and
   must not fabricate values that would affect the existing cost formula.
4. **Evidence/provenance.** Every adapted record must carry `Evidence`
   (source_file, row, verbatim quote) to satisfy the per-line evidence
   requirement.

## Matching

- Primary match: quote `po_reference` → PO `po_number`, refined by line id.
- This dataset is 1:1, but the unmatched path (AC-12) must still exist: if no PO
  matches, the line is flagged for manual review and eligibility is not guessed.

## Normalization rules (deterministic, pre-eligibility)

- Dates parsed as ISO `YYYY-MM-DD` → `date`.
- `product_material` trimmed, case-folded for alias comparison; original string
  retained for evidence.
- `product_category` trimmed, case-folded for family comparison; original
  retained for evidence.
- Monetary strings parsed to `Decimal`; quoted total stored as-is.
