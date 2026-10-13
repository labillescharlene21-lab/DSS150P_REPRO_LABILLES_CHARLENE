"""Airflow DAG: stroke-risk reproducible pipeline.

The DAG contains NO business logic. Every task calls the project CLI (`python -m src.cli <command>`),
so the same code runs from a laptop, Docker, or Airflow.

Design choices (see docs/runbook.md):
- schedule=None  : the source is a static, checksummed dataset, so there is nothing to run on a timer.
                   The pipeline is triggered manually (or by CI) when code or config changes.
- catchup=False  : no historical intervals exist to back-fill.
- retries        : every task is idempotent (checkpointed ingest, overwrite-style transforms,
                   ON CONFLICT upserts), so retrying any task is safe.
- run id         : Airflow's run_id is passed to every task as --run-id, so one id traces raw ->
                   staging -> curated -> PostgreSQL -> model -> outputs.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG, Param

log = logging.getLogger(__name__)

PROJECT_DIR = os.getenv("PIPELINE_PROJECT_DIR", "/opt/pipeline")
PYTHON = os.getenv("PIPELINE_PYTHON", "python")
RUN_ID = "--run-id '{{ run_id }}'"


def log_failure(context) -> None:
    """Failure callback: log enough context to find the task, the run and the error."""
    ti = context["task_instance"]
    log.error(
        "PIPELINE FAILURE dag=%s task=%s run_id=%s try=%s exception=%r",
        ti.dag_id, ti.task_id, context.get("run_id"), ti.try_number, context.get("exception"),
    )


def cli(command: str, *extra: str) -> str:
    return f"cd {PROJECT_DIR} && {PYTHON} -m src.cli {command} {RUN_ID} {' '.join(extra)}".strip()


default_args = {
    "owner": "data-engineering",
    "retries": 2,
    "retry_delay": timedelta(seconds=30),
    "on_failure_callback": log_failure,
}

with DAG(
    dag_id="predictive_repro_pipeline",
    description="Source -> raw -> staging -> curated -> PostgreSQL -> model -> reproducibility check",
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    params={
        "full_refresh": Param(True, type="boolean",
                              description="true = clear raw batches + checkpoint and re-ingest everything; "
                                          "false = incremental (skip batches already committed)"),
        "seed": Param(42, type="integer", description="random seed for the split and the model (baseline = 42)"),
    },
    tags=["dss150p", "stroke", "reproducibility"],
    doc_md=__doc__,
) as dag:

    ingest_source = BashOperator(
        task_id="ingest_source",
        bash_command=cli("ingest", "{% if params.full_refresh %}--force{% endif %}"),
    )
    validate_raw = BashOperator(task_id="validate_raw", bash_command=cli("validate-raw"))
    transform_staging = BashOperator(task_id="transform_staging", bash_command=cli("transform-staging"))
    build_curated = BashOperator(task_id="build_curated", bash_command=cli("build-curated"))
    load_postgres = BashOperator(task_id="load_postgres", bash_command=cli("load"))
    validate_curated = BashOperator(task_id="validate_curated", bash_command=cli("validate-curated"))
    train_model = BashOperator(
        task_id="train_model",
        bash_command=cli("train", "--seed {{ params.seed }}"),
        execution_timeout=timedelta(minutes=10),
    )
    evaluate_model = BashOperator(task_id="evaluate_model", bash_command=cli("evaluate", "--seed {{ params.seed }}"))
    reproducibility_check = BashOperator(task_id="reproducibility_check", bash_command=cli("repro-check"))
    publish_outputs = BashOperator(task_id="publish_outputs", bash_command=cli("publish"))

    (
        ingest_source >> validate_raw >> transform_staging >> build_curated >> load_postgres
        >> validate_curated >> train_model >> evaluate_model >> reproducibility_check >> publish_outputs
    )
