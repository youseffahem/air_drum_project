"""Non-blocking record bus and compact timing/diagnostic dashboard.

The producer path only calls :meth:`RecordBus.publish`, which uses ``put_nowait``.
Each subscriber owns a bounded queue: a slow UI loses UI frames and increments its
drop counter; it can never apply back-pressure to capture or decisions.
"""

from __future__ import annotations

import queue
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from spacedrums.contracts import TimingRecord
from spacedrums.timing.decomposition import CROSS_CLOCK_TERMS, frame_components, stats, strike_components
from spacedrums.ui.theme import DEFAULT_THEME, Theme


@dataclass(frozen=True)
class DashboardRecord:
    frame_id: int
    t_capture: float
    active_arm: str
    fallback_status: str | None = None
    capture_fps: float | None = None
    capture_drops: int = 0
    audio_underruns: int = 0
    processing_s: float | None = None
    timing: tuple[TimingRecord, ...] = ()
    hands: tuple[dict[str, Any], ...] = ()
    strike_zones: tuple[tuple[str, str], ...] = ()


class Subscription:
    def __init__(self, name: str, maxsize: int) -> None:
        self.name = name
        self._queue: queue.Queue[DashboardRecord] = queue.Queue(maxsize=maxsize)
        self.published = 0
        self.dropped = 0

    def _publish(self, record: DashboardRecord) -> None:
        try:
            self._queue.put_nowait(record)
            self.published += 1
        except queue.Full:
            self.dropped += 1

    def get(self, timeout: float | None = None) -> DashboardRecord:
        return self._queue.get(timeout=timeout)

    def get_latest(self) -> DashboardRecord | None:
        latest = None
        while True:
            try:
                latest = self._queue.get_nowait()
            except queue.Empty:
                return latest

    def stats(self) -> dict[str, int | str]:
        return {
            "name": self.name,
            "published": self.published,
            "dropped": self.dropped,
            "queued": self._queue.qsize(),
            "capacity": self._queue.maxsize,
        }


class RecordBus:
    """Fan-out bus with bounded queues and drop-if-full semantics."""

    def __init__(self) -> None:
        self._subscriptions: list[Subscription] = []
        self._lock = threading.Lock()

    def subscribe(self, name: str, *, maxsize: int = 2) -> Subscription:
        if maxsize < 1:
            raise ValueError("maxsize must be positive")
        subscription = Subscription(name, maxsize)
        with self._lock:
            self._subscriptions.append(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        with self._lock:
            if subscription in self._subscriptions:
                self._subscriptions.remove(subscription)

    def publish(self, record: DashboardRecord) -> None:
        with self._lock:
            subscriptions = tuple(self._subscriptions)
        for subscription in subscriptions:
            subscription._publish(record)


@dataclass(frozen=True)
class TimingRow:
    strike_id: str
    frame_id: int
    arm: str
    hand: str
    zone: str | None
    t_capture: float
    t_commit: float
    impact_label: str
    impact_time: float | None
    lead_label: str
    lead_s: float | None
    components: dict[str, float]


def timing_row(
    record: TimingRecord,
    *,
    zone: str | None = None,
    live: bool,
) -> TimingRow:
    """Build a truthful display row.

    Live anticipatory rows are explicitly ``predicted lead``.  ``L_pred`` is used
    only after an estimated impact exists, normally during replay/evaluation.
    """
    if record.kind != "STRIKE" or record.strike_id is None or record.t_commit is None:
        raise ValueError("timing_row needs a STRIKE TimingRecord")
    if not live and record.t_impact_est is not None:
        impact_label = "estimated impact"
        impact = record.t_impact_est
        lead_label = "L_pred (estimated impact - commit)"
    elif record.t_impact_pred is not None:
        impact_label = "predicted impact"
        impact = record.t_impact_pred
        lead_label = "predicted lead (predicted impact - commit)"
    elif record.t_impact_est is not None:
        impact_label = "estimated impact"
        impact = record.t_impact_est
        lead_label = "L_pred (estimated impact - commit)"
    else:
        impact_label = "impact unavailable"
        impact = None
        lead_label = "lead unavailable"
    components = strike_components(record)
    if not live:
        components = {key: value for key, value in components.items() if key not in CROSS_CLOCK_TERMS}
    return TimingRow(
        strike_id=record.strike_id,
        frame_id=record.frame_id,
        arm=str(record.arm or "NA"),
        hand=str(record.hand_id or "NA"),
        zone=zone,
        t_capture=record.t_capture,
        t_commit=record.t_commit,
        impact_label=impact_label,
        impact_time=impact,
        lead_label=lead_label,
        lead_s=None if impact is None else impact - record.t_commit,
        components=components,
    )


@dataclass
class DashboardModel:
    live: bool = True
    history: int = 240
    frames: deque[DashboardRecord] = field(init=False)
    strikes: deque[TimingRow] = field(init=False)

    def __post_init__(self) -> None:
        self.frames = deque(maxlen=self.history)
        self.strikes = deque(maxlen=max(16, self.history // 4))

    def update(self, record: DashboardRecord) -> None:
        self.frames.append(record)
        zones = dict(record.strike_zones)
        for timing in record.timing:
            if timing.kind == "STRIKE":
                self.strikes.append(
                    timing_row(timing, live=self.live, zone=zones.get(timing.strike_id or ""))
                )

    def rolling(self) -> dict[str, Any]:
        processing = [r.processing_s for r in self.frames if r.processing_s is not None]
        frame_terms: dict[str, list[float]] = {}
        for r in self.frames:
            for timing in r.timing:
                if timing.kind == "FRAME":
                    for key, value in frame_components(timing).items():
                        frame_terms.setdefault(key, []).append(value)
        leads = [row.lead_s for row in self.strikes if row.lead_s is not None]
        return {
            "frames": len(self.frames),
            "processing": stats(processing).to_dict(),
            "lead": stats(leads).to_dict(),
            "frame_components": {k: stats(v).to_dict() for k, v in frame_terms.items()},
        }


def render_dashboard(
    model: DashboardModel, *, size: tuple[int, int] = (720, 620), theme: Theme = DEFAULT_THEME
) -> np.ndarray:
    """Render a deterministic OpenCV side panel; safe for screenshots and headless tests."""
    width, height = size
    image = np.full((height, width, 3), theme.background, np.uint8)
    cv2.rectangle(image, (12, 12), (width - 12, 116), theme.panel, -1)
    latest = model.frames[-1] if model.frames else None
    lines = ["SPACE DRUMS / DEBUG DASHBOARD"]
    if latest:
        fps = "n/a" if latest.capture_fps is None else f"{latest.capture_fps:.1f}"
        lines.extend(
            [
                f"frame {latest.frame_id}   active {latest.active_arm}"
                + (f"   FALLBACK: {latest.fallback_status}" if latest.fallback_status else ""),
                f"capture {fps} fps   drops {latest.capture_drops}"
                f"   audio underruns {latest.audio_underruns}",
            ]
        )
    for index, line in enumerate(lines):
        cv2.putText(
            image, line, (24, 38 + index * 28), cv2.FONT_HERSHEY_SIMPLEX, 0.58, theme.text, 1, cv2.LINE_AA
        )
    cv2.putText(
        image,
        "PER-STRIKE TIMING (software stamps)",
        (24, 150),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        theme.muted,
        1,
        cv2.LINE_AA,
    )
    y = 180
    for row in list(model.strikes)[-4:][::-1]:
        lead = "n/a" if row.lead_s is None else f"{row.lead_s * 1000:+.1f} ms"
        text = f"f{row.frame_id} {row.arm}/{row.hand} {row.zone or '-'} | {row.lead_label}: {lead}"
        cv2.putText(image, text[:105], (24, y), cv2.FONT_HERSHEY_SIMPLEX, 0.40, theme.text, 1, cv2.LINE_AA)
        y += 19
        impact = "n/a" if row.impact_time is None else f"{row.impact_time:.4f}"
        components = " ".join(
            f"{name}={value * 1000:+.1f}ms"
            for name, value in row.components.items()
            if name in ("capture", "tracking", "inference", "commit", "audio_dispatch", "audio_out_est")
        )
        detail = (
            f"capture={row.t_capture:.4f} commit={row.t_commit:.4f} "
            f"{row.impact_label}={impact} | {components}"
        )
        cv2.putText(image, detail[:112], (36, y), cv2.FONT_HERSHEY_SIMPLEX, 0.32, theme.muted, 1, cv2.LINE_AA)
        y += 25
    if model.frames:
        plot_y = max(y + 8, 365)
        panel_width = (width - 72) // 2
        panels = (
            ("tip y / ROI (down)", "tip_y", (24, plot_y)),
            ("vertical velocity / ROI/s", "velocity_y", (width // 2 + 8, plot_y)),
            ("candidate TTI / ms", "tti_ms", (24, plot_y + 76)),
            ("frame processing / ms", "processing_ms", (width // 2 + 8, plot_y + 76)),
        )
        for label, quantity, origin in panels:
            _draw_rolling_plot(image, tuple(model.frames), label, quantity, origin, (panel_width, 64), theme)
    rolling = model.rolling()
    p = rolling["processing"]
    proc = (
        "n/a"
        if p["median_s"] is None
        else f"p50 {p['median_s'] * 1000:.2f} ms / p90 {p['p90_s'] * 1000:.2f} ms"
    )
    lead_stats = rolling["lead"]
    lead = (
        "n/a"
        if lead_stats["median_s"] is None
        else f"median {lead_stats['median_s'] * 1000:+.2f} ms / n={lead_stats['n']}"
    )
    cv2.putText(
        image,
        f"processing: {proc}   lead: {lead}",
        (24, height - 42),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        theme.muted,
        1,
        cv2.LINE_AA,
    )
    return image


def _draw_rolling_plot(
    image: np.ndarray,
    frames: tuple[DashboardRecord, ...],
    label: str,
    quantity: str,
    origin: tuple[int, int],
    size: tuple[int, int],
    theme: Theme,
) -> None:
    """Small time-based plot with commit ticks and a shared hand palette."""
    x0, y0 = origin
    width, height = size
    if y0 + height >= image.shape[0] - 55:
        return
    cv2.rectangle(image, (x0, y0), (x0 + width, y0 + height), theme.panel, -1)
    cv2.putText(image, label, (x0 + 5, y0 + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.32, theme.text, 1, cv2.LINE_AA)
    values: list[tuple[float, float, str]] = []
    commit_times: list[float] = []
    for frame in frames:
        if any(record.kind == "STRIKE" for record in frame.timing):
            commit_times.append(frame.t_capture)
        if quantity == "processing_ms":
            if frame.processing_s is not None:
                values.append((frame.t_capture, frame.processing_s * 1000, "GLOBAL"))
            continue
        for hand in frame.hands:
            hand_id = str(hand.get("hand_id", "?"))
            track = hand.get("track") or {}
            if quantity == "tip_y" and track.get("tip_filtered") is not None:
                values.append((frame.t_capture, float(track["tip_filtered"][1]), hand_id))
            elif quantity == "velocity_y" and track.get("tip_velocity") is not None:
                values.append((frame.t_capture, float(track["tip_velocity"][1]), hand_id))
            elif quantity == "tti_ms":
                for candidate in hand.get("candidates", ()):
                    if candidate.get("tti") is not None:
                        values.append((frame.t_capture, float(candidate["tti"]) * 1000, hand_id))
    if not values:
        cv2.putText(
            image, "no data", (x0 + 8, y0 + 39), cv2.FONT_HERSHEY_SIMPLEX, 0.35, theme.muted, 1, cv2.LINE_AA
        )
        return
    t_min = min(frame.t_capture for frame in frames)
    t_span = max(1e-9, max(frame.t_capture for frame in frames) - t_min)
    v_min = min(value for _, value, _ in values)
    v_max = max(value for _, value, _ in values)
    v_span = max(1e-9, v_max - v_min)
    left, right = x0 + 5, x0 + width - 5
    top, bottom = y0 + 20, y0 + height - 5
    for t in commit_times:
        x = round(left + (t - t_min) / t_span * (right - left))
        cv2.line(image, (x, top), (x, bottom), theme.error, 1)
    for hand_id, color in (("LEFT", theme.left), ("RIGHT", theme.right), ("GLOBAL", theme.arm_b)):
        points = []
        for t, value, source in values:
            if source != hand_id:
                continue
            x = round(left + (t - t_min) / t_span * (right - left))
            fraction = (value - v_min) / v_span
            y_point = (
                round(top + fraction * (bottom - top))
                if quantity == "tip_y"
                else round(bottom - fraction * (bottom - top))
            )
            points.append((x, y_point))
        if not points:
            continue
        if quantity == "tti_ms":
            for point in points:
                cv2.circle(image, point, 2, color, -1)
        elif len(points) > 1:
            cv2.polylines(image, [np.asarray(points, np.int32)], False, color, 1, cv2.LINE_AA)
        else:
            cv2.circle(image, points[0], 2, color, -1)
    cv2.putText(
        image,
        f"{v_min:.1f}..{v_max:.1f}",
        (right - 72, y0 + 13),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.27,
        theme.muted,
        1,
        cv2.LINE_AA,
    )


class DashboardWorker:
    """Independent renderer; the application's main UI thread owns OpenCV windows."""

    def __init__(
        self,
        subscription: Subscription,
        *,
        live: bool = True,
    ) -> None:
        self.subscription = subscription
        self.model = DashboardModel(live=live)
        self.latest_image: np.ndarray | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="spacedrums-dashboard", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                record = self.subscription.get(timeout=0.05)
            except queue.Empty:
                continue
            self.model.update(record)
            self.latest_image = render_dashboard(self.model)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None


__all__ = [
    "DashboardModel",
    "DashboardRecord",
    "DashboardWorker",
    "RecordBus",
    "Subscription",
    "TimingRow",
    "render_dashboard",
    "timing_row",
]
