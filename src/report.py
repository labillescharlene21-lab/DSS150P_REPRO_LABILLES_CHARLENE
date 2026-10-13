"""Side-by-side comparison of baseline vs reproduced results (machine-readable inputs, readable output)."""
from __future__ import annotations

import json
import platform

from src.config import ROOT, load_settings


def _j(p):
    return json.loads(p.read_text(encoding="utf-8"))


def write_metrics_comparison() -> dict:
    s = load_settings()
    out = s.path("outputs_dir")
    exp = _j(ROOT / "metadata" / "expected_metrics.json")
    act = _j(out / "metrics.json")
    chk = _j(out / "reproducibility_check.json")
    split = _j(ROOT / "metadata" / "split_manifest.json")
    cfg = _j(out / "model" / "model_config.json")

    def mark(ok):
        return "match" if ok else "DIFFERENT"

    L = ["# Baseline vs reproduced results (auto-generated)", "",
         f"Run: `{act['pipeline_run_id']}` | status: **{chk['status']}** | tolerance: {chk['tolerance']}", "",
         "| Quantity | Baseline (expected) | Reproduced (actual) | Result |", "|---|---:|---:|---|",
         f"| ROC-AUC (primary) | {exp['roc_auc']:.4f} | {act['roc_auc']:.5f} | diff {chk['abs_difference']:.6f}, within tolerance: {chk['abs_difference'] <= chk['tolerance']} |",
         f"| Train rows | {exp['train_rows']} | {split['train_rows']} | {mark(exp['train_rows'] == split['train_rows'])} |",
         f"| Test rows | {exp['test_rows']} | {act['test_rows']} | {mark(exp['test_rows'] == act['test_rows'])} |",
         f"| Test positives | {exp['test_positive']} | {act['test_positive']} | {mark(exp['test_positive'] == act['test_positive'])} |",
         f"| scale_pos_weight | {exp['scale_pos_weight']} | {split['scale_pos_weight']} | {mark(abs(exp['scale_pos_weight'] - split['scale_pos_weight']) < 1e-4)} |",
         f"| Train ids SHA-256 | `{exp['train_ids_sha256'][:16]}...` | `{split['train_ids_sha256'][:16]}...` | {mark(exp['train_ids_sha256'] == split['train_ids_sha256'])} |",
         f"| Test ids SHA-256 | `{exp['test_ids_sha256'][:16]}...` | `{split['test_ids_sha256'][:16]}...` | {mark(exp['test_ids_sha256'] == split['test_ids_sha256'])} |",
         "", "## Missed stroke cases (false negatives) by threshold", "",
         "| Threshold | Baseline | Reproduced | Result |", "|---:|---:|---:|---|"]
    got = {str(r["threshold"]): r["false_negatives"] for r in act["threshold_table"]}
    for t, v in exp["false_negatives_by_threshold"].items():
        L.append(f"| {t} | {v} | {got.get(t)} | {mark(got.get(t) == v)} |")
    L += ["", "## Environment", "",
          f"- xgboost {cfg['xgboost']}, scikit-learn {cfg['scikit_learn']}, Python {platform.python_version()}, {platform.platform()}",
          f"- Hyperparameters: `{json.dumps({k: v for k, v in cfg['hyperparameters'].items()})}`"]
    path = ROOT / "docs" / "metrics_comparison.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    return {"status_pass": chk["status"] == "pass", "auc": round(act["roc_auc"], 5)}
