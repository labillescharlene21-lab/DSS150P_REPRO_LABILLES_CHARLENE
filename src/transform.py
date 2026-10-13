"""Raw -> staging -> curated. Pure functions (transform_frame, curate_frame) + thin file wrappers."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yaml

from src.config import ROOT, load_settings

log = logging.getLogger("transform")

STAGING_FILE = "stroke_staging.csv"
CURATED_FILE = "stroke_curated.csv"
REJECT_FILE = "rejected_rows.csv"

INT_COLS = ["id", "hypertension", "heart_disease", "stroke"]
FLOAT_COLS = ["age", "avg_glucose_level", "bmi"]
STR_COLS = ["gender", "ever_married", "work_type", "Residence_type", "smoking_status"]
NULL_TOKENS = {"N/A", "NA", "null", "NULL", "None", ""}

CURATED_COLS = [
    "id", "gender", "age", "hypertension", "heart_disease", "Residence_type",
    "avg_glucose_level", "bmi", "smoking_status", "stroke",
    "gender_score_risk", "age_score_risk", "glucose_score_risk", "bmi_score_risk",
    "smoking_score_risk", "residence_score_risk", "VAAF", "TGI",
    "source_row_seq", "record_hash", "pipeline_run_id", "processed_at_utc",
]


# ---------------------------------------------------------------- loading
def load_contract() -> dict:
    return yaml.safe_load((ROOT / "metadata" / "data_contract.yml").read_text(encoding="utf-8"))


def load_raw(raw_dir) -> pd.DataFrame:
    files = sorted(raw_dir.glob("batch_*.csv"))
    if not files:
        raise FileNotFoundError(f"No raw batches in {raw_dir}. Run ingest first.")
    df = pd.concat([pd.read_csv(f, dtype=str, keep_default_na=False) for f in files], ignore_index=True)
    df["source_row_seq"] = df["source_row_seq"].astype(int)
    if df["source_row_seq"].duplicated().any():
        raise RuntimeError("Duplicate source_row_seq in raw layer")
    return df.sort_values("source_row_seq").reset_index(drop=True)   # original file order


# ---------------------------------------------------------------- staging steps
def parse_types(df: pd.DataFrame):
    """Explicit type conversion. Returns (typed_df, reject_reasons). Only bmi may be null."""
    out = df.copy()
    reasons = pd.Series("", index=df.index)
    for c in STR_COLS:
        out[c] = out[c].str.strip()
    for c in INT_COLS + FLOAT_COLS:
        text = out[c].str.strip()
        is_null_token = text.isin(NULL_TOKENS)
        num = pd.to_numeric(text.where(~is_null_token), errors="coerce")
        bad = num.isna() & ~is_null_token            # present but unparseable
        if c != "bmi":
            bad = bad | num.isna()                   # nulls not allowed
        reasons[bad] += f"{c}:unparseable_or_null;"
        out[c] = num
    return out, reasons


def contract_violations(df: pd.DataFrame, columns: dict) -> pd.Series:
    """Row-level range/category checks driven by data_contract.yml."""
    reasons = pd.Series("", index=df.index)
    for c, rule in columns.items():
        if c not in df.columns:
            raise ValueError(f"Schema violation: required column '{c}' missing")
        col = df[c]
        if "allowed" in rule:
            bad = ~col.isin(rule["allowed"]) & col.notna()
            reasons[bad] += f"{c}:not_allowed;"
        if "min" in rule:
            reasons[(col < rule["min"]).fillna(False)] += f"{c}:below_min;"
        if "max" in rule:
            reasons[(col > rule["max"]).fillna(False)] += f"{c}:above_max;"
    return reasons


def clean_rows(df: pd.DataFrame, age_min: float, age_max: float):
    """Business cleaning rules carried over from the baseline notebook."""
    df = df.copy()
    stats = {}
    mode_gender = df["gender"].mode()[0]
    stats["gender_other_imputed"] = int((df["gender"] == "Other").sum())
    df["gender"] = df["gender"].replace("Other", mode_gender)

    kids_unknown = (df["work_type"] == "children") & (df["smoking_status"] == "Unknown")
    stats["children_smoking_fixed"] = int(kids_unknown.sum())
    df.loc[kids_unknown, "smoking_status"] = "never smoked"

    before = len(df)
    df = df[(df["age"] >= age_min) & (df["age"] <= age_max)].copy()
    stats["filtered_out_of_age_scope"] = before - len(df)

    median_bmi = df["bmi"].median()                  # after the age filter, as in the baseline
    stats["bmi_imputed"] = int(df["bmi"].isna().sum())
    stats["bmi_median"] = float(median_bmi)
    df["bmi"] = df["bmi"].fillna(median_bmi)
    return df, stats


def transform_frame(raw: pd.DataFrame, run_id: str):
    """raw (strings) -> (staging, rejected, stats)."""
    s = load_settings()
    contract = load_contract()
    missing = [c for c in contract["columns"] if c not in raw.columns]
    if missing:
        raise ValueError(f"Schema violation: required columns missing from raw layer: {missing}")
    typed, r1 = parse_types(raw)
    r2 = contract_violations(typed, contract["columns"])
    reasons = r1 + r2
    bad = reasons != ""

    rejected = raw.loc[bad].copy()
    rejected["reject_reason"] = reasons[bad]
    good = typed.loc[~bad].copy()
    good[INT_COLS] = good[INT_COLS].astype(int)

    dup = good["id"].duplicated(keep="first")        # key uniqueness (contract: fail-level in validate step)
    if dup.any():
        raise RuntimeError(f"{int(dup.sum())} duplicate ids in raw layer")

    staging, stats = clean_rows(good, s.raw["transform"]["age_min"], s.raw["transform"]["age_max"])
    stats.update(raw_rows=len(raw), rejected_rows=int(bad.sum()), staging_rows=len(staging))

    staging["pipeline_run_id"] = run_id
    staging["processed_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    keep = ["source_row_seq", "record_hash"] + [c for c in raw.columns
            if c not in ("source_row_seq", "record_hash", "pipeline_run_id", "ingested_at_utc",
                         "source_file", "source_checksum", "batch_no")] 
    keep = list(dict.fromkeys(keep)) + ["pipeline_run_id", "processed_at_utc"]
    staging = staging[keep].sort_values("source_row_seq").reset_index(drop=True)
    return staging, rejected, stats


# ---------------------------------------------------------------- curated: features
def _age_points(age: float, male: bool) -> int:
    table = [(35, 0, 0), (40, 2, 2), (45, 5, 4), (50, 6, 5), (55, 8, 7),
             (60, 10, 8), (65, 11, 9), (70, 12, 10), (75, 14, 11)]
    for upper, pm, pf in table:
        if age < upper:
            return pm if male else pf
    return 15 if male else 12


def points_to_vascular_age(points: int, male: bool) -> int:
    table = ([(-1, 28), (0, 30), (2, 33), (4, 37), (6, 41), (8, 46), (10, 52),
              (12, 58), (14, 66), (15, 72), (16, 76)] if male else
             [(1, 28), (3, 32), (5, 38), (7, 43), (9, 49), (11, 57), (13, 66), (14, 76)])
    for upper, vage in table:
        if points <= upper:
            return vage
    return 82


def vascular_age(row) -> int:
    male = row["gender_score_risk"] == 1
    pts = _age_points(row["age"], male)
    if row["smoking_score_risk"] == 3:
        pts += 4 if male else 3
    pts += (3 if male else 4) if row["hypertension"] == 1 else (0 if male else -1)
    if row["avg_glucose_level"] >= 126.0:
        pts += 3 if male else 4
    if row["bmi"] >= 25.0:
        pts += 2
    return points_to_vascular_age(pts, male)


def curate_frame(staging: pd.DataFrame, run_id: str) -> pd.DataFrame:
    d = staging.sort_values("source_row_seq").reset_index(drop=True).copy()
    d["gender_score_risk"] = d["gender"].map({"Female": 0, "Male": 1})
    d["age_score_risk"] = pd.cut(d["age"], bins=[34, 54, 90], labels=[0, 1]).astype(int)
    d["glucose_score_risk"] = pd.cut(d["avg_glucose_level"], bins=[0, 140, 200, np.inf],
                                     labels=[0, 1, 2], right=False).astype(int)
    d["bmi_score_risk"] = pd.cut(d["bmi"], bins=[0, 23, np.inf], labels=[0, 1], right=False).astype(int)
    d["smoking_score_risk"] = d["smoking_status"].map(
        {"never smoked": 0, "Unknown": 1, "formerly smoked": 2, "smokes": 3}).astype(int)
    d["residence_score_risk"] = d["Residence_type"].map({"Rural": 1, "Urban": 2})
    d["VAAF"] = d.apply(vascular_age, axis=1) - d["age"]
    d["TGI"] = d["bmi"] * d["avg_glucose_level"]
    d["pipeline_run_id"] = run_id
    d["processed_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return d[CURATED_COLS]


# ---------------------------------------------------------------- file wrappers
def run_staging(run_id: str | None = None) -> dict:
    """raw batches -> staging (typed, cleaned, scoped) + quarantine."""
    s = load_settings()
    run_id = run_id or uuid.uuid4().hex[:12]
    for key in ("staging_dir", "quarantine_dir"):
        s.path(key).mkdir(parents=True, exist_ok=True)

    raw = load_raw(s.path("raw_dir"))
    staging, rejected, stats = transform_frame(raw, run_id)
    staging.to_csv(s.path("staging_dir") / STAGING_FILE, index=False, encoding="utf-8")

    reject_path = s.path("quarantine_dir") / REJECT_FILE
    if len(rejected):
        rejected.to_csv(reject_path, index=False, encoding="utf-8")
    else:
        reject_path.unlink(missing_ok=True)          # no stale rejects from older runs
    log.info("run=%s staging %s", run_id, stats)
    return stats


def run_curated(run_id: str | None = None) -> dict:
    """staging -> curated (score columns, VAAF, TGI), ordered by source_row_seq."""
    s = load_settings()
    run_id = run_id or uuid.uuid4().hex[:12]
    s.path("curated_dir").mkdir(parents=True, exist_ok=True)
    staging_path = s.path("staging_dir") / STAGING_FILE
    if not staging_path.exists():
        raise FileNotFoundError(f"{staging_path} not found. Run the staging step first.")
    curated = curate_frame(pd.read_csv(staging_path), run_id)
    curated.to_csv(s.path("curated_dir") / CURATED_FILE, index=False, encoding="utf-8")
    stats = {"curated_rows": len(curated)}
    log.info("run=%s curated %s", run_id, stats)
    return stats


def run_transform(run_id: str | None = None) -> dict:
    """Both steps, same run id (convenience for the CLI and local runs)."""
    run_id = run_id or uuid.uuid4().hex[:12]
    stats = run_staging(run_id)
    stats.update(run_curated(run_id))
    return stats
