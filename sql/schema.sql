-- Idempotent schema: safe to run on every start.

CREATE TABLE IF NOT EXISTS staging_stroke (
    id                 INTEGER PRIMARY KEY,                 -- business key (source id)
    gender             TEXT             NOT NULL CHECK (gender IN ('Male', 'Female')),
    age                DOUBLE PRECISION NOT NULL CHECK (age BETWEEN 35 AND 90),
    hypertension       SMALLINT         NOT NULL CHECK (hypertension IN (0, 1)),
    heart_disease      SMALLINT         NOT NULL CHECK (heart_disease IN (0, 1)),
    ever_married       TEXT             NOT NULL,
    work_type          TEXT             NOT NULL,
    residence_type     TEXT             NOT NULL CHECK (residence_type IN ('Urban', 'Rural')),
    avg_glucose_level  DOUBLE PRECISION NOT NULL CHECK (avg_glucose_level > 0),
    bmi                DOUBLE PRECISION NOT NULL CHECK (bmi > 0),
    smoking_status     TEXT             NOT NULL,
    stroke             SMALLINT         NOT NULL CHECK (stroke IN (0, 1)),
    source_row_seq     INTEGER          NOT NULL UNIQUE,
    record_hash        TEXT             NOT NULL UNIQUE,
    pipeline_run_id    TEXT             NOT NULL,
    processed_at_utc   TIMESTAMPTZ      NOT NULL
);

CREATE TABLE IF NOT EXISTS curated_stroke (
    id                    INTEGER PRIMARY KEY,
    gender                TEXT             NOT NULL,
    age                   DOUBLE PRECISION NOT NULL,
    hypertension          SMALLINT         NOT NULL CHECK (hypertension IN (0, 1)),
    heart_disease         SMALLINT         NOT NULL CHECK (heart_disease IN (0, 1)),
    residence_type        TEXT             NOT NULL,
    avg_glucose_level     DOUBLE PRECISION NOT NULL,
    bmi                   DOUBLE PRECISION NOT NULL,
    smoking_status        TEXT             NOT NULL,
    stroke                SMALLINT         NOT NULL CHECK (stroke IN (0, 1)),
    gender_score_risk     SMALLINT         NOT NULL CHECK (gender_score_risk IN (0, 1)),
    age_score_risk        SMALLINT         NOT NULL CHECK (age_score_risk IN (0, 1)),
    glucose_score_risk    SMALLINT         NOT NULL CHECK (glucose_score_risk IN (0, 1, 2)),
    bmi_score_risk        SMALLINT         NOT NULL CHECK (bmi_score_risk IN (0, 1)),
    smoking_score_risk    SMALLINT         NOT NULL CHECK (smoking_score_risk BETWEEN 0 AND 3),
    residence_score_risk  SMALLINT         NOT NULL CHECK (residence_score_risk IN (1, 2)),
    vaaf                  DOUBLE PRECISION NOT NULL,
    tgi                   DOUBLE PRECISION NOT NULL,
    source_row_seq        INTEGER          NOT NULL UNIQUE,
    record_hash           TEXT             NOT NULL UNIQUE,
    pipeline_run_id       TEXT             NOT NULL,
    processed_at_utc      TIMESTAMPTZ      NOT NULL
);

-- One row per (run, stage). Retried loads update the same row instead of adding duplicates.
CREATE TABLE IF NOT EXISTS pipeline_run_log (
    pipeline_run_id  TEXT        NOT NULL,
    stage            TEXT        NOT NULL,
    status           TEXT        NOT NULL,
    rows_loaded      INTEGER,
    started_at_utc   TIMESTAMPTZ NOT NULL,
    finished_at_utc  TIMESTAMPTZ,
    PRIMARY KEY (pipeline_run_id, stage)
);