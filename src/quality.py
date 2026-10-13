"""Data-quality checks. Each check has a name, a category from the brief, a layer, and a severity.

fail -> the pipeline stops (non-zero exit)     warn -> reported; row-level problems are quarantined
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.config import ROOT
from src.observability import log_event
from src.transform import CURATED_COLS, NULL_TOKENS, contract_violations, parse_types

log = logging.getLogger("quality")

# vascular ages that the Harvard/Framingham lookup tables can produce (male and female tables)
VASCULAR_AGES = {28, 30, 32, 33, 37, 38, 41, 43, 46, 49, 52, 57, 58, 66, 72, 76, 82}


class ValidationError(RuntimeError):
    """Raised when a fail-severity check does not pass. The CLI turns it into a non-zero exit."""


@dataclass
class Check:
    name: str
    category: str      # schema | completeness | uniqueness | validity | consistency | integrity |
                       # applicability | business | predictive
    layer: str
    status: str        # pass | warn | fail
    detail: str = ""


@dataclass
class QualityReport:
    layer: str
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, category: str, ok: bool, detail: str = "", severity: str = "fail") -> None:
        c = Check(name, category, self.layer, "pass" if ok else severity, "" if ok else detail)
        self.checks.append(c)
        log_event(log, f"check {self.layer}.{name}: {c.status}", level=logging.INFO if ok else logging.WARNING,
                  event="quality_check", check=name, category=category, layer=self.layer,
                  status=c.status, detail=c.detail)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.status == "fail"]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if c.status == "warn"]

    def summary(self) -> dict:
        return {f"{self.layer}_checks": len(self.checks),
                f"{self.layer}_checks_failed": len(self.failures),
                f"{self.layer}_checks_warned": len(self.warnings)}

    def write(self, run_id: str | None) -> None:
        out = ROOT / "outputs" / "quality"
        out.mkdir(parents=True, exist_ok=True)
        payload = {"pipeline_run_id": run_id, "layer": self.layer,
                   "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   **self.summary(), "checks": [asdict(c) for c in self.checks]}
        (out / f"{self.layer}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def raise_if_failed(self, label: str) -> None:
        if self.failures:
            raise ValidationError(f"{label} failed: " + "; ".join(f"{c.name} ({c.detail})" for c in self.failures))


# ---------------------------------------------------------------- helpers
def row_hash(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    """Same formula as ingestion: sha256 of the '|'-joined source columns (as text)."""
    return df[cols].agg("|".join, axis=1).map(lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest())


def sha256_file(path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def _null_tokens(col: pd.Series) -> pd.Series:
    return col.astype(str).str.strip().isin(NULL_TOKENS)


# ---------------------------------------------------------------- RAW layer
def check_raw(raw: pd.DataFrame, manifest: dict, contract: dict, source_path, settings: dict) -> QualityReport:
    r = QualityReport("raw")
    cols = list(contract["columns"])
    key, target = contract["key"]["column"], contract["target"]
    qcfg = settings["quality"]

    missing = [c for c in cols if c not in raw.columns]
    # a batch that lacks a column shows up as NaN cells after the batches are concatenated
    partial = {c: sorted(int(b) for b in raw.loc[raw[c].isna(), "batch_no"].unique())
               for c in cols if c in raw.columns and raw[c].isna().any()}
    r.add("schema_required_columns", "schema", not missing and not partial,
          f"missing columns {missing}; columns absent in some batches {partial}")
    missing = missing + list(partial)
    r.add("completeness_row_count", "completeness", len(raw) == manifest["row_count"],
          f"{len(raw)} rows, manifest says {manifest['row_count']}")
    r.add("applicability_source_file_checksum", "applicability",
          source_path.exists() and sha256_file(source_path) == manifest["sha256"],
          "source file on disk does not match source_manifest.yml (wrong dataset version)")
    r.add("applicability_raw_rows_carry_manifest_checksum", "applicability",
          bool((raw["source_checksum"] == manifest["sha256"]).all()), "raw rows from a different source version")
    for c in ("source_row_seq", "record_hash"):
        r.add(f"uniqueness_{c}", "uniqueness", not raw[c].duplicated().any(),
              f"{int(raw[c].duplicated().sum())} duplicates")

    if missing:                                    # the remaining checks need the full schema
        return r

    r.add(f"uniqueness_{key}", "uniqueness", not raw[key].duplicated().any(),
          f"{int(raw[key].duplicated().sum())} duplicate {key} values")
    r.add("completeness_target", "completeness", not _null_tokens(raw[target]).any(),
          f"{int(_null_tokens(raw[target]).sum())} rows with a missing {target}")

    limits = qcfg["max_null_rate"]
    over = {c: round(float(_null_tokens(raw[c]).mean()), 4) for c in cols
            if _null_tokens(raw[c]).mean() > limits.get(c, limits["default"])}
    r.add("completeness_null_rates", "completeness", not over, f"null rate above threshold: {over}")

    mismatch = int((row_hash(raw, cols) != raw["record_hash"]).sum())       # computed once
    r.add("integrity_record_hash", "integrity", mismatch == 0,
          f"{mismatch} raw rows changed after ingestion (hash mismatch)")

    typed, unparsable = parse_types(raw)
    r.add("schema_types_parseable", "schema", not (unparsable != "").any(),
          f"{int((unparsable != '').sum())} rows with unparseable numbers (will be quarantined)", severity="warn")
    bad = contract_violations(typed, contract["columns"])
    r.add("validity_ranges_categories", "validity", not (bad != "").any(),
          f"{int((bad != '').sum())} rows outside contract ranges/categories (will be quarantined)", severity="warn")
    return r


# ---------------------------------------------------------------- CURATED layer
def check_curated(cur: pd.DataFrame, features: list[str], target: str, expected: dict,
                  fingerprint: dict, settings: dict) -> QualityReport:
    r = QualityReport("curated")
    qcfg = settings["quality"]

    r.add("schema_columns_exact", "schema", list(cur.columns) == CURATED_COLS,
          "curated column set or order changed")
    if any(c not in cur.columns for c in features + [target]):
        r.add("schema_model_columns_present", "schema", False, "model columns missing")
        return r
    non_numeric = [c for c in features + [target] if not pd.api.types.is_numeric_dtype(cur[c])]
    r.add("schema_model_columns_numeric", "schema", not non_numeric, f"non-numeric: {non_numeric}")
    if non_numeric:
        return r

    nulls = cur[features + [target]].isna().sum()
    r.add("completeness_no_nulls_in_model_columns", "completeness", not nulls.any(),
          f"nulls: {nulls[nulls > 0].to_dict()}")
    r.add("completeness_row_count", "completeness", len(cur) == expected["curated_rows"],
          f"{len(cur)} curated rows, expected {expected['curated_rows']} (rows lost or gained)")
    for c in ("id", "source_row_seq", "record_hash"):
        r.add(f"uniqueness_{c}", "uniqueness", not cur[c].duplicated().any(), f"{int(cur[c].duplicated().sum())} duplicates")
    r.add("consistency_source_order", "consistency", bool(cur["source_row_seq"].is_monotonic_increasing),
          "not in source order: the train/test split would change")

    # validity
    r.add("validity_age_scope", "validity", bool(cur["age"].between(35, 90).all()), "age outside the 35-90 study scope")
    binary_bad = [c for c in ("hypertension", "heart_disease", target, "gender_score_risk", "age_score_risk",
                              "bmi_score_risk") if not set(cur[c].unique()) <= {0, 1}]
    r.add("validity_binary_columns", "validity", not binary_bad, f"non-binary values in {binary_bad}")
    sets_bad = [c for c, ok in {"glucose_score_risk": {0, 1, 2}, "smoking_score_risk": {0, 1, 2, 3},
                                "residence_score_risk": {1, 2}}.items() if not set(cur[c].unique()) <= ok]
    r.add("validity_score_categories", "validity", not sets_bad, f"unexpected categories in {sets_bad}")

    # consistency: derived columns must agree with the columns they were derived from
    r.add("consistency_tgi_equals_bmi_times_glucose", "consistency",
          bool(np.allclose(cur["TGI"], cur["bmi"] * cur["avg_glucose_level"], rtol=1e-9, atol=1e-6)),
          "TGI is not BMI x glucose")
    g = cur["avg_glucose_level"]
    checks = {
        "bmi_score_matches_bmi": ((cur["bmi"] >= 23).astype(int) == cur["bmi_score_risk"]).all(),
        "glucose_score_matches_glucose": (np.select([g < 140, g < 200], [0, 1], 2) == cur["glucose_score_risk"]).all(),
        "age_score_matches_age": ((cur["age"] > 54).astype(int) == cur["age_score_risk"]).all(),
        "gender_score_matches_gender": (cur["gender"].map({"Female": 0, "Male": 1}) == cur["gender_score_risk"]).all(),
    }
    for name, ok in checks.items():
        r.add(f"consistency_{name}", "consistency", bool(ok), "derived score disagrees with its source column")
    vage = cur["VAAF"] + cur["age"]
    r.add("consistency_vaaf_is_a_table_vascular_age_minus_age", "consistency",
          bool((np.abs(vage - np.round(vage)) < 1e-6).all() and set(np.round(vage).astype(int)) <= VASCULAR_AGES),
          "VAAF + age is not a vascular age the lookup tables can produce")

    # project-specific business / model rules
    rate = float(cur[target].mean())
    tol = qcfg["class_balance_tolerance"]
    r.add("business_stroke_rate_matches_baseline", "business",
          abs(rate - fingerprint["stroke_rate"]) <= tol,
          f"stroke rate {rate:.4f} vs baseline {fingerprint['stroke_rate']:.4f} (tolerance {tol})")
    rel = qcfg["fingerprint_rel_tol"]
    drift = {}
    for c, ref in fingerprint["features"].items():
        for stat, val in (("mean", cur[c].mean()), ("std", cur[c].std())):
            if abs(val - ref[stat]) > rel * max(1.0, abs(ref[stat])):
                drift[f"{c}.{stat}"] = (round(float(val), 6), ref[stat])
    r.add("business_feature_fingerprint_matches_baseline", "business", not drift,
          f"features drifted from baseline (actual, baseline): {drift}")
    return r


# ---------------------------------------------------------------- PREDICTIVE integrity
def check_predictive_inputs(cur: pd.DataFrame, features: list[str], target: str, fingerprint: dict,
                            settings: dict) -> QualityReport:
    r = QualityReport("predictive")
    r.add("no_target_or_identifier_in_features", "predictive",
          target not in features and "id" not in features and "source_row_seq" not in features,
          "target or identifier used as a feature (leakage)")
    baseline = list(fingerprint["features"])
    r.add("feature_count_and_order_stable", "predictive", features == baseline,
          f"features {features} differ from the baseline list {baseline}")
    if all(c in cur.columns for c in features + [target]):
        corr = cur[features].corrwith(cur[target]).abs()
        limit = settings["quality"]["max_abs_feature_target_corr"]
        r.add("no_feature_nearly_identical_to_target", "predictive", bool((corr < limit).all()),
              f"suspiciously high correlation with the target: {corr[corr >= limit].round(3).to_dict()}")
    return r


def check_split(manifest: dict, curated_rows: int) -> QualityReport:
    r = QualityReport("split")
    r.add("no_train_test_overlap", "predictive", manifest["train_test_overlap"] == 0,
          f"{manifest['train_test_overlap']} rows are in both train and test")
    r.add("train_plus_test_equals_curated", "predictive",
          manifest["train_rows"] + manifest["test_rows"] == curated_rows,
          f"{manifest['train_rows']} + {manifest['test_rows']} != {curated_rows}")
    return r
