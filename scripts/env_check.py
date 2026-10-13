"""Prints everything that could explain a different AUC on this machine. Run from the repo root:
    python scripts/env_check.py
"""
import json
import os
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import sklearn
import xgboost
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

from src.config import ROOT, load_settings
from src.train import ids_checksum, load_model_frame, make_split

s = load_settings().raw
exp = json.loads((ROOT / "metadata" / "expected_metrics.json").read_text(encoding="utf-8"))
print("python      ", sys.version.split()[0], "|", platform.platform(), "|", platform.machine(), "| cpus", os.cpu_count())
print("xgboost     ", xgboost.__version__, "| scikit-learn", sklearn.__version__, "| numpy", np.__version__, "| pandas", pd.__version__)

df = load_model_frame()
X_tr, X_te, y_tr, y_te, spw = make_split(df, 42)
print("curated rows", len(df), "| scale_pos_weight", round(spw, 4), "(expected", exp["scale_pos_weight"], ")")
print("test ids match baseline :", ids_checksum(df.loc[X_te.index, "id"]) == exp["test_ids_sha256"])
print("train ids match baseline:", ids_checksum(df.loc[X_tr.index, "id"]) == exp["train_ids_sha256"])

base = dict(s["xgboost"], scale_pos_weight=spw, random_state=42)
print("\nAUC by thread count (baseline 0.7500):")
for nj in (1, 2, 4, None):
    p = XGBClassifier(**base, n_jobs=nj).fit(X_tr, y_tr).predict_proba(X_te)[:, 1]
    print(f"  n_jobs={str(nj):>4}  AUC={roc_auc_score(y_te, p):.5f}")
print("\nAUC by tree method:")
for tm in ("hist", "exact", "approx"):
    p = XGBClassifier(**base, tree_method=tm, n_jobs=1).fit(X_tr, y_tr).predict_proba(X_te)[:, 1]
    print(f"  tree_method={tm:>6}  AUC={roc_auc_score(y_te, p):.5f}")