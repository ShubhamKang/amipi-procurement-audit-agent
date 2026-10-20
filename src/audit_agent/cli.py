"""Command-line interface: batch audit, export, review recording."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from .config import default_data_dir, default_db_path, load_llm_settings, load_settings
from .export import write_all
from .pipeline import run_audit
from .store import ReviewError, ReviewStore

app = typer.Typer(add_completion=False, help="AMIPI procurement & quotation audit agent")


@app.command()
def run(
    data: Path = typer.Option(None, help="Input folder (default: DATA_DIR or ./Data)"),
    out: Path = typer.Option(Path("sample_output"), help="Folder for JSON/CSV/XLSX reports"),
    provider: Optional[str] = typer.Option(None, help="gemini | mock | none (overrides LLM_PROVIDER)"),
    config: Optional[Path] = typer.Option(None, help="Alternative policy.yaml"),
    no_explain: bool = typer.Option(False, help="Skip AI explanations (deterministic templates only)"),
    db: Path = typer.Option(None, help="Review database (default: DB_PATH)"),
):
    """Audit all quotations and write reports."""
    s = load_settings(config)
    llm = load_llm_settings(provider)
    r = run_audit(data or default_data_dir(), s, llm, explain=False if no_explain else None)
    store = ReviewStore(db or default_db_path())
    store.apply(r.findings)
    store.save_run(r)
    paths = write_all(r, out, store.history())
    m = r.metrics
    typer.echo(f"Run {r.run_id} | provider {r.provider} | config {r.config_hash}")
    typer.echo(f"{m['quotations']} quotations from {m['source_records']} source records | FLAG {m['flag']} | "
               f"NEEDS_REVIEW {m['needs_review']} | WITHIN_TOLERANCE {m['within_tolerance']} | auto-approved {m['auto_approved']}")
    typer.echo(f"{'QUOTE':7} {'LINE':5} {'STATUS':17} {'PRI':3} {'QUOTED':>9} {'EXPECTED':>9} {'VAR':>8} RATE     ISSUES")
    for f in r.findings:
        fmt = lambda v: f"{v:9.2f}" if v is not None else f"{'—':>9}"
        typer.echo(f"{f.quote_id:7} {f.po_line_id or '—':5} {f.status:17} {f.priority:3} {fmt(f.quoted_total_usd)} "
                   f"{fmt(f.expected_total_usd)} {(f'{f.variance_usd:+8.2f}' if f.variance_usd is not None else '       —')} "
                   f"{(f.matched_rate_id or '—'):8} {', '.join(f.issue_codes[:4])}")
    errs = [e for e in r.ai_events if e.status in ("error", "rejected")]
    for e in errs[:5]:
        typer.echo(f"AI {e.status}: {e.task} {e.ref} {e.detail}", err=True)
    typer.echo("Reports: " + ", ".join(str(p) for p in paths.values()))


@app.command()
def review(
    quote_id: str, decision: str = typer.Option(..., help="approved | rejected | escalated | needs_info"),
    reviewer: str = typer.Option(...), reason: str = typer.Option(...),
    override: Optional[float] = typer.Option(None, help="Human override of expected total (kept separate)"),
    data: Path = typer.Option(None), provider: str = typer.Option("mock"), db: Path = typer.Option(None),
):
    """Record a human review decision for a quotation in the current audit."""
    r = run_audit(data or default_data_dir(), load_settings(), load_llm_settings(provider), explain=False)
    f = r.finding(quote_id.upper())
    if not f:
        raise typer.BadParameter(f"Unknown quote {quote_id}")
    try:
        hr = ReviewStore(db or default_db_path()).record(f, decision, reviewer, reason, r.run_id, override)
    except ReviewError as e:
        raise typer.BadParameter(str(e))
    typer.echo(f"Recorded {hr.decision} for {f.quote_id} by {hr.reviewer} at {hr.timestamp}")


@app.command()
def history(quote_id: Optional[str] = None, db: Path = typer.Option(None)):
    """Show the append-only review log."""
    for row in ReviewStore(db or default_db_path()).history(quote_id):
        typer.echo(f"{row['timestamp']} {row['quote_id']} {row['decision']:10} {row['reviewer']}: {row['reason']}")


if __name__ == "__main__":
    app()
