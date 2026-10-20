"""Text normalization and jewellery attribute extraction used by deterministic matching."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

ABBREVIATIONS = [
    (r"\byg\b", "yellow gold"), (r"\bwg\b", "white gold"), (r"\brg\b", "rose gold"), (r"\bpg\b", "rose gold"),
    (r"\brd\b", "round"), (r"\bdia\b", "diamond"), (r"\bdiam\b", "diamond"), (r"\bbrc\b", "bracelet"),
    (r"\bnck\b", "necklace"), (r"\bpnd\b", "pendant"), (r"\bpr\b", "pair"), (r"\bpcs?\b", "piece"),
    (r"\bear studs?\b", "stud earrings"), (r"\bhuggies\b", "huggie"), (r"\bhoops\b", "hoop"), (r"\bstuds\b", "stud"),
    (r"\bct\b", "carat"), (r"\bkt\b", "k"), (r"\bkarat\b", "k"),
]
CATEGORY_WORDS = {
    "Earrings": ["earring", "stud", "huggie", "hoop", "drop earring"],
    "Ring": ["ring", "band", "solitaire"],
    "Bracelet": ["bracelet", "bangle", "cuff", "tennis"],
    "Pendant": ["pendant"],
    "Necklace": ["necklace", "chain", "choker"],
}
STONES = ["diamond", "ruby", "sapphire", "emerald", "pearl", "topaz", "amethyst"]
COLORS = ["white", "yellow", "rose"]


def fold(text: str | None) -> str:
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"(\d+)\s*k\b", r"\1k", t)
    t = t.replace("emerald-cut", "emerald cut")
    for pat, rep in ABBREVIATIONS:
        t = re.sub(pat, rep, t)
    t = re.sub(r"[^a-z0-9.\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


@dataclass(frozen=True)
class Attributes:
    grade: str | None
    color: str | None
    category: str | None
    stones: frozenset[str]
    pair: bool
    normalized: str


def grade_of(text: str | None) -> str | None:
    m = re.search(r"\b(9|10|14|18|22|24)\s*k\b", (text or "").lower().replace("kt", "k"))
    return f"{m[1]}K" if m else None


def attributes(text: str | None, category_hint: str | None = None) -> Attributes:
    t = fold(text)
    cut_free = t.replace("emerald cut", "cut")  # "emerald cut" is a cut, not a gemstone
    category = None
    for cat, words in CATEGORY_WORDS.items():
        if any(re.search(rf"\b{w}s?\b", t) for w in words):
            category = cat
            break
    if category_hint and not category:
        category = category_hint.strip().title()
    color = next((c for c in COLORS if re.search(rf"\b{c}\b", t)), None)
    stones = frozenset(s for s in STONES if re.search(rf"\b{s}s?\b", cut_free))
    return Attributes(grade=grade_of(t), color=color, category=category, stones=stones,
                      pair=bool(re.search(r"\bpairs?\b", t)), normalized=t)


def norm_vendor(v: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (v or "").lower())


def line_number(s: str | None) -> int | None:
    m = re.search(r"(\d+)$", s or "")
    return int(m[1]) if m else None
