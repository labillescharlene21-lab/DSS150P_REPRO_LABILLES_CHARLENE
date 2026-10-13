"""Evaluation, baseline comparison, and publishing of the final outputs."""
from __future__ import annotations

import json
import logging
import platform
from datetime import datetime, timezone

import pandas as pd
from sklearn.metrics import accuracy_score, recall_score, roc_auc_score
from xgboost import XGBClassifier

from src.config import ROOT, load_settings
from src.quality import ValidationError
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
    feats = model.get_booster().feature_names
    if feats != s.raw["modeling"]["features"]:
        raise ValidationError(f"Model was trained on {feats}, configured features are {s.raw['modeling']['features']}")
    prob = model.predict_proba(X_te[feats])[:, 1]

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


def tolerance_for_platform(expected: dict, system: str) -> tuple[float, float, str]:
    """(strict, applicable, kind). Strict on the reference platform, the declared relaxed limit elsewhere."""
    strict = expected["tolerance"]
    reference = expected.get("reference_platform")
    if reference is None or system == reference:
        return strict, strict, "reference"
    return strict, expected.get("tolerance_non_reference_platform", strict), "non_reference"


def judge_status(diff: float, baseline_seed: bool, other_checks_ok: bool, strict: float, applicable: float) -> str:
    if not baseline_seed:                 # a different seed is a legitimate experiment, not a failure
        return "not_applicable_non_baseline_seed"
    if not other_checks_ok or diff > applicable:
        return "fail"
    return "pass" if diff <= strict else "pass_relaxed_tolerance"


def reproducibility_check(run_id: str | None = None) -> dict:
    """Compare actual vs expected, write a machine-readable side-by-side, fail if outside tolerance."""
    s = load_settings()
    out = s.path("outputs_dir")
    expected = json.loads((ROOT / "metadata" / "expected_metrics.json").read_text(encoding="utf-8"))
    actual = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "metadata" / "split_manifest.json").read_text(encoding="utf-8"))
    system = platform.system()
    strict, applicable, kind = tolerance_for_platform(expected, system)

    baseline_seed = actual["seed"] == expected["seed"]
    diff = abs(actual["roc_auc"] - expected["roc_auc"])
    exact_checks = {
        "test_rows_match": actual["test_rows"] == expected["test_rows"],
        "test_positive_match": actual["test_positive"] == expected["test_positive"],
        "test_ids_match": manifest["test_ids_sha256"] == expected["test_ids_sha256"],
        "train_ids_match": manifest["train_ids_sha256"] == expected["train_ids_sha256"],
        "no_train_test_overlap": manifest["train_test_overlap"] == 0,
    }
    checks = {"roc_auc_within_tolerance": baseline_seed and diff <= applicable, **exact_checks}
    fn_actual = {str(r["threshold"]): r["false_negatives"] for r in actual["threshold_table"]}
    fn_diff = {k: {"expected": v, "actual": fn_actual.get(k)} for k, v in expected["false_negatives_by_threshold"].items()
               if fn_actual.get(k) != v}

    status = judge_status(diff, baseline_seed, all(exact_checks.values()), strict, applicable)
    result = {
        "pipeline_run_id": run_id, "status": status, "primary_metric": "roc_auc",
        "expected": expected["roc_auc"], "actual": actual["roc_auc"], "abs_difference": diff,
        "tolerance": applicable, "tolerance_strict": strict, "tolerance_kind": kind,
        "platform": system, "reference_platform": expected.get("reference_platform"),
        "checks": checks, "false_negative_differences": fn_diff,
        "seed_expected": expected["seed"], "seed_actual": actual["seed"],
    }
    (out / "reproducibility_check.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    log.info("run=%s reproducibility %s (diff=%.6f, tolerance=%s on %s)", run_id, status, diff, applicable, system)
    if status == "pass_relaxed_tolerance":
        log.warning("run=%s AUC differs from the baseline by %.5f: within the %s limit allowed on %s, but not the strict %s "
                    "required on the reference platform (%s). Use the Docker image for the authoritative result.",
                    run_id, diff, applicable, system, strict, expected.get("reference_platform"))
    if status == "fail":
        raise RuntimeError(f"Reproducibility check failed: {checks} diff={diff:.6f} tolerance={applicable} ({system})")
    return result
