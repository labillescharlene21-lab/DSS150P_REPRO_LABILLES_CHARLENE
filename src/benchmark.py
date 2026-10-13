"""Storage benchmark (CSV / JSONL / Parquet / PostgreSQL) and partition workflow.

All formats hold the SAME logical records (the curated dataset). Every read is checked against
the original frame before it is timed, so the comparison cannot silently compare different data.
"""
from __future__ import annotations

import json
import logging
import platform
import shutil
import statistics
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pyarrow
from sqlalchemy import text

from src.config import ROOT, load_settings
from src.storage import get_engine
from src.transform import CURATED_FILE

log = logging.getLogger("benchmark")
BENCH_TABLE = "bench_curated"


# ---------------------------------------------------------------- helpers
def _cfg():
    s = load_settings()
    st = s.raw["storage"]
    return s, st, ROOT / st["formats_dir"], ROOT / st["partition_dir"]


def load_curated(scale: int = 1) -> pd.DataFrame:
    s = load_settings()
    df = pd.read_csv(s.path("curated_dir") / CURATED_FILE).sort_values("source_row_seq").reset_index(drop=True)
    if scale > 1:                                           # timing-only enlargement, labelled in the report
        n = int(df["source_row_seq"].max()) + 1            # seq has gaps (age filter), so offset by max
        copies = []
        for k in range(scale):                              # distinct keys per copy => stable ordering
            c = df.copy()
            c["id"] = c["id"] + k * 10_000_000
            c["source_row_seq"] = c["source_row_seq"] + k * n
            c["record_hash"] = c["record_hash"] + f"-{k}"
            copies.append(c)
        df = pd.concat(copies, ignore_index=True)
    return df


def timed(fn, repeats: int) -> dict:
    """1 cold run (reported separately, NOT in the median) + `repeats` warm runs."""
    t0 = time.perf_counter(); fn(); cold = time.perf_counter() - t0
    runs = []
    for _ in range(repeats):
        t0 = time.perf_counter(); fn(); runs.append(time.perf_counter() - t0)
    return {"cold_s": cold, "median_s": statistics.median(runs), "min_s": min(runs),
            "max_s": max(runs), "warm_runs": repeats}


def assert_equivalent(ref: pd.DataFrame, other: pd.DataFrame, label: str) -> None:
    other = other[ref.columns.tolist()]
    if len(ref) != len(other):
        raise AssertionError(f"{label}: {len(other)} rows, expected {len(ref)}")
    for c in ref.columns:
        a, b = ref[c].reset_index(drop=True), other[c].reset_index(drop=True)
        if pd.api.types.is_numeric_dtype(a):
            if not np.allclose(a.astype(float), b.astype(float), rtol=0, atol=1e-6):
                raise AssertionError(f"{label}: column {c} differs")
        elif not (a.astype(str) == b.astype(str)).all():
            raise AssertionError(f"{label}: column {c} differs")


def _pg_exec_ms(conn, sql: str) -> float:
    plan = conn.execute(text(f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}")).scalar()
    plan = plan if isinstance(plan, list) else json.loads(plan)
    return float(plan[0]["Execution Time"])


# ---------------------------------------------------------------- writers / readers
def write_csv(df, path):    df.to_csv(path, index=False, encoding="utf-8")
def write_jsonl(df, path):  df.to_json(path, orient="records", lines=True, double_precision=15)
def write_parquet(df, path): df.to_parquet(path, index=False, engine="pyarrow")
def write_pg(df, engine):
    df.to_sql(BENCH_TABLE, engine, if_exists="replace", index=False, method="multi", chunksize=500)

def read_csv(path):    return pd.read_csv(path)
def read_jsonl(path):  return pd.read_json(path, lines=True, convert_dates=False, dtype=False)
def read_parquet(path): return pd.read_parquet(path, engine="pyarrow")
def read_pg(engine):   return pd.read_sql(f"SELECT * FROM {BENCH_TABLE} ORDER BY source_row_seq", engine)


# ---------------------------------------------------------------- partitioning
def write_partitions(df: pd.DataFrame) -> dict:
    _, st, _, part_dir = _cfg()
    col = st["partition_column"]
    if part_dir.exists():
        shutil.rmtree(part_dir)                             # replace-whole-dataset: rerun safe
    part_dir.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(part_dir, partition_cols=[col], index=False, engine="pyarrow")
    counts = df[col].value_counts().sort_index().to_dict()
    log.info("partitioned by %s: %s", col, counts)
    return {str(k): int(v) for k, v in counts.items()}


def read_partition(value) -> pd.DataFrame:
    """Load ONE partition by reading only its directory (no other partition is touched)."""
    _, st, _, part_dir = _cfg()
    path = part_dir / f"{st['partition_column']}={value}"
    if not path.exists():
        raise FileNotFoundError(f"Partition not found: {path}")
    df = pd.read_parquet(path, engine="pyarrow")
    df[st["partition_column"]] = int(value)                 # column lives in the directory name
    return df


def verify_partition(value, full: pd.DataFrame | None = None) -> dict:
    _, st, _, _ = _cfg()
    col = st["partition_column"]
    full = full if full is not None else load_curated()
    part = read_partition(value)
    expected = int((full[col] == int(value)).sum())
    result = {"partition": f"{col}={value}", "rows_loaded": len(part), "rows_expected_from_curated": expected}
    try:
        with get_engine().connect() as conn:
            result["rows_in_postgres"] = int(conn.execute(
                text(f"SELECT COUNT(*) FROM curated_stroke WHERE {col.lower()} = :v"), {"v": int(value)}).scalar())
    except Exception as e:                                  # DB optional for this check
        result["rows_in_postgres"] = f"unavailable ({type(e).__name__})"
    pg = result["rows_in_postgres"]
    ok = len(part) == expected and (not isinstance(pg, int) or pg == expected)
    result["verified"] = bool(ok)
    if not ok:
        raise AssertionError(f"Partition verification failed: {result}")
    return result


# ---------------------------------------------------------------- benchmark
def run_benchmark(repeats: int | None = None, scale: int = 1) -> dict:
    _, st, fmt_dir, part_dir = _cfg()
    repeats = repeats or st["benchmark_repeats"]
    col = st["partition_column"]
    sel_value = 2                                           # "diabetic" tier: selective filter used everywhere
    fmt_dir.mkdir(parents=True, exist_ok=True)
    df = load_curated(scale)
    engine = get_engine()
    paths = {"csv": fmt_dir / "stroke_curated.csv", "jsonl": fmt_dir / "stroke_curated.jsonl",
             "parquet": fmt_dir / "stroke_curated.parquet"}

    results = {
        "environment": {
            "python": platform.python_version(), "platform": platform.platform(),
            "pandas": pd.__version__, "pyarrow": pyarrow.__version__,
            "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        "rows": len(df), "scale_factor": scale, "repeats": repeats,
        "timing_policy": f"1 cold run reported separately; median of {repeats} warm runs",
        "formats": {},
    }

    writers = {"csv": write_csv, "jsonl": write_jsonl, "parquet": write_parquet}
    readers = {"csv": read_csv, "jsonl": read_jsonl, "parquet": read_parquet}
    for name, path in paths.items():
        w = timed(lambda: writers[name](df, path), repeats)
        assert_equivalent(df, readers[name](path), name)    # same logical records, verified
        r = timed(lambda: readers[name](path), repeats)
        results["formats"][name] = {"size_bytes": path.stat().st_size, "write": w, "read_full": r}

    w = timed(lambda: write_pg(df, engine), repeats)
    assert_equivalent(df, read_pg(engine), "postgres")
    r = timed(lambda: read_pg(engine), repeats)
    with engine.begin() as conn:
        conn.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS ix_bench_{col} ON {BENCH_TABLE} ({col.lower()})")
        conn.exec_driver_sql(f"ANALYZE {BENCH_TABLE}")
        size = int(conn.execute(text(f"SELECT pg_total_relation_size('{BENCH_TABLE}')")).scalar())
    results["formats"]["postgres"] = {"size_bytes": size, "write": w, "read_full": r}

    # ---- selective reads (same filter everywhere: partition column == 2)
    expected = int((df[col] == sel_value).sum())
    part_counts = write_partitions(df)
    sel = {}

    def check(n, label):
        if n != expected:
            raise AssertionError(f"{label}: selective read returned {n}, expected {expected}")

    sel["csv_read_all_then_filter"] = timed(lambda: check(len(read_csv(paths["csv"]).query(f"{col} == {sel_value}")), "csv"), repeats)
    sel["jsonl_read_all_then_filter"] = timed(lambda: check(len(read_jsonl(paths["jsonl"]).query(f"{col} == {sel_value}")), "jsonl"), repeats)
    sel["parquet_filter_pushdown"] = timed(lambda: check(len(pd.read_parquet(paths["parquet"], filters=[(col, "==", sel_value)])), "parquet"), repeats)
    sel["parquet_partition_dir_only"] = timed(lambda: check(len(read_partition(sel_value)), "partition"), repeats)
    sel_sql = f"SELECT * FROM {BENCH_TABLE} WHERE {col.lower()} = {sel_value}"
    sel["postgres_select_where"] = timed(lambda: check(len(pd.read_sql(sel_sql, engine)), "postgres"), repeats)
    results["selective"] = {"filter": f"{col} = {sel_value}", "expected_rows": expected, "timings": sel}

    # ---- PostgreSQL server-side query timings (EXPLAIN ANALYZE execution time, median of repeats)
    queries = {
        "full_table_scan": f"SELECT * FROM {BENCH_TABLE}",
        "selective_filter": sel_sql,
        "aggregate_group_by": f"SELECT {col.lower()}, COUNT(*), AVG(stroke::float) FROM {BENCH_TABLE} GROUP BY 1",
    }
    pg_q = {}
    with engine.connect() as conn:
        for qname, sql in queries.items():
            runs = [_pg_exec_ms(conn, sql) for _ in range(repeats + 1)]
            pg_q[qname] = {"cold_ms": runs[0], "median_ms": statistics.median(runs[1:])}
    results["postgres_queries"] = pg_q
    results["partitions"] = {"column": col, "row_counts": part_counts}

    with engine.begin() as conn:
        conn.exec_driver_sql(f"DROP TABLE IF EXISTS {BENCH_TABLE}")   # keep the DB clean

    out = ROOT / "docs"
    out.mkdir(exist_ok=True)
    (out / "benchmark_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (out / "benchmark_results.md").write_text(render_markdown(results), encoding="utf-8")
    log.info("benchmark done -> docs/benchmark_results.json, docs/benchmark_results.md")
    return results


def render_markdown(r: dict) -> str:
    e = r["environment"]
    L = [f"# Benchmark results (auto-generated)", "",
         f"- Rows: **{r['rows']}** (scale factor {r['scale_factor']}) | Python {e['python']} | pandas {e['pandas']} | pyarrow {e['pyarrow']}",
         f"- Machine: {e['platform']} | Run: {e['run_at_utc']}",
         f"- Timing policy: {r['timing_policy']}", "",
         "## Size, write, and full-read", "",
         "| Format | Size (KB) | Write median (ms) | Read median (ms) | Read cold (ms) |", "|---|---:|---:|---:|---:|"]
    for n, f in r["formats"].items():
        L.append(f"| {n} | {f['size_bytes']/1024:.1f} | {f['write']['median_s']*1000:.1f} | "
                 f"{f['read_full']['median_s']*1000:.1f} | {f['read_full']['cold_s']*1000:.1f} |")
    L += ["", f"## Selective read ({r['selective']['filter']}, {r['selective']['expected_rows']} rows)", "",
          "| Method | Median (ms) | Cold (ms) |", "|---|---:|---:|"]
    for n, t in r["selective"]["timings"].items():
        L.append(f"| {n} | {t['median_s']*1000:.1f} | {t['cold_s']*1000:.1f} |")
    L += ["", "## PostgreSQL server-side query time (EXPLAIN ANALYZE)", "",
          "| Query | Median (ms) | Cold (ms) |", "|---|---:|---:|"]
    for n, t in r["postgres_queries"].items():
        L.append(f"| {n} | {t['median_ms']:.2f} | {t['cold_ms']:.2f} |")
    L += ["", f"## Partitions (by `{r['partitions']['column']}`)", "", "| Value | Rows |", "|---|---:|"]
    for k, v in r["partitions"]["row_counts"].items():
        L.append(f"| {k} | {v} |")
    return "\n".join(L) + "\n"