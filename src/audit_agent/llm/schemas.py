"""Structured-output schemas for every LLM task.

Deliberately contains NO status, approval or expected-price fields: the model cannot express
an approval or a pricing decision even if a prompt injection succeeded.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class MatchDecision(BaseModel):
    po_line_key: str | None = Field(description="Chosen candidate key exactly as given (e.g. 'PO-2602/L06'), or null if none fits")
    confidence: float = Field(ge=0.0, le=1.0, description="0..1 confidence that the quotation item is the same product")
    rationale: str = Field(max_length=400, description="One or two sentences citing the matching attributes")


class ExtractedLine(BaseModel):
    quote_id: str
    quote_date: str | None = None
    po_id: str | None = None
    supplier_line: str | None = None
    sku: str | None = None
    description: str | None = None
    qty: str | None = None
    unit: str | None = None
    total: str | None = Field(default=None, description="Total amount exactly as printed, e.g. '1,110.00'")
    currency: str | None = None


class ExtractionResult(BaseModel):
    lines: list[ExtractedLine]


class Explanation(BaseModel):
    quote_id: str
    text: str = Field(max_length=700)


class ExplanationBatch(BaseModel):
    items: list[Explanation]
