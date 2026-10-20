"""Batch capacity (>=100 records) and synthetic evaluation regression gate."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import synth  # noqa: E402
from run_eval import audit_metrics, extraction_metrics  # noqa: E402

from audit_agent.config import load_llm_settings, load_settings  # noqa: E402
from audit_agent.pipeline import run_audit  # noqa: E402


def test_synthetic_batch_of_100(tmp_path):
    gold = synth.generate(100, tmp_path / "synth", seed=11)
    run = run_audit(tmp_path / "synth", load_settings(), load_llm_settings("mock"), explain=False)
    assert len(run.findings) == 100
    m = audit_metrics(run, gold)
    ex = extraction_metrics(tmp_path / "synth", gold)
    assert ex["precision"] >= 0.99 and ex["recall"] >= 0.99
    assert m["calculation"]["accuracy_on_computed"] >= 0.95  # critical gate
    assert m["matching"]["precision"] >= 0.98
    assert m["unsafe_within_tolerance"] == [] and m["auto_approved"] == 0
