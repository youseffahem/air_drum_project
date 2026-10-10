"""The acoustic Salamander bank: provenance, levels, tails, pitch ordering, layers and polyphony.

Needs the git-ignored built WAVs (python scripts/fetch_acoustic_samples.py), like the TR-505 and model
assets; without them the module is skipped with that reason rather than faked.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
import pytest

from spacedrums.app import play
from spacedrums.app.audio_out import AudioOutput, OutputLatency
from spacedrums.audio import CallbackMixer, SampleBank, VariantSelector
from spacedrums.contracts import AudioEvent, CommittedStrike
from spacedrums.geometry.kit_layout import KIT_SAMPLES

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "assets/samples/acoustic-manifest.json"
RATE = 48_000
CYMBALS = ("salamander-crash", "salamander-ride")
DRUMS = ("salamander-snare", "salamander-tom1", "salamander-tom2", "salamander-floor-tom")

def built():
    if not MANIFEST.exists():
        return False
    files = [e["file"] for e in json.loads(MANIFEST.read_text(encoding="utf-8"))["samples"]]
    return all((ROOT / "assets/samples" / f).exists() for f in files)


pytestmark = pytest.mark.skipif(
    not built(), reason="git-ignored acoustic WAVs not built; run: python scripts/fetch_acoustic_samples.py"
)


@pytest.fixture(scope="module")
def doc():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def bank():
    return SampleBank.load(ROOT / "assets/samples", MANIFEST, sample_rate_hz=RATE)


def peak_db(x):
    return 20 * np.log10(np.abs(x).max())


def f0(x, lo=40, hi=300):
    seg = x[: int(0.2 * RATE)] * np.hanning(int(0.2 * RATE))
    spec = np.abs(np.fft.rfft(seg, 1 << 17))
    f = np.fft.rfftfreq(1 << 17, 1 / RATE)
    band = (f > lo) & (f < hi)
    return float(f[band][spec[band].argmax()])


# -- provenance ----------------------------------------------------------------------------------------


def test_manifest_records_source_licence_attribution_and_honest_provenance(doc):
    assert doc["license_id"] == "CC-BY-SA-3.0" and "licenses/by-sa/3.0" in doc["license_url"]
    assert "Alexander Holm" in doc["attribution"] and "CC BY-SA 3.0" in doc["attribution"]
    src = doc["source"]
    assert src["archive_url"].startswith("https://archive.org/") and len(src["archive_sha256"]) == 64
    assert "acoustic" in doc["recordings"] and "TR-505" not in json.dumps(doc)
    for e in doc["samples"]:  # every file traces to one archive member and a hash
        assert e["source_member"].startswith("OH/") and e["sha256"].startswith("sha256:")
    derived = {g for g, v in doc["groups"].items() if v["derived"]}
    assert derived == {"salamander-tom2"}  # the only sample that is not an unpitched recording
    assert doc["groups"]["salamander-tom2"]["derived"]["semitones"] == pytest.approx(-6.0, abs=0.01)
    assert {e["group"] for e in doc["samples"] if e["derived"]} == derived


def test_the_licence_and_attribution_are_in_the_repository_notes():
    notes = (ROOT / "assets/samples/LICENSES.md").read_text(encoding="utf-8")
    for needle in ("Salamander", "Alexander Holm", "CC BY-SA 3.0", "archive.org", "drum-machine", "TR-505",
        "DERIVED"):
        assert needle in notes, needle


# -- mapping --------------------------------------------------------------------------------------------


def test_every_zone_maps_to_its_own_acoustic_group_with_layers_and_round_robins(bank):
    assert len(set(KIT_SAMPLES.values())) == 7
    for zone, group in KIT_SAMPLES.items():
        layers = bank.groups[group]
        assert set(layers) == {"hard", "soft"}, zone
        assert len(layers["hard"]) >= 2 and len(layers["soft"]) >= 2, zone
        assert group.startswith("salamander-") and bank[group] is layers["hard"][0]
    expected = {"crash": "crash1", "ride": "ride1", "hihat": "hihatClosed", "snare": "snare", "tom1": "hiTom",
                "tom2": "hiTom", "floor_tom": "loTom"}
    members = {e["group"]: set() for e in json.loads(MANIFEST.read_text())["samples"]}
    for e in json.loads(MANIFEST.read_text())["samples"]:
        members[e["group"]].add(e["source_member"].split("/")[1].split("_")[0])
    assert {z: members[g] for z, g in KIT_SAMPLES.items()} == {z: {m} for z, m in expected.items()}


def test_tom_pitches_descend_rack_derived_mid_floor(bank):
    t1, t2, fl = (f0(bank[KIT_SAMPLES[z]].data) for z in ("tom1", "tom2", "floor_tom"))
    assert t1 > t2 > fl
    # the derived mid tom sits half an octave under the rack tom
    assert t1 / t2 == pytest.approx(2 ** 0.5, rel=0.1)
    assert t1 / fl == pytest.approx(2.0, rel=0.15)  # rack and floor tom are about an octave apart


# -- levels, tails, truncation ---------------------------------------------------------------------------


def all_samples(bank):
    return [(s.sample_id, s.data) for s in bank.samples.values()]


def test_no_clipping_headroom_and_no_excessive_normalisation(bank):
    for sid, x in all_samples(bank):
        assert np.isfinite(x).all() and abs(np.mean(x)) < 1e-3, sid  # no DC offset
        assert -20.0 < peak_db(x) <= -7.9, (sid, peak_db(x))  # >= 8 dB of headroom, not squashed up to 0 dBFS
    loudest = max(peak_db(x) for sid, x in all_samples(bank) if "-hard-" in sid)
    assert loudest == pytest.approx(-8.0, abs=0.3)  # one kit-wide gain, not per-sample normalisation
    peaks = {sid: peak_db(x) for sid, x in all_samples(bank) if "-hard-" in sid}
    assert max(peaks.values()) - min(peaks.values()) > 3  # the instruments keep their natural relative levels


def test_every_sample_starts_and_ends_without_a_click_or_cutoff(bank):
    for sid, x in all_samples(bank):
        assert abs(x[0]) < 0.01 and abs(x[-1]) < 1e-4, sid  # fade-out ends at zero, onset starts near silence
        # tail is already inaudible
        assert 20 * np.log10(np.abs(x[-int(0.005 * RATE):]).max() + 1e-12) < -60, sid
        onset = int(np.argmax(np.abs(x) > 0.01 * np.abs(x).max()))
        assert onset / RATE < 0.006, sid  # head trimmed: no dead air added to the playback latency


def test_cymbals_ring_long_and_drums_are_not_chopped(bank):
    dur = {sid: len(x) / RATE for sid, x in all_samples(bank)}
    for sid, d in dur.items():
        if sid.startswith(CYMBALS):
            assert d >= 5.0, (sid, d)  # real crash/ride decays last many seconds
        elif sid.startswith("salamander-hihat"):
            assert 0.3 <= d <= 1.5, (sid, d)
        else:
            assert d >= 1.0, (sid, d)


def test_soft_layers_sit_within_3_db_under_hard_so_gain_stays_monotone(bank):
    for group, layers in bank.groups.items():
        hard = np.median([peak_db(s.data) for s in layers["hard"]])
        soft = np.median([peak_db(s.data) for s in layers["soft"]])
        assert hard - 3.0 <= soft <= hard, (group, hard, soft)


def test_layers_really_differ_in_timbre_not_just_level(bank):
    for group, layers in bank.groups.items():
        a, b = layers["hard"][0].data, layers["soft"][0].data
        n = min(len(a), len(b))
        a, b = a[:n] / np.abs(a[:n]).max(), b[:n] / np.abs(b[:n]).max()
        assert np.abs(a - b).mean() > 1e-3, group  # not the same recording at two volumes


# -- polyphony: simultaneous hits and rolls ----------------------------------------------------------------

T0 = 1.0


def event(n, t, gain=1.0):
    return AudioEvent(f"s{n}", "g", T0, t, t, 0.0, gain, "test")


def render(plays, seconds):
    """plays: (t_target, samples, gain). Returns (mono signal, mixer stats) from the real CallbackMixer."""
    mixer = CallbackMixer(RATE, channels=2)
    for n, (t, data, gain) in enumerate(plays):
        mixer.enqueue(event(n, t, gain), data)
    chunk = 256
    frames = int(seconds * RATE) // chunk * chunk
    out = np.concatenate([mixer.mix(chunk, T0 - 0.1 + i * chunk / RATE) for i in range(frames // chunk)])
    assert np.array_equal(out[:, 0], out[:, 1])
    return out[:, 0], mixer.stats


def hits(bank, zone, times, gain=1.0, selector=None):
    selector = selector or VariantSelector(bank)
    return [(t, selector.pick(KIT_SAMPLES[zone], gain).data, gain) for t in times]


def test_two_simultaneous_hits_of_any_two_pieces_never_clip(bank):
    for a, b in itertools.combinations(KIT_SAMPLES, 2):
        plays = hits(bank, a, [T0]) + hits(bank, b, [T0])
        out, stats = render(plays, 0.5)
        assert stats.clipped_samples == 0 and np.abs(out).max() < 0.85, (a, b, np.abs(out).max())


def test_a_roll_is_the_exact_sum_of_its_hits_so_nothing_is_cut_off(bank):
    times = [T0 + 0.1 * k for k in range(20)]  # a 10 Hz two-hand roll on the cymbals for 2 s
    selector = VariantSelector(bank)
    plays = []
    for k, t in enumerate(times):
        plays += hits(bank, "crash" if k % 2 else "ride", [t], selector=selector)
    seconds = 2.0 + 12.5  # the last hit rings out fully inside the render
    mixed, stats = render(plays, seconds)
    separate = sum(render([p], seconds)[0] for p in plays)
    assert np.abs(mixed - separate).max() < 1e-6  # every earlier hit keeps ringing under the later ones
    assert stats.clipped_samples == 0 and stats.events_late == 0
    first_tail = render([plays[0]], seconds)[0][int(3.0 * RATE):int(4.0 * RATE)]
    assert np.abs(first_tail).max() > 1e-4  # a cymbal is still audibly decaying seconds after its hit


@pytest.mark.parametrize("zone", ["snare", "tom1", "floor_tom", "hihat"])
def test_a_fast_roll_of_one_piece_overlaps_naturally_without_clipping(bank, zone):
    times = [T0 + k / 15 for k in range(30)]  # 15 hits per second for 2 s, round robins rotating
    plays = hits(bank, zone, times)
    mixed, stats = render(plays, 4.5)
    assert np.abs(mixed - sum(render([p], 4.5)[0] for p in plays)).max() < 1e-6
    assert stats.clipped_samples == 0, (zone, np.abs(mixed).max())
    files = {id(p[1]) for p in plays}
    assert len(files) >= 2  # consecutive hits use different takes, so a roll does not machine-gun


# Highest hit rates in any recorded developer session (data/dev-product, 2026-10-04..10): 13 hits in one
# second with both hands, 7 with one hand. Every hit below is at gain 1.0, the loudest the curve allows.
OBSERVED_MAX_HITS_PER_S = (7, 6)


def busy_passage(bank, rates, order, seconds=4.0):
    sel = VariantSelector(bank)
    plays = hits(bank, "crash", [T0], selector=sel) + hits(bank, "ride", [T0 + 0.05], selector=sel)
    for hand, rate in enumerate(rates):  # each hand taps through the drums at its own rate
        for k in range(int(seconds * rate)):
            zone = order[(k + 2 * hand) % len(order)]
            plays += hits(bank, zone, [T0 + 0.2 + 0.07 * hand + k / rate], selector=sel)
    return plays


@pytest.mark.parametrize("order", [("snare", "tom1", "tom2", "floor_tom"), ("floor_tom", "tom2", "floor_tom",
    "tom1")])
def test_the_busiest_observed_two_handed_passage_at_full_intensity_never_clips(bank, order):
    out, stats = render(busy_passage(bank, OBSERVED_MAX_HITS_PER_S, order), 8.0)
    assert stats.clipped_samples == 0 and np.abs(out).max() < 0.9, np.abs(out).max()  # >= 0.9 dB left


def test_double_the_observed_rate_at_full_intensity_overshoots_by_under_two_db(bank):
    """Documents the limit rather than hiding it: 25 maximum-intensity hits/s is outside anything recorded and
    can exceed full scale (the mixer then hard-clips a few samples). The overshoot stays small."""
    plays = busy_passage(bank, (13, 12), ("snare", "tom1", "tom2", "floor_tom"))
    unclipped = sum(render([p], 8.0)[0] for p in plays)
    assert np.abs(unclipped).max() < 1.25  # +1.9 dBFS
    realistic = [(t, x, g * f) for (t, x, g), f in zip(plays, np.random.default_rng(0).uniform(0.2, 1.0,
        len(plays)), strict=True)]
    assert render(realistic, 8.0)[1].clipped_samples == 0  # with natural intensity variation it does not clip


# -- the real output path ------------------------------------------------------------------------------------


class Stream:
    def __init__(self, *a, **k):
        pass

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass


def strike(zone, n, t, gain):
    return CommittedStrike(
        strike_id=f"s{n}", candidate_id=f"c{n}", frame_id=n, t_capture=t, hand_id="RIGHT", zone_id=zone,
        source="RULE", derivation="GEOMETRY", arm="B", shadow=False, t_commit=t + 0.01,
        t_impact_target=t + 0.1,
        intensity_proxy=2.0, gain=gain, refractory_until=t + 0.2, episode_id=f"e{n}", commit_policy_id="test",
    )


def test_full_kit_commits_play_each_zones_own_recordings_through_audio_output():
    cfg = play.play_config(demo=True, kit="full")
    out = AudioOutput(cfg, latency=OutputLatency.unmeasured(), device_enabled=True, clock=lambda: 100.0,
                      stream_factory=Stream)
    out.device_state = "RUNNING"
    n = 0
    for zone in KIT_SAMPLES:
        for gain in (1.0, 1.0, 0.3):  # two hard hits (round robin) and one soft hit
            event = out.play(strike(zone, n, 100.0 + n * 0.01, gain))
            assert event.sample_id == KIT_SAMPLES[zone]
            n += 1
    played = out.variants_played
    for zone, group in KIT_SAMPLES.items():
        mine = {k: v for k, v in played.items() if k.startswith(group + "-")}
        assert sum(mine.values()) == 3 and sum(v for k, v in mine.items() if "-soft-" in k) == 1, zone
        assert len([k for k in mine if "-hard-" in k]) == 2  # the two hard hits used different takes
    assert sum(played.values()) == out.events == 21
    queued = out.mixer._queue.qsize()
    assert queued == 21
