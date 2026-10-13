import pandas as pd
import pytest

from src import benchmark as bm
from src.config import load_settings
from src.transform import CURATED_FILE


@pytest.fixture(scope="module")
def df():
    path = load_settings().path("curated_dir") / CURATED_FILE
    if not path.exists():
        pytest.skip("run `python -m src.cli transform` first")
    return bm.load_curated()


def test_formats_roundtrip_same_logical_records(df, tmp_path):
    bm.write_csv(df, tmp_path / "a.csv")
    bm.write_jsonl(df, tmp_path / "a.jsonl")
    bm.write_parquet(df, tmp_path / "a.parquet")
    bm.assert_equivalent(df, bm.read_csv(tmp_path / "a.csv"), "csv")
    bm.assert_equivalent(df, bm.read_jsonl(tmp_path / "a.jsonl"), "jsonl")
    bm.assert_equivalent(df, bm.read_parquet(tmp_path / "a.parquet"), "parquet")


def test_equivalence_check_detects_changed_data(df):
    tampered = df.copy()
    tampered.loc[5, "TGI"] += 1.0
    with pytest.raises(AssertionError):
        bm.assert_equivalent(df, tampered, "tampered")


def test_partitions_cover_all_rows_without_overlap(df):
    counts = bm.write_partitions(df)
    assert sum(counts.values()) == len(df)
    ids = pd.concat([bm.read_partition(v)["id"] for v in counts])
    assert ids.is_unique and len(ids) == len(df)


def test_single_partition_row_count_verified(df):
    bm.write_partitions(df)
    result = bm.verify_partition(2, df)
    assert result["verified"] and result["rows_loaded"] == result["rows_expected_from_curated"]


def test_missing_partition_fails_clearly(df):
    bm.write_partitions(df)
    with pytest.raises(FileNotFoundError):
        bm.read_partition(99)