"""Guided-protocol recorder (Phase 06, Task 06.1) — extends the Phase 05 record mode with segment
markers, on-screen cues, a post-segment quick check and the ``SessionMetadata`` document.

Layering: ``spacedrums.data`` sits below ``spacedrums.app`` (architecture.md section 2.2), so this
module never imports the application. It is a set of hooks the app loop calls (``on_frame``,
``on_key``, ``status_lines``, ``draw_cues``) — ``scripts/record_session.py`` composes them with
``spacedrums.app.main.run``; the pixels, streams and config snapshot are still written by the Phase 05
``SessionRecorder`` (raw video = lossless PNG sequence, ADR-0019), so the recorder uses the **same
causal pipeline** as the live application (phase document, Architecture).

Segment markers are placed on the **capture clock**: ``t_start`` / ``t_end`` are the ``t_capture`` of
the first frame in the segment and of the first frame after it (half-open interval on ``t_capture``),
so every frame belongs to at most one take and the assignment is reproducible from ``frames.jsonl``
alone. The post-segment quick check (frames, drops, FPS estimate from the frame timestamps, tracking
validity ratio per hand) is an *immediate* indication for the operator; the authoritative values are
recomputed from disk by ``verify_session``.

Keys (through ``on_key``): ``n`` next segment now, ``r`` re-take the current segment (the failed take
is kept and flagged RETAKEN), ``k`` skip the current segment, ``m`` place a CLAP sync marker at the
current frame (pad+mic condition), ``f`` record a fallback event. Nothing here records a person: the
person-dependent live mode is only reachable through the script's ``--live`` switch.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import cv2

from spacedrums.contracts import HandId, TrackStatus
from spacedrums.data.metadata import SessionMetadata
from spacedrums.data.protocol import Protocol, SegmentSpec, zone_name
from spacedrums.geometry import Ellipse, ZoneRegistry

HANDS = (HandId.LEFT, HandId.RIGHT)


@dataclass(frozen=True)
class QuickCheckThresholds:
    """Candidate thresholds for the post-segment quick check (the verify script owns the policy
    thresholds; these only decide whether the operator sees OK or REVIEW on screen)."""

    q_seg: float = 0.6  # candidate: minimum tracking validity ratio of the relevant hand(s)
    fps_tolerance: float = 0.15  # candidate: relative deviation of the FPS estimate from nominal
    nominal_fps: float | None = 30.0  # requested mode; MEASURED native FPS replaces it when cited
    max_drops: int = 5  # candidate: dropped frames per segment before REVIEW


@dataclass
class SegmentStats:
    """Running per-take statistics collected frame by frame."""

    n_frames: int = 0
    t_first: float | None = None
    t_last: float | None = None
    dropped: int = 0
    valid: dict[HandId, int] = field(default_factory=lambda: {h: 0 for h in HANDS})

    def add(self, t_capture: float, dropped_since_last: int, status: Mapping[HandId, TrackStatus]) -> None:
        self.n_frames += 1
        self.t_first = t_capture if self.t_first is None else self.t_first
        self.t_last = t_capture
        self.dropped += int(dropped_since_last)
        for h in HANDS:
            if status.get(h) is TrackStatus.VALID:
                self.valid[h] += 1

    def validity(self) -> dict[str, float | None]:
        return {str(h): (self.valid[h] / self.n_frames if self.n_frames else None) for h in HANDS}


def quick_check(stats: SegmentStats, spec: SegmentSpec, thresholds: QuickCheckThresholds) -> dict[str, Any]:
    """Immediate post-segment check (Task 06.1). ``fps_est`` = (n-1)/duration over delivered frames."""
    if stats.n_frames == 0:
        return {
            "n_frames": 0,
            "duration_s": 0.0,
            "fps_est": None,
            "dropped": stats.dropped,
            "tracking_validity": {"LEFT": None, "RIGHT": None},
            "verdict": "NO_FRAMES",
        }
    assert stats.t_first is not None and stats.t_last is not None
    duration = float(stats.t_last - stats.t_first)
    fps_est = (stats.n_frames - 1) / duration if duration > 0 and stats.n_frames > 1 else None
    validity = stats.validity()
    review = False
    for h in spec.hands:
        v = validity[str(h)]
        if v is None or v < thresholds.q_seg:
            review = True
    if stats.dropped > thresholds.max_drops:
        review = True
    if fps_est is not None and thresholds.nominal_fps:
        if abs(fps_est - thresholds.nominal_fps) / thresholds.nominal_fps > thresholds.fps_tolerance:
            review = True
    return {
        "n_frames": stats.n_frames,
        "duration_s": duration,
        "fps_est": fps_est,
        "dropped": stats.dropped,
        "tracking_validity": validity,
        "verdict": "REVIEW" if review else "OK",
    }


class GuidedRecorder:
    """Drives one session through a :class:`Protocol`, marks segments on ``t_capture`` and fills the
    :class:`SessionMetadata`.

    ``on_frame(sample, result)`` must be called for every frame the pipeline processed (``result``
    needs ``hands[h].track.status``); it returns ``False`` once the protocol is complete. The cue for
    the operator/participant comes from ``status_lines()`` and ``draw_cues()``.
    """

    KEYS = {"n": "next", "r": "retake", "k": "skip", "m": "sync_marker", "f": "fallback"}

    def __init__(
        self,
        protocol: Protocol,
        metadata: SessionMetadata,
        *,
        thresholds: QuickCheckThresholds | None = None,
        enable_optional: bool = False,
        log: Callable[[str], None] | None = print,
    ) -> None:
        self.protocol = protocol
        self.meta = metadata
        self.thresholds = thresholds or QuickCheckThresholds()
        self.log = log or (lambda _s: None)
        self.queue: list[SegmentSpec] = [s for s in protocol.segments if enable_optional or not s.optional]
        self.index = -1
        self.current: dict[str, Any] | None = None
        self.stats = SegmentStats()
        self.t_deadline: float | None = None
        self.last_check: dict[str, Any] | None = None
        self.last_t: float | None = None
        self.done = False
        self.n_frames_total = 0
        self._pending: str | None = None  # key action to apply on the next frame

    # -- state -----------------------------------------------------------------------------
    @property
    def spec(self) -> SegmentSpec | None:
        return self.queue[self.index] if 0 <= self.index < len(self.queue) else None

    def _close_current(self, t_end: float, *, status: str | None = None) -> None:
        if self.current is None:
            return
        spec = self.spec
        assert spec is not None
        check = quick_check(self.stats, spec, self.thresholds)
        self.meta.close_segment(self.current, t_end, check)
        if status:
            self.current["status"] = status
        self.last_check = check
        self.log(
            f"[protocol] closed {spec.segment_id} take {self.current['take']}: {check['n_frames']} frames, "
            f"fps_est {check['fps_est'] if check['fps_est'] is None else round(check['fps_est'], 2)}, "
            f"dropped {check['dropped']}, validity {check['tracking_validity']} -> {check['verdict']}"
        )
        self.current = None

    def _open(self, spec: SegmentSpec, t: float) -> None:
        take = 1 + self.meta.takes_of(spec.segment_id)
        if take > 1:
            self.meta.mark_retaken(spec.segment_id)
        self.current = self.meta.open_segment(spec, t, take)
        self.stats = SegmentStats()
        self.t_deadline = t + spec.duration_s
        self.log(
            f"[protocol] segment {self.index + 1}/{len(self.queue)} {spec.segment_id} take {take}: {spec.cue}"
        )

    def _advance(self, t: float) -> bool:
        """Close the current take and open the next queued segment at ``t``; False when finished."""
        self._close_current(t)
        self.index += 1
        if self.index >= len(self.queue):
            self.done = True
            self.log("[protocol] finished")
            return False
        self._open(self.queue[self.index], t)
        return True

    # -- hooks -----------------------------------------------------------------------------
    def on_frame(self, sample: Any, result: Any) -> bool:
        t = float(sample.t_capture)
        self.last_t = t
        self.n_frames_total += 1
        if self.done:
            return False
        action, self._pending = self._pending, None
        if self.index < 0:
            if not self._advance(t):
                return False
        elif action == "next" or (self.t_deadline is not None and t >= self.t_deadline):
            if not self._advance(t):
                return False
        elif action == "retake":
            spec = self.spec
            assert spec is not None
            self._close_current(t)
            self._open(spec, t)
        elif action == "skip":
            spec = self.spec
            assert spec is not None
            self._close_current(t, status="SKIPPED")
            self.current = None
            self.index += 1
            if self.index >= len(self.queue):
                self.done = True
                return False
            self._open(self.queue[self.index], t)
        elif action == "sync_marker":
            seg_id = self.current["segment_id"] if self.current else None
            m = self.meta.add_sync_marker("CLAP", t, seg_id, "operator key m at this frame")
            self.log(f"[protocol] sync marker {m['marker_id']} at t_capture {t:.4f}")
        elif action == "fallback":
            self.meta.add_fallback_event(t, "OPERATOR", "operator key f")
        status = {h: TrackStatus(result.hands[h].track.status) for h in HANDS}
        self.stats.add(t, int(sample.dropped_since_last), status)
        return True

    def on_key(self, key: str) -> None:
        action = self.KEYS.get(key)
        if action is not None:
            self._pending = action

    def finish(self, t_end: float | None = None) -> None:
        """Close an open take. Without ``t_end`` the take ends one estimated frame period after the last
        frame's ``t_capture`` so that the last frame belongs to it (half-open rule)."""
        t = t_end
        if t is None and self.last_t is not None:
            st = self.stats
            dt = (
                (st.t_last - st.t_first) / (st.n_frames - 1)
                if st.n_frames > 1
                and st.t_first is not None
                and st.t_last is not None
                and st.t_last > st.t_first
                else 1.0 / 30.0
            )
            t = self.last_t + dt
        if self.current is not None:
            if t is None:
                self.current["status"] = "ABORTED"
                self.current = None
            else:
                self._close_current(float(t))
        self.done = True

    def status_lines(self) -> list[str]:
        spec = self.spec
        if spec is None or self.done:
            return ["protocol finished - press q"]
        remaining = max(0.0, (self.t_deadline or 0.0) - (self.last_t or 0.0))
        lines = [
            f"[{self.index + 1}/{len(self.queue)}] {spec.cue}",
            f"{remaining:4.1f} s left | n next  r retake  k skip  m sync  q quit",
        ]
        if self.last_check is not None:
            lines.append(
                f"last segment: {self.last_check['verdict']} (fps_est "
                f"{'n/a' if self.last_check['fps_est'] is None else round(self.last_check['fps_est'], 1)}, "
                f"validity {self.last_check['tracking_validity']})"
            )
        return lines

    def draw_cues(self, canvas: Any, registry: ZoneRegistry) -> None:
        """Highlight the cued zones and draw the countdown bar on the ROI (in place).

        ``canvas`` is a ``spacedrums.ui.Canvas`` over the ROI, mirrored in live windows (duck-typed:
        data never imports ui). Cues follow the zones; the countdown and metronome text are HUD
        anchored to the ROI and stay upright."""
        spec = self.spec
        if spec is None or self.done:
            return
        h, w = canvas.height, canvas.width
        for zid in spec.zone_ids:
            try:
                zone = registry[zid]
            except KeyError:
                continue
            if isinstance(zone.shape, Ellipse):
                c = (round(zone.shape.center[0] * (w - 1)), round(zone.shape.center[1] * (h - 1)))
                axes = (max(1, round(zone.shape.rx * w)) + 6, max(1, round(zone.shape.ry * h)) + 6)
                canvas.ellipse(
                    c,
                    axes,
                    math.degrees(zone.shape.angle_rad),
                    0,
                    360,
                    (0, 255, 255),
                    4,
                    cv2.LINE_AA,
                )
                canvas.put_text(
                    zone_name(zid),
                    (c[0] - 30, c[1] + 6),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 255),
                    2,
                    cv2.LINE_AA,
                )
        hud = canvas.upright(0, w)
        if self.t_deadline is not None and self.last_t is not None and spec.duration_s > 0:
            frac = min(1.0, max(0.0, (self.t_deadline - self.last_t) / spec.duration_s))
            hud.rectangle((8, h - 14), (w - 8, h - 6), (60, 60, 60), -1)
            hud.rectangle((8, h - 14), (8 + int((w - 16) * frac), h - 6), (0, 200, 255), -1)
        if spec.tempo_bpm:
            hud.put_text(
                f"metronome {spec.tempo_bpm} bpm",
                (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )


def segment_frame_ranges(
    segments: Sequence[Mapping[str, Any]], t_captures: Sequence[float]
) -> dict[tuple[str, int], tuple[int, int]]:
    """Map each closed take to the half-open index range of frames with ``t_start <= t_capture < t_end``
    (the same rule the recorder used); frames are assumed sorted by ``t_capture``."""
    out: dict[tuple[str, int], tuple[int, int]] = {}
    n = len(t_captures)
    for s in segments:
        if s.get("t_end") is None:
            continue
        t0, t1 = float(s["t_start"]), float(s["t_end"])
        lo = 0
        while lo < n and t_captures[lo] < t0:
            lo += 1
        hi = lo
        while hi < n and t_captures[hi] < t1:
            hi += 1
        out[(s["segment_id"], int(s.get("take", 1)))] = (lo, hi)
    return out


__all__ = [
    "HANDS",
    "GuidedRecorder",
    "QuickCheckThresholds",
    "SegmentStats",
    "quick_check",
    "segment_frame_ranges",
]
