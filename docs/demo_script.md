# Technical demonstration script (brief section 10.1)

Run from a fresh clone or a clean working copy. `scripts/clean_clone_check.ps1` automates steps 1 to 10 and saves the
transcript to `docs/evidence/clean_clone.txt`.

| # | Required step | Command / what to show |
|---|---|---|
| 1 | Repository and commit history | `git log --oneline` (one commit per milestone) |
| 2 | `.env`, secrets and large artifacts not committed | `git ls-files .env` prints nothing; `git status`; `.gitignore` |
| 3 | Verify source checksum against the manifest | `(Get-FileHash data\source\Stroke_Prediction_Dataset.csv -Algorithm SHA256).Hash` vs `metadata\source_manifest.yml` |
| 4 | Build and start the environment | `docker compose up -d postgres`; `docker compose ps` (healthy); `docker compose build pipeline` |
| 5 | Execute the pipeline | `docker compose run --rm pipeline python -m src.cli run-all`, or trigger the DAG at http://localhost:8081 |
| 6 | Raw, staging, curated and outputs | `Get-ChildItem data\raw, data\staging, data\curated, outputs` |
| 7 | PostgreSQL tables and audit records | `docker compose exec postgres psql -U pipeline -d stroke_dw -c "SELECT pipeline_run_id, stage, rows_loaded FROM pipeline_run_log ORDER BY 1,2;"` and `-c "SELECT COUNT(*) FROM curated_stroke;"` |
| 8 | Data-quality and code tests | `docker compose run --rm pipeline python -m pytest -q`; show `outputs\quality\curated.json` |
| 9 | Airflow graph and run states | DAG Graph view with 10 green tasks; Grid view |
| 10 | Second run, no duplicates | `run-all --incremental`, then `verify-db` (3,265 rows, 0 duplicates) |
| 11 | Expected vs new metrics side by side | `python -m src.cli compare`, open `docs\metrics_comparison.md` |
| 12 | A failure and recovery | `inject-failure --kind missing_column`, `validate-raw` (fails), `--restore`, `validate-raw` (passes); or show `docs/evidence/failure_injection.txt` |
| 13 | One design decision I would change for production | e.g. replace row-wise INSERT with `COPY` and Airflow `standalone` with a real executor, Postgres metadata DB and authentication |

After step 12, run `run-all` again so every layer is rebuilt.

## Submission checklist (brief section 15) and where the evidence is

| Checklist item | Evidence |
|---|---|
| Repository URL accessible to instructor | add the instructor as a collaborator |
| README starts from a clean-machine perspective | `README.md` section 1 |
| Source data legally included or referenced with checksum | `metadata/source_manifest.yml` |
| No secrets or personal absolute paths | acceptance A3 and A4 |
| Data contract and source profile | `metadata/data_contract.yml`, `source_profile.md` |
| Raw, staging, curated, output semantics | `README.md` section 2, `docs/lineage.png` |
| Full and incremental ingestion demonstrated | `docs/evidence/ingest_runs.txt` |
| Docker and Compose | `Dockerfile`, `Dockerfile.airflow`, `docker-compose.yml` |
| PostgreSQL rerun-safe load | `tests/test_storage.py`, `docs/evidence/db_rerun.txt` |
| Storage benchmark on equivalent logical data | `docs/benchmark_report.md` |
| Partition demonstration | `docs/evidence/partition_demo.txt` |
| Airflow DAG runs successfully | screenshots in `docs/evidence/` |
| Quality tests and code tests pass | `pytest -q` |
| Failure and recovery evidence | `docs/evidence/failure_injection.txt` |
| Model retrains from curated data, deterministic | `src/train.py`, `metadata/split_manifest.json` |
| Expected vs actual metrics machine-readable | `outputs/reproducibility_check.json`, `docs/metrics_comparison.md` |
| Second run introduces no duplicates | `verify-db` output |
| Architecture and lineage match implementation | `docs/architecture.png`, `docs/lineage.png`, acceptance A18 |
| Runbook explains restart and recovery | `docs/runbook.md` |
| Reproducibility report explains deviations | `docs/reproducibility_report.md` |
