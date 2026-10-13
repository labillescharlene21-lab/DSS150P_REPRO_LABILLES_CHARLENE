"""Controlled experiments that answer: 'if the metric differs from the baseline, WHY?'

Each experiment changes exactly ONE factor from the reproduced configuration (the control) and
reports the AUC and its distance from the control. Whatever moves the metric by more than the
tolerance is a factor that must be pinned for the result to reproduce.
"""
from __future__ import annotations

import json
import platform
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import sklearn
import xgboost
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

from src.config import ROOT, load_settings
from src.train import ids_checksum, load_model_frame, make_split

FIXTURE = ROOT / "tests" / "fixtures" / "engineered2_baseline.csv"


def _fit_auc(df, features, *, split_seed=42, model_seed=42, stratify=False, spw_mode="earlier_split",
             params=None, order_by=None) -> float:
    s = load_settings().raw
    d = df.sort_values(order_by).reset_index(drop=True) if order_by else df
    X, y = d[features], d[s["source"]["target"]]
    if spw_mode == "earlier_split":                       # baseline quirk: weight from an earlier stratified split
        _, _, y_w, _ = train_test_split(X, y, test_size=s["modeling"]["weight_split_test_size"],
                                        random_state=split_seed, stratify=y)
        spw = (y_w == 0).sum() / (y_w == 1).sum()
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=s["modeling"]["test_size"],
                                              random_state=split_seed, stratify=y if stratify else None)
    if spw_mode == "final_train":
        spw = (y_tr == 0).sum() / (y_tr == 1).sum()
    elif spw_mode == "none":
        spw = 1.0
    p = dict(s["xgboost"], scale_pos_weight=float(spw), random_state=model_seed)
    p.update(params or {})
    model = XGBClassifier(**p).fit(X_tr, y_tr)
    return float(roc_auc_score(y_te, model.predict_proba(X_te)[:, 1]))


def run_diagnosis() -> dict:
    s = load_settings().raw
    tol = json.loads((ROOT / "metadata" / "expected_metrics.json").read_text(encoding="utf-8"))["tolerance"]
    expected = json.loads((ROOT / "metadata" / "expected_metrics.json").read_text(encoding="utf-8"))
    df = load_model_frame()
    feats = s["modeling"]["features"]

    # ---- data identity: are the pipeline's rows the baseline's rows?
    identity = {"curated_rows": len(df)}
    if FIXTURE.exists():
        base = pd.read_csv(FIXTURE)
        same_shape = len(base) == len(df)
        identical = same_shape and all(
            ((df[c].reset_index(drop=True) - base[c]).abs().max() < 1e-9) if pd.api.types.is_numeric_dtype(base[c])
            else (df[c].astype(str).reset_index(drop=True) == base[c].astype(str)).all() for c in base.columns)
        identity["identical_to_group_engineered_file"] = bool(identical)
    else:
        identity["identical_to_group_engineered_file"] = "baseline file not available (tests/fixtures)"
    _, X_te, _, _, _ = make_split(df, 42)
    identity["test_ids_match_baseline_hash"] = ids_checksum(df.loc[X_te.index, "id"]) == expected["test_ids_sha256"]

    control = _fit_auc(df, feats)
    rows = [("control", "-", "Reproduced configuration (seed 42, notebook split, notebook hyperparameters)", control)]

    def add(factor, what, **kw):
        rows.append((factor.split(":")[0], factor, what, _fit_auc(df, feats, **kw)))

    add("seed: model", "model random_state 7 (split unchanged)", model_seed=7)
    add("seed: split", "split random_state 7 (model seed unchanged)", split_seed=7)
    add("split: stratified", "final split stratified by target (baseline was NOT)", stratify=True)
    add("split: row order", "rows sorted by id before the split instead of source order", order_by="id")
    add("preprocessing: class weight", "scale_pos_weight from the final train set instead of the earlier 0.30 split",
        spw_mode="final_train")
    add("preprocessing: no class weight", "scale_pos_weight = 1", spw_mode="none")
    add("hyperparameters: paper table", "n_estimators 183, learning_rate 0.029 (paper's Model 2 values)",
        params={"n_estimators": 183, "learning_rate": 0.029})
    add("hyperparameters: depth", "max_depth 3 instead of 2", params={"max_depth": 3})
    no_eng = [f for f in feats if f not in ("VAAF", "TGI")]
    rows.append(("features", "features: drop VAAF+TGI", "model without the two engineered features (11 features)",
                 _fit_auc(df, no_eng)))

    # ---- how much does the metric move by chance alone?
    sweep = [_fit_auc(df, feats, split_seed=sd, model_seed=sd) for sd in range(20)]
    X_tr, X_te, y_tr, y_te, spw = make_split(df, 42)
    probs = XGBClassifier(**dict(s["xgboost"], scale_pos_weight=spw, random_state=42)).fit(X_tr, y_tr).predict_proba(X_te)[:, 1]
    rng, y_arr, boots = np.random.default_rng(0), y_te.to_numpy(), []
    for _ in range(1000):
        i = rng.integers(0, len(y_arr), len(y_arr))
        if 0 < y_arr[i].sum() < len(i):
            boots.append(roc_auc_score(y_arr[i], probs[i]))
    variability = {
        "split_seed_sweep": {"seeds": "0-19 (split and model seed equal)", "mean": round(float(np.mean(sweep)), 4),
                             "std": round(float(np.std(sweep, ddof=1)), 4), "min": round(float(min(sweep)), 4),
                             "max": round(float(max(sweep)), 4)},
        "bootstrap_95ci_on_baseline_test_set": [round(float(np.percentile(boots, 2.5)), 4),
                                                round(float(np.percentile(boots, 97.5)), 4)],
        "test_positives": int(y_arr.sum()), "test_rows": int(len(y_arr)),
    }

    table = [{"factor": f, "change": w, "auc": round(a, 5), "delta_vs_control": round(a - control, 5),
              "exceeds_tolerance": abs(a - control) > tol} for f, _, w, a in rows]
    result = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tolerance": tol, "baseline_auc": expected["roc_auc"], "control_auc": round(control, 5),
        "data_identity": identity, "experiments": table, "variability": variability,
        "library_versions": {"python": platform.python_version(), "xgboost": xgboost.__version__,
                             "scikit_learn": sklearn.__version__, "pandas": pd.__version__},
        "library_note": ("Library version cannot be varied inside one process. Measured separately: "
                         "xgboost 2.1.4 to 3.2.0 give AUC 0.75087; xgboost >= 3.3.0 gives 0.75004 on identical data, "
                         "split and parameters (scikit-learn 1.7.2 vs 1.8.0 made no difference)."),
    }
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "diagnosis_results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (ROOT / "docs" / "diagnosis_results.md").write_text(render_diagnosis(result), encoding="utf-8")
    return {"experiments": len(table), "control_auc": round(control, 5)}


def render_diagnosis(r: dict) -> str:
    L = ["# Diagnosis: what moves the metric? (auto-generated)", "",
         f"Baseline AUC (paper/notebook): **{r['baseline_auc']}** | reproduced control: **{r['control_auc']}** "
         f"| tolerance: {r['tolerance']}", "",
         "## Step 1: is it the data?", ""]
    for k, v in r["data_identity"].items():
        L.append(f"- {k}: **{v}**")
    L += ["", "## Step 2: change one factor at a time", "",
          "| Factor | Change | AUC | Delta vs control | Exceeds tolerance |", "|---|---|---:|---:|:---:|"]
    for e in r["experiments"]:
        L.append(f"| {e['factor']} | {e['change']} | {e['auc']:.5f} | {e['delta_vs_control']:+.5f} | "
                 f"{'yes' if e['exceeds_tolerance'] else 'no'} |")
    vb = r["variability"]
    sw = vb["split_seed_sweep"]
    L += ["", "## Step 3: how much does the metric move by chance alone?", "",
          f"- Splitting and training with 20 different seeds ({sw['seeds']}): mean AUC **{sw['mean']}**, "
          f"std **{sw['std']}**, range **{sw['min']} to {sw['max']}**.",
          f"- Bootstrap 95% confidence interval for the reproduced AUC on the baseline test set "
          f"({vb['test_rows']} rows, {vb['test_positives']} stroke cases): **{vb['bootstrap_95ci_on_baseline_test_set'][0]} "
          f"to {vb['bootstrap_95ci_on_baseline_test_set'][1]}**.",
          "- Meaning: differences of a few hundredths in AUC between two configurations are within split/seed noise on this "
          "dataset. Reproducing 0.7500 therefore depends on reproducing the exact split, which the split manifest hashes verify."]
    v = r["library_versions"]
    L += ["", "## Step 4: library versions", "", f"This run: Python {v['python']}, xgboost {v['xgboost']}, "
          f"scikit-learn {v['scikit_learn']}, pandas {v['pandas']}.", "", r["library_note"], "",
          "## How to read this", "",
          "1. Data identity true and split hashes matching means any metric difference is NOT the data or the split rows.",
          "2. A factor with `exceeds tolerance = yes` must be pinned or documented, otherwise it can silently change the result.",
          "3. A factor that changes nothing (`no`) is not the cause; move on to the next one.",
          "4. If nothing here explains a difference, compare library versions, then platform/threads."]
    return "\n".join(L) + "\n"
