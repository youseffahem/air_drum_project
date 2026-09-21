from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from spacedrums.audio import GainCurve, SampleBank

ROOT = Path(__file__).resolve().parents[2]


def test_recorded_sample_bank_load_hash_verify_and_resample():
    bank = SampleBank.load(
        ROOT / "assets/samples",
        ROOT / "assets/samples/recorded-manifest.json",
        sample_rate_hz=48_000,
    )
    assert len(bank.samples) == 7
    assert all(sample.sample_rate_hz == 48_000 for sample in bank.samples.values())
    assert all(sample.data.dtype == np.float32 and len(sample.data) > 100 for sample in bank.samples.values())


def test_sample_hash_failure(tmp_path):
    root = tmp_path / "samples"
    root.mkdir()
    (root / "x.wav").write_bytes(b"not-a-wave")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"samples":[{"sample_id":"x","file":"x.wav","sha256":"sha256:' + "0" * 64 + '"}]}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="hash"):
        SampleBank.load(root, manifest, sample_rate_hz=48_000)


@pytest.mark.parametrize("kind, exponent", [("LINEAR_CLIPPED", 1.0), ("POWER", 2.0)])
def test_gain_mapping_monotone_and_clipped(kind, exponent):
    curve = GainCurve("default", kind, 0.5, 4.0, 0.2, 1.0, exponent)
    values = [curve(x) for x in np.linspace(-2, 8, 500)]
    assert values[0] == pytest.approx(0.2) and values[-1] == pytest.approx(1.0)
    assert all(a <= b for a, b in zip(values, values[1:], strict=False))
