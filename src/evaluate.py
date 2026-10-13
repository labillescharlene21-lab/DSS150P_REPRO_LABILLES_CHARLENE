"""Evaluation, baseline comparison, and publishing of the final outputs."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import pandas as pd
from sklearn.metrics import accuracy_score, recall_score, roc_auc_score
from xgboost import XGBClassifier

from src.config import ROOT, load_settings
from src.train import MODEL_FILE, ids_checksum, load_model_frame, make_split, seed_everything

log = logging.getLogger("evaluate")


def evaluate_model(seed: int | None = None, run_id: str | None = None) -> dict:
    s = load_settings()
    seed = s.seed if seed is None else int(seed)
    seed_everything(seed)
    out = s.path("outputs_dir")

    df = load_model_frame()
    _, X_te, _, y_te, _ = make_split(df, seed)           # deterministic: same rows as in train

    manifest = json.loads((ROOT / "metadata" / "split_manifest.json").read_text(encoding="utf-8"))
    if ids_checksum(df.loc[X_te.index, "id"]) != manifest["test_ids_sha256"]:
        raise RuntimeError("Test rows differ from the split manifest written at training time")

    model = XGBClassifier()
    model.load_model(out / "model" / MODEL_FILE)
    prob = model.predict_proba(X_te[model.get_booster().feature_names])[:, 1]

    thresholds = s.raw["modeling"]["thresholds"]
    table = []
    for t in thresholds:
        pred = (prob >= t).astype(int)
        table.append({
            "threshold": t, "accuracy": round(float(accuracy_score(y_te, pred)), 6),
            "recall": round(float(recall_score(y_te, pred)), 6),
            "false_negatives": int(((y_te == 1) & (pred == 0)).sum()),
        })

    metrics = {
        "pipeline_run_id": run_id, "evaluated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed": seed, "primary_metric": "roc_auc", "roc_auc": float(roc_auc_score(y_te, prob)),
        "test_rows": len(y_te), "test_positive": int(y_te.sum()), "threshold_table": table,
    }
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    preds = pd.DataFrame({"id": df.loc[X_te.index, "id"].values,
                          "source_row_seq": df.loc[X_te.index, "source_row_seq"].values,
                          "y_true": y_te.values, "y_prob": prob})
    for t in (0.50, 0.20, 0.05):
        preds[f"y_pred_at_{t:.2f}"] = (prob >= t).astype(int)
    preds.to_csv(out / "predictions.csv", index=False)
    log.info("run=%s roc_auc=%.5f test_rows=%d", run_id, metrics["roc_auc"], len(y_te))
    return metrics


def reproducibility_check(run_id: str | None = None) -> dict:
    """Compare actual vs expected, write a machine-readable side-by-side, fail if outside tolerance."""
    s = load_settings()
    out = s.path("outputs_dir")
    expected = json.loads((ROOT / "metadata" / "expected_metrics.json").read_text(encoding="utf-8"))
    actual = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "metadata" / "split_manifest.json").read_text(encoding="utf-8"))
    tol = expected["tolerance"]

    baseline_seed = actual["seed"] == expected["seed"]
    diff = abs(actual["roc_auc"] - expected["roc_auc"])
    checks = {
        "roc_auc_within_tolerance": baseline_seed and diff <= tol,
        "test_rows_match": actual["test_rows"] == expected["test_rows"],
        "test_positive_match": actual["test_positive"] == expected["test_positive"],
        "test_ids_match": manifest["test_ids_sha256"] == expected["test_ids_sha256"],
        "train_ids_match": manifest["train_ids_sha256"] == expected["train_ids_sha256"],
        "no_train_test_overlap": manifest["train_test_overlap"] == 0,
    }
    fn_actual = {str(r["threshold"]): r["false_negatives"] for r in actual["threshold_table"]}
    fn_diff = {k: {"expected": v, "actual": fn_actual.get(k)} for k, v in expected["false_negatives_by_threshold"].items()
               if fn_actual.get(k) != v}

    if not baseline_seed:                           # a different seed is a legitimate experiment, not a failure
        status = "not_applicable_non_baseline_seed"
    else:
        status = "pass" if all(checks.values()) else "fail"

    result = {
        "pipeline_run_id": run_id, "status": status, "primary_metric": "roc_auc",
        "expected": expected["roc_auc"], "actual": actual["roc_auc"], "abs_difference": diff, "tolerance": tol,
        "checks": checks, "false_negative_differences": fn_diff,
        "seed_expected": expected["seed"], "seed_actual": actual["seed"],
    }
    (out / "reproducibility_check.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    log.info("run=%s reproducibility %s (diff=%.6f, tol=%s)", run_id, status, diff, tol)
    if status == "fail":
        raise RuntimeError(f"Reproducibility check failed: {result['checks']} diff={diff:.6f} tol={tol}")
    return result
