from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from audit_agent.config import load_settings
from audit_agent.models import Evidence, POLine, RateCard

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "Data"
EV = Evidence(source_file="t", sheet_or_page="t", row_or_line="row 1", quote="t")


@pytest.fixture
def settings():
    return load_settings()


def po(qty="1", g="4", pcs="1", finish="Standard", category="Ring", desc="14K white gold ring", line="L01", po_id="PO-1", sku="RNG-1"):
    return POLine(po_id=po_id, line_id=line, product_id=sku, description=desc, category=category, qty=Decimal(qty),
                  metal_g=Decimal(g), set_pcs=Decimal(pcs), finish=finish, evidence=EV)


def rate(rid="R1", vendor="Aurora Craftworks", frm="2026-01-01", to="2026-12-31", metal="14K", g="38", s="2.5", lab="35",
         h="0.08", rh="12", category="ALL"):
    return RateCard(rate_id=rid, vendor=vendor, effective_from=date.fromisoformat(frm),
                    effective_to=date.fromisoformat(to) if to else None, category=category, metal=metal,
                    metal_usd_per_gram=Decimal(g), setting_usd_per_stone=Decimal(s), labor_usd_per_unit=Decimal(lab),
                    handling_rate=Decimal(h), finish_rhodium_usd_per_unit=Decimal(rh), evidence=EV)
