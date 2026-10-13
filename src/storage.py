"""PostgreSQL storage: schema setup and rerun-safe (idempotent) loading."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import create_engine, text

from src.config import ROOT, db_url, load_settings
from src.transform import CURATED_FILE, STAGING_FILE

log = logging.getLogger("storage")

TABLES = {"staging": "staging_stroke", "curated": "curated_stroke"}


def get_engine():
    return create_engine(db_url(), pool_pre_ping=True)


def init_db(engine=None) -> None:
    engine = engine or get_engine()
    with engine.begin() as conn:
        for f in ("schema.sql", "transformations.sql"):
            conn.exec_driver_sql((ROOT / "sql" / f).read_text(encoding="utf-8"))
    log.info("schema applied")


def _records(df: pd.DataFrame) -> list[dict]:
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]                  # Residence_type -> residence_type
    df = df.astype(object).where(df.notna(), None)                # native Python types, NaN -> NULL
    return df.to_dict("records")


def upsert(conn, table: str, df: pd.DataFrame, key: str = "id") -> int:
    """INSERT ... ON CONFLICT (key) DO UPDATE. Re-running the same data changes nothing."""
    rows = _records(df)
    cols = list(rows[0].keys())
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != key)
    sql = text(
        f"INSERT INTO {table} ({', '.join(cols)}) "
        f"VALUES ({', '.join(':' + c for c in cols)}) "
        f"ON CONFLICT ({key}) DO UPDATE SET {updates}"
    )
    conn.execute(sql, rows)
    return len(rows)


def _log_run(conn, run_id, stage, status, rows, started):
    conn.execute(text(
        "INSERT INTO pipeline_run_log (pipeline_run_id, stage, status, rows_loaded, started_at_utc, finished_at_utc) "
        "VALUES (:r, :s, :st, :n, :t0, :t1) "
        "ON CONFLICT (pipeline_run_id, stage) DO UPDATE SET status = EXCLUDED.status, "
        "rows_loaded = EXCLUDED.rows_loaded, finished_at_utc = EXCLUDED.finished_at_utc"),
        {"r": run_id, "s": stage, "st": status, "n": rows, "t0": started, "t1": datetime.now(timezone.utc)})


def load_postgres(run_id: str | None = None) -> dict:
    """Load staging + curated in ONE transaction: either both land or neither does."""
    s = load_settings()
    run_id = run_id or uuid.uuid4().hex[:12]
    started = datetime.now(timezone.utc)
    staging = pd.read_csv(s.path("staging_dir") / STAGING_FILE)
    curated = pd.read_csv(s.path("curated_dir") / CURATED_FILE)

    engine = get_engine()
    init_db(engine)
    with engine.begin() as conn:
        n_stage = upsert(conn, TABLES["staging"], staging)
        n_cur = upsert(conn, TABLES["curated"], curated)
        _log_run(conn, run_id, "load_staging", "success", n_stage, started)
        _log_run(conn, run_id, "load_curated", "success", n_cur, started)
    stats = {"run_id": run_id, "staging_rows_upserted": n_stage, "curated_rows_upserted": n_cur}
    log.info("load complete %s", stats)
    return stats


def verify_db() -> dict:
    """Row counts + duplicate-key checks. Raises if anything is off."""
    engine = get_engine()
    out = {}
    with engine.connect() as conn:
        for name, table in TABLES.items():
            n = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            d = conn.execute(text(f"SELECT COUNT(*) - COUNT(DISTINCT id) FROM {table}")).scalar()
            out[f"{name}_rows"], out[f"{name}_duplicate_ids"] = n, d
        out["run_log_rows"] = conn.execute(text("SELECT COUNT(*) FROM pipeline_run_log")).scalar()
    log.info("db verification %s", out)
    if any(v for k, v in out.items() if k.endswith("duplicate_ids")):
        raise RuntimeError(f"Duplicate business keys in PostgreSQL: {out}")
    return out