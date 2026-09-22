"""Offline label generator (Phase 07, Task 07.3).

Pipeline, per accepted session:

    records/StickObservation.jsonl  (measurements)
        -> ReferenceSmoother (NON-CAUSAL, Task 07.2)      -> labels/<session>/tracks_reference.jsonl
    records/TrackState.jsonl        (causal, frozen tracker, Phase 03)
        -> copied unchanged                               -> labels/<session>/tracks_causal.jsonl
    reference trajectory + Phase 04 entry test + rules.py -> labels/<session>/labels.jsonl
                                                          -> labels/<session>/labels.meta.json

Both trajectories are stored. Only the causal one may ever be a model input; the reference one
exists to build labels and is marked ``causal: false`` in its header
(``docs/architecture/causality-tests.md`` section 1.1). The record's ``runtime_reference`` block
carries the causal status and, when the recorded session produced them, the runtime
``StrikeCandidate`` / ``CommittedStrike`` ids for the same entry - as cross-reference, never as
ground truth.

The entry test is Phase 04's, unchanged: outside-to-inside crossing of the zone impact surface
(``geometry.impact.segment_surface``) with the crossing instant from
``geometry.impact.crossing_time`` (LINEAR) or the quadratic alternative of ``interp`` (ADR-0020).
What Phase 07 adds is not a different impact definition but the *classification* of crossings and
approaches that Phase 04's ``v_min`` filter simply dropped: an entry below ``v_min`` becomes an
explicit ``NEG_UPWARD_CROSSING`` instead of silence.

Determinism: with the same session, config, thresholds, smoother and interpolation the generator
produces byte-identical ``labels.jsonl`` and an identical ``set_hash`` (Task 07.3 evidence). The
only wall-clock field, ``generated_at``, is excluded from the hash.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spacedrums import timing
from spacedrums.config import load_config
from spacedrums.contracts import HandId
from spacedrums.data.labels import interp
from spacedrums.data.labels.rules import (
    EventEvidence,
    Thresholds,
    classify,
    distance_to_surface,
    intensity_proxy_gt,
    inward_speed,
    label_confidence,
    rules_hash,
    signed_distance_to_surface,
)
from spacedrums.data.labels.schema import (
    CAUSAL_TRACK_FILENAME,
    GENERATOR,
    GEOMETRY_VERSION,
    LABEL_RECORD_SCHEMA_VERSION,
    LABEL_SET_FILENAME,
    LABEL_SET_SCHEMA_VERSION,
    LABELS_FILENAME,
    LABELS_VERSION,
    REFERENCE_TRACK_BANNER,
    REFERENCE_TRACK_FILENAME,
    REFERENCE_TRACK_SCHEMA_VERSION,
    RULES_VERSION,
    DATASET_LABELS,
    Interpolation,
    LabelClass,
    Level,
    Provenance,
    QCStatus,
    admissible_source,
    dataset_kind,
    empty_review,
    evidence_label,
    label_id as make_label_id,
    label_set_hash,
    runtime_reference,
    sha256_file,
    sha256_obj,
    validate_label,
    validate_label_set,
    validate_reference_header,
    validate_reference_sample,
)
from spacedrums.data.labels.smooth import (
    LossInterval,
    Measurement,
    ReferenceSample,
    ReferenceSmoother,
    resample,
    speed,
)
from spacedrums.data.metadata import METADATA_FILENAME, SessionKind, SessionMetadata
from spacedrums.data.validation import VERIFY_FILENAME
from spacedrums.geometry.impact import crossing_time as linear_crossing_time
from spacedrums.geometry.impact import segment_surface
from spacedrums.geometry.zones import Point, Zone, ZoneRegistry
from spacedrums.timing.logger import read_record_stream

RECORDS_DIRNAME = "records"
CONFIG_SNAPSHOT = "config.snapshot.yaml"
FRAMES_FILENAME = "frames.jsonl"


# ----------------------------------------------------------------------------- inputs


@dataclass(frozen=True)
class CrossingDiagnostic:
    """Both sub-frame estimates for one crossing (Task 07.4 input; not written to labels.jsonl)."""

    label_id: str
    hand_id: str
    zone_id: str
    t_linear: float
    t_quadratic: float | None
    frame_before: int
    frame_after: int
    inward_speed: float


@dataclass
class GenerateResult:
    session_id: str
    participant_id: str
    source_kind: SessionKind
    label_dir: Path
    labels: list[dict[str, Any]] = field(default_factory=list)
    label_set: dict[str, Any] = field(default_factory=dict)
    reference_headers: dict[str, dict[str, Any]] = field(default_factory=dict)
    reference_samples: dict[str, list[ReferenceSample]] = field(default_factory=dict)
    crossings: list[CrossingDiagnostic] = field(default_factory=list)
    written: tuple[Path, ...] = ()

    def by_class(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for rec in self.labels:
            out[rec["label_class"]] = out.get(rec["label_class"], 0) + 1
        return dict(sorted(out.items()))


def read_measurements(session_dir: Path) -> dict[HandId, list[Measurement]]:
    """Per-hand tip measurements from the recorded ``StickObservation`` stream.

    The smoother consumes the MEASUREMENTS, not the causal filter output: smoothing an already
    filtered signal would be a different estimator and would inherit the causal filter's lag.
    """
    path = session_dir / RECORDS_DIRNAME / "StickObservation.jsonl"
    _, records = read_record_stream(path)
    out: dict[HandId, list[Measurement]] = {HandId.LEFT: [], HandId.RIGHT: []}
    for rec in records:
        hand = HandId(rec["hand_id"])
        tip = rec.get("tip")
        present = bool(rec.get("present")) and tip is not None
        out[hand].append(
            Measurement(
                frame_id=int(rec["frame_id"]),
                t=float(rec["t_capture"]),
                p=(float(tip[0]), float(tip[1])) if present else None,
                confidence=float(rec.get("tip_confidence") or 0.0),
            )
        )
    for hand in out:
        out[hand].sort(key=lambda m: (m.t, m.frame_id))
    return out


def read_causal(session_dir: Path) -> tuple[str, dict[tuple[int, str], str], dict[str, Any]]:
    """(tracker_id, {(frame_id, hand): status}, stream header) of the causal ``TrackState`` stream."""
    path = session_dir / RECORDS_DIRNAME / "TrackState.jsonl"
    header, records = read_record_stream(path)
    status: dict[tuple[int, str], str] = {}
    tracker_id = ""
    for rec in records:
        status[(int(rec["frame_id"]), str(rec["hand_id"]))] = str(rec["status"])
        tracker_id = tracker_id or str(rec.get("tracker_id", ""))
    return tracker_id or "unknown-tracker", status, header


def read_runtime_events(session_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Recorded ``StrikeCandidate`` and ``CommittedStrike`` records (runtime signals, not labels)."""
    out: list[list[dict[str, Any]]] = []
    for name in ("StrikeCandidate.jsonl", "CommittedStrike.jsonl"):
        path = session_dir / RECORDS_DIRNAME / name
        out.append(read_record_stream(path)[1] if path.exists() else [])
    return out[0], out[1]


def read_quarantine(session_dir: Path) -> tuple[dict[tuple[str, int], str], str | None]:
    """({(segment_id, take): exclusion_id}, session-level exclusion id) from ``verify.json``."""
    path = session_dir / VERIFY_FILENAME
    if not path.exists():
        return {}, None
    doc = json.loads(path.read_text(encoding="utf-8"))
    segments: dict[tuple[str, int], str] = {}
    session_level: str | None = None
    for exc in doc.get("exclusions", []):
        if exc.get("status") != "QUARANTINED":
            continue
        if exc.get("level") == "SEGMENT" and exc.get("segment_id"):
            segments[(str(exc["segment_id"]), int(exc.get("take") or 1))] = str(exc["exclusion_id"])
        else:
            session_level = str(exc["exclusion_id"])
    return segments, session_level


def count_frames(session_dir: Path) -> int:
    """Number of recorded frames. ``frames.jsonl`` carries no stream header (it is written beside the
    raw video and is authoritative, ``contracts.md`` section 4), so its lines are counted directly."""
    path = session_dir / FRAMES_FILENAME
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


# ----------------------------------------------------------------------------- geometry scan


@dataclass(frozen=True)
class _Crossing:
    kind: str  # ENTRY | EXIT
    index: int  # index of the sample before the crossing
    t_linear: float
    t_quadratic: float | None
    position: Point
    velocity: Point
    inward: float


def _signed_distances(samples: Sequence[ReferenceSample], zone: Zone) -> list[float]:
    return [signed_distance_to_surface(zone, s.p) for s in samples]


def _scan_crossings(
    samples: Sequence[ReferenceSample], zone: Zone, distances: Sequence[float]
) -> list[_Crossing]:
    """Every crossing of the zone's IMPACT SURFACE, in both directions, with both sub-frame estimates.

    This is the Phase 04 entry test with its ``v_min`` filter lifted out: the geometric predicate
    (containment change plus an intersection with the impact surface, not with another part of the
    boundary) is identical to ``geometry.first_impact``; the speed threshold is applied afterwards
    by ``rules.classify`` so that a too-slow entry becomes an explicit negative instead of silence.
    """
    times = [s.t for s in samples]
    out: list[_Crossing] = []
    for i in range(len(samples) - 1):
        a, b = samples[i], samples[i + 1]
        dt = b.t - a.t
        if dt <= 0:
            raise ValueError("reference samples must be strictly increasing in time")
        inside_a = zone.shape.contains(a.p)
        inside_b = zone.shape.contains(b.p, include_boundary=False)
        if inside_a == inside_b:
            continue
        crossing = segment_surface(a.p, b.p, zone.impact_surface)
        if crossing is None or crossing.s <= 1e-9:
            continue  # entered or left through a non-impact boundary: no candidate (Phase 04)
        velocity = ((b.p[0] - a.p[0]) / dt, (b.p[1] - a.p[1]) / dt)
        t_lin = linear_crossing_time(a.t, b.t, crossing.s)
        quad = interp.quadratic_crossing(times, distances, bracket=(i, i + 1)) if not inside_a else None
        out.append(
            _Crossing(
                kind="ENTRY" if not inside_a else "EXIT",
                index=i,
                t_linear=t_lin,
                t_quadratic=None if quad is None else quad.t_cross,
                position=crossing.point,
                velocity=velocity,
                inward=inward_speed(zone, velocity),
            )
        )
    return out


@dataclass(frozen=True)
class _Approach:
    i_start: int
    i_min: int
    i_end: int
    min_distance: float
    max_inward: float
    speed_at_min: float


def _scan_approaches(
    samples: Sequence[ReferenceSample],
    zone: Zone,
    distances: Sequence[float],
    thresholds: Thresholds,
    crossing_indices: set[int],
) -> list[_Approach]:
    """Approach episodes that never entered the zone (input to rules R3 / R4).

    An episode opens when the distance to the impact surface falls to ``near_zone_distance`` and
    closes when it rises above it again; an episode that contains a crossing is dropped, because
    the crossing event already describes it.
    """
    out: list[_Approach] = []
    i = 0
    n = len(samples)
    while i < n:
        if distances[i] > thresholds.near_zone_distance or distances[i] < 0:
            i += 1
            continue
        j = i
        while j + 1 < n and 0 <= distances[j + 1] <= thresholds.near_zone_distance:
            j += 1
        if not any(k in crossing_indices for k in range(max(0, i - 1), j + 1)):
            i_min = min(range(i, j + 1), key=lambda k: distances[k])
            t_min = samples[i_min].t
            window = [
                k for k in range(0, i_min + 1)
                if samples[k].t >= t_min - thresholds.approach_window_s
            ]
            max_inward = max((inward_speed(zone, samples[k].v) for k in window), default=0.0)
            out.append(
                _Approach(
                    i_start=i,
                    i_min=i_min,
                    i_end=j,
                    min_distance=float(distances[i_min]),
                    max_inward=float(max_inward),
                    speed_at_min=float(speed(samples[i_min])),
                )
            )
        i = j + 1
    return out


def _window_quality(
    samples: Sequence[ReferenceSample],
    t: float,
    thresholds: Thresholds,
    losses: Sequence[LossInterval],
) -> tuple[int, int, int, float, bool, float]:
    """(n_samples, n_valid, n_degraded, gap_max_s, interpolated, mean_quality) around ``t``."""
    lo, hi = t - thresholds.event_window_s, t + thresholds.event_window_s
    window = [s for s in samples if lo <= s.t <= hi]
    n = len(window)
    n_interp = sum(1 for s in window if s.interpolated)
    gaps = [b.t - a.t for a, b in zip(window, window[1:], strict=False)]
    gap_max = max(gaps) if gaps else 0.0
    touches_loss = any(not (li.t_end < lo or li.t_start > hi) for li in losses)
    mean_q = sum(s.quality for s in window) / n if n else 0.0
    return n, n - n_interp, n_interp, float(gap_max), bool(n_interp or touches_loss), float(mean_q)


# ----------------------------------------------------------------------------- generator


def _segment_at(meta: SessionMetadata, t: float) -> dict[str, Any] | None:
    for seg in meta.data["segments"]:
        end = seg["t_end"]
        if seg["t_start"] <= t and (end is None or t < end):
            return seg
    return None


def _frames_around(samples: Sequence[ReferenceSample], t: float) -> tuple[int, int]:
    before = samples[0].frame_id
    after = samples[-1].frame_id
    for a, b in zip(samples, samples[1:], strict=False):
        if a.t <= t <= b.t:
            return int(a.frame_id), int(b.frame_id)
    return int(before), int(after)


def _nearest_runtime(
    candidates: Sequence[dict[str, Any]], hand: str, zone_id: str, t: float, window_s: float
) -> dict[str, Any] | None:
    best, best_dt = None, window_s
    for c in candidates:
        if c["hand_id"] != hand or c["zone_id"] != zone_id:
            continue
        tc = c.get("t_impact_est") if c.get("t_impact_est") is not None else c.get("t_impact_pred")
        if tc is None:
            continue
        dt = abs(float(tc) - t)
        if dt <= best_dt:
            best, best_dt = c, dt
    return best


class LabelGenerator:
    """Generate the label set of one recorded session (Task 07.3)."""

    def __init__(
        self,
        *,
        dataset_version: str,
        thresholds: Thresholds | None = None,
        smoother: ReferenceSmoother | None = None,
        interpolation: Interpolation | str = Interpolation.QUADRATIC,
        labels_version: str = LABELS_VERSION,
        git_sha: str = "0" * 40,
        runtime_match_window_s: float = 0.25,
    ) -> None:
        dataset_kind(dataset_version)  # raises on an unknown version pattern
        self.dataset_version = dataset_version
        self.thresholds = thresholds or Thresholds()
        self.smoother = smoother or ReferenceSmoother()
        self.interpolation = Interpolation(interpolation)
        self.labels_version = labels_version
        self.git_sha = git_sha
        self.runtime_match_window_s = float(runtime_match_window_s)

    # -- main ------------------------------------------------------------------------------

    def generate(
        self,
        session_dir: str | Path,
        out_root: str | Path,
        *,
        write: bool = True,
        generated_at: str | None = None,
    ) -> GenerateResult:
        session_dir = Path(session_dir)
        meta = SessionMetadata.read(session_dir)
        errs = meta.errors()
        if errs:
            raise ValueError(f"{session_dir}: session metadata invalid: {errs[0]}")
        why = admissible_source(self.dataset_version, meta.kind)
        if why:
            raise ValueError(f"{session_dir}: {why}")

        cfg = load_config(session_dir / CONFIG_SNAPSHOT)
        registry = ZoneRegistry.from_config(cfg["zones"])
        v_min = float(cfg.data.get("geometry", {}).get("v_min", 0.0))
        thresholds = self.thresholds.with_v_min(v_min)

        measurements = read_measurements(session_dir)
        tracker_id, causal_status, _ = read_causal(session_dir)
        candidates, commits = read_runtime_events(session_dir)
        quarantined_segments, session_exclusion = read_quarantine(session_dir)

        label_dir = Path(out_root) / meta.session_id
        provenance = self._provenance(session_dir, meta, cfg, thresholds, tracker_id)

        result = GenerateResult(
            session_id=meta.session_id,
            participant_id=meta.data["participant_id"],
            source_kind=meta.kind,
            label_dir=label_dir,
        )
        counter = {str(c): 0 for c in LabelClass}

        def new_id(cls: LabelClass, hand: HandId) -> str:
            counter[str(cls)] += 1
            return make_label_id(meta.session_id, hand, cls, counter[str(cls)])

        for hand in (HandId.LEFT, HandId.RIGHT):
            smoothed = self.smoother.smooth(measurements[hand])
            samples = list(smoothed.samples)
            result.reference_samples[str(hand)] = samples
            result.reference_headers[str(hand)] = self._reference_header(
                meta, hand, smoothed, provenance
            )
            if not samples:
                continue
            entry_episodes: dict[str, int] = {}
            for zone in registry:
                if hand not in zone.allowed_hands:
                    continue
                distances = _signed_distances(samples, zone)
                crossings = _scan_crossings(samples, zone, distances)
                crossing_idx = {c.index for c in crossings}
                last_entry_labelled = False
                for cr in crossings:
                    t_event = (
                        cr.t_linear
                        if self.interpolation is Interpolation.LINEAR or cr.t_quadratic is None
                        else cr.t_quadratic
                    )
                    n, n_valid, n_deg, gap_max, interpolated, mean_q = _window_quality(
                        samples, t_event, thresholds, smoothed.loss_intervals
                    )
                    valid_fraction = n_valid / n if n else 0.0
                    seg = _segment_at(meta, t_event)
                    exclusion = self._exclusion_for(seg, quarantined_segments, session_exclusion)
                    evidence = EventEvidence(
                        direction=cr.kind,
                        inward_speed=cr.inward,
                        min_distance=0.0,
                        max_inward_speed=cr.inward,
                        speed_at_min_distance=math.hypot(*cr.velocity),
                        valid_fraction=valid_fraction,
                        mean_quality=mean_q,
                        interpolated=interpolated,
                        in_quarantine=exclusion is not None,
                        recovery_of_entry=last_entry_labelled,
                    )
                    verdict = self._classify(evidence, thresholds)
                    if cr.kind == "ENTRY":
                        last_entry_labelled = verdict is not None
                    else:
                        last_entry_labelled = False
                    if verdict is None:
                        continue
                    cls, rule_id = verdict
                    if cr.kind == "ENTRY":
                        entry_episodes[zone.zone_id] = entry_episodes.get(zone.zone_id, 0) + 1
                        episode_id = (
                            f"{meta.session_id}-{hand}-{zone.zone_id}-e"
                            f"{entry_episodes[zone.zone_id]:06d}"
                        )
                    else:
                        episode_id = None
                    lid = new_id(cls, hand)
                    result.crossings.append(
                        CrossingDiagnostic(
                            label_id=lid,
                            hand_id=str(hand),
                            zone_id=zone.zone_id,
                            t_linear=cr.t_linear,
                            t_quadratic=cr.t_quadratic,
                            frame_before=samples[cr.index].frame_id,
                            frame_after=samples[cr.index + 1].frame_id,
                            inward_speed=cr.inward,
                        )
                    )
                    result.labels.append(
                        self._event_record(
                            label_id=lid,
                            meta=meta,
                            provenance=provenance,
                            hand=hand,
                            zone=zone,
                            cls=cls,
                            rule_id=rule_id,
                            t_event=t_event,
                            samples=samples,
                            crossing=cr,
                            evidence=evidence,
                            quality=(n, n_valid, n_deg, gap_max, interpolated, mean_q),
                            segment=seg,
                            episode_id=episode_id,
                            exclusion=exclusion,
                            thresholds=thresholds,
                            causal_status=causal_status,
                            candidates=candidates,
                            commits=commits,
                        )
                    )
                for ap in _scan_approaches(samples, zone, distances, thresholds, crossing_idx):
                    t_event = samples[ap.i_min].t
                    n, n_valid, n_deg, gap_max, interpolated, mean_q = _window_quality(
                        samples, t_event, thresholds, smoothed.loss_intervals
                    )
                    seg = _segment_at(meta, t_event)
                    exclusion = self._exclusion_for(seg, quarantined_segments, session_exclusion)
                    evidence = EventEvidence(
                        direction="APPROACH",
                        inward_speed=inward_speed(zone, samples[ap.i_min].v),
                        min_distance=ap.min_distance,
                        max_inward_speed=ap.max_inward,
                        speed_at_min_distance=ap.speed_at_min,
                        valid_fraction=n_valid / n if n else 0.0,
                        mean_quality=mean_q,
                        interpolated=interpolated,
                        in_quarantine=exclusion is not None,
                    )
                    verdict = self._classify(evidence, thresholds)
                    if verdict is None:
                        continue
                    cls, rule_id = verdict
                    result.labels.append(
                        self._event_record(
                            label_id=new_id(cls, hand),
                            meta=meta,
                            provenance=provenance,
                            hand=hand,
                            zone=zone,
                            cls=cls,
                            rule_id=rule_id,
                            t_event=t_event,
                            samples=samples,
                            crossing=None,
                            evidence=evidence,
                            quality=(n, n_valid, n_deg, gap_max, interpolated, mean_q),
                            segment=seg,
                            episode_id=None,
                            exclusion=exclusion,
                            thresholds=thresholds,
                            causal_status=causal_status,
                            candidates=candidates,
                            commits=commits,
                        )
                    )
            result.labels += self._interval_records(
                meta=meta,
                provenance=provenance,
                hand=hand,
                samples=samples,
                losses=smoothed.loss_intervals,
                registry=registry,
                thresholds=thresholds,
                quarantined=quarantined_segments,
                session_exclusion=session_exclusion,
                new_id=new_id,
            )

        result.labels.sort(key=lambda r: (r["t_start"] if r["t_event"] is None else r["t_event"],
                                          r["hand_id"], r["label_class"], r["label_id"]))
        for rec in result.labels:
            errs = validate_label(rec)
            if errs:
                raise ValueError(f"generated label {rec['label_id']} is invalid: {errs[0]}")
        result.label_set = self._label_set(
            meta=meta,
            session_dir=session_dir,
            provenance=provenance,
            labels=result.labels,
            label_dir=label_dir,
            generated_at=generated_at,
        )
        if write:
            self._write_all(result, session_dir, label_dir)
        return result

    def _write_all(self, result: GenerateResult, session_dir: Path, label_dir: Path) -> None:
        """Write both trajectories, the labels and the label-set document, in that order.

        The label set is written last because it hashes the files that precede it, so a truncated
        run leaves no self-consistent label set behind.
        """
        written = list(self._write(result, label_dir))
        written.append(copy_causal_track(session_dir, label_dir))
        result.label_set["files"] = self._file_entries(label_dir)
        result.label_set["set_hash"] = label_set_hash(result.label_set)
        errs = validate_label_set(result.label_set)
        if errs:
            raise ValueError(f"label set invalid: {errs[0]}")
        meta_path = label_dir / LABEL_SET_FILENAME
        meta_path.write_text(
            json.dumps(result.label_set, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        written.append(meta_path)
        result.written = tuple(written)

    # -- pieces ----------------------------------------------------------------------------

    @staticmethod
    def _classify(evidence: EventEvidence, thresholds: Thresholds) -> tuple[LabelClass, str] | None:
        return classify(evidence, thresholds)

    @staticmethod
    def _exclusion_for(
        segment: dict[str, Any] | None,
        quarantined: dict[tuple[str, int], str],
        session_exclusion: str | None,
    ) -> str | None:
        if session_exclusion:
            return session_exclusion
        if segment is None:
            return None
        return quarantined.get((str(segment["segment_id"]), int(segment.get("take") or 1)))

    def _provenance(
        self,
        session_dir: Path,
        meta: SessionMetadata,
        cfg: Any,
        thresholds: Thresholds,
        tracker_id: str,
    ) -> Provenance:
        return Provenance(
            rules_version=RULES_VERSION,
            rules_hash=rules_hash(),
            thresholds_hash=thresholds.thresholds_hash,
            smoother_id=self.smoother.smoother_id,
            smoother_hash=self.smoother.smoother_hash,
            tracker_id=tracker_id,
            # The hash identifies the TRACKER, not the commit the session was recorded on: the
            # Phase 03 tracker_id already encodes the filter type and every one of its parameters
            # (ADR-0016), and that is the "frozen tracker version" Task 07.2 pins. Folding the
            # session's git_sha in here would make two sessions recorded on different commits
            # incompatible inside one dataset even when they used the identical tracker. The
            # recording commit stays where it belongs, in SessionMetadata and the raw manifest.
            tracker_hash=sha256_obj({"tracker_id": tracker_id}),
            geometry_version=GEOMETRY_VERSION,
            zone_layout_id=meta.data["zone_layout_id"],
            v_min=thresholds.v_min,
            interpolation=str(self.interpolation),
            config_hash=cfg.config_hash,
            git_sha=self.git_sha,
            reference_track_ref=REFERENCE_TRACK_FILENAME,
            causal_track_ref=CAUSAL_TRACK_FILENAME,
            session_metadata_sha256=sha256_file(session_dir / METADATA_FILENAME),
            generator=dict(GENERATOR),
        )

    def _reference_header(
        self, meta: SessionMetadata, hand: HandId, smoothed: Any, provenance: Provenance
    ) -> dict[str, Any]:
        header = {
            "schema_version": REFERENCE_TRACK_SCHEMA_VERSION,
            "kind": "ReferenceTrack",
            "causal": False,
            "labels_version": self.labels_version,
            "dataset_version": self.dataset_version,
            "source_kind": str(meta.kind),
            "session_id": meta.session_id,
            "participant_id": meta.data["participant_id"],
            "hand_id": str(hand),
            "method_id": self.smoother.smoother_id,
            "method_params": dict(self.smoother.params),
            "units": {"time": "s", "clock": "t_mono", "position": "roi_norm",
                      "velocity": "roi_norm_per_s"},
            "source_stream": f"{RECORDS_DIRNAME}/StickObservation.jsonl",
            "gap_policy": {
                "max_gap_s": self.smoother.max_gap_s,
                "interpolate_below_bound": True,
                "loss_intervals": [li.to_dict() for li in smoothed.loss_intervals],
            },
            "n_samples": len(smoothed.samples),
            "config_hash": provenance.config_hash,
            "git_sha": provenance.git_sha,
            "clock_id": meta.data["clock_id"],
            "generator": dict(GENERATOR),
            "label": REFERENCE_TRACK_BANNER,
        }
        errs = validate_reference_header(header)
        if errs:
            raise ValueError(f"reference-track header invalid: {errs[0]}")
        return header

    def _event_record(
        self,
        *,
        label_id: str,
        meta: SessionMetadata,
        provenance: Provenance,
        hand: HandId,
        zone: Zone,
        cls: LabelClass,
        rule_id: str,
        t_event: float,
        samples: Sequence[ReferenceSample],
        crossing: _Crossing | None,
        evidence: EventEvidence,
        quality: tuple[int, int, int, float, bool, float],
        segment: dict[str, Any] | None,
        episode_id: str | None,
        exclusion: str | None,
        thresholds: Thresholds,
        causal_status: dict[tuple[int, str], str],
        candidates: Sequence[dict[str, Any]],
        commits: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        n, n_valid, n_deg, gap_max, interpolated, mean_q = quality
        before, after = _frames_around(samples, t_event)
        at = resample(samples, t_event)
        is_impact = cls in (LabelClass.POSITIVE, LabelClass.AMBIGUOUS, LabelClass.EXCLUDED)
        crossed = crossing is not None and crossing.kind == "ENTRY"
        t_impact_est = t_event if (crossed and is_impact) else None
        position = list(crossing.position) if crossing is not None else (
            list(at.p) if at is not None else None
        )
        velocity = list(crossing.velocity) if crossing is not None else (
            list(at.v) if at is not None else None
        )
        intensity = (
            intensity_proxy_gt(zone, tuple(velocity)) if (t_impact_est is not None and velocity) else None
        )
        pre = [s for s in samples if t_event - thresholds.intensity_window_s <= s.t <= t_event]
        secondary = {
            "window_s": thresholds.intensity_window_s,
            "peak_speed_pre": max((speed(s) for s in pre), default=None),
            "peak_inward_speed_pre": max((inward_speed(zone, s.v) for s in pre), default=None),
        }
        cand = _nearest_runtime(candidates, str(hand), zone.zone_id, t_event, self.runtime_match_window_s)
        commit = None
        if cand is not None:
            commit = next((c for c in commits if c.get("candidate_id") == cand.get("candidate_id")), None)
        notes = ""
        if cls is LabelClass.EXCLUDED:
            inner = self._classify(
                EventEvidence(
                    direction=evidence.direction,
                    inward_speed=evidence.inward_speed,
                    min_distance=evidence.min_distance,
                    max_inward_speed=evidence.max_inward_speed,
                    speed_at_min_distance=evidence.speed_at_min_distance,
                    valid_fraction=evidence.valid_fraction,
                    mean_quality=evidence.mean_quality,
                    interpolated=evidence.interpolated,
                    in_quarantine=False,
                    recovery_of_entry=evidence.recovery_of_entry,
                ),
                thresholds,
            )
            notes = (
                "quarantined segment; class before exclusion: "
                f"{inner[0] if inner else 'none'} ({inner[1] if inner else '-'})"
            )
        record = {
            "schema_version": LABEL_RECORD_SCHEMA_VERSION,
            "label_id": label_id,
            "labels_version": self.labels_version,
            "dataset_version": self.dataset_version,
            "source_kind": str(meta.kind),
            "session_id": meta.session_id,
            "participant_id": meta.data["participant_id"],
            "segment_id": None if segment is None else str(segment["segment_id"]),
            "segment_take": None if segment is None else int(segment.get("take") or 1),
            "segment_type": None if segment is None else str(segment["type"]),
            "episode_id": episode_id,
            "hand_id": str(hand),
            "label_class": str(cls),
            "level": str(Level.EVENT),
            "zone_id": zone.zone_id,
            "t_event": float(t_event),
            "t_start": None,
            "t_end": None,
            "t_impact_est": None if t_impact_est is None else float(t_impact_est),
            "frames": {
                "first_frame_id": int(samples[0].frame_id),
                "last_frame_id": int(samples[-1].frame_id),
                "before_event": int(before),
                "after_event": int(after),
            },
            "impact_position": position,
            "crossing_velocity": velocity,
            "intensity_proxy_gt": None if intensity is None else float(intensity),
            "intensity_secondary": secondary,
            "approach": {
                "min_distance_to_surface": float(evidence.min_distance),
                "max_inward_speed": float(evidence.max_inward_speed),
                "speed_at_min_distance": float(evidence.speed_at_min_distance),
            },
            "confidence": label_confidence(mean_q, n_valid / n if n else 0.0),
            "reference_quality": {
                "n_samples": int(n),
                "n_valid": int(n_valid),
                "n_degraded": int(n_deg),
                "gap_max_s": float(gap_max),
                "interpolated": bool(interpolated),
            },
            "t_impact_phys": None,
            "phys": None,
            "label_rule_id": rule_id,
            "qc_status": str(QCStatus.PENDING_REVIEW),
            "labeller_id": f"generator:{self.labels_version}",
            "review": empty_review(),
            "runtime_reference": runtime_reference(
                causal_status=causal_status.get((before, str(hand))),
                causal_t_impact_est=None if cand is None else cand.get("t_impact_est"),
                candidate_id=None if cand is None else cand.get("candidate_id"),
                strike_id=None if commit is None else commit.get("strike_id"),
                arm=None if commit is None else commit.get("arm"),
            ),
            "causal": False,
            "provenance": provenance.to_dict(),
            "excluded": exclusion is not None,
            "exclusion_ref": exclusion,
            "notes": notes,
        }
        return record

    def _interval_records(
        self,
        *,
        meta: SessionMetadata,
        provenance: Provenance,
        hand: HandId,
        samples: Sequence[ReferenceSample],
        losses: Sequence[LossInterval],
        registry: ZoneRegistry,
        thresholds: Thresholds,
        quarantined: dict[tuple[str, int], str],
        session_exclusion: str | None,
        new_id: Any,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []

        def interval(
            cls: LabelClass, rule_id: str, t0: float, t1: float, f0: int, f1: int, zone_id: str | None
        ) -> dict[str, Any]:
            seg = _segment_at(meta, t0)
            exclusion = self._exclusion_for(seg, quarantined, session_exclusion)
            if exclusion is not None:
                cls, rule_id = LabelClass.EXCLUDED, "P07-R11"
            window = [s for s in samples if t0 <= s.t <= t1]
            n = len(window)
            n_valid = sum(1 for s in window if not s.interpolated)
            mean_q = sum(s.quality for s in window) / n if n else 0.0
            return {
                "schema_version": LABEL_RECORD_SCHEMA_VERSION,
                "label_id": new_id(cls, hand),
                "labels_version": self.labels_version,
                "dataset_version": self.dataset_version,
                "source_kind": str(meta.kind),
                "session_id": meta.session_id,
                "participant_id": meta.data["participant_id"],
                "segment_id": None if seg is None else str(seg["segment_id"]),
                "segment_take": None if seg is None else int(seg.get("take") or 1),
                "segment_type": None if seg is None else str(seg["type"]),
                "episode_id": None,
                "hand_id": str(hand),
                "label_class": str(cls),
                "level": str(Level.INTERVAL),
                "zone_id": zone_id,
                "t_event": None,
                "t_start": float(t0),
                "t_end": float(t1),
                "t_impact_est": None,
                "frames": {
                    "first_frame_id": int(f0),
                    "last_frame_id": int(f1),
                    "before_event": None,
                    "after_event": None,
                },
                "impact_position": None,
                "crossing_velocity": None,
                "intensity_proxy_gt": None,
                "intensity_secondary": {"window_s": None, "peak_speed_pre": None,
                                        "peak_inward_speed_pre": None},
                "approach": {"min_distance_to_surface": None, "max_inward_speed": None,
                             "speed_at_min_distance": None},
                "confidence": label_confidence(mean_q, n_valid / n if n else 0.0),
                "reference_quality": {
                    "n_samples": int(n),
                    "n_valid": int(n_valid),
                    "n_degraded": int(n - n_valid),
                    "gap_max_s": 0.0,
                    "interpolated": bool(n - n_valid),
                },
                "t_impact_phys": None,
                "phys": None,
                "label_rule_id": rule_id,
                "qc_status": str(QCStatus.PENDING_REVIEW),
                "labeller_id": f"generator:{self.labels_version}",
                "review": empty_review(),
                "runtime_reference": runtime_reference(),
                "causal": False,
                "provenance": provenance.to_dict(),
                "excluded": exclusion is not None,
                "exclusion_ref": exclusion,
                "notes": "",
            }

        for li in losses:
            out.append(
                interval(LabelClass.NEG_TRACKING_LOSS, "P07-R8", li.t_start, li.t_end,
                         li.first_frame_id, li.last_frame_id, None)
            )
        entries = self._entry_times(samples, registry, hand)
        for seg in meta.data["segments"]:
            t0, t1 = float(seg["t_start"]), seg["t_end"]
            if t1 is None:
                continue
            t1 = float(t1)
            if t1 - t0 < thresholds.no_strike_min_s:
                continue
            window = [s for s in samples if t0 <= s.t < t1]
            if len(window) < 2 or any(t0 <= t < t1 for t in entries):
                continue
            mean_speed = sum(speed(s) for s in window) / len(window)
            if mean_speed < thresholds.motion_min_speed:
                continue
            out.append(
                interval(LabelClass.NEG_NO_STRIKE_MOTION, "P07-R9", window[0].t, window[-1].t,
                         window[0].frame_id, window[-1].frame_id, None)
            )
        out += [
            interval(LabelClass.NEG_BETWEEN_ZONES, "P07-R10", a_t, b_t, a_f, b_f, None)
            for a_t, b_t, a_f, b_f in self._between_zone_intervals(
                samples, registry, hand, thresholds, entries
            )
        ]
        return out

    @staticmethod
    def _entry_times(
        samples: Sequence[ReferenceSample], registry: ZoneRegistry, hand: HandId
    ) -> list[float]:
        out: list[float] = []
        for zone in registry:
            if hand not in zone.allowed_hands:
                continue
            distances = _signed_distances(samples, zone)
            out += [c.t_linear for c in _scan_crossings(samples, zone, distances) if c.kind == "ENTRY"]
        return sorted(out)

    @staticmethod
    def _between_zone_intervals(
        samples: Sequence[ReferenceSample],
        registry: ZoneRegistry,
        hand: HandId,
        thresholds: Thresholds,
        entry_times: Sequence[float],
    ) -> list[tuple[float, float, int, int]]:
        """Maximal intervals from 'near zone A' to 'near zone B != A' without any entry in between."""
        zones = [z for z in registry if hand in z.allowed_hands]
        if len(zones) < 2:
            return []
        near: list[str | None] = []
        for s in samples:
            best, best_d = None, thresholds.near_zone_distance
            for z in zones:
                d = distance_to_surface(z, s.p)
                if d <= best_d:
                    best, best_d = z.zone_id, d
            near.append(best)
        out: list[tuple[float, float, int, int]] = []
        last_zone_idx: int | None = None
        for i, z in enumerate(near):
            if z is None:
                continue
            if last_zone_idx is not None and near[last_zone_idx] != z:
                t0, t1 = samples[last_zone_idx].t, samples[i].t
                if t1 - t0 >= thresholds.between_zones_min_s and not any(
                    t0 < t < t1 for t in entry_times
                ):
                    out.append((t0, t1, samples[last_zone_idx].frame_id, samples[i].frame_id))
            last_zone_idx = i
        return out

    # -- artefacts -------------------------------------------------------------------------

    def _label_set(
        self,
        *,
        meta: SessionMetadata,
        session_dir: Path,
        provenance: Provenance,
        labels: Sequence[dict[str, Any]],
        label_dir: Path,
        generated_at: str | None,
    ) -> dict[str, Any]:
        by_class: dict[str, int] = {}
        by_hand: dict[str, int] = {}
        by_zone: dict[str, int] = {}
        by_segment: dict[str, int] = {}
        for rec in labels:
            by_class[rec["label_class"]] = by_class.get(rec["label_class"], 0) + 1
            by_hand[rec["hand_id"]] = by_hand.get(rec["hand_id"], 0) + 1
            if rec["zone_id"]:
                by_zone[rec["zone_id"]] = by_zone.get(rec["zone_id"], 0) + 1
            key = rec["segment_type"] or "NO_SEGMENT"
            by_segment[key] = by_segment.get(key, 0) + 1
        streams = []
        for name in ("StickObservation.jsonl", "TrackState.jsonl", "StrikeCandidate.jsonl",
                     "CommittedStrike.jsonl"):
            p = session_dir / RECORDS_DIRNAME / name
            if p.exists():
                streams.append(
                    {
                        "path": f"{RECORDS_DIRNAME}/{name}",
                        "sha256": sha256_file(p),
                        "records": len(read_record_stream(p)[1]),
                    }
                )
        quarantined, session_exclusion = read_quarantine(session_dir)
        doc = {
            "schema_version": LABEL_SET_SCHEMA_VERSION,
            "labels_version": self.labels_version,
            "dataset_version": self.dataset_version,
            "source_kind": str(meta.kind),
            "session_id": meta.session_id,
            "participant_id": meta.data["participant_id"],
            "generated_at": generated_at or timing.wall_clock_iso(),
            "provenance": provenance.to_dict(),
            "inputs": {
                "session_dir": session_dir.as_posix(),
                "n_frames": count_frames(session_dir),
                "n_segments": len(meta.data["segments"]),
                "n_quarantined_segments": len(quarantined) + (1 if session_exclusion else 0),
                "streams": streams,
            },
            "counts": {
                "total": len(labels),
                "by_class": dict(sorted(by_class.items())),
                "by_hand": dict(sorted(by_hand.items())),
                "by_zone": dict(sorted(by_zone.items())),
                "by_segment_type": dict(sorted(by_segment.items())),
                "excluded": sum(1 for r in labels if r["excluded"]),
                "ambiguous": sum(1 for r in labels if r["label_class"] == str(LabelClass.AMBIGUOUS)),
                "label": "MEASURED from this session's labels; evidence class: "
                + evidence_label({meta.kind}),
            },
            "files": [],
            "qc": {
                "protocol_id": "P07-QC-1",
                "reviewed": 0,
                "accepted": 0,
                "rejected": 0,
                "adjusted": 0,
                "pending": len(labels),
                "second_pass": 0,
                "sampling": {"positives_rate": 0.0, "ambiguous_rate": 0.0, "negatives_rate": 0.0},
                "label": "NOT REVIEWED - generator output only; QC protocol P07-QC-1 not yet applied",
            },
            "phys": {
                "available": False,
                "reason": "no microphone track paired for this session (Task 07.6)",
                "n_pad_positives": sum(
                    1
                    for r in labels
                    if r["label_class"] == str(LabelClass.POSITIVE)
                    and r["segment_type"] == "PAD_MIC"
                ),
                "n_paired": 0,
                "residual_bias_s": None,
                "residual_iqr_s": None,
                "mic_latency_bound_s": None,
                "label": "PENDING - no acoustic ground truth (ADR-0002 condition not recorded)",
            },
            "notes": "",
            "label": DATASET_LABELS[dataset_kind(self.dataset_version)],
            "set_hash": "sha256:" + "0" * 64,
        }
        doc["set_hash"] = label_set_hash(doc)
        return doc

    def _write(self, result: GenerateResult, label_dir: Path) -> tuple[Path, ...]:
        label_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        labels_path = label_dir / LABELS_FILENAME
        with labels_path.open("w", encoding="utf-8", newline="\n") as fh:
            for rec in result.labels:
                fh.write(json.dumps(rec, allow_nan=False, sort_keys=True) + "\n")
        written.append(labels_path)
        ref_path = label_dir / REFERENCE_TRACK_FILENAME
        with ref_path.open("w", encoding="utf-8", newline="\n") as fh:
            for hand in sorted(result.reference_headers):
                fh.write(json.dumps(result.reference_headers[hand], allow_nan=False) + "\n")
                for s in result.reference_samples.get(hand, []):
                    line = {"hand_id": hand, **s.to_dict()}
                    errs = validate_reference_sample(line)
                    if errs:
                        raise ValueError(f"reference sample invalid: {errs[0]}")
                    fh.write(json.dumps(line, allow_nan=False) + "\n")
        written.append(ref_path)
        return tuple(written)

    @staticmethod
    def _file_entries(label_dir: Path) -> list[dict[str, Any]]:
        causal_map = {
            LABELS_FILENAME: False,
            REFERENCE_TRACK_FILENAME: False,
            CAUSAL_TRACK_FILENAME: True,
        }
        out = []
        for p in sorted(label_dir.rglob("*")):
            if not p.is_file() or p.name == LABEL_SET_FILENAME:
                continue
            rel = p.relative_to(label_dir).as_posix()
            out.append(
                {
                    "path": rel,
                    "bytes": p.stat().st_size,
                    "sha256": sha256_file(p),
                    "causal": causal_map.get(rel),
                }
            )
        return out


def copy_causal_track(session_dir: str | Path, label_dir: str | Path) -> Path:
    """Copy the session's causal ``TrackState`` stream into the label directory, unchanged.

    Both trajectories live side by side so a consumer can see which is which by name
    (Task 07.2 / acceptance criterion 2); the causal one keeps its original
    ``RecordStreamHeader`` and stays a valid record stream, the reference one cannot be one.
    """
    src = Path(session_dir) / RECORDS_DIRNAME / "TrackState.jsonl"
    dst = Path(label_dir) / CAUSAL_TRACK_FILENAME
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8", newline="")
    return dst


def generate_labels(
    session_dir: str | Path,
    out_root: str | Path,
    *,
    dataset_version: str,
    thresholds: Thresholds | None = None,
    smoother: ReferenceSmoother | None = None,
    interpolation: Interpolation | str = Interpolation.QUADRATIC,
    labels_version: str = LABELS_VERSION,
    git_sha: str = "0" * 40,
    generated_at: str | None = None,
    write: bool = True,
) -> GenerateResult:
    """Generate (and by default write) the label set of one session."""
    gen = LabelGenerator(
        dataset_version=dataset_version,
        thresholds=thresholds,
        smoother=smoother,
        interpolation=interpolation,
        labels_version=labels_version,
        git_sha=git_sha,
    )
    return gen.generate(session_dir, out_root, write=write, generated_at=generated_at)


def read_labels(path: str | Path) -> list[dict[str, Any]]:
    """Read a ``labels.jsonl`` file (no stream header: labels are not a record stream)."""
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def read_reference_track(
    path: str | Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[ReferenceSample]]]:
    """Parse ``tracks_reference.jsonl`` into (headers by hand, samples by hand).

    The file interleaves one header line per hand with that hand's samples; a line with ``kind ==
    "ReferenceTrack"`` opens a new hand. It is deliberately *not* a record stream: a
    ``RecordStreamHeader`` cannot name a label artefact, so this reader is the only way in.
    """
    headers: dict[str, dict[str, Any]] = {}
    samples: dict[str, list[ReferenceSample]] = {}
    current = ""
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        doc = json.loads(line)
        if doc.get("kind") == "ReferenceTrack":
            current = str(doc["hand_id"])
            headers[current] = doc
            samples.setdefault(current, [])
            continue
        hand = str(doc["hand_id"])
        samples.setdefault(hand, []).append(
            ReferenceSample(
                frame_id=int(doc["frame_id"]),
                t=float(doc["t"]),
                p=(float(doc["p"][0]), float(doc["p"][1])),
                v=(float(doc["v"][0]), float(doc["v"][1])),
                quality=float(doc["quality"]),
                interpolated=bool(doc["interpolated"]),
            )
        )
    return headers, samples


def read_label_set(path: str | Path) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    errs = validate_label_set(doc)
    if errs:
        raise ValueError(f"{path}: " + "; ".join(errs[:3]))
    return doc


__all__ = [
    "CONFIG_SNAPSHOT",
    "RECORDS_DIRNAME",
    "CrossingDiagnostic",
    "GenerateResult",
    "LabelGenerator",
    "copy_causal_track",
    "count_frames",
    "generate_labels",
    "read_causal",
    "read_label_set",
    "read_labels",
    "read_measurements",
    "read_quarantine",
    "read_reference_track",
    "read_runtime_events",
]
