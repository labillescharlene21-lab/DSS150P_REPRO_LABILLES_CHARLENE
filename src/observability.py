"""Structured logging + per-run records.

Every log line carries timestamp, pipeline_run_id and stage. Every CLI command is wrapped by
`run_stage`, which times it, logs start/end/error events with row counts, and updates
outputs/run_records/<run_id>.json so a run can be inspected after the fact (also after a failure).
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone

from src.config import ROOT

_run_id = contextvars.ContextVar("run_id", default="-")
_stage = contextvars.ContextVar("stage", default="-")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id, record.stage = _run_id.get(), _stage.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname, "logger": record.name,
            "pipeline_run_id": getattr(record, "run_id", "-"), "stage": getattr(record, "stage", "-"),
            "message": record.getMessage(),
        }
        payload.update(getattr(record, "fields", {}) or {})
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging() -> None:
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    flt = _ContextFilter()
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | %(run_id)s | %(stage)s | %(name)s | %(message)s"))
    human = logging.FileHandler(logs / "pipeline.log", encoding="utf-8")
    human.setFormatter(console.formatter)
    jsonl = logging.FileHandler(logs / "pipeline.jsonl", encoding="utf-8")
    jsonl.setFormatter(_JsonFormatter())
    for h in (console, human, jsonl):
        h.addFilter(flt)
    logging.basicConfig(level=logging.INFO, handlers=[console, human, jsonl], force=True)


def log_event(logger: logging.Logger, message: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, message, extra={"fields": fields})


# ---------------------------------------------------------------- run record
def _safe(run_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", run_id)          # Airflow run ids contain ':' and '+'


def run_record_path(run_id: str):
    return ROOT / "outputs" / "run_records" / f"{_safe(run_id)}.json"


def load_run_record(run_id: str) -> dict | None:
    p = run_record_path(run_id)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _record_stage(run_id: str, stage: str, entry: dict) -> dict:
    p = run_record_path(run_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = load_run_record(run_id) or {"pipeline_run_id": run_id, "started_at_utc": _now(), "stages": {}}
    prev = rec["stages"].get(stage, {})
    entry["attempts"] = prev.get("attempts", 0) + 1
    rec["stages"][stage] = entry
    failed = [s for s, e in rec["stages"].items() if e["status"] == "failed"]
    if failed:
        rec["status"] = "failed"
    elif stage == "publish" and entry["status"] == "success":
        rec["status"] = "success"
        rec["finished_at_utc"] = _now()
    else:
        rec["status"] = "running"
    rec["failed_stages"] = failed
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, p)
    return rec


def _scalar_counts(result) -> dict:
    """Keep only simple numbers/flags from a stage's return value, plus a nested `counts` dict."""
    if not isinstance(result, dict):
        return {}
    out = {k: v for k, v in result.items() if isinstance(v, (int, float, bool))}
    if isinstance(result.get("counts"), dict):
        out.update({k: v for k, v in result["counts"].items() if isinstance(v, (int, float))})
    return out


def run_stage(run_id: str, stage: str, func, logger: logging.Logger | None = None):
    """Run `func()` as a pipeline stage. Returns (ok, result). Never swallows the failure silently."""
    log = logger or logging.getLogger("stage")
    tok_r, tok_s = _run_id.set(run_id), _stage.set(stage)
    started, t0 = _now(), time.perf_counter()
    log_event(log, f"stage_start {stage}", event="stage_start")
    try:
        result = func()
        counts = _scalar_counts(result)
        dur = round(time.perf_counter() - t0, 3)
        _record_stage(run_id, stage, {"status": "success", "started_at_utc": started,
                                      "finished_at_utc": _now(), "duration_s": dur, "counts": counts})
        log_event(log, f"stage_end {stage} ok", event="stage_end", status="success", duration_s=dur, **counts)
        return True, result
    except Exception as e:                                   # noqa: BLE001 - recorded, then reported by the CLI
        dur = round(time.perf_counter() - t0, 3)
        err = {"type": type(e).__name__, "message": str(e)[:2000]}
        _record_stage(run_id, stage, {"status": "failed", "started_at_utc": started,
                                      "finished_at_utc": _now(), "duration_s": dur, "error": err})
        log_event(log, f"stage_error {stage}: {err['type']}: {err['message']}", level=logging.ERROR,
                  event="stage_error", status="failed", duration_s=dur, error_type=err["type"],
                  error_message=err["message"])
        return False, e
    finally:
        _run_id.reset(tok_r)
        _stage.reset(tok_s)
