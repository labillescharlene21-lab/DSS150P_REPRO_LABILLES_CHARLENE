import json

from src.config import ROOT
from src.evaluate import judge_status, tolerance_for_platform

EXPECTED = json.loads((ROOT / "metadata" / "expected_metrics.json").read_text(encoding="utf-8"))


def test_reference_platform_gets_the_strict_tolerance_and_others_the_declared_relaxed_one():
    assert tolerance_for_platform(EXPECTED, "Linux") == (0.001, 0.001, "reference")
    for system in ("Windows", "Darwin"):
        assert tolerance_for_platform(EXPECTED, system) == (0.001, 0.01, "non_reference")


def test_the_relaxed_limit_never_exceeds_the_briefs_recommended_maximum():
    assert EXPECTED["tolerance_non_reference_platform"] <= 0.01


def test_status_rules():
    strict, relaxed = 0.001, 0.01
    assert judge_status(0.00004, True, True, strict, strict) == "pass"
    assert judge_status(0.0035, True, True, strict, relaxed) == "pass_relaxed_tolerance"   # e.g. Windows, 1 thread
    assert judge_status(0.0082, True, True, strict, relaxed) == "pass_relaxed_tolerance"   # e.g. Windows, 4 threads
    assert judge_status(0.0035, True, True, strict, strict) == "fail"                      # same gap on the reference platform
    assert judge_status(0.02, True, True, strict, relaxed) == "fail"                       # beyond even the relaxed limit
    assert judge_status(0.00004, True, False, strict, relaxed) == "fail"                   # exact checks never relax
    assert judge_status(0.5, False, True, strict, relaxed) == "not_applicable_non_baseline_seed"


def test_split_identity_checks_are_not_relaxed():
    # a different split must fail even if the AUC happens to be close
    assert judge_status(0.0001, True, other_checks_ok=False, strict=0.001, applicable=0.01) == "fail"
