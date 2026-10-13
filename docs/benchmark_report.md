# Storage Benchmark Report

## Setup
- Data: curated stroke dataset, 3,265 rows x 22 columns; identical logical records in every format
  (each read-back is compared to the original before timing; a mismatch aborts the run).
- Machine: Windows 10, Python 3.12.4, pandas 3.0.6, pyarrow 26.0.0; PostgreSQL 16 in Docker.
- Timing: 1 cold run reported separately and excluded from the median; median of 5 warm runs.
  "Cold" is not a true cold start (the OS file cache was not cleared).
- Raw results: `docs/benchmark_results.md` / `.json`. Evidence: `docs/evidence/`.

## Results
| Format | Size (KB) | Write (ms) | Full read (ms) |
|---|---:|---:|---:|
| CSV | 603.0 | 27.6 | 17.0 |
| JSONL | 1772.2 | 25.7 | 50.0 |
| Parquet | 325.4 | 11.2 | 4.1 |
| PostgreSQL | 1008.0 | 1359.2 | 31.3 |

Selective read (`glucose_score_risk = 2`, 412 rows): Parquet filter pushdown 5.0 ms,
PostgreSQL 14.9 ms (0.20 ms server-side), CSV read-then-filter 24.8 ms,
Parquet partition directory only 21.9 ms, JSONL read-then-filter 66.8 ms.
PostgreSQL server-side: full scan 0.46 ms, selective filter 0.20 ms, GROUP BY 1.02 ms.

## Partition demonstration
Partitioned by `glucose_score_risk` (0 normal / 1 prediabetic / 2 diabetic):
2,555 / 298 / 412 rows. Loading only partition 2 returned 412 rows, matching the curated
dataset (412) and PostgreSQL (412). No natural partition key exists (the dataset has no
date, region, or other time/geography field and is static), so this is a pedagogical
partition chosen because the glucose tiers are analytically meaningful in the study.
At this size the partition-only read (21.9 ms) was slower than Parquet filter pushdown
(5.0 ms): directory listing and dataset discovery cost more than reading 412 rows.
Partitioning pays off with larger data, not here.

## Conclusions for this project (not universal)
- **Source exchange: CSV.** Original format, human-readable, easy to checksum; JSONL is 2.9x
  larger with no benefit for flat tabular data.
- **Pipeline intermediate storage: Parquet** would be best (smallest, fastest, preserves
  types). The current pipeline keeps CSV in raw/staging/curated for readability and
  debugging; at 3,265 rows the cost is negligible. Parquet is the change I would make first.
- **Model input: Parquet**, loaded in ~4 ms with types intact. The `v_model_input` view in
  PostgreSQL is the audited, ordered copy.
- **Analytical querying: PostgreSQL.** Filters and aggregates run in under 1.1 ms
  server-side, with indexes, SQL, and constraints. Client-side cost is dominated by
  transferring rows into pandas, not by the query.

## Limitations
- 3,265 rows means millisecond timings; differences are small and noisy. Single machine,
  single run session.
- PostgreSQL write used `to_sql` multi-row INSERT, not `COPY`, so it overstates database
  write cost.
- Postgres ran in Docker on Windows, which adds network and filesystem overhead.
- Results must not be generalized to other workloads or larger datasets.