# Reproducible stroke-risk pipeline (DSS150P laboratory)

An individual data-engineering rebuild of the group's *Predictive Analysis* project
(**"Strengthening Philippine Stroke Care: A Machine Learning-Based Stroke Risk Assessment"**,
S. Abad, C. Labilles, T. Tumaneng, Mapua University, DSS141P). The prior project is the **baseline data
product**; this repository ingests the same source dataset, validates, transforms, stores, orchestrates and
tests it, and regenerates the baseline predictive result in a clean environment.

> **Result:** the pipeline reproduces the baseline XGBoost ROC-AUC of **0.7500** (reproduced 0.75004,
> difference 0.00004, tolerance 0.001) on the *same* 653 test rows (SHA-256 of train/test ids match the baseline).
> See `docs/metrics_comparison.md` (regenerated on every run) and `docs/reproducibility_report.md`.

Prior group work is reused (dataset, target, features, model family, hyperparameters, cleaning rules) and is
credited in `notebooks/baseline/README.md`. All engineering in this repository is my own work; AI assistance is
acknowledged at the end of this file.

---

## 1. Quick start on a clean machine

**Prerequisites:** Git, Docker Desktop (Compose v2), and the source dataset file. Commands are PowerShell.
Python is only needed for local development (section 5).

```powershell
# 1. Clone
git clone https://github.com/labillescharlene21-lab/DSS150P_REPRO_LABILLES_CHARLENE.git
cd DSS150P_REPRO_LABILLES_CHARLENE

# 2. Place the exact source dataset (it is NOT committed; see section 4), then verify its identity
Copy-Item "<path to>\Stroke_Prediction_Dataset.csv" data\source\Stroke_Prediction_Dataset.csv
(Get-FileHash data\source\Stroke_Prediction_Dataset.csv -Algorithm SHA256).Hash   # must equal sha256 in metadata\source_manifest.yml

# 3. Environment-specific values only (if port 5432 is busy on your machine, set POSTGRES_PORT=5433)
Copy-Item .env.example .env

# 4. Start PostgreSQL and wait until it is healthy
docker compose up -d postgres
docker compose ps

# 5. Run the full pipeline (first run builds the image)
docker compose run --rm pipeline python -m src.cli run-all

# 6. Validate
docker compose run --rm pipeline python -m src.cli verify-db      # row counts + duplicate keys in PostgreSQL
docker compose run --rm pipeline python -m pytest -q              # code and data-quality tests
docker compose run --rm pipeline python -m src.cli compare        # baseline vs reproduced, side by side
docker compose run --rm pipeline python -m src.cli acceptance     # the brief's acceptance tests A1-A18

# 7. Run again: no duplicate logical records, same metrics
docker compose run --rm pipeline python -m src.cli run-all --incremental
docker compose run --rm pipeline python -m src.cli verify-db
```

Expected: `verify-db` shows `staging_rows: 3265`, `curated_rows: 3265`, and `0` duplicate ids after **every** run.
`outputs\reproducibility_check.json` shows `"status": "pass"`.

### Airflow

```powershell
docker compose up -d airflow
# open http://localhost:8081   (local lab setup: no login screen)
```
Unpause `predictive_repro_pipeline` and press **Trigger**. Parameters: `full_refresh` (true re-ingests everything,
false skips committed batches) and `seed` (42 = baseline; other seeds are legitimate experiments and report
`not_applicable_non_baseline_seed` instead of failing). The DAG calls the same CLI as `run-all`; it contains no
business logic. `docker compose exec airflow airflow dags list-import-errors` should print `No data found`.

## 2. What the pipeline does

```
source CSV -> ingest_source -> validate_raw -> transform_staging -> build_curated -> load_postgres
          -> validate_curated -> train_model -> evaluate_model -> reproducibility_check -> publish_outputs
```

| Layer | Location | Meaning |
|---|---|---|
| Source | `data/source/` | immutable original file; identity = SHA-256 in `metadata/source_manifest.yml` |
| Raw | `data/raw/batch_00N.csv` | faithful text copy in 3 deterministic batches + audit columns (`pipeline_run_id`, `record_hash`, ...) |
| Staging | `data/staging/`, table `staging_stroke` | typed, cleaned, in study scope (age 35-90), BMI imputed; bad rows in `data/quarantine/` |
| Curated | `data/curated/`, table `curated_stroke`, view `v_model_input` | score columns, VAAF, TGI; ordered by `source_row_seq` |
| Outputs | `outputs/` | `metrics.json`, `predictions.csv`, `model/xgb_model.json`, `run_summary.json`, quality reports |

Diagrams: `docs/architecture.png` (components and data movement) and `docs/lineage.png` (dataset- and field-level lineage).

## 3. Repository layout

```
config/settings.yml          paths, seeds, hyperparameters, thresholds, quality limits (no secrets)
.env.example                 environment-specific values (copy to .env; never commit .env)
metadata/                    source_manifest.yml, data_contract.yml, expected_metrics.json,
                             feature_fingerprint.json, split_manifest.json, source_profile.md
src/                         config, ingest, transform, storage, validate, quality, train, evaluate, publish, cli
                             + benchmark, observability, inject, diagnose, report, acceptance
sql/                         schema.sql, transformations.sql
dags/                        predictive_repro_pipeline.py
tests/                       unit, integration, data-quality and failure-injection tests
docs/                        architecture.png, lineage.png, runbook.md, benchmark_report.md,
                             reproducibility_report.md, reflection_questions.md, demo_script.md, evidence/
scripts/                     make_diagrams.py, clean_clone_check.ps1
Dockerfile, Dockerfile.airflow, docker-compose.yml, requirements.txt
```

**Deviations from the suggested structure (equivalent separation of concerns):** quality rules live in
`src/quality.py` (called by `validate.py`); logging and run records in `src/observability.py`; the storage benchmark
in `src/benchmark.py` (so `storage.py` stays focused on loading); transformation is split into `run_staging` and
`run_curated` to match the DAG; `Dockerfile.airflow` builds the Airflow image with the pipeline in its own virtualenv.

## 4. Data, licensing and secrets

- The raw dataset is **not committed**: its redistribution terms are stated in `metadata/source_manifest.yml`
  (`origin`, `license`). To obtain it, follow `origin` there and verify the checksum (step 2 above).
- No credentials are committed. `.env` is git-ignored; `.env.example` holds placeholders only.
- Generated data layers (`data/raw|staging|curated|partitioned|quarantine`) are git-ignored and rebuilt by the pipeline.
  Small delivery outputs (`outputs/metrics.json`, `predictions.csv`, reports) are committed as evidence.

## 5. Local development (optional)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
docker compose up -d postgres          # .env: POSTGRES_HOST=localhost, POSTGRES_PORT=5432 (or your mapped port)
python -m src.cli run-all
python -m pytest -q
```
`requirements.txt` pins `xgboost` to 3.3.0 or newer on purpose: older versions give AUC 0.7509 on identical data
(see `docs/diagnosis_results.md`). Airflow does not run on Windows, so it runs only in Docker.

## 6. Commands

| Command | Purpose |
|---|---|
| `python -m src.cli run-all [--incremental] [--seed N]` | whole pipeline under one run id |
| `python -m src.cli ingest / validate-raw / transform-staging / build-curated / load / validate-curated / train / evaluate / repro-check / publish` | individual stages (same names as the DAG tasks) |
| `python -m src.cli verify-db` | row counts and duplicate-key check in PostgreSQL |
| `python -m src.cli benchmark` and `partition --value 2` | storage benchmark; load and verify one partition |
| `python -m src.cli diagnose` | one-factor-at-a-time experiments: what moves the metric |
| `python -m src.cli compare` | baseline vs reproduced results |
| `python -m src.cli acceptance` | acceptance tests A1-A18 |
| `python -m src.cli inject-failure --kind missing_column` / `--restore` | **demo only**: reversible fault in one raw batch |

## 7. Troubleshooting (details in `docs/runbook.md`)

| Symptom | Fix |
|---|---|
| `port is already allocated` | change `POSTGRES_PORT` in `.env` (or the Airflow host port in `docker-compose.yml`) |
| `variable is not set` / `.env not found` | `Copy-Item .env.example .env` |
| `Checksum mismatch` | the CSV in `data\source` is not the file in `source_manifest.yml`; replace it |
| AUC `0.7509` instead of `0.7500` | XGBoost older than 3.3.0; rebuild from `requirements.txt` |
| `curated rows ... expected 3265` after a failure demo | rerun `run-all` to rebuild every layer |
| tests are skipped (`s`) | PostgreSQL is not reachable; `docker compose up -d postgres` |

## 8. Acknowledgements

- **Prior work:** the dataset, problem, features, model family, hyperparameters and cleaning rules come from the
  group project cited above; its notebooks are kept in `notebooks/baseline/` for reference.
- **AI assistance:** Claude (Anthropic) was used for guidance, code drafting, debugging and documentation drafting.
  I reviewed, ran and tested the code, and I can explain every module, the failure behavior and the design choices.
