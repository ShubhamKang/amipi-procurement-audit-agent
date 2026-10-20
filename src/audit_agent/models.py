"""Normalized domain models. Every record carries provenance (Evidence)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    source_file: str
    sheet_or_page: str
    row_or_line: str
    quote: str

    def ref(self) -> str:
        return f"{self.source_file} · {self.sheet_or_page} · {self.row_or_line}"


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class IngestionIssue(BaseModel):
    code: str
    severity: Severity
    source_file: str
    location: str = ""
    message: str


class POLine(BaseModel):
    po_id: str
    line_id: str
    product_id: str | None
    description: str
    category: str
    qty: Decimal
    metal_g: Decimal
    stone_ct: Decimal | None = None
    set_pcs: Decimal
    finish: str
    due_date: date | None = None
    evidence: Evidence

    @property
    def key(self) -> str:
        return f"{self.po_id}/{self.line_id}"


class RateCard(BaseModel):
    rate_id: str
    vendor: str
    effective_from: date
    effective_to: date | None
    category: str
    metal: str
    metal_usd_per_gram: Decimal
    setting_usd_per_stone: Decimal
    labor_usd_per_unit: Decimal
    handling_rate: Decimal
    finish_rhodium_usd_per_unit: Decimal
    notes: str = ""
    evidence: Evidence


class QuoteRecord(BaseModel):
    """One quotation line as read from ONE source (PDF block or CSV row)."""

    origin: Literal["pdf", "csv", "llm_pdf"]
    quote_id: str
    vendor: str | None = None
    quote_date: date | None = None
    po_id: str | None = None
    supplier_line: str | None = None
    vendor_sku: str | None = None
    description: str | None = None
    qty: Decimal | None = None
    unit: str | None = None
    quoted_total: Decimal | None = None
    currency: str | None = "USD"
    terms: str | None = None
    declared_source_doc: str | None = None
    parse_errors: list[str] = Field(default_factory=list)
    evidence: Evidence


class FieldConflict(BaseModel):
    field: str
    values: dict[str, str]
    critical: bool


class Quote(BaseModel):
    """Reconciled business quotation (one per quote_id, regardless of how many sources)."""

    quote_id: str
    vendor: str | None
    quote_date: date | None
    po_id: str | None
    supplier_line: str | None
    vendor_sku: str | None
    description: str | None
    qty: Decimal | None
    unit: str | None
    quoted_total: Decimal | None
    currency: str | None
    origins: list[str]
    evidence: list[Evidence]
    conflicts: list[FieldConflict] = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)
    filled_from_secondary: list[str] = Field(default_factory=list)


class ReviewNote(BaseModel):
    """Supplementary vendor note (untrusted). Never changes calculated values."""

    note_id: str
    vendor: str
    note_date: date | None
    po_id: str | None
    line_id: str | None
    text: str
    evidence: Evidence
    kind: str = "GENERAL_NOTE"
    referenced_quote_ids: list[str] = Field(default_factory=list)
    injection_detected: bool = False
    injection_matches: list[str] = Field(default_factory=list)
    amounts: list[Decimal] = Field(default_factory=list)


class HistoryRecord(BaseModel):
    quote_id: str
    vendor: str | None
    product_id: str | None
    quoted_date: date | None
    quoted_total: Decimal | None
    status: str | None
    evidence: Evidence


class PolicyClause(BaseModel):
    rule_id: str
    title: str
    text: str
    source_file: str
    page: int

    def citation(self) -> str:
        return f"{self.source_file} p.{self.page} {self.rule_id}"


class CostBreakdown(BaseModel):
    rate_id: str
    metal: Decimal
    setting: Decimal
    labor: Decimal
    subtotal: Decimal
    handling: Decimal
    finish: Decimal
    unit_cost: Decimal
    qty: Decimal
    total: Decimal
    inputs: dict[str, str]


class MatchResult(BaseModel):
    po_line_key: str | None
    proposed_po_line_key: str | None = None
    method: str  # sku | rules | rules+llm | llm | none
    confidence: float
    trustworthy: bool
    rationale: str
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    llm_used: bool = False


class Issue(BaseModel):
    code: str
    severity: Literal["critical", "high", "medium", "low", "info"]
    message: str
    blocking: bool = False  # True -> finding must be NEEDS_REVIEW


class Citation(BaseModel):
    rule_id: str
    title: str
    source_file: str
    page: int
    excerpt: str
    score: float = 0.0


class HumanReview(BaseModel):
    decision: str = "pending"
    reviewer: str | None = None
    reason: str | None = None
    timestamp: str | None = None
    override_expected_total_usd: float | None = None
    stale: bool = False


class Finding(BaseModel):
    quote_id: str
    po_line_id: str | None
    po_id: str | None
    vendor: str | None
    quote_date: str | None
    description: str | None
    status: Literal["FLAG", "NEEDS_REVIEW", "WITHIN_TOLERANCE"]
    priority: Literal["P1", "P2", "P3"]
    quoted_total_usd: float | None
    expected_total_usd: float | None
    variance_usd: float | None
    variance_pct: float | None
    matched_rate_id: str | None
    issue_codes: list[str]
    issues: list[Issue]
    evidence: list[Evidence]
    match: MatchResult
    calculation: CostBreakdown | None
    hypotheses: list[str] = Field(default_factory=list)
    policy_citations: list[Citation] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    ai_explanation: str
    explanation_source: str
    fingerprint: str
    human_review: HumanReview = Field(default_factory=HumanReview)
