"""Every quality check must (a) pass on clean data and (b) catch the fault it exists for."""
import json

import numpy as np
import pandas as pd
import pytest

from src import quality
from src.config import ROOT, load_settings
from src.inject import KINDS, apply_fault
from src.quality import ValidationError, check_curated, check_predictive_inputs, check_raw, check_split
from src.transform import curate_frame, load_contract, transform_frame

S = load_settings().raw
FEATURES, TARGET = S["modeling"]["features"], S["source"]["target"]


def _json(name):
    return json.loads((ROOT / "metadata" / name).read_text(encoding="utf-8"))


EXPECTED, FINGERPRINT = _json("expected_metrics.json"), _json("feature_fingerprint.json")
CONTRACT = load_contract()
SOURCE = load_settings().source_file


@pytest.fixture()
def raw():
    df = pd.read_csv(SOURCE, dtype=str, keep_default_na=False)
    df.insert(0, "source_row_seq", range(len(df)))
    df["record_hash"] = quality.row_hash(df, list(CONTRACT["columns"]))
    df["source_checksum"] = quality.sha256_file(SOURCE)
    df["batch_no"] = (np.arange(len(df)) * 3 // len(df)) + 1
    return df


@pytest.fixture()
def manifest():
    return {"row_count": 5110, "sha256": quality.sha256_file(SOURCE)}


@pytest.fixture()
def curated(raw):
    staging, _, _ = transform_frame(raw, "t")
    return curate_frame(staging, "t")


def _names(report, status="fail"):
    return {c.name for c in report.checks if c.status == status}


def _curated_report(cur):
    return check_curated(cur, FEATURES, TARGET, EXPECTED, FINGERPRINT, S)


# ---------------------------------------------------------------- clean data passes
def test_clean_raw_passes_every_check(raw, manifest):
    rep = check_raw(raw, manifest, CONTRACT, SOURCE, S)
    assert not rep.failures and not rep.warnings, [c for c in rep.checks if c.status != "pass"]


def test_clean_curated_and_predictive_inputs_pass(curated):
    assert not _curated_report(curated).failures
    assert not check_predictive_inputs(curated, FEATURES, TARGET, FINGERPRINT, S).failures


# ---------------------------------------------------------------- raw: injected faults are caught
@pytest.mark.parametrize("kind,expected_check", [
    ("duplicate_id", "uniqueness_id"),
    ("null_target", "completeness_target"),
    ("tamper_bmi", "integrity_record_hash"),
])
def test_raw_faults_are_detected(raw, manifest, kind, expected_check):
    bad, _ = apply_fault(raw, kind)
    assert expected_check in _names(check_raw(bad, manifest, CONTRACT, SOURCE, S))


def test_missing_column_in_one_batch_is_detected_with_batch_number(raw, manifest):
    bad = raw.copy()
    bad.loc[bad["batch_no"] == 2, "smoking_status"] = np.nan        # what concat does to a batch lacking the column
    rep = check_raw(bad, manifest, CONTRACT, SOURCE, S)
    assert "schema_required_columns" in _names(rep)
    assert "[2]" in next(c.detail for c in rep.checks if c.name == "schema_required_columns")


def test_wrong_source_version_is_detected(raw):
    rep = check_raw(raw, {"row_count": 5110, "sha256": "0" * 64}, CONTRACT, SOURCE, S)
    assert {"applicability_source_file_checksum", "applicability_raw_rows_carry_manifest_checksum"} <= _names(rep)


def test_lost_rows_are_detected(raw, manifest):
    rep = check_raw(raw.iloc[:-10], manifest, CONTRACT, SOURCE, S)
    assert "completeness_row_count" in _names(rep)


# ---------------------------------------------------------------- bad rows never reach curated silently
def test_bad_glucose_is_quarantined_and_the_curated_gate_stops_it(raw):
    bad, _ = apply_fault(raw, "bad_glucose")
    staging, rejected, stats = transform_frame(bad, "t")
    assert stats["rejected_rows"] == len(rejected) == 1
    cur = curate_frame(staging, "t")
    assert "completeness_row_count" in _names(_curated_report(cur))


# ---------------------------------------------------------------- curated: silent damage is caught
def test_changed_derived_column_is_inconsistent(curated):
    bad = curated.copy()
    bad.loc[5, "TGI"] += 100
    assert "consistency_tgi_equals_bmi_times_glucose" in _names(_curated_report(bad))


def test_wrong_bmi_threshold_is_detected(curated):
    bad = curated.copy()
    bad["bmi_score_risk"] = (bad["bmi"] >= 25).astype(int)            # Western cutoff instead of the Asian 23
    assert "consistency_bmi_score_matches_bmi" in _names(_curated_report(bad))


def test_shifted_distribution_with_valid_ranges_is_caught_by_the_fingerprint(curated):
    bad = curated.copy()
    bad["bmi"] = bad["bmi"].clip(upper=90) + 0.5                       # still plausible values, every schema/range rule passes
    bad["TGI"] = bad["bmi"] * bad["avg_glucose_level"]                 # keep the rows internally consistent
    names = _names(_curated_report(bad))
    assert "business_feature_fingerprint_matches_baseline" in names
    assert "validity_age_scope" not in names                           # i.e. only the fingerprint noticed


def test_class_balance_shift_is_detected(curated):
    bad = curated.copy()
    bad.loc[bad.index[-400:], TARGET] = 1            # the first ~250 raw rows are already all positive
    assert "business_stroke_rate_matches_baseline" in _names(_curated_report(bad))


def test_reordered_columns_and_lost_rows_are_detected(curated):
    assert "schema_columns_exact" in _names(_curated_report(curated[curated.columns[::-1]]))
    assert "completeness_row_count" in _names(_curated_report(curated.iloc[:-5]))


def test_rows_out_of_source_order_are_detected(curated):
    bad = curated.sample(frac=1.0, random_state=1)
    assert "consistency_source_order" in _names(_curated_report(bad))


# ---------------------------------------------------------------- predictive integrity
def test_target_in_features_is_leakage(curated):
    rep = check_predictive_inputs(curated, FEATURES + [TARGET], TARGET, FINGERPRINT, S)
    assert {"no_target_or_identifier_in_features", "feature_count_and_order_stable"} <= _names(rep)


def test_feature_order_change_is_detected(curated):
    rep = check_predictive_inputs(curated, FEATURES[::-1], TARGET, FINGERPRINT, S)
    assert "feature_count_and_order_stable" in _names(rep)


def test_near_duplicate_of_target_is_flagged(curated):
    bad = curated.copy()
    bad["TGI"] = bad[TARGET] * 1000.0 + np.random.default_rng(0).normal(0, 1e-3, len(bad))
    assert "no_feature_nearly_identical_to_target" in _names(check_predictive_inputs(bad, FEATURES, TARGET, FINGERPRINT, S))


def test_train_test_overlap_is_detected():
    rep = check_split({"train_test_overlap": 3, "train_rows": 2612, "test_rows": 653}, 3265)
    assert "no_train_test_overlap" in _names(rep)


def test_failed_report_raises_validation_error(raw, manifest):
    bad, _ = apply_fault(raw, "duplicate_id")
    with pytest.raises(ValidationError, match="uniqueness_id"):
        check_raw(bad, manifest, CONTRACT, SOURCE, S).raise_if_failed("validate_raw")


def test_every_documented_fault_has_a_detecting_test():
    assert set(KINDS) == {"missing_column", "duplicate_id", "null_target", "tamper_bmi", "bad_glucose"}
