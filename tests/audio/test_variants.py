"""SYNTHETIC checks of grouped samples, velocity layers and round robins (tiny generated WAVs)."""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest
import soundfile as sf

from spacedrums.app.audio_out import AudioOutput, OutputLatency
from spacedrums.audio import SampleBank, VariantSelector
from spacedrums.contracts import CommittedStrike

RATE = 48_000


def write_bank(root, entries, *, rate=RATE):
    """entries: (sample_id, group|None, layer, round_robin, amplitude). Returns the manifest path."""
    rows = []
    for sample_id, group, layer, robin, amp in entries:
        path = root / f"{sample_id}.wav"
        sf.write(path, (amp * np.sin(np.arange(2400) / 9.0)).astype(np.float32), rate, subtype="FLOAT")
        row = {"sample_id": sample_id, "file": path.name,
               "sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()}
        if group:
            row.update(group=group, layer=layer, round_robin=robin)
        rows.append(row)
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"samples": rows}), encoding="utf-8")
    return manifest


@pytest.fixture
def bank(tmp_path):
    entries = [
        ("sn-hard-1", "snare", "hard", 1, 0.5), ("sn-hard-2", "snare", "hard", 2, 0.5),
        ("sn-hard-3", "snare", "hard", 3, 0.5), ("sn-soft-1", "snare", "soft", 1, 0.3),
        ("sn-soft-2", "snare", "soft", 2, 0.3),
        ("ride-hard-1", "ride", "hard", 1, 0.4),  # a group with a single take and no soft layer
        ("plain", None, "", 0, 0.2),  # an ungrouped sample, exactly like the TR-505 manifest
    ]
    return SampleBank.load(tmp_path, write_bank(tmp_path, entries), sample_rate_hz=RATE)


def test_groups_are_loaded_in_round_robin_order_and_a_group_id_resolves_to_a_hard_take(bank):
    assert [s.sample_id for s in bank.groups["snare"]["hard"]] == ["sn-hard-1", "sn-hard-2", "sn-hard-3"]
    assert [s.sample_id for s in bank.groups["snare"]["soft"]] == ["sn-soft-1", "sn-soft-2"]
    assert bank["snare"].sample_id == "sn-hard-1"  # what check_assets and an old caller see
    assert bank["sn-soft-2"].sample_id == "sn-soft-2" and bank["plain"].sample_id == "plain"
    with pytest.raises(KeyError):
        bank["missing"]


def test_layer_follows_the_gain_and_falls_back_when_a_layer_is_missing(bank):
    pick = VariantSelector(bank).pick
    assert pick("snare", 0.2).sample_id.startswith("sn-soft")
    assert pick("snare", 0.54).sample_id.startswith("sn-soft")
    assert pick("snare", 0.55).sample_id.startswith("sn-hard")
    assert pick("snare", 1.0).sample_id.startswith("sn-hard")
    assert pick("ride", 0.2).sample_id == "ride-hard-1"  # no soft layer: hard plays, never an error
    assert pick("plain", 0.2).sample_id == "plain"


def test_round_robin_rotates_per_layer_and_never_repeats_back_to_back(bank):
    sel = VariantSelector(bank)
    hard = [sel.pick("snare", 1.0).sample_id for _ in range(7)]
    assert hard == ["sn-hard-1", "sn-hard-2", "sn-hard-3"] * 2 + ["sn-hard-1"]
    soft = [sel.pick("snare", 0.3).sample_id for _ in range(4)]
    assert soft == ["sn-soft-1", "sn-soft-2", "sn-soft-1", "sn-soft-2"]  # layers rotate independently
    assert all(a != b for a, b in zip(hard, hard[1:], strict=False))
    # a fresh selector over the same bank replays the same sequence: deterministic, no randomness
    again = VariantSelector(bank)
    assert [again.pick("snare", 1.0).sample_id for _ in range(7)] == hard
    solo = [sel.pick("ride", 1.0).sample_id for _ in range(3)]
    assert solo == ["ride-hard-1"] * 3  # one take can only repeat


def test_manifest_errors_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="hard layer"):
        SampleBank.load(tmp_path, write_bank(tmp_path, [("a", "g", "soft", 1, 0.3)]), sample_rate_hz=RATE)
    with pytest.raises(ValueError, match="duplicate round robin"):
        SampleBank.load(tmp_path, write_bank(tmp_path, [("a", "g", "hard", 1, 0.3), ("b", "g", "hard", 1,
            0.3)]),
                        sample_rate_hz=RATE)
    with pytest.raises(ValueError, match="layer"):
        SampleBank.load(tmp_path, write_bank(tmp_path, [("a", "g", "medium", 1, 0.3)]), sample_rate_hz=RATE)


def committed(zone, gain, t=1.0, n=0):
    return CommittedStrike(
        strike_id=f"s{n}", candidate_id=f"c{n}", frame_id=n, t_capture=t, hand_id="RIGHT", zone_id=zone,
        source="RULE", derivation="GEOMETRY", arm="B", shadow=False, t_commit=t + 0.01,
        t_impact_target=t + 0.1,
        intensity_proxy=2.0, gain=gain, refractory_until=t + 0.2, episode_id=f"e{n}", commit_policy_id="test",
    )


def output(tmp_path, bank_manifest):
    cfg = {
        "audio": {
            "audio_profile_id": "test", "sample_rate_hz": RATE, "buffer_frames": 256,
            "gain": {"curves": [{"gain_curve_id": "default", "type": "LINEAR_CLIPPED", "proxy_min": 0.5,
                                 "proxy_max": 4.0, "gain_min": 0.2, "gain_max": 1.0}]},
            "sample_bank": {"path": str(tmp_path), "manifest": str(bank_manifest)},
            "device": {"name": "test"},
        },
        "zones": [{"zone_id": "snare", "sample_id": "snare", "gain_curve_id": "default"},
                  {"zone_id": "ride", "sample_id": "ride", "gain_curve_id": "default"}],
    }

    class Stream:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass

    out = AudioOutput(cfg, latency=OutputLatency.unmeasured(), device_enabled=True, clock=lambda: 1.0,
                      stream_factory=Stream)
    out.device_state = "RUNNING"
    return out


def test_audio_output_plays_a_variant_but_reports_the_group_in_the_event(tmp_path):
    manifest = write_bank(tmp_path, [
        ("sn-hard-1", "snare", "hard", 1, 0.5), ("sn-hard-2", "snare", "hard", 2, 0.5),
        ("sn-soft-1", "snare", "soft", 1, 0.3), ("ride-hard-1", "ride", "hard", 1, 0.4),
    ])
    out = output(tmp_path, manifest)
    events = [out.play(committed("snare", g, n=i)) for i, g in enumerate((1.0, 1.0, 0.3, 1.0))]
    assert {e.sample_id for e in events} == {"snare"}  # the AudioEvent contract keeps the group id
    assert out.variants_played == {"sn-hard-1": 2, "sn-hard-2": 1, "sn-soft-1": 1}
    assert out.stats()["variants_played"] == dict(out.variants_played)
    # every queued voice carries exactly the chosen take, so overlapping hits keep their own audio
    voices = []
    while not out.mixer._queue.empty():
        voices.append(out.mixer._queue.get_nowait())
    assert [round(float(np.abs(v.samples).max()), 2) for v in voices] == [0.5, 0.5, 0.3, 0.5]


def test_an_ungrouped_bank_behaves_exactly_as_before(tmp_path):
    manifest = write_bank(tmp_path, [("snare", None, "", 0, 0.5), ("ride", None, "", 0, 0.4)])
    out = output(tmp_path, manifest)
    out.play(committed("snare", 0.3))
    assert "variants_played" not in out.stats()
    assert float(np.abs(out.mixer._queue.get_nowait().samples).max()) == pytest.approx(0.5)
