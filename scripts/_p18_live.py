"""Phase 18 live-experiment helpers shared by run_live_session, external_sync, analyze_live and the pilot.

Composes library code only. Anything labelled SYNTHETIC here is a generated signal for exercising
the analysis chain; it is never a microphone, a camera, a participant or a measurement.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from spacedrums.audio import SampleBank
from spacedrums.data.audio_capture import read_wav, write_wav
from spacedrums.live_eval import acoustic
from spacedrums.live_eval.software import read_stream
from spacedrums.live_eval.sync import align_event_trains

SYNTHETIC_OUTPUT_DELAY_S = 0.050  # SYNTHETIC: sound leaves 50 ms after its scheduled play time
SYNTHETIC_PAD_OFFSET_S = 0.004  # SYNTHETIC: pad transient 4 ms after the analytic crossing
M1_SYNC_TOLERANCE_S = 0.030  # candidate: output-path jitter allowed when matching sounds to audio events


def bank_for(cfg: Mapping[str, Any]) -> SampleBank:
    audio = cfg["audio"]
    return SampleBank.load(
        audio["sample_bank"]["path"],
        audio["sample_bank"]["manifest"],
        sample_rate_hz=int(audio["sample_rate_hz"]),
    )


def zone_samples(cfg: Mapping[str, Any]) -> dict[str, str]:
    return {z["zone_id"]: z["sample_id"] for z in cfg["zones"]}


def strike_rows(session_dir: Path) -> list[dict[str, Any]]:
    """CommittedStrike rows joined with their StrikeCandidate (t_impact_pred / est, position), in the
    harness row format: like ``ReplayResult.strike_rows``, each row carries the session and participant."""
    records = session_dir / "records"
    meta = read_json(session_dir / "metadata.json")
    committed = read_stream(records / "CommittedStrike.jsonl")[1]
    candidates = {c["candidate_id"]: c for c in read_stream(records / "StrikeCandidate.jsonl")[1]}
    rows = []
    for s in committed:
        c = candidates.get(s["candidate_id"], {})
        rows.append(
            {
                **s,
                "session_id": meta["session_id"],
                "participant_id": meta["participant_id"],
                "t_impact_pred": c.get("t_impact_pred"),
                "t_impact_est": c.get("t_impact_est"),
                "impact_position": c.get("impact_position"),
                "intensity_proxy": s.get("intensity_proxy", c.get("intensity_proxy")),
            }
        )
    return rows


def synthetic_microphone(
    session_dir: Path,
    cfg: Mapping[str, Any],
    truth: Sequence[Mapping[str, Any]],
    pad_windows: Sequence[tuple[float, float]],
    *,
    rate: int = 48000,
    seed: int = 18,
) -> dict[str, Any]:
    """SYNTHETIC M1 track: pad transients at the truth crossings inside PAD takes, and each sounded
    sample at ``t_target_play + SYNTHETIC_OUTPUT_DELAY_S``, on a noise floor. The known answer per
    strike is ``t_target_play + delay - (t_cross + pad offset)``."""
    audio = read_stream(session_dir / "records" / "AudioEvent.jsonl")[1]
    committed = {s["strike_id"]: s for s in read_stream(session_dir / "records" / "CommittedStrike.jsonl")[1]}
    bank, samples = bank_for(cfg), zone_samples(cfg)
    in_pad = [
        t for t in truth if t["kind"] == "strike" and any(a <= t["t_cross"] < b for a, b in pad_windows)
    ]
    t0 = min([a for a, _ in pad_windows] + [e["t_target_play"] for e in audio]) - 1.0
    t1 = max([b for _, b in pad_windows] + [e["t_target_play"] for e in audio]) + 1.0
    rng = np.random.default_rng(seed)
    x = rng.normal(0.0, 0.002, int((t1 - t0) * rate)).astype(np.float64)
    burst = int(0.01 * rate)
    env = np.exp(-np.arange(burst) / (0.0015 * rate))
    for t in in_pad:
        i = int(round((t["t_cross"] + SYNTHETIC_PAD_OFFSET_S - t0) * rate))
        x[i : i + burst] += 0.5 * env * rng.choice([-1.0, 1.0], size=burst)
    placed = []
    for e in audio:
        zone = committed.get(e["strike_id"], {}).get("zone_id")
        data = bank[e["sample_id"] if e.get("sample_id") else samples[zone]].data.astype(np.float64)
        i = int(round((e["t_target_play"] + SYNTHETIC_OUTPUT_DELAY_S - t0) * rate))
        if 0 <= i and i + len(data) <= len(x):
            x[i : i + len(data)] += 0.5 * float(e.get("gain", 1.0)) * data
            placed.append(e["strike_id"])
    x = np.clip(x, -1.0, 1.0)
    path = write_wav(session_dir / "m1_synthetic.wav", x.astype(np.float32), rate)
    return {
        "path": path.name,
        "rate": rate,
        "t_mono_first_sample": t0,
        "device": "SYNTHETIC generator (no microphone)",
        "pad_strikes": len(in_pad),
        "sounds_placed": len(placed),
        "known": {"output_delay_s": SYNTHETIC_OUTPUT_DELAY_S, "pad_offset_s": SYNTHETIC_PAD_OFFSET_S},
    }


def m1_session(
    session_dir: Path,
    cfg: Mapping[str, Any],
    recording: Path,
    *,
    pad_windows: Sequence[tuple[float, float]],
    min_ncc: float = 0.5,
) -> dict[str, Any]:
    """Locate every played sample in the recording, align the sounds with the software audio events
    (the recording->t_mono map; strikes then carry their strike_id and arm), find pad onsets on the
    residual inside PAD takes, and pair them. Latency = sound onset - pad onset, in one recording."""
    x, rate = read_wav(recording)
    x = x.mean(axis=1)
    audio = read_stream(session_dir / "records" / "AudioEvent.jsonl")[1]
    committed = {s["strike_id"]: s for s in read_stream(session_dir / "records" / "CommittedStrike.jsonl")[1]}
    bank = bank_for(cfg)
    located: list[dict[str, Any]] = []
    for sample_id in sorted({e["sample_id"] for e in audio}):
        template = bank[sample_id].data
        for f in acoustic.locate_template(x, template, rate, min_ncc=min_ncc):
            located.append({**f, "sample_id": sample_id, "template_len": len(template)})
    located.sort(key=lambda f: f["t_s"])
    targets = sorted(float(e["t_target_play"]) for e in audio)
    sync = align_event_trains(
        [f["t_s"] for f in located], targets, tolerance_s=M1_SYNC_TOLERANCE_S, max_offset_s=None
    )
    out: dict[str, Any] = {
        "sync": {
            **{k: sync[k] for k in ("status", "reason", "map", "unmatched_markers")},
            "n_matched": len(sync["matches"]),
        },
        "n_sounds_located": len(located),
        "n_audio_events": len(audio),
    }
    if sync["status"] != "OK":
        out.update(
            strikes=[], excluded=[], note="sync failed: external latencies excluded (pre-registration §7)"
        )
        return out
    by_target = {}
    for e in audio:
        by_target.setdefault(float(e["t_target_play"]), e)
    sound_of = {}
    for ext, mono in sync["matches"]:
        f = min(located, key=lambda item: abs(item["t_s"] - ext))
        sound_of[round(f["t_s"], 9)] = (f, by_target[mono])
    offset, drift = sync["map"]["offset_s"], sync["map"]["drift"]
    to_ext = lambda t: (t - offset) / (1.0 + drift)  # noqa: E731
    pad_ext = [(to_ext(a), to_ext(b)) for a, b in pad_windows]
    sounds_in_pad = [
        (f, e)
        for f, e in sound_of.values()
        if any(a <= f["t_s"] + 0.3 and f["t_s"] - 0.3 <= b for a, b in pad_ext)
    ]
    residual = x.copy()
    for sample_id in {e["sample_id"] for _, e in sounds_in_pad}:
        tpl = bank[sample_id].data
        residual = acoustic.subtract_templates(
            residual, rate, [f for f, e in sounds_in_pad if e["sample_id"] == sample_id], tpl
        )
    pads = []  # per PAD window: a global threshold would follow the loudest drum sample elsewhere
    for a, b in pad_ext:
        i0, i1 = max(0, int(a * rate)), min(len(residual), int(b * rate))
        if i1 - i0 > int(0.05 * rate):
            pads += [i0 / rate + t for t in acoustic.pad_onsets(residual[i0:i1], rate)]
    paired = acoustic.pair_strikes(pads, [f["t_s"] for f, _ in sounds_in_pad])
    strikes = []
    for p in paired["pairs"]:
        f, e = sounds_in_pad[p["sound_index"]]
        s = committed.get(e["strike_id"], {})
        strikes.append(
            {
                "strike_id": e["strike_id"],
                "arm": s.get("arm"),
                "zone_id": s.get("zone_id"),
                "latency_s": p["latency_s"],
                "t_pad_ext_s": p["t_pad_s"],
                "t_sound_ext_s": p["t_sound_s"],
                "ncc": f["ncc"],
                "rise_time_s": acoustic.rise_time(x, rate, p["t_pad_s"]),
            }
        )
    out.update(
        strikes=strikes,
        excluded=paired["excluded"],
        unpaired_pads=paired["unpaired_pads"],
        n_pad_onsets=len(pads),
        window=paired["window"],
    )
    return out


def pad_windows(meta: Mapping[str, Any]) -> list[tuple[float, float]]:
    return [
        (float(s["t_start"]), float(s["t_end"]))
        for s in meta["segments"]
        if s["condition"] == "PAD" and s["status"] == "RECORDED" and s["t_end"] is not None
    ]


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "SYNTHETIC_OUTPUT_DELAY_S",
    "SYNTHETIC_PAD_OFFSET_S",
    "bank_for",
    "m1_session",
    "pad_windows",
    "read_json",
    "strike_rows",
    "synthetic_microphone",
    "zone_samples",
]
