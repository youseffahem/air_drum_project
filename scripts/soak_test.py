"""Phase 17 Task 17.8: soak test of the live application with periodic scripted playing.

    python scripts/soak_test.py --minutes 60 --executor-model M --executor-effort E

Runs ``spacedrums.app.main.run`` (live camera, real perception, the configured model arm with A and
B shadow, the real audio callback, the dashboard worker, invariant monitor in ``log`` mode, health
monitor, structured event log) for ``--minutes``. Every ``--stroke-every-s`` seconds a **SYNTHETIC
scripted stroke** replaces the perception output for about one second (alternating hands and
zones, ``app.synthetic`` kinematics re-timed to the live frames) so tracking, prediction, geometry,
commit and audio scheduling are exercised periodically; outside those windows the camera image is
processed as usual. This is **not** a person playing: the person-played soak stays PENDING.

``--gain-scale`` (default 0.1) attenuates only the soak's played samples so an unattended laptop
does not play full-volume drums for an hour; mixing, callbacks and scheduling are unchanged.

A sampler thread records process working set, private bytes, handle and thread counts every
``--sample-s`` seconds (bounded storage); the run reports memory growth (median of the first vs the
last ten minutes), capture drops / stalls / timestamp interventions, audio underruns / late events /
device recoveries, fallback events, invariant violations and whether the process crashed. An
observation-only probe on ``AudioScheduler.schedule`` records each audio event's lead (target play
time minus scheduling time; negative = already late when scheduled) without changing the event.

Outputs (evidence run directory): ``soak-report.json`` (digest), ``soak-samples.json`` (process
samples), ``app-summary.json`` (the application's full run summary; ``run()`` returns it, only the
CLI ``main()`` writes ``--summary-json``) and the structured event log under ``logs/``.
"""

from __future__ import annotations

import argparse
import ctypes as ct
import json
import threading
import time
from pathlib import Path

import numpy as np
from _p17 import MODEL_CONFIG, add_executor_args, enable_fault_injection, evidence

enable_fault_injection()

from spacedrums.app.main import build_parser, run  # noqa: E402
from spacedrums.app.synthetic import Swing, hand_position  # noqa: E402
from spacedrums.contracts import HandId, HandObservation, StickObservation, TipMethod  # noqa: E402
from spacedrums.geometry import ZoneRegistry  # noqa: E402
from spacedrums.timing import now  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class ProcessSampler(threading.Thread):
    """Working set / private bytes / handles / threads of this process (Windows; bounded)."""

    def __init__(self, period_s: float, keep: int = 20000) -> None:
        super().__init__(name="soak-sampler", daemon=True)
        self.period_s = period_s
        self.samples: list[dict] = []
        self.keep = keep
        self._halt = threading.Event()  # never "_stop": threading.Thread uses that name internally

    def snapshot(self) -> dict:
        from ctypes import wintypes as wt

        class Counters(ct.Structure):
            _fields_ = [
                ("cb", wt.DWORD),
                ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ct.c_size_t),
                ("WorkingSetSize", ct.c_size_t),
                ("QuotaPeakPagedPoolUsage", ct.c_size_t),
                ("QuotaPagedPoolUsage", ct.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ct.c_size_t),
                ("QuotaNonPagedPoolUsage", ct.c_size_t),
                ("PagefileUsage", ct.c_size_t),
                ("PeakPagefileUsage", ct.c_size_t),
                ("PrivateUsage", ct.c_size_t),
            ]

        k32, psapi = ct.WinDLL("kernel32"), ct.WinDLL("psapi")
        k32.GetCurrentProcess.restype = wt.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ct.c_void_p, wt.DWORD]
        k32.GetProcessHandleCount.argtypes = [wt.HANDLE, ct.POINTER(wt.DWORD)]
        proc = k32.GetCurrentProcess()
        c = Counters()
        c.cb = ct.sizeof(Counters)
        psapi.GetProcessMemoryInfo(proc, ct.byref(c), c.cb)
        handles = wt.DWORD()
        k32.GetProcessHandleCount(proc, ct.byref(handles))
        return {
            "t": now(),
            "working_set_mib": c.WorkingSetSize / 2**20,
            "private_mib": c.PrivateUsage / 2**20,
            "handles": int(handles.value),
            "threads": threading.active_count(),
        }

    def run(self) -> None:
        while not self._halt.is_set():
            try:
                if len(self.samples) < self.keep:
                    self.samples.append(self.snapshot())
            except OSError:
                pass
            self._halt.wait(self.period_s)

    def stop(self) -> None:
        self._halt.set()


class ScriptedStrokes:
    """SYNTHETIC strokes injected at the observation level every ``every_s`` seconds."""

    def __init__(self, registry: ZoneRegistry, every_s: float, t0: float) -> None:
        self.registry, self.every_s, self.t0 = registry, every_s, t0
        self.zones = [z.zone_id for z in registry][:4]
        self.windows = 0
        self.injected_frames = 0
        self._current = None

    def __call__(self, sample, obs):
        rel = sample.t_capture - self.t0
        k = int(rel // self.every_s)
        start = k * self.every_s + 1.0  # first stroke after 1 s of the period
        if k < 1 or not (start - 0.3 <= rel <= start + 0.9):
            return obs
        if self._current != k:
            self._current = k
            self.windows += 1
        hand = HandId.RIGHT if k % 2 else HandId.LEFT
        zone = self.zones[k % len(self.zones)]
        swing = Swing(hand, zone, start, t_down=0.15)
        p = hand_position(self.registry, [swing], hand, rel)
        out = dict(obs)
        out[hand] = (
            HandObservation(
                frame_id=sample.frame_id,
                t_capture=sample.t_capture,
                hand_id=hand,
                present=True,
                detector_id="synthetic-soak",
                landmarks=tuple(
                    (p[0] + 0.004 * (i % 5), min(0.98, p[1] + 0.25) - 0.006 * (i // 5)) for i in range(21)
                ),
                landmark_visibility=None,
                handedness_score=0.95,
                bbox=(p[0] - 0.05, min(0.98, p[1] + 0.25) - 0.05, 0.1, 0.1),
            ),
            StickObservation(
                frame_id=sample.frame_id,
                t_capture=sample.t_capture,
                hand_id=hand,
                present=True,
                method_id=TipMethod.GEOM,
                axis_origin=(p[0], min(0.98, p[1] + 0.25)),
                axis_dir=(0.0, -1.0),
                tip=p,
                tip_confidence=0.9,
                axis_confidence=0.95,
                stick_length_est=0.27,
            ),
        )
        self.injected_frames += 1
        return out


class ScheduleProbe:
    """Observation-only wrapper of ``AudioScheduler.schedule``: records each event's lead (bounded)."""

    def __init__(self, keep: int = 20000) -> None:
        from spacedrums.audio.scheduler import AudioScheduler

        self.cls, self.original, self.keep = AudioScheduler, AudioScheduler.schedule, keep
        self.leads_s: list[float] = []
        probe = self

        def schedule(scheduler, committed):
            event = probe.original(scheduler, committed)
            if len(probe.leads_s) < probe.keep:
                probe.leads_s.append(float(event.t_target_play) - float(event.t_audio_scheduled))
            return event

        AudioScheduler.schedule = schedule

    def close(self) -> None:
        self.cls.schedule = self.original

    def report(self) -> dict:
        x = np.asarray(self.leads_s) * 1000.0
        if not len(x):
            return {"n": 0}
        return {
            "n": int(len(x)),
            "late_when_scheduled": int(np.sum(x < 0)),
            "lead_ms_p5": float(np.percentile(x, 5)),
            "lead_ms_p50": float(np.median(x)),
            "lead_ms_p95": float(np.percentile(x, 95)),
            "lead_ms_min": float(x.min()),
            "lead_ms_max": float(x.max()),
            "note": "t_target_play - t_audio_scheduled per audio event; output latency is unmeasured "
            "(placeholder 0), so the mixer counts an event late when its target precedes the buffer",
        }


def median(values):
    return float(np.median(values)) if len(values) else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=60.0)
    ap.add_argument("--config", type=Path, default=MODEL_CONFIG)
    ap.add_argument("--stroke-every-s", type=float, default=15.0)
    ap.add_argument("--gain-scale", type=float, default=0.1)
    ap.add_argument("--sample-s", type=float, default=5.0)
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--output", type=Path, default=ROOT / "experiments" / "phase-17")
    add_executor_args(ap)
    args = ap.parse_args()
    with evidence(
        args.config,
        args,
        slug=f"soak-{int(args.minutes)}min",
        task="17.8",
        description="Live soak with SYNTHETIC scripted strokes (not a person); development evidence",
        output=args.output,
    ) as (run_log, cfg):
        registry = ZoneRegistry.from_config(cfg["zones"])
        strokes = ScriptedStrokes(registry, args.stroke_every_s, t0=now())
        sampler = ProcessSampler(args.sample_s)
        argv = [
            "--config",
            str(args.config),
            "--source",
            "live",
            "--no-window",
            "--dashboard",
            "--max-seconds",
            str(args.minutes * 60),
            "--invariants",
            "log",
            "--log-dir",
            str(run_log.dir / "logs"),
            "--session-id",
            run_log.run_id,
        ]
        if args.no_audio:
            argv.append("--no-audio")
        app_args = build_parser().parse_args(argv)
        crash = None
        started = time.time()
        probe = ScheduleProbe()
        sampler.start()
        try:
            summary = run(app_args, observation_hook=strokes, gain_scale=args.gain_scale)
        except BaseException as exc:  # noqa: BLE001 - a crash is the soak's primary outcome
            crash = {"type": type(exc).__name__, "message": str(exc)[:500]}
            summary = None
        finally:
            sampler.stop()
            sampler.join(timeout=5)
            probe.close()
        if summary is not None:
            (run_log.dir / "app-summary.json").write_text(
                json.dumps(summary, indent=2, default=str), encoding="utf-8"
            )
        wall_s = time.time() - started
        samples = sampler.samples
        t0 = samples[0]["t"] if samples else 0.0
        first = [s["private_mib"] for s in samples if s["t"] - t0 <= 600]
        last = [s["private_mib"] for s in samples if samples and samples[-1]["t"] - s["t"] <= 600]
        counters = (summary or {}).get("counters", {})
        report = {
            "label": "DEVELOPMENT: unattended live soak, SYNTHETIC scripted strokes; no person played",
            "minutes_requested": args.minutes,
            "wall_s": wall_s,
            "crash": crash,
            "frames": (summary or {}).get("frames"),
            "scripted_stroke_windows": strokes.windows,
            "scripted_frames": strokes.injected_frames,
            "memory": {
                "samples": len(samples),
                "private_mib_first_10min_median": median(first),
                "private_mib_last_10min_median": median(last),
                "private_mib_growth": (median(last) - median(first)) if first and last else None,
                "working_set_mib_max": max((s["working_set_mib"] for s in samples), default=None),
                "handles_first": samples[0]["handles"] if samples else None,
                "handles_last": samples[-1]["handles"] if samples else None,
                "threads_max": max((s["threads"] for s in samples), default=None),
            },
            "capture": ((summary or {}).get("source") or {}).get("capture_stats"),
            "audio": counters.get("audio"),
            "audio_schedule_lead": probe.report(),
            "model_error": (counters.get("model") or {}).get("error"),
            "fallback_events": counters.get("fallback_events"),
            "arm_switches": counters.get("arm_switches"),
            "invariants": counters.get("invariants"),
            "health": counters.get("health"),
            "events": counters.get("events"),
            "commits": {
                arm: sum(v["commits"] for v in per.values())
                for arm, per in (counters.get("commit") or {}).items()
            },
            "per_frame_processing_s": counters.get("per_frame_processing_s"),
        }
        (run_log.dir / "soak-samples.json").write_text(json.dumps(samples), encoding="utf-8")
        (run_log.dir / "soak-report.json").write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )
        print(
            json.dumps(
                {k: report[k] for k in ("wall_s", "crash", "frames", "memory", "invariants")},
                indent=2,
                default=str,
            )
        )
    return 0 if crash is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
