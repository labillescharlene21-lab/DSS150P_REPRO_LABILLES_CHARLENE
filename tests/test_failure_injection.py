import hashlib

import pandas as pd
import pytest

from src import inject
from src.config import load_settings


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture()
def raw_dir(tmp_path):
    src = pd.read_csv(load_settings().source_file, dtype=str, keep_default_na=False).head(300)
    src.insert(0, "source_row_seq", range(len(src)))
    src["record_hash"] = "h"
    d = tmp_path / "raw"
    d.mkdir()
    src.to_csv(d / inject.TARGET_BATCH, index=False)
    return d


@pytest.mark.parametrize("kind", inject.KINDS)
def test_injection_changes_the_file_and_restore_brings_back_identical_bytes(raw_dir, tmp_path, kind):
    target = raw_dir / inject.TARGET_BATCH
    before = _sha(target)
    inject.inject_fault(kind, raw_dir, tmp_path / "bk")
    assert _sha(target) != before
    assert inject.restore(raw_dir, tmp_path / "bk")["restored"] is True
    assert _sha(target) == before


def test_second_injection_still_restores_the_original(raw_dir, tmp_path):
    target = raw_dir / inject.TARGET_BATCH
    before = _sha(target)
    inject.inject_fault("null_target", raw_dir, tmp_path / "bk")
    inject.inject_fault("bad_glucose", raw_dir, tmp_path / "bk")      # must not overwrite the first backup
    inject.restore(raw_dir, tmp_path / "bk")
    assert _sha(target) == before


def test_unknown_fault_is_rejected(raw_dir, tmp_path):
    with pytest.raises(ValueError):
        inject.inject_fault("rm_rf", raw_dir, tmp_path / "bk")


def test_restore_without_backup_is_harmless(raw_dir, tmp_path):
    assert inject.restore(raw_dir, tmp_path / "none")["restored"] is False
