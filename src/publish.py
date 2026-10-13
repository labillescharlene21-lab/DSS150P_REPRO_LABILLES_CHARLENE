"""Publish the data product + a run summary with counts for every layer."""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
from datetime import datetime, timezone

import pandas as pd

from src.config import ROOT, load_settings
from src.transform import CURATED_FILE, STAGING_FILE, load_raw

log = logging.getLogger("publish")


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def publish_outputs(run_id: str | None = None) -> dict:
    s = load_settings()
    out = s.path("outputs_dir")
    manifest = json.loads((ROOT / "metadata" / "split_manifest.json").read_text(encoding="utf-8"))
    repro = json.loads((out / "reproducibility_check.json").read_text(encoding="utf-8"))

    curated_src = s.path("curated_dir") / CURATED_FILE
    shutil.copyfile(curated_src, out / "curated_stroke.csv")          # the published data product

    reject = s.path("quarantine_dir") / "rejected_rows.csv"
    summary = {
        "pipeline_run_id": run_id, "status": "success",
        "finished_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counts": {
            "raw": len(load_raw(s.path("raw_dir"))),
            "quarantined": len(pd.read_csv(reject)) if reject.exists() else 0,
            "staging": len(pd.read_csv(s.path("staging_dir") / STAGING_FILE)),
            "curated": len(pd.read_csv(curated_src)),
            "train": manifest["train_rows"], "test": manifest["test_rows"],
            "predictions": len(pd.read_csv(out / "predictions.csv")),
        },
        "reproducibility": {k: repro[k] for k in ("status", "expected", "actual", "abs_difference", "tolerance")},
        "published_files": {f: _sha256(out / f) for f in
                            ("curated_stroke.csv", "metrics.json", "predictions.csv", "reproducibility_check.json")},
    }
    (out / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log.info("run=%s published %s", run_id, summary["counts"])
    return summary
