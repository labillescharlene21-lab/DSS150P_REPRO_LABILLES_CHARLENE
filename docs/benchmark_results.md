# Benchmark results (auto-generated)

- Rows: **3265** (scale factor 1) | Python 3.12.4 | pandas 3.0.6 | pyarrow 26.0.0
- Machine: Windows-10-10.0.19045-SP0 | Run: 2026-10-13T07:22:58+00:00
- Timing policy: 1 cold run reported separately; median of 5 warm runs

## Size, write, and full-read

| Format | Size (KB) | Write median (ms) | Read median (ms) | Read cold (ms) |
|---|---:|---:|---:|---:|
| csv | 603.0 | 27.6 | 17.0 | 18.0 |
| jsonl | 1772.2 | 25.7 | 50.0 | 51.3 |
| parquet | 325.4 | 11.2 | 4.1 | 4.6 |
| postgres | 1008.0 | 1359.2 | 31.3 | 30.2 |

## Selective read (glucose_score_risk = 2, 412 rows)

| Method | Median (ms) | Cold (ms) |
|---|---:|---:|
| csv_read_all_then_filter | 24.8 | 23.6 |
| jsonl_read_all_then_filter | 66.8 | 74.7 |
| parquet_filter_pushdown | 5.0 | 16.9 |
| parquet_partition_dir_only | 21.9 | 16.4 |
| postgres_select_where | 14.9 | 55.9 |

## PostgreSQL server-side query time (EXPLAIN ANALYZE)

| Query | Median (ms) | Cold (ms) |
|---|---:|---:|
| full_table_scan | 0.46 | 1.20 |
| selective_filter | 0.20 | 0.20 |
| aggregate_group_by | 1.02 | 1.98 |

## Partitions (by `glucose_score_risk`)

| Value | Rows |
|---|---:|
| 0 | 2555 |
| 1 | 298 |
| 2 | 412 |
