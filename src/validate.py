"""Data-quality gates used by the pipeline. (Milestone 08 extends these with more checks.)"""
from __future__ import annotations

import json
import logging

import pandas as pd
import yaml
from sqlalchemy import text

from src.config import ROOT, load_settings
from src.transform import CURATED_COLS, CURATED_FILE, load_contract, load_raw

log = logging.getLogger("validate")


class ValidationError(RuntimeError):
    """Raised when a data-quality gate fails. The CLI turns this into a non-zero exit."""


def _fail(failures: list[str], label: str) -> None:
    if failures:
        raise ValidationError(f"{label} failed: " + "; ".join(failures))


def validate_raw() -> dict:
    s = load_settings()
    manifest = yaml.safe_load((ROOT / "metadata" / "source_manifest.yml").read_text(encoding="utf-8"))
    contract = load_contract()
    raw = load_raw(s.path("raw_dir"))
    key = contract["key"]["column"]
    failures = []

    missing = [c for c in contract["columns"] if c not in raw.columns]
    if missing:
        failures.append(f"missing columns {missing}")
    if len(raw) != manifest["row_count"]:
        failures.append(f"row count {len(raw)} != manifest {manifest['row_count']}")
    if key in raw.columns and raw[key].duplicated().any():
        failures.append(f"{int(raw[key].duplicated().sum())} duplicate {key}")
    if raw["record_hash"].duplicated().any():
        failures.append("duplicate record_hash")
    bad_checksum = (raw["source_checksum"] != manifest["sha256"]).sum()
    if bad_checksum:
        failures.append(f"{int(bad_checksum)} rows carry a checksum different from source_manifest.yml")
    _fail(failures, "validate_raw")

    result = {"raw_rows": len(raw), "batches": int(raw["batch_no"].nunique())}
    log.info("validate_raw OK %s", result)
    return result


def validate_curated() -> dict:
    s = load_settings()
    expected = json.loads((ROOT / "metadata" / "expected_metrics.json").read_text(encoding="utf-8"))
    cur = pd.read_csv(s.path("curated_dir") / CURATED_FILE)
    features = s.raw["modeling"]["features"]
    target = s.raw["source"]["target"]
    failures = []

    if list(cur.columns) != CURATED_COLS:
        failures.append("curated column set/order changed")
    if len(cur) != expected["curated_rows"]:
        failures.append(f"curated rows {len(cur)} != expected {expected['curated_rows']}")
    if cur["id"].duplicated().any():
        failures.append("duplicate id in curated")
    if not cur["source_row_seq"].is_monotonic_increasing:
        failures.append("curated is not in source order (would change the train/test split)")
    nulls = cur[features + [target]].isna().sum()
    if nulls.any():
        failures.append(f"nulls in model columns: {nulls[nulls > 0].to_dict()}")
    if not set(cur[target].unique()) <= {0, 1}:
        failures.append("target is not binary")
    if target in features or "id" in features:
        failures.append("target/identifier present in feature list (leakage)")

    # Postgres must agree with the curated file
    try:
        from src.storage import get_engine
        with get_engine().connect() as conn:
            n_db = conn.execute(text("SELECT COUNT(*) FROM curated_stroke")).scalar()
        if n_db != len(cur):
            failures.append(f"PostgreSQL has {n_db} curated rows, file has {len(cur)}")
    except Exception as e:
        failures.append(f"PostgreSQL unreachable: {type(e).__name__}")
    _fail(failures, "validate_curated")

    result = {"curated_rows": len(cur), "stroke_positive": int(cur[target].sum())}
    log.info("validate_curated OK %s", result)
    return result
