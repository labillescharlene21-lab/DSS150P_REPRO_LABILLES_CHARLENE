from __future__ import annotations
import argparse, logging, sys
from src.config import ROOT


def _logging():
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(ROOT / "logs" / "pipeline.log", encoding="utf-8")],
    )


def main() -> int:
    p = argparse.ArgumentParser(prog="pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("ingest")
    i.add_argument("--force", action="store_true", help="full refresh")
    i.add_argument("--fail-after", type=int, help="simulate a crash after batch N")
    sub.add_parser("verify-raw")
    sub.add_parser("transform")
    sub.add_parser("init-db")
    ld = sub.add_parser("load")
    ld.add_argument("--run-id", help="reuse a run id (e.g. on retry)")
    sub.add_parser("verify-db")
    a = p.parse_args()

    _logging()
    try:
        if a.cmd == "ingest":
            from src import ingest
            ingest.ingest(force=a.force, fail_after=a.fail_after)
        elif a.cmd == "verify-raw":
            from src import ingest
            ingest.verify_raw()
        elif a.cmd == "transform":
            from src import transform
            transform.run_transform()
        elif a.cmd == "init-db":
            from src import storage
            storage.init_db()
        elif a.cmd == "load":
            from src import storage
            storage.load_postgres(run_id=a.run_id)
        elif a.cmd == "verify-db":
            from src import storage
            storage.verify_db()
    except Exception as e:
        logging.getLogger("cli").error("FAILED: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())