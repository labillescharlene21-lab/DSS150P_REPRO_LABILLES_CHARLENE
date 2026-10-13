# Runbook

For operators of the stroke-risk pipeline. Commands are PowerShell; replace `docker compose run --rm pipeline` with
nothing if you run locally in the virtual environment.

## 1. Normal execution

| How | Command |
|---|---|
| CLI, full refresh | `docker compose run --rm pipeline python -m src.cli run-all` |
| CLI, incremental (skip committed batches) | `docker compose run --rm pipeline python -m src.cli run-all --incremental` |
| Airflow | `docker compose up -d airflow`, open http://localhost:8081, trigger `predictive_repro_pipeline` |

Success = `outputs/run_records/<run_id>.json` has `"status": "success"`, and `outputs/reproducibility_check.json` has `"status": "pass"`.

## 2. Stages (CLI command = DAG task)

| DAG task | Command | What it guarantees | Typical failure |
|---|---|---|---|
| `ingest_source` | `ingest [--force]` | source checksum equals manifest; batches written atomically; checkpoint advanced only after a batch is written | `Checksum mismatch`, `FileNotFoundError` for the CSV |
| `validate_raw` | `validate-raw` | 12 checks: schema, row count, source checksum, key uniqueness, target completeness, null rates, record-hash integrity | `schema_required_columns`, `uniqueness_id`, `completeness_target`, `integrity_record_hash` |
| `transform_staging` | `transform-staging` | typed, cleaned, in-scope rows; invalid rows to `data/quarantine/rejected_rows.csv` | `Schema violation: required columns missing` |
| `build_curated` | `build-curated` | score columns, VAAF, TGI; ordered by `source_row_seq` | `staging ... not found` (run the previous stage) |
| `load_postgres` | `load` | one transaction, `ON CONFLICT (id) DO UPDATE`; idempotent | `OperationalError` (database down) |
| `validate_curated` | `validate-curated` | 23 checks incl. derived-column consistency, class balance, feature fingerprint, PostgreSQL agrees with the file | `completeness_row_count`, `business_feature_fingerprint_matches_baseline` |
| `train_model` | `train [--seed N]` | deterministic split, split manifest, no train/test overlap | `train split failed: no_train_test_overlap` |
| `evaluate_model` | `evaluate [--seed N]` | test rows equal the split manifest; model features equal configured features | `Test rows differ from the split manifest` |
| `reproducibility_check` | `repro-check` | AUC within 0.001 of 0.7500; split ids equal the baseline hashes | `Reproducibility check failed` |
| `publish_outputs` | `publish` | copies the data product, writes `run_summary.json` with counts and quality results | missing `reproducibility_check.json` |

## 3. Where to look when something fails

1. `outputs/run_records/<run_id>.json`: which stage failed, its error type and message, attempts, durations.
2. `outputs/quality/raw.json` and `curated.json`: every check with category and result.
3. `logs/pipeline.jsonl`: one JSON line per event (`ts`, `pipeline_run_id`, `stage`, counts, `error_message`).
4. Airflow: Grid view, then the task's **Logs** tab. `Upstream Failed` tasks never ran; fix the first red task.
5. `data/quarantine/rejected_rows.csv`: rows removed for contract violations, with `reject_reason`.

## 4. Common failures

| Message | Cause | Fix |
|---|---|---|
| `Checksum mismatch` | wrong file in `data/source` | put the original CSV back; `(Get-FileHash ... -Algorithm SHA256)` must equal `source_manifest.yml` |
| `validate_raw failed: schema_required_columns (... absent in some batches {'col': [2]})` | a raw batch lost a column | `ingest --force` to rebuild raw from the source |
| `validate_raw failed: integrity_record_hash` | a raw batch was edited after ingestion | `ingest --force` |
| `validate_curated failed: completeness_row_count (3264 ...)` | a row was quarantined; see `rejected_rows.csv` | fix or remove the cause, then `run-all` |
| `business_feature_fingerprint_matches_baseline` | feature distribution drifted: a cleaning or feature rule changed | review `git diff src/transform.py config/settings.yml`; the rule change is the cause |
| `PostgreSQL unreachable` / `OperationalError` | database not running or wrong `.env` | `docker compose up -d postgres`; check `docker compose ps` shows `healthy` |
| `port is already allocated` | another process uses the port | change `POSTGRES_PORT` in `.env` or the Airflow host port |
| AUC `0.7509` | XGBoost < 3.3.0 | rebuild the image / venv from `requirements.txt` |
| `Reproducibility check failed` after a code change | the change altered data, split, or model | `python -m src.cli diagnose` and read `docs/diagnosis_results.md` |

## 5. Restart and rerun

Every stage is idempotent, so any stage can be retried safely.

- **Retry in Airflow:** open the failed run, select the first failed task, **Clear Task** with downstream. Tasks retry
  automatically twice, 30 seconds apart.
- **Rerun from a stage on the CLI:** run that stage and the ones after it with the same `--run-id`.
  The run record keeps both attempts.
- **Checkpoint recovery:** the ingest checkpoint is `state/ingest_checkpoint.json` (committed batches + source
  checksum). If ingestion stopped after batch 1, rerun `ingest` and only batches 2-3 are written. To start over,
  use `ingest --force`, which clears raw batches and the checkpoint.
- **Load retried after an unacknowledged commit:** re-running `load` is safe; rows are upserted by `id` in one
  transaction and the run log is keyed by `(pipeline_run_id, stage)`.

## 6. Database reset

| Goal | Command |
|---|---|
| Re-create tables only | `docker compose run --rm pipeline python -m src.cli init-db` (idempotent) |
| Empty the data tables | `docker compose exec postgres psql -U pipeline -d stroke_dw -c "TRUNCATE staging_stroke, curated_stroke, pipeline_run_log;"` then `run-all` |
| Destroy the database volume | `docker compose down -v` (deletes ALL PostgreSQL data), then `docker compose up -d postgres` and `run-all` |

## 7. Rollback and cleanup

- **Generated data only:** delete `data\raw\*`, `data\staging\*`, `data\curated\*`, `data\partitioned\*`, `state\*`
  (keep the `.gitkeep` files), then `run-all`. The source file and PostgreSQL are untouched.
- **Code or config regression:** `git log --oneline`, then `git checkout <good commit> -- <file>` (or `git revert`),
  and `run-all`. `reproducibility_check` tells you whether the baseline result is back.
- **After the failure-injection demo:** `inject-failure --restore` (or `ingest --force`), then `run-all`, so every layer is rebuilt.

## 8. Failure-injection demonstration (safe and reversible)

```powershell
python -m src.cli inject-failure --kind missing_column     # also: duplicate_id, null_target, tamper_bmi, bad_glucose
python -m src.cli validate-raw                              # fails; nothing downstream runs; outputs\ is untouched
python -m src.cli inject-failure --restore
python -m src.cli validate-raw                              # passes
```

## 9. What to monitor if this ran daily

Run status and duration per stage; row counts per layer against expectations; quarantine count; null rates;
source checksum or a new source version (freshness for a static file); feature-distribution drift against
`metadata/feature_fingerprint.json`; class balance; PostgreSQL duplicate keys; model AUC against the baseline with
its confidence interval; Airflow retries and failures; disk usage of `data/` and `outputs/`.
