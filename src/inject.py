"""Safe, reversible failure injection for the demonstration (Milestone 08).

Corrupts ONE raw batch file after a backup copy is taken. `--restore` (or `ingest --force`) puts the
original back. Nothing else in the repository is touched.

  missing_column  drop smoking_status           -> schema check fails
  duplicate_id    two rows share an id          -> uniqueness check fails
  null_target     a row loses its stroke label  -> completeness check fails
  tamper_bmi      BMI edited after ingestion    -> record-hash integrity check fails
  bad_glucose     one glucose value = 9999      -> row is quarantined; curated row-count gate fails
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from src.config import ROOT, load_settings
from src.quality import row_hash
from src.transform import load_contract

KINDS = ("missing_column", "duplicate_id", "null_target", "tamper_bmi", "bad_glucose")
TARGET_BATCH = "batch_002.csv"


def _valid_row_positions(df: pd.DataFrame, n: int = 1) -> list[int]:
    age = pd.to_numeric(df["age"], errors="coerce")
    return list(df.index[(age >= 36) & (age <= 89)][:n])          # rows that are in the study scope


def apply_fault(df: pd.DataFrame, kind: str) -> tuple[pd.DataFrame, str]:
    """Pure function: returns (corrupted copy, description). Upstream-style faults keep the row hash
    consistent (the bad data 'arrived that way'); tamper_bmi leaves it stale (changed after ingestion)."""
    if kind not in KINDS:
        raise ValueError(f"unknown fault '{kind}'. Choose from {KINDS}")
    out = df.copy()
    cols = [c for c in load_contract()["columns"] if c in out.columns]

    def rehash():
        out["record_hash"] = row_hash(out, cols)

    if kind == "missing_column":
        return out.drop(columns=["smoking_status"]), "dropped column smoking_status"
    if kind == "duplicate_id":
        a, b = _valid_row_positions(out, 2)
        out.loc[b, "id"] = out.loc[a, "id"]
        rehash()
        return out, f"row {b} now has the same id as row {a}"
    if kind == "null_target":
        (a,) = _valid_row_positions(out)
        out.loc[a, "stroke"] = ""
        rehash()
        return out, f"row {a} has an empty stroke label"
    if kind == "bad_glucose":
        (a,) = _valid_row_positions(out)
        out.loc[a, "avg_glucose_level"] = "9999"
        rehash()
        return out, f"row {a} has avg_glucose_level = 9999"
    bmi = pd.to_numeric(out["bmi"], errors="coerce")                # tamper_bmi
    idx = list(out.index[bmi < 50][:50])
    out.loc[idx, "bmi"] = (bmi[idx] + 2.0).round(1).astype(str)
    return out, f"BMI +2.0 on {len(idx)} rows without updating record_hash"


def _paths(raw_dir: Path | None, backup_dir: Path | None) -> tuple[Path, Path]:
    raw_dir = raw_dir or load_settings().path("raw_dir")
    backup_dir = backup_dir or ROOT / "state" / "failure_backup"
    return raw_dir / TARGET_BATCH, backup_dir / (TARGET_BATCH + ".orig")


def inject_fault(kind: str, raw_dir: Path | None = None, backup_dir: Path | None = None) -> dict:
    target, backup = _paths(raw_dir, backup_dir)
    if not target.exists():
        raise FileNotFoundError(f"{target} not found. Run ingest first.")
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():                                         # never overwrite the first backup
        shutil.copyfile(target, backup)
    df = pd.read_csv(backup, dtype=str, keep_default_na=False)      # always corrupt from the original
    bad, description = apply_fault(df, kind)
    bad.to_csv(target, index=False, encoding="utf-8")
    return {"fault": kind, "file": str(target.name), "description": description}


def restore(raw_dir: Path | None = None, backup_dir: Path | None = None) -> dict:
    target, backup = _paths(raw_dir, backup_dir)
    if not backup.exists():
        return {"restored": False, "note": "no backup found (nothing was injected, or ingest --force already reset it)"}
    shutil.copyfile(backup, target)
    backup.unlink()
    return {"restored": True, "file": target.name}
