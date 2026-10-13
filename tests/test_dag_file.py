"""Static checks on the DAG file. They need no Airflow install (Airflow does not run on Windows)."""
import ast
from pathlib import Path

DAG_FILE = Path(__file__).resolve().parents[1] / "dags" / "predictive_repro_pipeline.py"
EXPECTED_TASKS = ["ingest_source", "validate_raw", "transform_staging", "build_curated", "load_postgres",
                  "validate_curated", "train_model", "evaluate_model", "reproducibility_check", "publish_outputs"]
FORBIDDEN_IMPORTS = {"pandas", "numpy", "xgboost", "sklearn", "sqlalchemy", "psycopg2", "src"}


def _tree():
    return ast.parse(DAG_FILE.read_text(encoding="utf-8"))


def test_dag_has_no_business_logic_imports():
    roots = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert not (roots & FORBIDDEN_IMPORTS), f"DAG imports business-logic libraries: {roots & FORBIDDEN_IMPORTS}"


def test_dag_declares_all_tasks_in_the_required_order():
    ids = [kw.value.value for n in ast.walk(_tree()) if isinstance(n, ast.Call)
           and getattr(n.func, "id", "") == "BashOperator"
           for kw in n.keywords if kw.arg == "task_id"]
    assert ids == EXPECTED_TASKS


def test_dag_settings_are_declared():
    src = DAG_FILE.read_text(encoding="utf-8")
    for needle in ("schedule=None", "catchup=False", '"retries"', '"retry_delay"', "execution_timeout",
                   "on_failure_callback", "Param(", "{{ run_id }}"):
        assert needle in src, f"missing in DAG: {needle}"
