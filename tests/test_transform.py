import numpy as np
import pandas as pd
import pytest

from src.config import ROOT, load_settings
from src.transform import (parse_types, points_to_vascular_age, transform_frame,
                           curate_frame, clean_rows)

FIXTURE = ROOT / "tests" / "fixtures" / "engineered2_baseline.csv"
AUDIT = ["source_row_seq", "record_hash", "pipeline_run_id", "processed_at_utc"]


def raw_from_source() -> pd.DataFrame:
    df = pd.read_csv(load_settings().source_file, dtype=str, keep_default_na=False)
    df.insert(0, "source_row_seq", range(len(df)))
    df["record_hash"] = [f"h{i}" for i in range(len(df))]
    return df


# ---------- unit tests ----------
def test_points_to_vascular_age_boundaries():
    assert points_to_vascular_age(-5, True) == 28
    assert points_to_vascular_age(16, True) == 76
    assert points_to_vascular_age(17, True) == 82
    assert points_to_vascular_age(1, False) == 28
    assert points_to_vascular_age(15, False) == 82


def test_parse_types_treats_na_bmi_as_null_but_rejects_garbage():
    raw = raw_from_source().head(3).copy()
    raw.loc[0, "bmi"] = "N/A"
    raw.loc[1, "age"] = "abc"
    typed, reasons = parse_types(raw)
    assert reasons[0] == ""                       # bmi may be null
    assert "age" in reasons[1]                    # age may not
    assert np.isnan(typed.loc[0, "bmi"])


def test_clean_rows_rules():
    df = pd.DataFrame({
        "gender": ["Female", "Female", "Male", "Other"],
        "age": [40.0, 50.0, 20.0, 60.0],
        "work_type": ["Private", "children", "children", "Private"],
        "smoking_status": ["Unknown", "Unknown", "Unknown", "smokes"],
        "bmi": [30.0, np.nan, 25.0, 40.0],
    })
    out, stats = clean_rows(df, 35, 90)
    assert len(out) == 3 and stats["filtered_out_of_age_scope"] == 1
    assert out["gender"].tolist() == ["Female", "Female", "Female"]      # Other -> mode
    assert out["smoking_status"].tolist()[1] == "never smoked"           # children rule
    assert out["bmi"].notna().all()


# ---------- integration tests ----------
@pytest.mark.skipif(not FIXTURE.exists(), reason="baseline fixture missing")
def test_curated_matches_group_baseline_exactly():
    s, _, _ = transform_frame(raw_from_source(), "t")
    cur = curate_frame(s, "t")
    ref = pd.read_csv(FIXTURE)
    assert len(cur) == len(ref) == 3265
    for c in ref.columns:
        if pd.api.types.is_numeric_dtype(ref[c]):
            assert np.allclose(cur[c], ref[c]), c
        else:
            assert (cur[c].astype(str) == ref[c].astype(str)).all(), c


def test_bad_rows_are_quarantined_not_curated():
    raw = raw_from_source()
    raw.loc[10, "avg_glucose_level"] = "9999"      # out of contract range
    raw.loc[11, "stroke"] = "maybe"                # unparseable target
    staging, rejected, stats = transform_frame(raw, "t")
    assert set(rejected["source_row_seq"].astype(int)) == {10, 11}
    assert not staging["source_row_seq"].isin([10, 11]).any()
    assert stats["rejected_rows"] == 2


def test_missing_required_column_fails_loudly():
    raw = raw_from_source().drop(columns=["smoking_status"])
    with pytest.raises(ValueError, match="Schema violation"):
        transform_frame(raw, "t")


def test_transform_is_deterministic():
    a = curate_frame(transform_frame(raw_from_source(), "a")[0], "a").drop(columns=AUDIT[2:])
    b = curate_frame(transform_frame(raw_from_source(), "b")[0], "b").drop(columns=AUDIT[2:])
    pd.testing.assert_frame_equal(a, b)