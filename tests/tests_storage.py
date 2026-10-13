"""Integration tests against a real PostgreSQL (skipped if the database is not reachable)."""
import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from src import storage
from src.config import load_settings
from src.transform import CURATED_FILE


def _engine_or_skip():
    try:
        eng = storage.get_engine()
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        storage.init_db(eng)
        return eng
    except Exception as e:                                 # no DB in this environment
        pytest.skip(f"PostgreSQL not reachable: {e}")


@pytest.fixture()
def curated():
    path = load_settings().path("curated_dir") / CURATED_FILE
    if not path.exists():
        pytest.skip("run `python -m src.cli transform` first")
    return pd.read_csv(path)


def _count(eng, table):
    with eng.connect() as c:
        return c.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()


def test_upsert_twice_does_not_duplicate(curated):
    eng = _engine_or_skip()
    with eng.begin() as c:
        storage.upsert(c, "curated_stroke", curated)
    first = _count(eng, "curated_stroke")
    with eng.begin() as c:
        storage.upsert(c, "curated_stroke", curated)
    assert _count(eng, "curated_stroke") == first == len(curated)


def test_db_constraint_rejects_invalid_row(curated):
    eng = _engine_or_skip()
    bad = curated.head(1).copy()
    bad["id"] = 999999999
    bad["source_row_seq"] = 999999999
    bad["record_hash"] = "bad-row-hash"
    bad["stroke"] = 7                                      # violates CHECK (stroke IN (0,1))
    with pytest.raises(DBAPIError):
        with eng.begin() as c:
            storage.upsert(c, "curated_stroke", bad)
    with eng.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM curated_stroke WHERE id = 999999999")).scalar() == 0


def test_failed_load_is_atomic(curated):
    """If a later statement fails, earlier rows from that transaction must roll back."""
    eng = _engine_or_skip()
    marker = curated.head(1).copy()
    marker["id"] = 888888888
    marker["source_row_seq"] = 888888888
    marker["record_hash"] = "atomic-marker"
    broken = marker.copy()
    broken["id"] = 888888889
    broken["source_row_seq"] = 888888889
    broken["record_hash"] = "atomic-broken"
    broken["stroke"] = 7
    with pytest.raises(DBAPIError):
        with eng.begin() as c:
            storage.upsert(c, "curated_stroke", marker)    # would succeed on its own
            storage.upsert(c, "curated_stroke", broken)    # fails -> everything rolls back
    with eng.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM curated_stroke WHERE id = 888888888")).scalar() == 0


def test_postgres_matches_curated_csv(curated):
    eng = _engine_or_skip()
    storage.load_postgres(run_id="test-run")
    db = pd.read_sql("SELECT * FROM v_model_input", eng)
    assert len(db) == len(curated)
    assert db["id"].tolist() == curated.sort_values("source_row_seq")["id"].tolist()   # same order
    assert abs(db["tgi"].sum() - curated["TGI"].sum()) < 1e-6