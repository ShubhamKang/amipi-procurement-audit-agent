"""Strict value parsing shared by all loaders. Malformed values raise ValueError (never guessed)."""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

_NUM_RE = re.compile(r"^[+-]?(\d+(\.\d+)?|\.\d+)$")
_THOUSANDS_RE = re.compile(r"^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$")


def is_blank(v: object) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "") or (isinstance(v, float) and math.isnan(v))


def to_decimal(v: object, field: str) -> Decimal:
    """Parse a numeric/monetary value exactly.

    Floats from spreadsheets carry binary noise (0.07000000000000001); they are rounded to
    9 decimal places before conversion, which is far below any monetary precision used.
    """
    if is_blank(v):
        raise ValueError(f"{field}: value is empty")
    if isinstance(v, bool):
        raise ValueError(f"{field}: boolean is not a number")
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ValueError(f"{field}: non-finite number {v!r}")
        return Decimal(str(round(v, 9)))
    if isinstance(v, Decimal):
        return v
    s = str(v).strip()
    s = re.sub(r"(?i)^(usd|us\$|\$)\s*", "", s)
    s = re.sub(r"(?i)\s*(usd)$", "", s).strip()
    if _THOUSANDS_RE.match(s):
        s = s.replace(",", "")
    s = s.replace(" ", "")
    if not _NUM_RE.match(s):
        raise ValueError(f"{field}: malformed number {v!r}")
    try:
        return Decimal(s)
    except InvalidOperation as e:  # pragma: no cover - regex guards this
        raise ValueError(f"{field}: malformed number {v!r}") from e


def to_date(v: object, field: str) -> date:
    if is_blank(v):
        raise ValueError(f"{field}: date is empty")
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$", s)
    if m:
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        if a > 12 >= b:
            return date(y, b, a)
        if b > 12 >= a:
            return date(y, a, b)
        raise ValueError(f"{field}: ambiguous day/month order in {v!r}")
    raise ValueError(f"{field}: unrecognised date {v!r}")


def to_text(v: object) -> str | None:
    if is_blank(v):
        return None
    s = str(v).strip()
    if s.lower() in {"[not provided]", "not provided", "n/a", "na", "none", "null", "-"}:
        return None
    return s


def norm_header(h: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(h or "").lower())
