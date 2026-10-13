"""Deterministic split + model training (reproduces the baseline XGBoost model)."""
from __future__ import annotations

import hashlib
import json
import logging
import random
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import sklearn
import xgboost
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

from src import quality
from src.config import ROOT, load_settings
from src.transform import CURATED_FILE

log = logging.getLogger("train")
MODEL_FILE = "xgb_model.json"


def ids_checksum(ids) -> str:
    return hashlib.sha256(",".join(str(i) for i in sorted(ids)).encode("utf-8")).hexdigest()


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)


def load_model_frame() -> pd.DataFrame:
    s = load_settings()
    df = pd.read_csv(s.path("curated_dir") / CURATED_FILE)
    return df.sort_values("source_row_seq").reset_index(drop=True)      # source order, as in the baseline


def make_split(df: pd.DataFrame, seed: int):
    """Baseline logic: (1) stratified 0.30 split ONLY to compute scale_pos_weight,
    (2) the real train/test split: test_size 0.20, no stratify."""
    m = load_settings().raw["modeling"]
    X, y = df[m["features"]], df[load_settings().raw["source"]["target"]]
    _, _, y_w, _ = train_test_split(X, y, test_size=m["weight_split_test_size"], random_state=seed, stratify=y)
    spw = float((y_w == 0).sum() / (y_w == 1).sum())
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=m["test_size"], random_state=seed)
    return X_tr, X_te, y_tr, y_te, spw


def split_manifest(df, X_tr, X_te, y_te, spw, seed, run_id) -> dict:
    m = load_settings().raw["modeling"]
    tr_ids, te_ids = df.loc[X_tr.index, "id"], df.loc[X_te.index, "id"]
    return {                                   # no run id/timestamps: this file must be deterministic
        "method": "sklearn.model_selection.train_test_split",
        "random_state": seed, "test_size": m["test_size"], "stratify": m["stratify"],
        "scale_pos_weight": round(spw, 4),
        "scale_pos_weight_origin": f"stratified {m['weight_split_test_size']} split, train neg/pos ratio",
        "train_rows": len(X_tr), "test_rows": len(X_te), "test_positive": int(y_te.sum()),
        "train_ids_sha256": ids_checksum(tr_ids), "test_ids_sha256": ids_checksum(te_ids),
        "train_test_overlap": len(set(tr_ids) & set(te_ids)),
        "features": m["features"],
    }


def train_model(seed: int | None = None, run_id: str | None = None) -> dict:
    s = load_settings()
    seed = s.seed if seed is None else int(seed)
    seed_everything(seed)
    df = load_model_frame()
    X_tr, X_te, y_tr, y_te, spw = make_split(df, seed)

    params = dict(s.raw["xgboost"], scale_pos_weight=spw, random_state=seed)
    model = XGBClassifier(**params)
    model.fit(X_tr, y_tr)

    out = s.path("outputs_dir") / "model"
    out.mkdir(parents=True, exist_ok=True)
    model.save_model(out / MODEL_FILE)
    (out / "model_config.json").write_text(json.dumps({
        "pipeline_run_id": run_id, "trained_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "hyperparameters": params, "features": list(X_tr.columns),
        "xgboost": xgboost.__version__, "scikit_learn": sklearn.__version__,
    }, indent=2, default=float), encoding="utf-8")

    manifest = split_manifest(df, X_tr, X_te, y_te, spw, seed, run_id)
    split_report = quality.check_split(manifest, len(df))
    split_report.write(run_id)
    split_report.raise_if_failed("train split")
    (ROOT / "metadata" / "split_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("run=%s trained seed=%d train=%d test=%d spw=%.4f", run_id, seed, len(X_tr), len(X_te), spw)
    return manifest
