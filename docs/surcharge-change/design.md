# Design — Nova 18K Bracelet Per-Unit Surcharge

## Guiding principle

The existing architecture has two invariants we preserve:

1. **`calc.py` is the only source of monetary values.** No AI layer ever
   produces or alters money.
2. **Rules live in configuration (`config/policy.yaml`), not in code.** Code
   reads typed `Settings`; the config file is hashed per run for auditability.

The surcharge must fit these invariants, not bend them.

## Why the surcharge amount belongs in `calc.py`

- `compute_expected` is already the single function that produces expected line
  totals from `POLine` + `RateCard` + `Settings`, using pure `Decimal`
  arithmetic. The surcharge is a monetary quantity, so it must originate here to
  keep "one source of money" true.
- The surcharge is a deterministic function of `(unit_amount, quantity)` —
  exactly the kind of arithmetic `calc.py` owns. It is added as a distinct,
  separately-reported component so existing totals and the existing formula for
  non-qualifying lines remain byte-for-byte unchanged.
- Variance is computed against the adjusted expected total, but the supplier's
  quoted total is never mutated (see AC-11).

## Why the parameters belong in `config/policy.yaml`

- Effective date, unit amount, qualifying metal aliases, and bracelet-family
  categories are **policy**, not logic. Per invariant 2 they live in YAML so a
  future rate/date change needs no code edit.
- They flow through `settings_from_dict` into the frozen `Settings` dataclass,
  which means they are automatically captured in the per-run `config_hash`.
  Reading YAML directly inside `calc.py` would bypass that hash and break
  auditability — so we do not do that.
- New settings are added with safe defaults so existing policy files that lack a
  surcharge block still load unchanged (backward compatible).

## Why eligibility stays AI-independent

- Eligibility is a **pure predicate** over normalized, deterministic inputs:
  metal designation, category, PO date, quote date, and the configured
  parameters. It mirrors the existing `is_rhodium(finish, s)` pattern — small,
  pure, testable, no side effects.
- The predicate returns a **structured decision** (qualifies: bool + reason +
  the facts it checked) so each finding can cite concrete evidence rather than a
  model's opinion.
- No LLM input is consulted for the amount or the decision. The AI layer's role
  in the wider system (matching hints, explanations) is unchanged and remains
  advisory; it cannot flip eligibility or change money.

## The two-date problem and where eligibility is evaluated

The dual date gate needs **both** the quotation date and the PO date. Those
live on different records:

- `quotation_date` → on the `Quote` / `QuoteRecord`.
- `po_date` → the purchase-order date (the live-test CSV's `po_date`; note this
  differs from `POLine.due_date`, see data-mapping.md).

`compute_expected` today takes only a `POLine`. Rather than overload it with
cross-record state, the design splits responsibilities:

- **Eligibility predicate (pure):** takes the normalized metal designation,
  category, PO date, quote date, and `Settings`; returns the structured decision.
  Lives alongside the engine as a pure function (sibling to `is_rhodium`).
- **Surcharge amount (pure, in `calc.py`):** given the decision is "qualifies"
  and a quantity, returns `unit_amount * qty` as `Decimal`, reported as a
  distinct component. Non-qualifying → `0.00`, expected total unchanged.
- **Finding-assembly site — `_build_finding` in `pipeline.py`:** the confirmed
  place where the `Quote` (`q`) and matched `POLine` (`po`) coexist, right where
  `calc = compute_expected(po, rate, s)` runs and `expected`/`var`/status are
  set. It extracts both dates (`q.quote_date` and the PO date), calls the
  predicate, then asks `calc.py` for the surcharge amount, and records original
  quoted, surcharge, adjusted expected, and the rule reference on the finding.

This keeps money in `calc.py`, keeps eligibility a pure config-driven function,
and keeps the AI layer entirely out of both.

### Integration facts verified in `pipeline.py`

- `expected` is only set when `trusted_calc` (match trustworthy AND calc
  present). So an unmatched/untrusted line never receives an expected total and
  therefore never a surcharge — AC-12's "don't guess" is enforced by existing
  control flow, not a new branch.
- `_build_finding` maintains an `allowed_amounts` safety set that bounds which
  monetary values the explanation layer may mention. The surcharge amount and
  the adjusted expected total MUST be added to this set, or the explanation
  guard will reject them.
- Date inputs already available at the site: `q.quote_date` and `po.due_date`.
  Per data-mapping.md the CSV `po_date` must be carried as the PO date; today
  the only date field on `POLine` is `due_date` (used for rate selection). The
  adapter must supply the PO date without silently repurposing `due_date`.

## Unmatched PO handling

If the PO cannot be matched, `_build_finding` already raises a blocking issue
(`NO_PO_MATCH` / `LOW_MATCH_CONFIDENCE` / `MATCH_DISAGREEMENT`) and sets
`status = "NEEDS_REVIEW"`, and `expected` stays `None`. Per AC-12 the surcharge
path must not guess: it piggybacks on this existing machinery — no surcharge is
applied or assumed. No new code path is introduced.

## What stays unchanged

- The existing formula (metal/setting/labor/handling/finish) and its rounding.
- Supplier quoted totals (never overwritten).
- The AI/matching/explanation layers' responsibilities.
- Existing findings for non-qualifying lines (surcharge component = 0.00).
