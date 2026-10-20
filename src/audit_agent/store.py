"""Persistent, append-only human review log (SQLite).

* Reviews are never overwritten; the latest row per quote_id is the current decision.
* Reviews are bound to the finding fingerprint; if inputs/rules change, the old decision is shown
  as stale and the finding returns to 'pending'.
* Human overrides are stored separately and never replace the calculated values.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .models import Finding, HumanReview

DECISIONS = ("approved", "rejected", "escalated", "needs_info")
MIN_REASON = 10

SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    run_id TEXT,
    decision TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    reason TEXT NOT NULL,
    override_expected_total_usd REAL,
    status_at_review TEXT,
    calculated_expected_usd REAL,
    quoted_total_usd REAL,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_reviews_q ON reviews(quote_id, id);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT, provider TEXT, config_hash TEXT, data_dir TEXT, metrics TEXT, file_hashes TEXT
);
"""


class ReviewError(ValueError):
    pass


class ReviewStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._mem = sqlite3.connect(":memory:") if str(path) == ":memory:" else None
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        if self._mem is not None:
            yield self._mem
            self._mem.commit()
            return
        c = sqlite3.connect(self.path, timeout=10)
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def record(self, finding: Finding, decision: str, reviewer: str, reason: str, run_id: str | None = None,
               override_expected_total_usd: float | None = None) -> HumanReview:
        decision = (decision or "").strip().lower()
        reviewer = (reviewer or "").strip()
        reason = (reason or "").strip()
        if decision not in DECISIONS:
            raise ReviewError(f"decision must be one of {DECISIONS}")
        if not reviewer:
            raise ReviewError("reviewer name is required")
        if len(reason) < MIN_REASON:
            raise ReviewError(f"justification must be at least {MIN_REASON} characters")
        if decision == "approved" and finding.status != "WITHIN_TOLERANCE" and len(reason) < 25:
            raise ReviewError("approving a FLAG/NEEDS_REVIEW finding requires a detailed justification (>= 25 chars)")
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._conn() as c:
            c.execute(
                "INSERT INTO reviews (quote_id, fingerprint, run_id, decision, reviewer, reason, override_expected_total_usd,"
                " status_at_review, calculated_expected_usd, quoted_total_usd, timestamp) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (finding.quote_id, finding.fingerprint, run_id, decision, reviewer, reason, override_expected_total_usd,
                 finding.status, finding.expected_total_usd, finding.quoted_total_usd, ts))
        return HumanReview(decision=decision, reviewer=reviewer, reason=reason, timestamp=ts,
                           override_expected_total_usd=override_expected_total_usd)

    def history(self, quote_id: str | None = None) -> list[dict]:
        q = "SELECT * FROM reviews" + (" WHERE quote_id=?" if quote_id else "") + " ORDER BY id DESC"
        with self._conn() as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(q, (quote_id,) if quote_id else ()).fetchall()
            c.row_factory = None
        return [dict(r) for r in rows]

    def apply(self, findings: list[Finding]) -> None:
        """Attach the latest review to each finding (stale if fingerprint changed)."""
        latest: dict[str, dict] = {}
        for r in reversed(self.history()):
            latest[r["quote_id"]] = r
        for f in findings:
            r = latest.get(f.quote_id)
            if not r:
                f.human_review = HumanReview()
            elif r["fingerprint"] != f.fingerprint:
                f.human_review = HumanReview(decision="pending", reviewer=r["reviewer"], timestamp=r["timestamp"],
                                             reason=f"Previous decision '{r['decision']}' is stale: inputs or rules changed", stale=True)
            else:
                f.human_review = HumanReview(decision=r["decision"], reviewer=r["reviewer"], reason=r["reason"], timestamp=r["timestamp"],
                                             override_expected_total_usd=r["override_expected_total_usd"])

    def save_run(self, run) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?)",
                      (run.run_id, run.started_at, run.provider, run.config_hash, run.data_dir,
                       json.dumps(run.metrics), json.dumps(run.file_hashes)))
