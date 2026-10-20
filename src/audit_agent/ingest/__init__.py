"""Input discovery and loading of the complete document package."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from ..models import HistoryRecord, IngestionIssue, POLine, PolicyClause, QuoteRecord, RateCard, ReviewNote, Severity
from .pdf import PageText, load_policy, load_quotation_pdfs
from .tabular import load_history, load_po_lines, load_quote_register, load_rate_cards


@dataclass
class InputPaths:
    purchase_orders: Path | None = None
    rate_cards: Path | None = None
    quote_register: Path | None = None
    history: Path | None = None
    policy: Path | None = None
    quotation_pdfs: list[Path] = field(default_factory=list)


@dataclass
class Bundle:
    paths: InputPaths
    po_lines: list[POLine]
    rates: list[RateCard]
    csv_quotes: list[QuoteRecord]
    pdf_quotes: list[QuoteRecord]
    notes: list[ReviewNote]
    history: list[HistoryRecord]
    policy: list[PolicyClause]
    unparsed_pages: list[PageText]
    pdf_pages: list[PageText]
    issues: list[IngestionIssue]
    file_hashes: dict[str, str]


def _pick(files: list[Path], *keywords: str) -> Path | None:
    for f in sorted(files):
        name = f.name.lower()
        if any(k in name for k in keywords):
            return f
    return None


def discover(data_dir: Path) -> InputPaths:
    """Locate inputs by filename keywords (works for supplied layout and uploaded sets)."""
    files = [p for p in data_dir.rglob("*") if p.is_file() and not p.name.startswith((".", "~"))]
    xlsx = [f for f in files if f.suffix.lower() in {".xlsx", ".xlsm"}]
    csvs = [f for f in files if f.suffix.lower() == ".csv"]
    pdfs = [f for f in files if f.suffix.lower() == ".pdf"]
    policy = _pick([p for p in pdfs if "contract" in str(p.parent).lower()], "") or _pick(pdfs, "policy", "contract")
    quotations = sorted(p for p in pdfs if p != policy)
    return InputPaths(
        purchase_orders=_pick(xlsx, "purchase", "po_", "order"),
        rate_cards=_pick(xlsx, "rate"),
        quote_register=_pick(csvs, "register", "quote") or (sorted(csvs)[0] if csvs else None),
        history=_pick(xlsx, "histor"),
        policy=policy,
        quotation_pdfs=quotations,
    )


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def load_bundle(data_dir: Path) -> Bundle:
    issues: list[IngestionIssue] = []
    if not data_dir.exists():
        issues.append(IngestionIssue(code="DATA_DIR_MISSING", severity=Severity.ERROR, source_file=str(data_dir),
                                     message="Data directory does not exist"))
        paths = InputPaths()
    else:
        paths = discover(data_dir)

    def load(p: Path | None, label: str, loader, required: bool = True) -> list:
        if p is None:
            issues.append(IngestionIssue(code="FILE_MISSING", severity=Severity.ERROR if required else Severity.WARNING,
                                         source_file=label, message=f"No {label} file found in {data_dir}"))
            return []
        return loader(p, issues)

    po = load(paths.purchase_orders, "Purchase_Orders.xlsx", load_po_lines)
    rates = load(paths.rate_cards, "Vendor_Rate_Cards.xlsx", load_rate_cards)
    csvq = load(paths.quote_register, "Quote_Register.csv", load_quote_register, required=False)
    hist = load(paths.history, "Historical_Quotation_Log.xlsx", load_history, required=False)
    policy = load(paths.policy, "Procurement_Policy.pdf", load_policy)
    if not paths.quotation_pdfs:
        issues.append(IngestionIssue(code="FILE_MISSING", severity=Severity.WARNING, source_file="Quotations/*.pdf",
                                     message="No quotation PDFs found; register entries will be audited without a primary document"))
    pdfx = load_quotation_pdfs(paths.quotation_pdfs, issues)

    hashes = {}
    for p in [paths.purchase_orders, paths.rate_cards, paths.quote_register, paths.history, paths.policy, *paths.quotation_pdfs]:
        if p and p.exists():
            hashes[p.name] = _sha(p)
    return Bundle(paths, po, rates, csvq, pdfx.quotes, pdfx.notes, hist, policy, pdfx.unparsed_pages, pdfx.pages, issues, hashes)
