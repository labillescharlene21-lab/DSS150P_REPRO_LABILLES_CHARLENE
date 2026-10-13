from __future__ import annotations
import hashlib, json, logging, os, uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yaml

from src.config import ROOT, load_settings
from src.profile_source import sha256_file

log = logging.getLogger("ingest")


def _load_state(path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"completed_batches": [], "source_sha256": None}


def _save_state(path, state):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, path)  # atomic


def _row_hash(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    joined = df[cols].agg("|".join, axis=1)
    return joined.map(lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest())


def ingest(force: bool = False, fail_after: int | None = None, run_id: str | None = None) -> None:
    s = load_settings()
    run_id = run_id or uuid.uuid4().hex[:12]
    src = s.source_file

    manifest = yaml.safe_load((ROOT / "metadata" / "source_manifest.yml").read_text(encoding="utf-8"))
    checksum = sha256_file(src)
    if checksum != manifest["sha256"]:
        raise RuntimeError(f"Checksum mismatch for {src.name}: expected {manifest['sha256']}, got {checksum}")

    raw_dir, state_dir = s.path("raw_dir"), s.path("state_dir")
    raw_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    ckpt = state_dir / "ingest_checkpoint.json"

    if force:
        log.warning("run=%s FORCE full refresh: clearing raw batches and checkpoint", run_id)
        for f in raw_dir.glob("batch_*.csv"):
            f.unlink()
        ckpt.unlink(missing_ok=True)

    state = _load_state(ckpt)
    if state["source_sha256"] not in (None, checksum):
        raise RuntimeError("Checkpoint belongs to a different source version. Use --force.")

    # Raw = faithful copy: read everything as text, no NA coercion
    df = pd.read_csv(src, dtype=str, keep_default_na=False)
    src_cols = list(df.columns)
    df.insert(0, "source_row_seq", range(len(df)))          # immutable ordering = simulated sequence
    df["record_hash"] = _row_hash(df, src_cols)

    n = s.raw["ingestion"]["n_batches"]
    batches = np.array_split(np.arange(len(df)), n)          # deterministic contiguous chunks
    log.info("run=%s source_rows=%d batches=%d done=%s", run_id, len(df), n, state["completed_batches"])

    for i, idx in enumerate(batches, start=1):
        if i in state["completed_batches"]:
            log.info("run=%s batch=%d SKIP (already committed)", run_id, i)
            continue

        batch = df.iloc[idx].copy()
        batch["pipeline_run_id"] = run_id
        batch["ingested_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        batch["source_file"] = src.name
        batch["source_checksum"] = checksum
        batch["batch_no"] = i

        out = raw_dir / f"batch_{i:03d}.csv"
        tmp = out.with_suffix(".tmp")
        batch.to_csv(tmp, index=False, encoding="utf-8")
        written = len(pd.read_csv(tmp, dtype=str, keep_default_na=False))
        if written != len(batch):
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"batch {i}: wrote {written} rows, expected {len(batch)}")
        os.replace(tmp, out)

        # checkpoint advances only AFTER the batch is written and validated
        state["completed_batches"].append(i)
        state["source_sha256"] = checksum
        _save_state(ckpt, state)
        log.info("run=%s batch=%d COMMITTED rows=%d", run_id, i, len(batch))

        if fail_after == i:
            raise RuntimeError(f"Simulated failure after batch {i}")

    log.info("run=%s ingestion complete", run_id)


def verify_raw() -> None:
    s = load_settings()
    files = sorted(s.path("raw_dir").glob("batch_*.csv"))
    if not files:
        raise RuntimeError("No raw batches found")
    df = pd.concat([pd.read_csv(f, dtype=str, keep_default_na=False) for f in files])
    key = s.raw["source"]["key"]
    manifest = yaml.safe_load((ROOT / "metadata" / "source_manifest.yml").read_text(encoding="utf-8"))
    rows, dup_key, dup_hash = len(df), int(df[key].duplicated().sum()), int(df["record_hash"].duplicated().sum())
    print(f"batches={len(files)} raw_rows={rows} expected={manifest['row_count']} "
          f"duplicate_{key}={dup_key} duplicate_record_hash={dup_hash}")
    if rows != manifest["row_count"] or dup_key or dup_hash:
        raise SystemExit(1)
    print("VERIFY OK")