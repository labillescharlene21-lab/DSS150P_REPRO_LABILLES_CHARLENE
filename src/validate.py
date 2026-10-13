"""Stage entry points for the quality gates (DAG tasks validate_raw and validate_curated)."""
from __future__ import annotations

import json
import logging

import pandas as pd
import yaml
from sqlalchemy import text

from src import quality
from src.config import ROOT, load_settings
from src.quality import ValidationError  # noqa: F401  (re-exported for callers and tests)
from src.transform import CURATED_FILE, load_contract, load_raw

log = logging.getLogger("validate")


def _json(name: str) -> dict:
    return json.loads((ROOT / "metadata" / name).read_text(encoding="utf-8"))


def validate_raw(run_id: str | None = None) -> dict:
    s = load_settings()
    manifest = yaml.safe_load((ROOT / "metadata" / "source_manifest.yml").read_text(encoding="utf-8"))
    raw = load_raw(s.path("raw_dir"))
    report = quality.check_raw(raw, manifest, load_contract(), s.source_file, s.raw)
    report.write(run_id)
    report.raise_if_failed("validate_raw")
    return {"raw_rows": len(raw), "batches": int(raw["batch_no"].nunique()), **report.summary()}


def validate_curated(run_id: str | None = None) -> dict:
    s = load_settings()
    expected, fingerprint = _json("expected_metrics.json"), _json("feature_fingerprint.json")
    cur = pd.read_csv(s.path("curated_dir") / CURATED_FILE)
    features, target = s.raw["modeling"]["features"], s.raw["source"]["target"]

    report = quality.check_curated(cur, features, target, expected, fingerprint, s.raw)
    report.checks += quality.check_predictive_inputs(cur, features, target, fingerprint, s.raw).checks
    for c in report.checks:                       # one combined report for the curated gate
        c.layer = "curated"

    try:                                          # PostgreSQL must agree with the curated file
        from src.storage import get_engine
        with get_engine().connect() as conn:
            n_db = conn.execute(text("SELECT COUNT(*) FROM curated_stroke")).scalar()
        report.add("consistency_postgres_row_count_matches_file", "consistency", n_db == len(cur),
                   f"PostgreSQL has {n_db} curated rows, file has {len(cur)}")
    except Exception as e:                        # noqa: BLE001
        report.add("consistency_postgres_reachable", "consistency", False, f"{type(e).__name__}: {e}")

    report.write(run_id)
    report.raise_if_failed("validate_curated")
    return {"curated_rows": len(cur), "stroke_positive": int(cur[target].sum()), **report.summary()}
