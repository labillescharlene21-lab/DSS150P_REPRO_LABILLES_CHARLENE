"""Tests for the diagnosis and comparison TOOLS. Whether this environment reproduces the baseline is decided by
`repro-check` and acceptance test A17, not here: a tool test must not fail just because a library differs."""
import json

import pytest

from src import diagnose, report
from src.config import ROOT, load_settings
from src.transform import CURATED_FILE

pytestmark = pytest.mark.skipif(
    not (load_settings().path("curated_dir") / CURATED_FILE).exists(), reason="run the pipeline first")


def test_diagnosis_control_equals_the_pipeline_result_and_isolates_one_factor_per_row():
    res = diagnose.run_diagnosis()
    out = json.loads((ROOT / "docs" / "diagnosis_results.json").read_text(encoding="utf-8"))
    metrics_file = load_settings().path("outputs_dir") / "metrics.json"
    if metrics_file.exists() and json.loads(metrics_file.read_text(encoding="utf-8")).get("seed") == 42:
        pipeline_auc = json.loads(metrics_file.read_text(encoding="utf-8"))["roc_auc"]
        assert abs(out["control_auc"] - pipeline_auc) < 2e-5          # same config => same number as the pipeline
    assert res["experiments"] == len(out["experiments"]) >= 9
    assert out["experiments"][0]["delta_vs_control"] == 0
    assert out["data_identity"]["test_ids_match_baseline_hash"] is True   # data + split algorithm, any environment
    sweep = out["variability"]["split_seed_sweep"]
    assert sweep["min"] < out["control_auc"] < sweep["max"] and sweep["std"] > 0
    lo, hi = out["variability"]["bootstrap_95ci_on_baseline_test_set"]
    assert lo < out["control_auc"] < hi
    assert "Step 1: is it the data?" in (ROOT / "docs" / "diagnosis_results.md").read_text(encoding="utf-8")


def test_metrics_comparison_lists_every_threshold_and_the_environment():
    out = load_settings().path("outputs_dir")
    if not (out / "reproducibility_check.json").exists():
        pytest.skip("run the pipeline first")
    report.write_metrics_comparison()
    text = (ROOT / "docs" / "metrics_comparison.md").read_text(encoding="utf-8")
    for t in ("0.05", "0.075", "0.2", "0.35", "0.4", "0.45", "0.5"):
        assert f"| {t} |" in text
    assert "## Environment" in text and "xgboost" in text
    assert "ROC-AUC (primary)" in text and ("match" in text or "DIFFERENT" in text)
