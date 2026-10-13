# Technical acceptance report (auto-generated)

Generated 2026-10-13T12:03:06+00:00 | **13 pass, 2 fail, 3 manual**

| ID | Test | Result | Evidence |
|---|---|:---:|---|
| A1 | Repository clones and README setup is sufficient | MANUAL | run scripts/clean_clone_check.ps1 and keep its output in docs/evidence/clean_clone.txt |
| A2 | Source dataset identity verifiable by checksum/manifest | PASS | source SHA-256 matches source_manifest.yml |
| A3 | No machine-specific absolute paths required | PASS | 25 code/config files scanned |
| A4 | No secret credentials committed | PASS | .env ignored and not tracked; no hard-coded secrets found |
| A5 | Environment creatable from declared dependencies/containers | PASS | 24 pinned requirements (xgboost==3.4.1); Dockerfile and compose present |
| A6 | Full ingestion produces expected raw count/checksum | PASS | 5110 raw rows (manifest 5110), checksum on every row matches |
| A7 | Checkpoint demonstration avoids duplicates on rerun | PASS | checkpoint complete and a rerun logged SKIP for committed batches |
| A8 | Staging and curated layers are deterministic | PASS | two independent transforms identical: True; match curated file on disk: True |
| A9 | PostgreSQL load is rerun-safe | PASS | 10 loads logged, table holds 3265 rows, 0 duplicate ids |
| A10 | CSV/JSON/Parquet/PostgreSQL comparison uses the same logical records | PASS | CSV, JSONL and Parquet read back identical to the curated data (benchmark_results.json found; PostgreSQL equality is checked inside `benchmark`) |
| A11 | Selected partition can be read/loaded independently | PASS | partition glucose_score_risk=2 loaded alone: 412 rows (of 3265); postgres: 412 |
| A12 | Airflow DAG has valid dependencies and completes end to end | MANUAL | DAG declares 10 tasks; no completed Airflow run found in outputs/run_records (trigger it and screenshot the Graph) |
| A13 | At least one recoverable failure demonstrated | PASS | recovery evidence: run record demo-fail |
| A14 | Automated quality checks detect intentionally invalid conditions | PASS | quality + failure-injection tests: 29 passed in 28.68s |
| A15 | Second end-to-end run does not increase duplicate business keys | MANUAL | only 0 successful end-to-end run on record; run the pipeline twice |
| A16 | Model metrics regenerated from curated data, not copied | FAIL | metrics, check and summary share run id {'m8-run1', 'final-2'}; metrics newer than curated data: True |
| A17 | Reproduced metric passes the documented tolerance rule | FAIL | status fail: AUC 0.74183 vs 0.75 (diff 0.008165, tolerance 0.001) |
| A18 | Architecture, lineage, runbook, report present and consistent | PASS | 6 documents present; every documented command exists; all 10 DAG tasks are in the runbook |

MANUAL means code cannot prove it alone; the evidence named in the row must be collected.
