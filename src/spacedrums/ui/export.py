"""Reproducible Phase 15 frame, plot, timing-table and summary exports."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import matplotlib
import numpy as np

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

from spacedrums.contracts import TimingRecord
from spacedrums.timing.decomposition import decompose
from spacedrums.timing.logger import read_record_stream
from spacedrums.ui.overlay import OverlayConfig
from spacedrums.ui.replay_viewer import ReplaySession


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError("export identifiers must contain a safe filename character")
    return cleaned


@dataclass(frozen=True)
class ExportIdentity:
    session_id: str
    arm: str
    model_id: str = "none"

    @property
    def stem(self) -> str:
        return "__".join(_slug(value) for value in (self.session_id, self.arm, self.model_id))


def identity_for(session: ReplaySession) -> ExportIdentity:
    return ExportIdentity(
        session.session_id,
        str(session.meta.get("arm_active", "unknown")),
        str(session.meta.get("model_id") or "none"),
    )


def _save_figure(fig: Any, base: Path) -> list[Path]:
    paths = [base.with_suffix(".png"), base.with_suffix(".svg")]
    fig.savefig(paths[0], dpi=220, bbox_inches="tight")
    fig.savefig(paths[1], bbox_inches="tight")
    plt.close(fig)
    return paths


def export_annotated_frame(
    session: ReplaySession, frame_index: int, output_dir: str | Path, *, mode: str = "full"
) -> Path:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    sample = session.source.samples[frame_index]
    path = destination / f"{identity_for(session).stem}__frame-{sample.frame_id:06d}.png"
    image = session.render(frame_index, config=OverlayConfig.for_mode(mode))
    if not cv2.imwrite(str(path), image, [cv2.IMWRITE_PNG_COMPRESSION, 3]):
        raise OSError(f"cannot write {path}")
    return path


def export_timing_csv(session: ReplaySession, output_dir: str | Path) -> Path:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"{identity_for(session).stem}__timing.csv"
    timing_path = session.dir / "timing.jsonl"
    rows = read_record_stream(timing_path)[1] if timing_path.exists() else []
    candidates = {
        record.candidate_id: record
        for records in session.by_frame["StrikeCandidate"].values()
        for record in records
    }
    commits = {
        record.strike_id: record
        for records in session.by_frame["CommittedStrike"].values()
        for record in records
    }
    fields = [
        "strike_id",
        "frame_id",
        "arm",
        "hand_id",
        "zone_id",
        "t_capture",
        "t_commit",
        "t_impact_pred",
        "t_impact_est",
        "lead_kind",
        "lead_s",
        "t_tracking_done",
        "t_features_done",
        "t_inference_done",
        "t_audio_scheduled",
        "t_audio_out_est",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            if row.get("kind") != "STRIKE":
                continue
            record = TimingRecord.from_dict(row)
            commit = commits.get(str(record.strike_id))
            candidate = candidates.get(commit.candidate_id) if commit else None
            if record.t_impact_est is not None:
                lead_kind, impact = "L_pred_ESTIMATED", record.t_impact_est
            elif record.t_impact_pred is not None:
                lead_kind, impact = "PREDICTED_LEAD", record.t_impact_pred
            else:
                lead_kind, impact = "UNAVAILABLE", None
            writer.writerow(
                {
                    "strike_id": record.strike_id,
                    "frame_id": record.frame_id,
                    "arm": record.arm,
                    "hand_id": record.hand_id,
                    "zone_id": candidate.zone_id if candidate else None,
                    "t_capture": record.t_capture,
                    "t_commit": record.t_commit,
                    "t_impact_pred": record.t_impact_pred,
                    "t_impact_est": record.t_impact_est,
                    "lead_kind": lead_kind,
                    "lead_s": None if impact is None else impact - float(record.t_commit),
                    "t_tracking_done": record.t_tracking_done,
                    "t_features_done": record.t_features_done,
                    "t_inference_done": record.t_inference_done,
                    "t_audio_scheduled": record.t_audio_scheduled,
                    "t_audio_out_est": record.t_audio_out_est,
                }
            )
    return path


def export_rolling_plots(session: ReplaySession, output_dir: str | Path) -> list[Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    stem = identity_for(session).stem
    tracks = [record for frame in session.by_frame["TrackState"].values() for record in frame]
    commits = [record for frame in session.by_frame["CommittedStrike"].values() for record in frame]
    candidates = [record for frame in session.by_frame["StrikeCandidate"].values() for record in frame]
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True, constrained_layout=True)
    for hand, color in (("LEFT", "#e69f00"), ("RIGHT", "#0072b2")):
        rows = [row for row in tracks if str(row.hand_id) == hand and row.tip_filtered is not None]
        axes[0].plot(
            [row.t_capture for row in rows],
            [row.tip_filtered[1] for row in rows],
            label=hand,
            color=color,
            linewidth=1.2,
        )
        axes[1].plot(
            [row.t_capture for row in rows],
            [row.tip_velocity[1] for row in rows],
            label=hand,
            color=color,
            linewidth=1.2,
        )
    for commit in commits:
        for axis in axes[:2]:
            axis.axvline(commit.t_capture, color="#cc3311", alpha=0.25, linewidth=0.8)
    tti_rows = [row for row in candidates if row.tti is not None]
    axes[2].scatter(
        [row.t_capture for row in tti_rows],
        [row.tti for row in tti_rows],
        s=12,
        c="#009988",
        label="candidate TTI",
    )
    axes[0].set_ylabel("tip y / ROI")
    axes[1].set_ylabel("vertical velocity\nROI/s")
    axes[2].set_ylabel("TTI / s")
    axes[2].set_xlabel("capture time / s")
    axes[0].invert_yaxis()
    for axis in axes:
        axis.grid(alpha=0.22)
        axis.legend(loc="best")
    paths = _save_figure(fig, destination / f"{stem}__rolling")

    timing_path = session.dir / "timing.jsonl"
    timings = (
        [TimingRecord.from_dict(row) for row in read_record_stream(timing_path)[1]]
        if timing_path.exists()
        else []
    )
    processing = []
    live_session = session.meta.get("producer") == "LIVE"
    for row in timings:
        if row.kind == "FRAME" and row.t_tracking_done is not None:
            if live_session:
                done = row.t_inference_done if row.t_inference_done is not None else row.t_tracking_done
                processing.append((row.frame_id, max(0.0, done - row.t_frame_available)))
            elif row.t_inference_done is not None:
                processing.append((row.frame_id, max(0.0, row.t_inference_done - row.t_tracking_done)))
    fig, axis = plt.subplots(figsize=(9, 3.8), constrained_layout=True)
    axis.plot([v[0] for v in processing], [v[1] * 1000 for v in processing], color="#0072b2")
    ylabel = "total processing / ms" if live_session else "inference stage / ms (replay-safe)"
    title = "Per-frame software processing time" if live_session else "Per-frame replay-safe stage time"
    axis.set(xlabel="frame id", ylabel=ylabel, title=title)
    axis.grid(alpha=0.22)
    paths += _save_figure(fig, destination / f"{stem}__processing")

    lead = [c.t_impact_target - c.t_commit for c in commits if c.t_impact_target is not None]
    fig, axis = plt.subplots(figsize=(7, 4), constrained_layout=True)
    axis.hist(np.asarray(lead) * 1000, bins=max(5, min(30, len(lead) or 5)), color="#009988")
    axis.set(xlabel="commit-to-target lead / ms", ylabel="count", title="Session lead-time distribution")
    axis.grid(axis="y", alpha=0.22)
    paths += _save_figure(fig, destination / f"{stem}__lead-histogram")
    return paths


def export_trajectory_plot(session: ReplaySession, frame_index: int, output_dir: str | Path) -> list[Path]:
    sample = session.source.samples[frame_index]
    predictions = session.by_frame["TrajectoryPrediction"].get(sample.frame_id, [])
    if not predictions:
        raise ValueError(f"frame {sample.frame_id} has no trajectory prediction")
    fig, axis = plt.subplots(figsize=(6, 6), constrained_layout=True)
    for prediction in predictions:
        xy = np.asarray(prediction.positions)
        axis.plot(xy[:, 0], xy[:, 1], marker="o", label=f"predicted {prediction.hand_id}")
        future = [
            row
            for fid in sorted(session.by_frame["TrackState"])
            if fid > sample.frame_id
            for row in session.by_frame["TrackState"][fid]
            if row.hand_id == prediction.hand_id and row.tip_filtered is not None
        ][: prediction.K]
        if future:
            actual = np.asarray([row.tip_filtered for row in future])
            axis.plot(
                actual[:, 0],
                actual[:, 1],
                marker="x",
                linestyle="--",
                label=f"observed future {prediction.hand_id}",
            )
    axis.set(xlabel="ROI x", ylabel="ROI y", title=f"Trajectory horizon at frame {sample.frame_id}")
    axis.invert_yaxis()
    axis.grid(alpha=0.22)
    axis.legend()
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    return _save_figure(fig, destination / f"{identity_for(session).stem}__trajectory-{sample.frame_id:06d}")


def export_false_positives(session: ReplaySession, output_dir: str | Path) -> Path:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"{identity_for(session).stem}__false-positives.csv"
    labels = session.labels
    intervals = [row for row in labels if row.get("level") == "INTERVAL"]
    commits = [record for frame in session.by_frame["CommittedStrike"].values() for record in frame]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=("strike_id", "t_commit", "hand_id", "zone_id", "segment_type")
        )
        writer.writeheader()
        for commit in commits:
            if commit.strike_id not in session.false_positive_ids:
                continue
            segment = next(
                (
                    row.get("segment_type")
                    for row in intervals
                    if row.get("t_start") is not None
                    and row.get("t_end") is not None
                    and float(row["t_start"]) <= commit.t_commit <= float(row["t_end"])
                ),
                "UNKNOWN",
            )
            writer.writerow(
                {
                    "strike_id": commit.strike_id,
                    "t_commit": commit.t_commit,
                    "hand_id": commit.hand_id,
                    "zone_id": commit.zone_id,
                    "segment_type": segment,
                }
            )
    return path


def export_session(session: ReplaySession, output_dir: str | Path, *, frame_index: int = 0) -> list[Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    outputs = [
        export_annotated_frame(session, frame_index, destination),
        export_timing_csv(session, destination),
    ]
    outputs += export_rolling_plots(session, destination)
    outputs.append(export_false_positives(session, destination))
    trajectory_frames = sorted(session.by_frame["TrajectoryPrediction"])
    if trajectory_frames:
        selected = next(
            i for i, sample in enumerate(session.source.samples) if sample.frame_id == trajectory_frames[0]
        )
        outputs += export_trajectory_plot(session, selected, destination)
    timing_path = session.dir / "timing.jsonl"
    timings = (
        [TimingRecord.from_dict(row) for row in read_record_stream(timing_path)[1]]
        if timing_path.exists()
        else []
    )
    summary = {
        "schema_version": "phase15-session-summary-v1",
        "identity": identity_for(session).__dict__,
        "source_session": str(session.dir),
        "frames": len(session.source),
        "ground_truth_events": sum(len(rows) for rows in session.gt_by_frame.values()),
        "false_positive_commits": len(session.false_positive_ids),
        "timing": decompose(timings, live=session.meta.get("producer") == "LIVE"),
        "artifacts": [path.name for path in outputs],
    }
    summary_path = destination / f"{identity_for(session).stem}__summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    outputs.append(summary_path)
    return outputs


__all__ = [
    "ExportIdentity",
    "export_annotated_frame",
    "export_false_positives",
    "export_rolling_plots",
    "export_session",
    "export_timing_csv",
    "export_trajectory_plot",
    "identity_for",
]
