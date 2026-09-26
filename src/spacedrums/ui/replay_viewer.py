"""Frame-id aligned recorded-session viewer with optional Phase 07 ground truth."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import cv2
import yaml

from spacedrums.capture import ReplayFrameSource, Roi
from spacedrums.contracts import (
    CommittedStrike,
    HandObservation,
    StickObservation,
    StrikeCandidate,
    TrackState,
    TrajectoryPrediction,
)
from spacedrums.geometry import ZoneRegistry
from spacedrums.timing.logger import read_record_stream
from spacedrums.ui.overlay import OverlayConfig, OverlayRecords, RuntimeStats, draw_scientific_overlay

RECORD_CLASSES = {
    "HandObservation": HandObservation,
    "StickObservation": StickObservation,
    "TrackState": TrackState,
    "TrajectoryPrediction": TrajectoryPrediction,
    "StrikeCandidate": StrikeCandidate,
    "CommittedStrike": CommittedStrike,
}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _match_ids(
    strikes: list[dict[str, Any]], labels: list[dict[str, Any]], *, window_s: float
) -> tuple[set[str], set[str]]:
    """Phase 09 matching semantics, reduced to IDs to keep the UI layer independent."""
    if not 0 <= window_s < float("inf"):
        raise ValueError("window_s must be finite and nonnegative")
    edges: list[tuple[float, float, float, int, int]] = []
    for i, strike in enumerate(strikes):
        for j, label in enumerate(labels):
            if (str(strike["session_id"]), str(strike["hand_id"])) != (
                str(label["session_id"]),
                str(label["hand_id"]),
            ):
                continue
            delta = abs(float(strike["t_commit"]) - float(label["t_impact_est"]))
            if delta <= window_s + 1e-12:
                edges.append((delta, float(strike["t_commit"]), float(label["t_impact_est"]), i, j))
    used_strikes: set[int] = set()
    used_labels: set[int] = set()
    for _, _, _, i, j in sorted(edges):
        if i not in used_strikes and j not in used_labels:
            used_strikes.add(i)
            used_labels.add(j)
    return (
        {str(labels[j]["label_id"]) for j in used_labels},
        {str(strikes[i]["strike_id"]) for i in range(len(strikes)) if i not in used_strikes},
    )


class ReplaySession:
    """Loads once, indexes every stream by ``frame_id``, and never aligns by line number."""

    def __init__(
        self, session_dir: str | Path, *, labels: str | Path | None = None, match_window_s: float = 0.05
    ) -> None:
        self.dir = Path(session_dir)
        self.source = ReplayFrameSource(self.dir)
        self.meta = self.source.meta
        config_path = self.dir / "config.snapshot.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        if not isinstance(config, dict) or not config.get("zones"):
            raise ValueError(f"{self.dir}: config.snapshot.yaml has no zones")
        self.registry = ZoneRegistry.from_config(config["zones"])
        self.by_frame: dict[str, dict[int, list[Any]]] = {}
        for name, cls in RECORD_CLASSES.items():
            path = self.dir / "records" / f"{name}.jsonl"
            rows = read_record_stream(path)[1] if path.exists() else []
            index: dict[int, list[Any]] = defaultdict(list)
            for row in rows:
                index[int(row["frame_id"])].append(cls.from_dict(row))
            self.by_frame[name] = dict(index)
        self.labels = _jsonl(Path(labels)) if labels else []
        self.has_labels = labels is not None
        self.gt_by_frame: dict[int, list[dict[str, Any]]] = defaultdict(list)
        self.false_positive_ids: set[str] = set()
        self._align_ground_truth(match_window_s)

    @property
    def session_id(self) -> str:
        return str(self.meta.get("session_id", self.dir.name))

    def _align_ground_truth(self, window_s: float) -> None:
        if not self.has_labels:
            return
        events = [
            dict(row)
            for row in self.labels
            if row.get("level") == "EVENT"
            and row.get("t_impact_est") is not None
            and not row.get("excluded", False)
        ]
        commits = [
            {**record.to_dict(), "session_id": self.session_id}
            for records in self.by_frame.get("CommittedStrike", {}).values()
            for record in records
            if not record.shadow
        ]
        matched_labels, self.false_positive_ids = _match_ids(commits, events, window_s=window_s)
        sample_times = [(sample.frame_id, sample.t_capture) for sample in self.source.samples]
        for label in events:
            label = dict(label)
            label["match_status"] = "MATCHED" if str(label["label_id"]) in matched_labels else "UNMATCHED"
            frames = label.get("frames") or {}
            before = frames.get("before_event")
            if before is not None and any(fid == int(before) for fid, _ in sample_times):
                frame_id = int(before)
            else:
                frame_id = min(sample_times, key=lambda item: abs(item[1] - float(label["t_impact_est"])))[0]
            self.gt_by_frame[frame_id].append(label)

    def frame_records(self, frame_id: int) -> dict[str, list[Any]]:
        return {name: index.get(frame_id, []) for name, index in self.by_frame.items()}

    def render(self, index: int, *, config: OverlayConfig | None = None) -> Any:
        sample = self.source.samples[index]
        view = self.source.view(sample)
        image = view.full if view.full is not None else view.roi
        roi = (
            Roi.from_rect(sample.roi_px)
            if view.full is not None
            else Roi(0, 0, image.shape[1], image.shape[0])
        )
        recs = self.frame_records(sample.frame_id)
        hands = {record.hand_id: record for record in recs["HandObservation"]}
        sticks = {record.hand_id: record for record in recs["StickObservation"]}
        tracks = {record.hand_id: record for record in recs["TrackState"]}
        predictions = tuple(
            ("B" if str(p.anticipator_id).startswith("rule") else "C", p)
            for p in recs["TrajectoryPrediction"]
        )
        commits = tuple(recs["CommittedStrike"])
        runtime = RuntimeStats(
            active_arm=str(self.meta.get("arm_active", "?")),
            fallback_status=(self.meta.get("model_runtime") or {}).get("error"),
            capture_drops=sample.dropped_since_last,
        )
        records = OverlayRecords(
            predictions=predictions,
            candidates=tuple(recs["StrikeCandidate"]),
            commits=commits,
            ground_truth=tuple(self.gt_by_frame.get(sample.frame_id, ())),
            runtime=runtime,
        )
        rendered = draw_scientific_overlay(
            image,
            roi,
            config=config or OverlayConfig(),
            hands=hands,
            sticks=sticks,
            tracks=tracks,
            records=records,
            registry=self.registry,
        )
        for commit in commits:
            if commit.strike_id in self.false_positive_ids:
                cv2.putText(
                    rendered,
                    f"UNMATCHED COMMIT {commit.strike_id}",
                    (8, 52),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.43,
                    (70, 70, 245),
                    1,
                    cv2.LINE_AA,
                )
        cv2.putText(
            rendered,
            f"{index + 1}/{len(self.source)} frame_id={sample.frame_id}",
            (8, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.50,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        return rendered

    def export_clip(
        self,
        path: str | Path,
        *,
        start: int = 0,
        end: int | None = None,
        fps: float = 30.0,
        config: OverlayConfig | None = None,
    ) -> Path:
        end = len(self.source) if end is None else min(end, len(self.source))
        if not 0 <= start < end:
            raise ValueError("clip range must satisfy 0 <= start < end")
        first = self.render(start, config=config)
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(
            str(destination), cv2.VideoWriter_fourcc(*"mp4v"), fps, (first.shape[1], first.shape[0])
        )
        if not writer.isOpened():
            raise OSError(f"cannot create {destination}")
        try:
            writer.write(first)
            for index in range(start + 1, end):
                writer.write(self.render(index, config=config))
        finally:
            writer.release()
        return destination


def run_viewer(session: ReplaySession, *, mode: str = "full") -> None:
    """Interactive scrubber: arrows/a-d step, space plays, home/end jump, q exits."""
    window = "Space Drums - replay viewer"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.createTrackbar("frame", window, 0, max(0, len(session.source) - 1), lambda _value: None)
    index, playing = 0, False
    try:
        while True:
            index = cv2.getTrackbarPos("frame", window)
            cv2.imshow(window, session.render(index, config=OverlayConfig.for_mode(mode)))
            key = cv2.waitKey(30 if playing else 0) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord(" "):
                playing = not playing
            elif key in (ord("a"), 81):
                index = max(0, index - 1)
            elif key in (ord("d"), 83):
                index = min(len(session.source) - 1, index + 1)
            elif playing:
                index = min(len(session.source) - 1, index + 1)
                playing = index < len(session.source) - 1
            cv2.setTrackbarPos("frame", window, index)
    finally:
        cv2.destroyWindow(window)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--mode", choices=("experiment", "full"), default="full")
    parser.add_argument("--export-clip", type=Path)
    args = parser.parse_args(argv)
    session = ReplaySession(args.session_dir, labels=args.labels)
    if args.export_clip:
        session.export_clip(args.export_clip, config=OverlayConfig.for_mode(args.mode))
    else:
        run_viewer(session, mode=args.mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ReplaySession", "run_viewer"]
