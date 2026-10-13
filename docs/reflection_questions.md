# Analysis and reflection questions (draft answers grounded in this implementation)

> These drafts describe what this repository actually does. Rewrite them in your own words and be ready to
> explain each one and demonstrate it; the technical defense tests exactly that.

**1. What prevented another person from reproducing the previous project immediately?**
The work was split across three Colab notebooks chained through intermediate CSV files, reading `/content/...`
paths that exist only in one Colab session. Cleaning rules (gender "Other" to the mode, children with "Unknown"
smoking, BMI median) lived only in notebook cells. No library versions were recorded, and they matter: XGBoost
before 3.3.0 gives AUC 0.75087, not 0.7500. The split was done twice, with the class weight taken from an earlier
stratified split. The paper lists hyperparameters (183 trees, 0.029) that differ from the notebook's (250, 0.02,
depth 2). The paper says there were no nulls, but the raw data has 201 missing BMI values.

**2. Which artifact is the true authoritative source?**
The original file is the only authority on *content*; it is immutable and identified by its SHA-256. The raw copy is
evidence of exactly what was ingested (text, with run id, checksum and row hash), not a new authority. The curated
dataset is the authoritative *data product* for analysis and modeling: it is rebuildable from the source by
deterministic code. The model-ready input (`v_model_input`, 13 features plus target) is a projection of curated and
never replaces it.

**3. What identifier or rule prevents duplicates, and what makes it valid?**
The business key `id` (primary key in PostgreSQL, used in `ON CONFLICT (id)`), plus `source_row_seq` and a SHA-256
`record_hash` of each source row, both unique. This is valid because the profile shows 5,110 distinct ids and no
duplicate rows, so an id identifies one patient record; the hash detects a changed record under the same id.

**4. With no natural update timestamp, how was incremental ingestion simulated honestly?**
The file order gives an immutable sequence (`source_row_seq`). The source is cut into 3 deterministic contiguous
batches, and a checkpoint (`state/ingest_checkpoint.json`) records which batches are committed, tied to the source
checksum. It advances only after a batch is written and validated. It is documented everywhere as a laboratory
simulation; the checkpoint is a batch counter, not a business timestamp.

**5. Which transformations belong in staging versus curated, and why?**
Staging makes data trustworthy without adding meaning: type conversion, contract checks and quarantine, gender and
smoking fixes, the study age scope, and BMI imputation. Curated adds clinical or business meaning: the score columns
(Asian BMI cutoff 23, glucose tiers, smoking score), VAAF and TGI, and the deterministic ordering. Separating them
means a feature-definition change does not require re-cleaning, and a cleaning change is visible in staging counts.

**6. Which storage format performed best, and why not generalize?**
In my run (`docs/benchmark_report.md`) Parquet was smallest (325 KB vs 603 KB CSV, 1,772 KB JSONL) and fastest to
read (4.1 ms); PostgreSQL answered filtered queries in under 1.1 ms server-side. The result is specific to a
3,265-row table with 22 columns on one machine, a read-heavy pandas workload, and `to_sql` INSERT loading
(PostgreSQL write was slow because of that method, not the database). Other workloads, sizes, concurrency or
`COPY` loading could rank them differently.

**7. What happens if Airflow retries the load task after the database committed but Airflow did not receive confirmation?**
The task runs again against rows that are already there.

**8. How does the design make that retry safe?**
The load is an upsert (`INSERT ... ON CONFLICT (id) DO UPDATE`), so writing the same rows again leaves the table
unchanged. Staging and curated load in one transaction (all or nothing). The run log is keyed by
`(pipeline_run_id, stage)`, so a retry updates one row instead of adding another. Tests cover double upsert, constraint
rejection and rollback (`tests/test_storage.py`).

**9. Which data-quality check is most likely to detect a change that would silently damage model accuracy?**
`business_feature_fingerprint_matches_baseline`: it compares the mean and standard deviation of all 13 features with
the baseline. A change such as a different BMI imputation or cutoff keeps every schema, null and range check green
but shifts these statistics; a test demonstrates it. The derived-column consistency checks (TGI equals BMI times
glucose, score columns match their sources) are a close second.

**10. How do you know training and test rows are the same logical rows as the baseline?**
`metadata/split_manifest.json` stores SHA-256 hashes of the sorted train and test ids, and `expected_metrics.json`
holds the hashes obtained by applying the notebook's split to the group's own `Engineered2.csv`. `repro-check`
compares them, and `diagnose` confirms the curated data equals the group's file.

**11. What sources of nondeterminism remain?**
XGBoost version (pinned to 3.3.0 or newer), possible differences across CPU architectures or operating systems (not
verified), and the BMI median computed before the split (deterministic but a leakage choice). Python, NumPy and
XGBoost are seeded from one setting. pandas 2.3.3 vs 3.0 and scikit-learn 1.7.2 vs 1.8.0 produced identical results
in my tests. Airflow scheduling cannot change results because the stages are deterministic and ordered.

**12. If the reproduced metric differs, how do you find out why?**
Follow `docs/diagnosis_results.md`: first confirm data identity and the split hashes; then change one factor at a time
(preprocessing, split, hyperparameters, seeds) and see which moves the AUC beyond the tolerance; then compare library
versions, then platform. The experiment table shows, for example, that a stratified split moves AUC by -0.07 and an
older XGBoost by +0.0008.

**13. What would you monitor if this ran daily?**
Run status, duration and retries per stage; row counts per layer and the quarantine count; null rates and schema
changes; the source checksum or new-version arrivals; feature-distribution drift against the fingerprint and class
balance; PostgreSQL duplicate keys; model AUC with its confidence interval against the baseline; disk usage.

**14. Which part would become the first bottleneck at 100x data?**
The PostgreSQL load (row-wise INSERT; in my benchmark the write already took 1,359 ms for 3,265 rows against 28 ms for
CSV and 11 ms for Parquet, and INSERT cost grows with the row count), then the row-wise Python `apply` that computes
VAAF, and finally holding whole layers as CSV in memory. Fixes: `COPY`, vectorized features, Parquet intermediates, and partitioned processing.

**15. What would change if the dataset were sensitive or regulated?**
Health records are sensitive personal information (Philippine Data Privacy Act, RA 10173). I would never commit raw
data or quarantine files; encrypt at rest and in transit; use a secrets manager instead of `.env`; give the pipeline
a least-privilege database role; replace `id` with a pseudonymous key and remove direct identifiers; keep row values
out of logs; add audit trails and retention rules; replace Airflow's no-login mode with real authentication and roles;
and document the lawful basis and access controls.
