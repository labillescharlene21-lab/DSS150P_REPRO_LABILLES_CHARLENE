from __future__ import annotations

import argparse
import logging
import sys

from src.config import ROOT


def _logging():
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(ROOT / "logs" / "pipeline.log", encoding="utf-8")],
    )


def _ingest(a):
    from src import ingest
    ingest.ingest(force=a.force, fail_after=a.fail_after, run_id=a.run_id)


def _verify_raw(a):
    from src import ingest
    ingest.verify_raw()


def _transform(a):
    from src import transform
    transform.run_transform(run_id=a.run_id)


def _staging(a):
    from src import transform
    transform.run_staging(run_id=a.run_id)


def _curated(a):
    from src import transform
    transform.run_curated(run_id=a.run_id)


def _init_db(a):
    from src import storage
    storage.init_db()


def _load(a):
    from src import storage
    storage.load_postgres(run_id=a.run_id)


def _verify_db(a):
    from src import storage
    storage.verify_db()


def _validate_raw(a):
    from src import validate
    validate.validate_raw()


def _validate_curated(a):
    from src import validate
    validate.validate_curated()


def _train(a):
    from src import train
    train.train_model(seed=a.seed, run_id=a.run_id)


def _evaluate(a):
    from src import evaluate
    evaluate.evaluate_model(seed=a.seed, run_id=a.run_id)


def _repro(a):
    from src import evaluate
    evaluate.reproducibility_check(run_id=a.run_id)


def _publish(a):
    from src import publish
    publish.publish_outputs(run_id=a.run_id)


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
    pt = add("partition", _partition, common)
    pt.add_argument("--value", type=int, default=2, help="partition value to load and verify")
    return p


def main() -> int:
    a = build_parser().parse_args()
    _logging()
    try:
        a.func(a)
    except Exception as e:
        logging.getLogger("cli").error("FAILED: %s: %s", type(e).__name__, e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
