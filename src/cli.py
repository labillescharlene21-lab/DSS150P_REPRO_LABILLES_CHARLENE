from __future__ import annotations

import argparse
import logging
import sys
import uuid

from src.observability import run_stage, setup_logging


def _ingest(a):
    from src import ingest
    from src.config import load_settings
    from src.transform import load_raw
    ingest.ingest(force=a.force, fail_after=a.fail_after, run_id=a.run_id)
    return {"raw_rows": len(load_raw(load_settings().path("raw_dir")))}


def _verify_raw(a):
    from src import ingest
    ingest.verify_raw()


def _transform(a):
    from src import transform
    return transform.run_transform(run_id=a.run_id)


def _staging(a):
    from src import transform
    return transform.run_staging(run_id=a.run_id)


def _curated(a):
    from src import transform
    return transform.run_curated(run_id=a.run_id)


def _init_db(a):
    from src import storage
    storage.init_db()


def _load(a):
    from src import storage
    return storage.load_postgres(run_id=a.run_id)


def _verify_db(a):
    from src import storage
    return storage.verify_db()


def _validate_raw(a):
    from src import validate
    return validate.validate_raw(run_id=a.run_id)


def _validate_curated(a):
    from src import validate
    return validate.validate_curated(run_id=a.run_id)


def _train(a):
    from src import train
    return train.train_model(seed=a.seed, run_id=a.run_id)


def _evaluate(a):
    from src import evaluate
    return evaluate.evaluate_model(seed=a.seed, run_id=a.run_id)


def _repro(a):
    from src import evaluate
    return evaluate.reproducibility_check(run_id=a.run_id)


def _publish(a):
    from src import publish
    return publish.publish_outputs(run_id=a.run_id)


def _inject(a):
    from src import inject
    log = logging.getLogger("inject")
    if a.restore:
        result = inject.restore()
        log.warning("RESTORED: %s", result)
        return {}
    if not a.kind:
        raise ValueError(f"choose --kind from {inject.KINDS} or use --restore")
    result = inject.inject_fault(a.kind)
    log.warning("INJECTED FAULT (demo only): %s", result)
    return {}


def _benchmark(a):
    from src import benchmark
    benchmark.run_benchmark(repeats=a.repeats, scale=a.scale)


def _partition(a):
    from src import benchmark
    benchmark.write_partitions(benchmark.load_curated())
    logging.getLogger("cli").info("partition check: %s", benchmark.verify_partition(a.value))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pipeline")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--run-id", help="pipeline run id (Airflow passes its run_id here)")
    seeded = argparse.ArgumentParser(add_help=False)
    seeded.add_argument("--seed", type=int, help="random seed (default from settings/.env)")

    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, func, *parents, **kw):
        sp = sub.add_parser(name, parents=list(parents), **kw)
        sp.set_defaults(func=func)
        return sp

    i = add("ingest", _ingest, common)
    i.add_argument("--force", action="store_true", help="full refresh")
    i.add_argument("--fail-after", type=int, help="simulate a crash after batch N")
    add("verify-raw", _verify_raw, common)
    add("validate-raw", _validate_raw, common)
    add("transform", _transform, common, help="staging + curated in one go")
    add("transform-staging", _staging, common)
    add("build-curated", _curated, common)
    add("init-db", _init_db, common)
    add("load", _load, common)
    add("verify-db", _verify_db, common)
    add("validate-curated", _validate_curated, common)
    add("train", _train, common, seeded)
    add("evaluate", _evaluate, common, seeded)
    add("repro-check", _repro, common)
    add("publish", _publish, common)
    b = add("benchmark", _benchmark, common)
    b.add_argument("--repeats", type=int, help="warm repeats per measurement")
    b.add_argument("--scale", type=int, default=1, help="replicate rows N times (timing experiment only)")
    ij = add("inject-failure", _inject, common, help="DEMO ONLY: corrupt one raw batch (reversible)")
    ij.add_argument("--kind", help="missing_column | duplicate_id | null_target | tamper_bmi | bad_glucose")
    ij.add_argument("--restore", action="store_true", help="put the original batch back")
    pt = add("partition", _partition, common)
    pt.add_argument("--value", type=int, default=2, help="partition value to load and verify")
    return p


def main() -> int:
    a = build_parser().parse_args()
    a.run_id = a.run_id or f"local-{uuid.uuid4().hex[:8]}"
    setup_logging()
    ok, result = run_stage(a.run_id, a.cmd, lambda: a.func(a), logging.getLogger("cli"))
    if not ok:
        logging.getLogger("cli").error("FAILED: %s: %s", type(result).__name__, result)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
