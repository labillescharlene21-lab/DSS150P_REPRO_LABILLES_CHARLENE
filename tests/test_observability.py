import json
import logging

import pytest

from src import observability as obs


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(obs, "ROOT", tmp_path)
    obs.setup_logging()
    yield tmp_path
    logging.getLogger().handlers.clear()


def _lines(tmp):
    return [json.loads(x) for x in (tmp / "logs" / "pipeline.jsonl").read_text(encoding="utf-8").splitlines()]


def test_success_is_logged_with_run_id_stage_duration_and_counts(sandbox):
    ok, _ = obs.run_stage("run:1+x", "transform-staging", lambda: {"raw_rows": 5110, "staging_rows": 3265})
    assert ok
    end = [r for r in _lines(sandbox) if r.get("event") == "stage_end"][0]
    assert end["pipeline_run_id"] == "run:1+x" and end["stage"] == "transform-staging"
    assert end["staging_rows"] == 3265 and end["duration_s"] >= 0 and end["ts"].endswith("+00:00")
    rec = json.loads(obs.run_record_path("run:1+x").read_text(encoding="utf-8"))
    assert ":" not in obs.run_record_path("run:1+x").name                   # safe file name for Windows
    assert rec["stages"]["transform-staging"]["counts"]["raw_rows"] == 5110


def test_failure_is_logged_with_error_details_and_marks_the_run_failed(sandbox):
    def boom():
        raise ValueError("bad column x")

    ok, err = obs.run_stage("r2", "validate-raw", boom)
    assert not ok and isinstance(err, ValueError)
    rec = obs.load_run_record("r2")
    assert rec["status"] == "failed" and rec["failed_stages"] == ["validate-raw"]
    assert rec["stages"]["validate-raw"]["error"] == {"type": "ValueError", "message": "bad column x"}
    e = [r for r in _lines(sandbox) if r.get("event") == "stage_error"][0]
    assert e["error_type"] == "ValueError" and "bad column x" in e["error_message"] and e["level"] == "ERROR"


def test_retry_of_a_failed_stage_recovers_the_run_and_counts_attempts(sandbox):
    obs.run_stage("r3", "ingest", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    assert obs.load_run_record("r3")["status"] == "failed"
    obs.run_stage("r3", "ingest", lambda: {"raw_rows": 5110})
    rec = obs.load_run_record("r3")
    assert rec["status"] == "running" and rec["failed_stages"] == []
    assert rec["stages"]["ingest"]["attempts"] == 2
    obs.run_stage("r3", "publish", lambda: {})
    assert obs.load_run_record("r3")["status"] == "success"


def test_library_log_lines_inherit_run_id_and_stage(sandbox):
    def work():
        logging.getLogger("transform").info("inside a stage")

    obs.run_stage("r4", "build-curated", work)
    line = [r for r in _lines(sandbox) if r["message"] == "inside a stage"][0]
    assert line["pipeline_run_id"] == "r4" and line["stage"] == "build-curated"
