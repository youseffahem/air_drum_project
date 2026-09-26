"""Measure Phase 15 overlay modes and dashboard producer-loop impact on one replay.

This is development-machine evidence. It does not measure physical or acoustic latency.
"""

from __future__ import annotations

import argparse
import csv
import json
import socket
import statistics
import threading
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from spacedrums.contracts import TimingRecord
from spacedrums.timing import wall_clock_iso
from spacedrums.timing.logger import read_record_stream
from spacedrums.ui.dashboard import DashboardRecord, DashboardWorker, RecordBus, render_dashboard
from spacedrums.ui.export import export_session
from spacedrums.ui.overlay import OverlayConfig
from spacedrums.ui.replay_viewer import ReplaySession


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), q))


def summary(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "mean_ms": statistics.fmean(values) * 1000,
        "p50_ms": percentile(values, 50) * 1000,
        "p95_ms": percentile(values, 95) * 1000,
        "max_ms": max(values) * 1000,
    }


def overlay_measurements(session: ReplaySession, n_frames: int, repeats: int) -> dict[str, Any]:
    n = min(n_frames, len(session.source))
    values = {mode: [] for mode in ("off", "experiment", "full")}
    orders = (("off", "experiment", "full"), ("full", "off", "experiment"), ("experiment", "full", "off"))
    # Prime image decoding and filesystem cache; each measured mode still reads the same frames.
    for index in range(n):
        session.render(index, config=OverlayConfig.off())
    for repeat in range(repeats):
        for mode in orders[repeat % len(orders)]:
            config = OverlayConfig.for_mode(mode)
            for index in range(n):
                start = time.perf_counter()
                session.render(index, config=config)
                values[mode].append(time.perf_counter() - start)
    result = {mode: summary(rows) for mode, rows in values.items()}
    for mode in ("experiment", "full"):
        result[mode]["incremental_p50_ms_vs_off"] = result[mode]["p50_ms"] - result["off"]["p50_ms"]
        result[mode]["incremental_p95_ms_vs_off"] = result[mode]["p95_ms"] - result["off"]["p95_ms"]
    result["bound"] = {
        "definition": (
            "experiment incremental p95 <= 5.0 ms versus overlay-off on identical replay "
            "(15% of a 30 fps frame period, rounded)"
        ),
        "bound_ms": 5.0,
        "observed_ms": result["experiment"]["incremental_p95_ms_vs_off"],
        "pass": result["experiment"]["incremental_p95_ms_vs_off"] <= 5.0,
    }
    result["capture_drops"] = {
        mode: sum(sample.dropped_since_last for sample in session.source.samples[:n]) for mode in values
    }
    return result


def framework_measurements(iterations: int = 5000) -> dict[str, Any]:
    record = DashboardRecord(1, 1.0, "A", processing_s=0.001)
    bus = RecordBus()
    sub = bus.subscribe("opencv-thread", maxsize=2)
    worker = DashboardWorker(sub)
    worker.start()
    queue_times: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        bus.publish(record)
        queue_times.append(time.perf_counter() - start)
    worker.stop()

    sender, receiver = socket.socketpair(type=socket.SOCK_STREAM)
    sender.setblocking(False)
    receiver.setblocking(False)
    stopping = threading.Event()

    def drain() -> None:
        while not stopping.is_set():
            try:
                receiver.recv(65536)
            except BlockingIOError:
                time.sleep(0.0002)

    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    socket_times: list[float] = []
    socket_drops = 0
    payload = json.dumps(
        {"frame_id": 1, "t_capture": 1.0, "active_arm": "A", "processing_s": 0.001}, separators=(",", ":")
    ).encode()
    try:
        for _ in range(iterations):
            start = time.perf_counter()
            try:
                sender.send(payload)
            except BlockingIOError:
                socket_drops += 1
            socket_times.append(time.perf_counter() - start)
    finally:
        stopping.set()
        thread.join(timeout=1.0)
        sender.close()
        receiver.close()
    return {
        "opencv_thread_bounded_queue": {**summary(queue_times), **sub.stats()},
        "browser_socket_json_transport_prototype": {
            **summary(socket_times),
            "payload_bytes": len(payload),
            "dropped": socket_drops,
            "note": "minimal local stream transport prototype; browser DOM/plot rendering excluded",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args(argv)
    if args.frames < 1 or args.repeats < 1:
        parser.error("--frames and --repeats must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    session = ReplaySession(args.session, labels=args.labels)
    result = {
        "schema_version": "phase15-overhead-v1",
        "measured_at": wall_clock_iso(),
        "evidence_label": "MEASURED development replay wall time; not physical/acoustic latency",
        "session": str(args.session),
        "session_id": session.session_id,
        "frames_per_repeat": min(args.frames, len(session.source)),
        "repeats": args.repeats,
        "overlay": overlay_measurements(session, args.frames, args.repeats),
        "framework": framework_measurements(),
    }
    (args.output / "overhead.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    with (args.output / "overhead.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("mode", "n", "p50_ms", "p95_ms", "max_ms", "incremental_p95_ms_vs_off"))
        for mode in ("off", "experiment", "full"):
            row = result["overlay"][mode]
            writer.writerow(
                (
                    mode,
                    row["n"],
                    row["p50_ms"],
                    row["p95_ms"],
                    row["max_ms"],
                    row.get("incremental_p95_ms_vs_off", 0.0),
                )
            )
    dashboard = DashboardWorker(RecordBus().subscribe("screenshot"), live=False)
    timing_path = session.dir / "timing.jsonl"
    strike_rows = (
        tuple(
            TimingRecord.from_dict(row)
            for row in read_record_stream(timing_path)[1]
            if row.get("kind") == "STRIKE"
        )[:8]
        if timing_path.exists()
        else ()
    )
    strike_zones = tuple(
        (record.strike_id, record.zone_id)
        for records in session.by_frame["CommittedStrike"].values()
        for record in records
        if any(timing.strike_id == record.strike_id for timing in strike_rows)
    )
    screenshot_index = min(60, len(session.source) - 1)
    screenshot_samples = session.source.samples[: screenshot_index + 1]
    capture_drops = 0
    previous_capture = None
    for sample in screenshot_samples:
        capture_drops += sample.dropped_since_last
        capture_dt = sample.t_capture - previous_capture if previous_capture is not None else None
        capture_fps = 1.0 / capture_dt if capture_dt is not None and capture_dt > 0 else None
        previous_capture = sample.t_capture
        frame_records = session.frame_records(sample.frame_id)
        tracks = {str(track.hand_id): track for track in frame_records["TrackState"]}
        candidates = frame_records["StrikeCandidate"]
        dashboard.model.update(
            DashboardRecord(
                sample.frame_id,
                sample.t_capture,
                "B",
                capture_fps=capture_fps,
                capture_drops=capture_drops,
                timing=tuple(row for row in strike_rows if row.frame_id == sample.frame_id),
                strike_zones=strike_zones,
                hands=tuple(
                    {
                        "hand_id": hand_id,
                        "track": track.to_dict(),
                        "candidates": tuple(
                            candidate.to_dict()
                            for candidate in candidates
                            if str(candidate.hand_id) == hand_id
                        ),
                    }
                    for hand_id, track in tracks.items()
                ),
            )
        )
    cv2.imwrite(str(args.output / "dashboard.png"), render_dashboard(dashboard.model))
    export_dir = args.output / "exports"
    exports = export_session(session, export_dir, frame_index=min(60, len(session.source) - 1))
    (args.output / "artifacts.json").write_text(
        json.dumps([str(path.relative_to(args.output)) for path in exports], indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2))
    return 0 if result["overlay"]["bound"]["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
