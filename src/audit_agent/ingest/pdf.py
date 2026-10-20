"""PDF loaders: quotation blocks, supplementary notes and policy clauses, with page/line provenance.

The deterministic parser handles the supplied layout. Pages that contain text but no
recognisable quotation blocks are returned as `unparsed_pages` so the pipeline can try
AI-assisted extraction (with grounding validation) instead of silently dropping them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from ..models import Evidence, IngestionIssue, PolicyClause, QuoteRecord, ReviewNote, Severity
from .parsing import to_date, to_decimal, to_text

QUOTE_HEADER = re.compile(
    r"^(?:Quote\s*(?:No\.?|#|ID)?:?\s*)?(?P<qid>[A-Z]{1,4}-[\w-]+)\s+Date:\s*(?P<date>\S+)\s+PO:\s*(?P<po>\S+)\s+Line:\s*(?P<line>\S+)", re.I)
VENDOR_HEADER = re.compile(r"^(?P<vendor>.+?)\s*\|\s*COMMERCIAL QUOTATIONS", re.I)
SKU_LINE = re.compile(
    r"SKU:\s*(?P<sku>.*?)\s+QTY:\s*(?P<qty>[-\d.,]+)\s*(?P<unit>[A-Za-z]+)?\s+Total:\s*(?P<cur>USD|\$|[A-Z]{3})?\s*(?P<total>\S+)",
    re.I)
NOTE_HEADER = re.compile(
    r"^(?P<nid>X-\d+)\s*\|\s*(?P<vendor>[^|]+?)\s*\|\s*(?P<date>[^|]+?)\s*\|\s*(?P<po>PO-[\w-]+)\s*/\s*(?P<line>L\d+)", re.I)
RULE_HEADER = re.compile(r"^Rule\s+(?P<num>\d+)\s*\|\s*(?P<title>.+)$", re.I)
FOOTER = re.compile(r"^Document line identifiers", re.I)


@dataclass
class PageText:
    source_file: str
    page: int
    lines: list[str]


@dataclass
class PdfExtraction:
    quotes: list[QuoteRecord] = field(default_factory=list)
    notes: list[ReviewNote] = field(default_factory=list)
    unparsed_pages: list[PageText] = field(default_factory=list)
    pages: list[PageText] = field(default_factory=list)


def read_pdf_pages(path: Path, issues: list[IngestionIssue]) -> list[PageText]:
    if not path.exists():
        issues.append(IngestionIssue(code="FILE_MISSING", severity=Severity.ERROR, source_file=path.name,
                                     message=f"PDF not found: {path}"))
        return []
    try:
        with pdfplumber.open(path) as pdf:
            pages = []
            for i, pg in enumerate(pdf.pages, start=1):
                text = pg.extract_text() or ""
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                if not lines:
                    issues.append(IngestionIssue(code="NO_TEXT_LAYER", severity=Severity.WARNING, source_file=path.name,
                                                 location=f"page {i}", message="Page has no extractable text (scanned?). OCR not implemented."))
                pages.append(PageText(path.name, i, lines))
            return pages
    except Exception as e:
        issues.append(IngestionIssue(code="FILE_UNREADABLE", severity=Severity.ERROR, source_file=path.name,
                                     message=f"Cannot open PDF: {type(e).__name__}: {e}"))
        return []


def _parse_quote_block(vendor: str | None, header: re.Match, block: list[tuple[int, str]], src: str, page: int) -> QuoteRecord:
    errors: list[str] = []
    qid = header["qid"].upper()

    def soft(fn, *a):
        try:
            return fn(*a)
        except ValueError as e:
            errors.append(str(e))
            return None

    desc_parts: list[str] = []
    sku = qty = unit = total = cur = terms = None
    in_item = False
    for _, ln in block[1:]:
        if ln.lower().startswith("item:"):
            desc_parts.append(ln.split(":", 1)[1].strip())
            in_item = True
            continue
        m = SKU_LINE.search(ln)
        if m:
            in_item = False
            sku = to_text(m["sku"])
            qty = soft(to_decimal, m["qty"], "qty")
            unit = (m["unit"] or "").lower() or None
            cur = (m["cur"] or "USD").replace("$", "USD").upper()
            total = soft(to_decimal, m["total"], "quoted_total")
            continue
        if ln.lower().startswith("payment:"):
            terms = ln.split(":", 1)[1].strip()
            in_item = False
            continue
        if in_item:
            desc_parts.append(ln)
    if total is None and not any("quoted_total" in e for e in errors):
        errors.append("quoted_total: not found in document block")
    if unit is None:
        errors.append("unit: not stated")
    first, last = block[0][0], block[-1][0]
    quote_txt = " / ".join(ln for _, ln in block[:3])
    return QuoteRecord(
        origin="pdf", quote_id=qid, vendor=vendor,
        quote_date=soft(to_date, header["date"], "quote_date"), po_id=header["po"].upper(),
        supplier_line=header["line"].upper(), vendor_sku=sku, description=" ".join(desc_parts) or None,
        qty=qty, unit=unit, quoted_total=total, currency=cur, terms=terms, parse_errors=errors,
        evidence=Evidence(source_file=src, sheet_or_page=f"page {page}", row_or_line=f"lines {first}-{last}", quote=quote_txt[:300]),
    )


def parse_quotation_pages(pages: list[PageText]) -> PdfExtraction:
    """Parse quotation/note blocks. Blocks may continue across page breaks within one file."""
    out = PdfExtraction(pages=pages)
    state = {"file": None, "vendor": None, "q": None, "n": None}  # q/n: (match, [(line_no, text)], start_page, end_page)

    def page_ref(blk) -> str:
        return f"page {blk[2]}" if blk[2] == blk[3] else f"pages {blk[2]}-{blk[3]}"

    def flush():
        if state["q"]:
            m, lines, p0, p1 = state["q"]
            rec = _parse_quote_block(state["vendor"], m, lines, state["file"], p0)
            if p1 != p0:
                rec.evidence.sheet_or_page = page_ref(state["q"])
            out.quotes.append(rec)
            state["q"] = None
        if state["n"]:
            m, blk, p0, p1 = state["n"]
            text = " ".join(ln for _, ln in blk[1:]).strip()
            try:
                nd = to_date(m["date"], "note_date")
            except ValueError:
                nd = None
            out.notes.append(ReviewNote(
                note_id=m["nid"].upper(), vendor=m["vendor"].strip(), note_date=nd, po_id=m["po"].upper(),
                line_id=m["line"].upper(), text=text,
                evidence=Evidence(source_file=state["file"], sheet_or_page=page_ref(state["n"]),
                                  row_or_line=f"lines {blk[0][0]}-{blk[-1][0]}", quote=(blk[0][1] + " " + text)[:300])))
            state["n"] = None

    for pg in pages:
        if pg.source_file != state["file"]:
            flush()
            state.update(file=pg.source_file, vendor=None)
        consumed = False
        for n, ln in enumerate(pg.lines, start=1):
            if (vm := VENDOR_HEADER.match(ln)):
                flush()
                state["vendor"] = vm["vendor"].strip()
                continue
            if (qm := QUOTE_HEADER.match(ln)):
                flush(); consumed = True
                state["q"] = (qm, [(n, ln)], pg.page, pg.page)
                continue
            if (nm := NOTE_HEADER.match(ln)):
                flush(); consumed = True
                state["n"] = (nm, [(n, ln)], pg.page, pg.page)
                continue
            if FOOTER.match(ln):
                flush()
                continue
            for key in ("q", "n"):
                if state[key]:
                    m, lines, p0, _ = state[key]
                    lines.append((n, ln))
                    state[key] = (m, lines, p0, pg.page)
                    consumed = True
                    break
        if not consumed and pg.lines:
            out.unparsed_pages.append(pg)
    flush()
    return out


def load_quotation_pdfs(paths: list[Path], issues: list[IngestionIssue]) -> PdfExtraction:
    agg = PdfExtraction()
    for p in paths:
        pages = read_pdf_pages(p, issues)
        ex = parse_quotation_pages(pages)
        agg.quotes += ex.quotes
        agg.notes += ex.notes
        agg.unparsed_pages += ex.unparsed_pages
        agg.pages += ex.pages
        for q in ex.quotes:
            for err in q.parse_errors:
                issues.append(IngestionIssue(code="FIELD_INVALID", severity=Severity.ERROR, source_file=p.name,
                                             location=f"{q.evidence.sheet_or_page} {q.evidence.row_or_line}", message=f"{q.quote_id}: {err}"))
        for up in ex.unparsed_pages:
            issues.append(IngestionIssue(code="UNPARSED_PAGE", severity=Severity.WARNING, source_file=p.name,
                                         location=f"page {up.page}", message="Text found but no quotation layout recognised; AI extraction attempted if enabled."))
    return agg


def load_policy(path: Path, issues: list[IngestionIssue]) -> list[PolicyClause]:
    pages = read_pdf_pages(path, issues)
    clauses: list[PolicyClause] = []
    cur: dict | None = None
    for pg in pages:
        for ln in pg.lines:
            if (m := RULE_HEADER.match(ln)):
                if cur:
                    clauses.append(PolicyClause(**cur))
                cur = {"rule_id": f"Rule {m['num']}", "title": m["title"].strip(), "text": "", "source_file": pg.source_file, "page": pg.page}
            elif cur:
                cur["text"] = (cur["text"] + " " + ln).strip()
    if cur:
        clauses.append(PolicyClause(**cur))
    if pages and not clauses:
        issues.append(IngestionIssue(code="POLICY_UNPARSED", severity=Severity.ERROR, source_file=path.name,
                                     message="No 'Rule N | Title' clauses found in policy document"))
    return clauses
