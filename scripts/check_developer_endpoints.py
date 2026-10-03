"""One short, cued developer endpoint check; no decisions, commits or audio.

Space/Enter starts four six-second steps. Esc/Q stops. Frames are buffered in
memory and saved after camera shutdown so recording I/O cannot lower live FPS.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import cv2
from camera_quality_experiment import AuditCamera, analysis_record, properties

from spacedrums.app.main import Perception
from spacedrums.app.play import distribution, play_config
from spacedrums.capture import CaptureSettings, LiveFrameSource, Roi
from spacedrums.config import config_hash
from spacedrums.geometry import ZoneRegistry
from spacedrums.timing import now
from spacedrums.ui.developer_demo import DemoOverlay

STEPS = ("HOLD BOTH STILL", "RAISE BOTH", "MOVE ONE SLOWLY", "ONE SLOW DOWNSTROKE")
STEP_SECONDS = 6
WINDOW = "SpaceDrums - endpoint check (audio off)"


def summarize(rows):
    if not rows:
        return {"frames": 0}
    times = [r["t_capture"] for r in rows]
    n = len(rows)
    present = sum(h["present"] for r in rows for h in r["hands"])
    measured = sum(e["kind"] == "MEASURED" for r in rows for e in r["endpoints"])
    both = [all(e["kind"] == "MEASURED" for e in r["endpoints"]) for r in rows]
    runs, current = [], []
    for i, ok in enumerate(both):
        if current and (not ok or times[i] - times[current[-1]] > 0.115):
            runs.append(current)
            current = []
        if ok:
            current.append(i)
    if current:
        runs.append(current)
    return {
        "frames": n,
        "span_s": times[-1] - times[0],
        "processed_fps": (n - 1) / (times[-1] - times[0]) if n > 1 else None,
        "dropped_frames": sum(r["dropped_since_last"] for r in rows[1:]),
        "hand_presence_fraction": present / (2 * n),
        "both_hands_fraction": sum(all(h["present"] for h in r["hands"]) for r in rows) / n,
        "hand_observations": present,
        "measured_endpoints": measured,
        "endpoint_acceptance_given_hand": measured / present if present else None,
        "measured_endpoint_fraction": measured / (2 * n),
        "both_tip_frames": sum(both),
        "both_tip_fraction": sum(both) / n,
        "both_tip_runs": len(runs),
        "longest_both_tip_run_frames": max((len(r) for r in runs), default=0),
        "longest_both_tip_run_span_s": max((times[r[-1]] - times[r[0]] for r in runs), default=0),
        "both_tip_losses": sum(a and not b for a, b in zip(both, both[1:], strict=False)),
        "endpoint_reasons": dict(Counter(e["reason"] for r in rows for e in r["endpoints"])),
        "perception_ms": distribution([r["perception_ms"] for r in rows]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    cv2.setNumThreads(1)
    cfg, normal = play_config(demo=True), play_config()
    assert normal["camera_profile"]["exposure"] == {"mode": "MANUAL", "value": -6}
    assert cfg["camera_profile"]["exposure"] == {"mode": "MANUAL", "value": -5}
    settings = CaptureSettings.from_config(cfg)
    assert (settings.spec.backend, settings.spec.width, settings.spec.height, settings.spec.fps) == (
        "DSHOW", 640, 480, 30)
    camera = AuditCamera()
    source = LiveFrameSource(camera, settings)
    overlay = DemoOverlay()
    registry = ZoneRegistry.from_config(cfg["zones"])
    roi = Roi.from_rect(cfg["roi"]["px"])
    rows, images = [], []
    perception = None
    report = {"provenance": "DEVELOPER_LIVE_ENDPOINT_CHECK", "participant_evidence": False,
              "strikes_enabled": False, "audio_enabled": False, "config_hash": config_hash(cfg),
              "config": cfg, "error": None, "completed": False, "started": False,
              "steps": list(STEPS), "step_seconds": STEP_SECONDS,
              "recording": "All processed check frames buffered; JPEG quality 95 after shutdown",
              "tip_accuracy": "REQUIRES_VISUAL_REVIEW; acceptance is not endpoint ground truth"}
    try:
        perception = Perception(cfg)
        report["negotiated"] = source.start().to_dict()
        if report["negotiated"]["fourcc"] != "YUY2":
            raise RuntimeError("Expected negotiated YUY2; stopping before physical check")
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WINDOW, 960, 720)
        opened, started, last_frame, last_step = now(), None, now(), None
        while True:
            sample = source.next_frame(timeout=0.2)
            if sample is None:
                if now() - last_frame > 5:
                    raise RuntimeError("Camera stopped delivering frames")
                if cv2.pollKey() & 0xFF in (27, ord("q")):
                    break
                continue
            last_frame = now()
            view = source.view(sample)
            begin = now()
            observations = perception(view)
            latency = (now() - begin) * 1000
            evidence = perception.estimator.evidence
            elapsed = now() - started if started is not None else None
            if elapsed is not None and elapsed >= len(STEPS) * STEP_SECONDS:
                report["completed"] = True
                break
            if started is None:
                cue = "SETTLING" if now() - opened < 3 else "SPACE: START 24s CHECK"
                if now() - opened > 120:
                    report["stop_reason"] = "READY_TIMEOUT"
                    break
            else:
                step = int(elapsed // STEP_SECONDS)
                cue = f"{step + 1}/4 {STEPS[step]} {STEP_SECONDS - int(elapsed % STEP_SECONDS)}s"
                if step != last_step:
                    print(cue, flush=True)
                    last_step = step
                # Early rejection can retain an old debug object. Omit it in logs.
                absent_analysis = {"HAND_MISSING", "GRIP_DIRECTION_UNCERTAIN", "HAND_OUTSIDE_ROI"}
                row = {"frame_id": sample.frame_id, "t_capture": sample.t_capture,
                       "elapsed_s": elapsed, "step": step + 1, "cue": STEPS[step],
                       "dropped_since_last": sample.dropped_since_last, "perception_ms": latency,
                       "hands": [h.to_dict() for h, _ in observations.values()],
                       "endpoints": [e.to_dict() for e in evidence.values()],
                       "stages": {str(h): analysis_record(perception.last_analyses[h])
                                  if e.reason not in absent_analysis else None
                                  for h, e in evidence.items()},
                       "image": f"frames/{len(images):04d}.jpg"}
                rows.append(row)
                images.append(view.full.copy())
                if len(images) > 1000:
                    raise RuntimeError("Check frame buffer limit exceeded")
            img = overlay.render(view.full, roi, registry, evidence,
                                 SimpleNamespace(sample=sample, commits=[]),
                                 dropped=sample.dropped_since_last, perception_ms=latency,
                                 audio_state="DISABLED", stroke_diagnostics={}, cue=cue)
            cv2.imshow(WINDOW, img)
            key = cv2.pollKey() & 0xFF
            if key in (27, ord("q")):
                report["stop_reason"] = "USER_CLOSED"
                break
            if key in (32, 13) and started is None and now() - opened >= 3:
                report["properties_at_start"] = properties(camera)
                if report["properties_at_start"]["EXPOSURE"] != -5:
                    raise RuntimeError("Manual exposure -5 did not read back")
                started = now()
                report["started"] = True
        report["properties_at_end"] = properties(camera)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        source.stop()
        if perception:
            perception.close()
        cv2.destroyAllWindows()
    report.update(capture=source.stats().to_dict(), timestamps=source.timestamp_report(),
                  exposure_calls=camera.exposure_calls, camera_closed=True,
                  overall=summarize(rows), by_step={str(i): summarize([r for r in rows if r["step"] == i])
                                                   for i in range(1, 5)})
    (args.output / "observations.jsonl").write_text(
        "".join(json.dumps(r, allow_nan=False) + "\n" for r in rows), encoding="utf-8")
    report_path = args.output / "report.json"
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if images:
        (args.output / "frames").mkdir()
        print(f"Camera closed. Saving {len(images)} review frames.", flush=True)
        for row, img in zip(rows, images, strict=True):
            if not cv2.imwrite(str(args.output / row["image"]), img, [cv2.IMWRITE_JPEG_QUALITY, 95]):
                raise OSError(f"Could not save frame {row['frame_id']}")
    print(json.dumps({k: report[k] for k in ("error", "completed", "overall")}), flush=True)
    return 0 if report["completed"] and not report["error"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
