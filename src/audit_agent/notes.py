"""Classification of supplementary vendor notes (untrusted). Notes never alter calculated values."""
from __future__ import annotations

import re
from decimal import Decimal

from .config import Settings
from .models import ReviewNote
from .security import detect_injection

_AMOUNT = re.compile(r"(?:USD|\$)\s*([\d,]+(?:\.\d+)?)", re.I)
_QREF = re.compile(r"\bQ-\d+\b", re.I)


def classify_notes(notes: list[ReviewNote], s: Settings) -> list[ReviewNote]:
    out = []
    for n in notes:
        text = n.text
        low = text.lower()
        hits = detect_injection(text, s)
        amounts = [Decimal(a.replace(",", "")) for a in _AMOUNT.findall(text)]
        refs = sorted({r.upper() for r in _QREF.findall(text)})
        if hits:
            kind = "PROMPT_INJECTION"
        elif "duplicate" in low or "cancel" in low or "replacement" in low:
            kind = "DUPLICATE_NOTICE"
        elif "surcharge" in low or "extra charge" in low or "fee" in low:
            kind = "SURCHARGE_CLAIM"
        elif "rate increase" in low or "price increase" in low or "new rate" in low:
            kind = "RATE_CHANGE_NOTICE"
        else:
            kind = "GENERAL_NOTE"
        out.append(n.model_copy(update={
            "kind": kind, "injection_detected": bool(hits), "injection_matches": hits,
            "amounts": amounts, "referenced_quote_ids": refs,
        }))
    return out


def has_signed_exception(note: ReviewNote) -> bool:
    low = note.text.lower()
    if re.search(r"\bno (signed )?exception", low) or "not signed" in low or "unsigned" in low:
        return False
    return "signed exception" in low or "approved exception" in low
