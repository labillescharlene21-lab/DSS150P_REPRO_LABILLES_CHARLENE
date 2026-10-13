from __future__ import annotations
import hashlib
from datetime import datetime, timezone

import pandas as pd
import yaml

from src.config import load_settings


def sha256_file(path, chunk=1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    s = load_settings()
    src = s.source_file
    if not src.exists():
        raise FileNotFoundError(f"Source file not found: {src}. See README for placement.")

    df = pd.read_csv(src)
    target = s.raw["source"]["target"]
    meta_dir = s.path("metadata_dir")
    meta_dir.mkdir(exist_ok=True)

    # ---- manifest ----
    manifest = {
        "dataset_id": s.raw["dataset_id"],
        "filename": src.name,
        "expected_path": f"{s.raw['paths']['source_dir']}/{src.name}",
        "sha256": sha256_file(src),
        "size_bytes": src.stat().st_size,
        "row_count": int(len(df)),
        "column_count": int(df.shape[1]),
        "encoding": "utf-8",
        "format": "csv",
        "profiled_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "license": "TODO: state license / redistribution status",
        "origin": "TODO: URL or acquisition instructions",
    }
    with open(meta_dir / "source_manifest.yml", "w", encoding="utf-8") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)

    # ---- profile ----
    lines = [
        f"# Source Profile: {manifest['dataset_id']}",
        "",
        f"- Rows: {len(df)}  |  Columns: {df.shape[1]}  |  Size: {manifest['size_bytes']} bytes",
        f"- SHA-256: `{manifest['sha256']}`",
        f"- Duplicate rows: {int(df.duplicated().sum())}",
        "",
        "## Columns",
        "| column | dtype | nulls | null % | distinct | min | max |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in df.columns:
        col = df[c]
        numeric = pd.api.types.is_numeric_dtype(col)
        lines.append(
            f"| {c} | {col.dtype} | {int(col.isna().sum())} | {col.isna().mean():.2%} | "
            f"{col.nunique()} | {col.min() if numeric else ''} | {col.max() if numeric else ''} |"
        )

    if target in df.columns:
        lines += ["", f"## Target distribution (`{target}`)", "```",
                  df[target].value_counts(dropna=False).to_string(), "```"]

    # candidate keys + duplicate business-key check
    key_candidates = [c for c in df.columns if df[c].is_unique]
    lines += ["", f"## Candidate unique keys: {key_candidates or 'none, use deterministic row hash'}"]

    cats = [c for c in df.columns if df[c].dtype == "object"]
    for c in cats:
        lines += ["", f"### Categories: {c}", "```", df[c].value_counts(dropna=False).to_string(), "```"]

    lines += ["", "## Risks / notes", "- TODO: leakage fields, malformed values, schema risks"]
    (meta_dir / "source_profile.md").write_text("\n".join(lines), encoding="utf-8")
    print("Wrote source_manifest.yml and source_profile.md")


if __name__ == "__main__":
    main()