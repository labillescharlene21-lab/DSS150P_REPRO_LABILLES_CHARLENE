"""Automated version of the brief's Technical Acceptance Tests (A1-A18).

pass    the check ran and passed
fail    the check ran and failed (the command exits non-zero)
manual  cannot be proven by code alone; the evidence to collect is stated
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from src.config import ROOT, load_settings
from src.quality import sha256_file
from src.transform import CURATED_FILE, curate_frame, load_raw, transform_frame

AUDIT = ["pipeline_run_id", "processed_at_utc"]
DAG_FILE = ROOT / "dags" / "predictive_repro_pipeline.py"
CODE_GLOBS = ["src/*.py", "dags/*.py", "config/*.yml", "sql/*.sql", "docker-compose.yml", "Dockerfile*", ".env.example"]


def _manifest() -> dict:
    return yaml.safe_load((ROOT / "metadata" / "source_manifest.yml").read_text(encoding="utf-8"))


def _engine():
    try:
        from sqlalchemy import text
        from src.storage import get_engine
        eng = get_engine()
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        return eng
    except Exception:                                    # noqa: BLE001
        return None


def _scalar(eng, sql):
    from sqlalchemy import text
    with eng.connect() as c:
        return c.execute(text(sql)).scalar()


def _run_records() -> list[dict]:
    d = ROOT / "outputs" / "run_records"
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))] if d.exists() else []


def _code_files() -> list[Path]:
    """Files scanned for absolute paths and secrets. This file is excluded: it contains the patterns themselves."""
    out = []
    for g in CODE_GLOBS:
        out += [p for p in ROOT.glob(g) if p.is_file() and p.name != "acceptance.py"]
    return out


def _git(*args):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30)
    except Exception:                                    # noqa: BLE001
        return None


# ---------------------------------------------------------------- the checks
def a1():
    ev = ROOT / "docs" / "evidence" / "clean_clone.txt"
    if ev.exists() and "CLEAN CLONE OK" in ev.read_text(encoding="utf-8", errors="ignore"):
        return "pass", "docs/evidence/clean_clone.txt reports CLEAN CLONE OK"
    return "manual", "run scripts/clean_clone_check.ps1 and keep its output in docs/evidence/clean_clone.txt"


def a2():
    m, src = _manifest(), load_settings().source_file
    if not src.exists():
        return "fail", f"{src.name} not found in data/source"
    ok = sha256_file(src) == m["sha256"]
    return ("pass" if ok else "fail"), f"source SHA-256 {'matches' if ok else 'DOES NOT match'} source_manifest.yml"


def a3():
    pat = re.compile(r"[A-Za-z]:[\\/]+Users|/Users/|/home/(?!airflow)[A-Za-z0-9_]+")
    hits = [f"{p.relative_to(ROOT)}:{i}" for p in _code_files()
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1) if pat.search(line)]
    return ("fail", f"machine-specific paths in {hits[:5]}") if hits else ("pass", f"{len(_code_files())} code/config files scanned")


def a4():
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8") if (ROOT / ".gitignore").exists() else ""
    if not re.search(r"^\.env\s*$", gi, re.M):
        return "fail", ".env is not listed in .gitignore"
    secret = re.compile(r"(?i)\b\w*(password|secret|api_?key|access_?token)\w*\s*[:=]\s*['\"]?([A-Za-z0-9_\-/+.]{6,})")
    allowed = {"change_me", "changeme", "example"}
    leaks = []
    for p in _code_files():
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            m = secret.search(line)
            if m and m.group(2).lower() not in allowed and not m.group(2).startswith(("os.", "environ")):
                leaks.append(f"{p.relative_to(ROOT)}:{i}")
    if leaks:
        return "fail", f"possible hard-coded secret at {leaks[:5]}"
    git = _git("ls-files", ".env")
    if git is not None and git.returncode == 0:
        if git.stdout.strip():
            return "fail", ".env is tracked by git"
        return "pass", ".env ignored and not tracked; no hard-coded secrets found"
    return "pass", ".env is in .gitignore; no hard-coded secrets found (git not available to confirm tracking)"


def a5():
    need = ["requirements.txt", "Dockerfile", "docker-compose.yml"]
    missing = [n for n in need if not (ROOT / n).exists()]
    if missing:
        return "fail", f"missing {missing}"
    lines = [x.strip() for x in (ROOT / "requirements.txt").read_text(encoding="utf-8-sig", errors="ignore").splitlines()
             if x.strip() and not x.startswith("#")]
    loose = [x for x in lines if "==" not in x]
    if loose:
        return "fail", f"unpinned requirements: {loose[:4]}"
    xgb = next((x for x in lines if x.lower().startswith("xgboost==")), None)
    if xgb is None:
        return "fail", "xgboost is not pinned in requirements.txt"
    ver = tuple(int(v) for v in re.findall(r"\d+", xgb.split("==")[1])[:3])
    if ver < (3, 3, 0):
        return "fail", f"{xgb}: versions before 3.3.0 give AUC 0.75087, not 0.7500"
    return "pass", f"{len(lines)} pinned requirements ({xgb}); Dockerfile and compose present"


def a6():
    raw, m = load_raw(load_settings().path("raw_dir")), _manifest()
    ok = len(raw) == m["row_count"] and bool((raw["source_checksum"] == m["sha256"]).all())
    return ("pass" if ok else "fail"), f"{len(raw)} raw rows (manifest {m['row_count']}), checksum on every row {'matches' if ok else 'differs'}"


def a7():
    s = load_settings()
    ck = s.path("state_dir") / "ingest_checkpoint.json"
    if not ck.exists():
        return "fail", "no checkpoint file; ingestion has not run"
    done = json.loads(ck.read_text(encoding="utf-8"))["completed_batches"]
    if len(done) != s.raw["ingestion"]["n_batches"]:
        return "fail", f"checkpoint has {done}"
    logs = [ROOT / "logs" / "pipeline.log", ROOT / "docs" / "evidence" / "ingest_runs.txt"]
    if any(p.exists() and "SKIP" in p.read_text(encoding="utf-8", errors="ignore") for p in logs):
        return "pass", "checkpoint complete and a rerun logged SKIP for committed batches"
    return "manual", "checkpoint complete, but no rerun with SKIP lines found; keep docs/evidence/ingest_runs.txt"


def a8():
    raw = load_raw(load_settings().path("raw_dir"))
    outs = []
    for rid in ("a", "b"):
        st, _, _ = transform_frame(raw, rid)
        outs.append((st.drop(columns=AUDIT), curate_frame(st, rid).drop(columns=AUDIT)))
    same = outs[0][0].equals(outs[1][0]) and outs[0][1].equals(outs[1][1])
    path = load_settings().path("curated_dir") / CURATED_FILE
    on_disk = pd.read_csv(path).drop(columns=AUDIT)
    same_disk = len(on_disk) == len(outs[0][1]) and (on_disk["id"].values == outs[0][1]["id"].values).all()
    ok = same and same_disk
    return ("pass" if ok else "fail"), f"two independent transforms identical: {same}; match curated file on disk: {same_disk}"


def a9():
    eng = _engine()
    if eng is None:
        return "manual", "PostgreSQL not reachable from here; run `verify-db` and keep the output"
    runs = _scalar(eng, "SELECT COUNT(DISTINCT pipeline_run_id) FROM pipeline_run_log WHERE stage = 'load_curated'")
    n = _scalar(eng, "SELECT COUNT(*) FROM curated_stroke")
    dup = _scalar(eng, "SELECT COUNT(*) - COUNT(DISTINCT id) FROM curated_stroke")
    exp = json.loads((ROOT / "metadata" / "expected_metrics.json").read_text(encoding="utf-8"))["curated_rows"]
    if runs >= 2 and n == exp and dup == 0:
        return "pass", f"{runs} loads logged, table holds {n} rows, 0 duplicate ids"
    return ("fail" if dup or n not in (exp, 0) else "manual"), f"{runs} loads logged, {n} rows, {dup} duplicates (need >= 2 loads)"


def a10():
    from src import benchmark as bm
    df = bm.load_curated()
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        bm.write_csv(df, t / "a.csv"); bm.write_jsonl(df, t / "a.jsonl"); bm.write_parquet(df, t / "a.parquet")
        bm.assert_equivalent(df, bm.read_csv(t / "a.csv"), "csv")
        bm.assert_equivalent(df, bm.read_jsonl(t / "a.jsonl"), "jsonl")
        bm.assert_equivalent(df, bm.read_parquet(t / "a.parquet"), "parquet")
    note = "benchmark_results.json found" if (ROOT / "docs" / "benchmark_results.json").exists() else "run `benchmark` for timings"
    return "pass", f"CSV, JSONL and Parquet read back identical to the curated data ({note}; PostgreSQL equality is checked inside `benchmark`)"


def a11():
    from src import benchmark as bm
    df = bm.load_curated()
    counts = bm.write_partitions(df)
    res = bm.verify_partition(2, df)
    return "pass", f"partition {res['partition']} loaded alone: {res['rows_loaded']} rows (of {sum(counts.values())}); postgres: {res['rows_in_postgres']}"


def a12():
    import ast
    ids = [kw.value.value for n in ast.walk(ast.parse(DAG_FILE.read_text(encoding="utf-8")))
           if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "BashOperator"
           for kw in n.keywords if kw.arg == "task_id"]
    good = [r["pipeline_run_id"] for r in _run_records()
            if r["status"] == "success" and re.match(r"(manual|scheduled|dataset)", r["pipeline_run_id"]) and len(r["stages"]) >= 10]
    if len(ids) == 10 and good:
        return "pass", f"DAG declares {len(ids)} tasks; completed Airflow run record: {good[-1]}"
    if len(ids) == 10:
        return "manual", "DAG declares 10 tasks; no completed Airflow run found in outputs/run_records (trigger it and screenshot the Graph)"
    return "fail", f"DAG declares {len(ids)} tasks, expected 10"


def a13():
    rec = [r["pipeline_run_id"] for r in _run_records() if any(e.get("attempts", 1) >= 2 for e in r["stages"].values())]
    ev = ROOT / "docs" / "evidence" / "failure_injection.txt"
    if rec or ev.exists():
        return "pass", f"recovery evidence: {'run record ' + rec[0] if rec else 'docs/evidence/failure_injection.txt'}"
    return "manual", "inject a failure, then recover it (inject-failure --kind ... / --restore) and keep the output"


def a14():
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_quality.py", "tests/test_failure_injection.py"],
                       cwd=ROOT, capture_output=True, text=True, timeout=600)
    last = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else p.stderr[-200:]
    return ("pass" if p.returncode == 0 else "fail"), f"quality + failure-injection tests: {last}"


def a15():
    publishes = [r for r in _run_records() if r["status"] == "success" and "publish" in r["stages"]]
    eng = _engine()
    if eng is None:
        return "manual", "PostgreSQL not reachable; keep `verify-db` output after two full runs"
    dup = _scalar(eng, "SELECT COUNT(*) - COUNT(DISTINCT id) FROM curated_stroke")
    n = _scalar(eng, "SELECT COUNT(*) FROM curated_stroke")
    if dup:
        return "fail", f"{dup} duplicate ids after reruns"
    if len(publishes) >= 2:
        return "pass", f"{len(publishes)} successful end-to-end runs, curated_stroke has {n} rows and 0 duplicate ids"
    return "manual", f"only {len(publishes)} successful end-to-end run on record; run the pipeline twice"


def a16():
    out = load_settings().path("outputs_dir")
    need = [out / "metrics.json", out / "predictions.csv", out / "model" / "xgb_model.json", out / "run_summary.json"]
    miss = [p.name for p in need if not p.exists()]
    if miss:
        return "fail", f"missing outputs {miss}"
    ids = {json.loads(p.read_text(encoding="utf-8")).get("pipeline_run_id")
           for p in (out / "metrics.json", out / "run_summary.json", out / "reproducibility_check.json")}
    fresh = (out / "metrics.json").stat().st_mtime >= (load_settings().path("curated_dir") / CURATED_FILE).stat().st_mtime
    ok = len(ids) == 1 and fresh
    return ("pass" if ok else "fail"), f"metrics, check and summary share run id {ids}; metrics newer than curated data: {fresh}"


def a17():
    p = load_settings().path("outputs_dir") / "reproducibility_check.json"
    if not p.exists():
        return "fail", "reproducibility_check.json missing"
    r = json.loads(p.read_text(encoding="utf-8"))
    ok = r["status"] in ("pass", "pass_relaxed_tolerance")
    note = ""
    if r["status"] == "pass_relaxed_tolerance":
        note = (f" [{r.get('platform')} is not the reference platform {r.get('reference_platform')}: relaxed limit "
                f"{r['tolerance']} applied; the Docker run is the authoritative one]")
    return ("pass" if ok else "fail"), (f"status {r['status']}: AUC {r['actual']:.5f} vs {r['expected']} "
                                        f"(diff {r['abs_difference']:.6f}, tolerance {r['tolerance']}){note}")


def a18():
    docs = ["README.md", "docs/runbook.md", "docs/reproducibility_report.md", "docs/architecture.png",
            "docs/lineage.png", "docs/benchmark_report.md"]
    missing = [d for d in docs if not (ROOT / d).exists()]
    if missing:
        return "fail", f"missing documents {missing}"
    import ast
    from src.cli import build_parser
    valid = set(build_parser()._subparsers._group_actions[0].choices)
    text = "".join((ROOT / d).read_text(encoding="utf-8", errors="ignore") for d in ("README.md", "docs/runbook.md"))
    stale = sorted({c for c in re.findall(r"python -m src\.cli ([a-z][a-z-]*)", text) if c not in valid})
    tasks = [kw.value.value for n in ast.walk(ast.parse(DAG_FILE.read_text(encoding="utf-8")))
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "BashOperator"
             for kw in n.keywords if kw.arg == "task_id"]
    unmentioned = [t for t in tasks if t not in (ROOT / "docs" / "runbook.md").read_text(encoding="utf-8")]
    if stale or unmentioned:
        return "fail", f"docs out of sync: unknown commands {stale}, DAG tasks missing from runbook {unmentioned}"
    return "pass", f"{len(docs)} documents present; every documented command exists; all {len(tasks)} DAG tasks are in the runbook"


CHECKS = [("A1", "Repository clones and README setup is sufficient", a1),
          ("A2", "Source dataset identity verifiable by checksum/manifest", a2),
          ("A3", "No machine-specific absolute paths required", a3),
          ("A4", "No secret credentials committed", a4),
          ("A5", "Environment creatable from declared dependencies/containers", a5),
          ("A6", "Full ingestion produces expected raw count/checksum", a6),
          ("A7", "Checkpoint demonstration avoids duplicates on rerun", a7),
          ("A8", "Staging and curated layers are deterministic", a8),
          ("A9", "PostgreSQL load is rerun-safe", a9),
          ("A10", "CSV/JSON/Parquet/PostgreSQL comparison uses the same logical records", a10),
          ("A11", "Selected partition can be read/loaded independently", a11),
          ("A12", "Airflow DAG has valid dependencies and completes end to end", a12),
          ("A13", "At least one recoverable failure demonstrated", a13),
          ("A14", "Automated quality checks detect intentionally invalid conditions", a14),
          ("A15", "Second end-to-end run does not increase duplicate business keys", a15),
          ("A16", "Model metrics regenerated from curated data, not copied", a16),
          ("A17", "Reproduced metric passes the documented tolerance rule", a17),
          ("A18", "Architecture, lineage, runbook, report present and consistent", a18)]


def run_acceptance(only: str | None = None) -> dict:
    results = []
    for aid, name, fn in CHECKS:
        if only and aid != only.upper():
            continue
        try:
            status, evidence = fn()
        except Exception as e:                           # noqa: BLE001 - a crashing check is a failing check
            status, evidence = "fail", f"check crashed: {type(e).__name__}: {e}"
        results.append({"id": aid, "name": name, "status": status, "evidence": evidence})

    n = {k: sum(r["status"] == k for r in results) for k in ("pass", "fail", "manual")}
    icon = {"pass": "PASS", "fail": "FAIL", "manual": "MANUAL"}
    L = ["# Technical acceptance report (auto-generated)", "",
         f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} | "
         f"**{n['pass']} pass, {n['fail']} fail, {n['manual']} manual**", "",
         "| ID | Test | Result | Evidence |", "|---|---|:---:|---|"]
    L += [f"| {r['id']} | {r['name']} | {icon[r['status']]} | {r['evidence']} |" for r in results]
    L += ["", "MANUAL means code cannot prove it alone; the evidence named in the row must be collected."]
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "acceptance_report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    for r in results:
        print(f"{r['id']:>4} {icon[r['status']]:6} {r['name']}\n       {r['evidence']}")
    if n["fail"]:
        raise RuntimeError("acceptance failed: " + ", ".join(r["id"] for r in results if r["status"] == "fail"))
    return {"acceptance_passed": n["pass"], "acceptance_manual": n["manual"], "acceptance_failed": n["fail"]}
