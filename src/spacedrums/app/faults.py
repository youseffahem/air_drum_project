"""``FaultInjector`` test interface (Phase 17, Tasks 17.3-17.5). **TEST BUILDS ONLY.**

Deterministic fault injection at every layer the Phase 17 architecture names:

    capture   stall (frames never delivered), drop burst (queue drops), timestamp jump, FPS change
              (replay streams: :func:`apply_stream_faults`); non-monotone / stalled / disconnected
              camera for the live source (:class:`FaultyCamera`)
    vision    occlusion masks, lighting (gain / gamma) perturbation on replayed images
    hands     hand dropped (occlusion / out-of-ROI), identity swap, low confidence, tip moved out of
              the ROI, a spurious (background) hand replacing a hand's observation
    model     slow inference, exception of any type, non-finite (corrupt) outputs
    audio     device removal / re-attach and underrun bursts behind a fake PortAudio stream

Nothing here is ever reachable from the application CLI: every constructor calls
:func:`require_test_build`, which refuses unless ``SPACEDRUMS_FAULT_INJECTION=1`` is set (the test
suites and ``scripts/inject_faults.py`` set it). Every injected fault is recorded as a
:class:`FaultEvent` so reports can attribute outcomes to the injected interval. Injected data is
SYNTHETIC perturbation of recorded or synthetic input and is labelled as such in every report.
"""

from __future__ import annotations

import dataclasses
import math
import os
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from spacedrums.capture.backend import CameraOpenSpec, NegotiatedMode, RawFrame
from spacedrums.contracts import FrameSample, FrameView, HandId, HandObservation, StickObservation

ENV = "SPACEDRUMS_FAULT_INJECTION"
Observations = dict[HandId, tuple[HandObservation, StickObservation]]
Box = tuple[float, float, float, float]  # x0, y0, x1, y1 in ROI-normalized units


def require_test_build() -> None:
    if os.environ.get(ENV) != "1":
        raise RuntimeError(f"fault injection is available in test builds only (set {ENV}=1)")


@dataclass(frozen=True)
class FaultEvent:
    kind: str
    start_frame: int  # index in the *original* stream (inclusive)
    end_frame: int  # exclusive
    hand: str | None = None
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# ============================================================================ capture (replay streams)


@dataclass(frozen=True)
class Stall:
    """Frames ``[at, at + frames)`` are never delivered; later frames keep their true timestamps."""

    at: int
    frames: int
    kind: str = "STALL"


@dataclass(frozen=True)
class DropBurst:
    """Frames ``[at, at + frames)`` are dropped by the queue; the next delivered frame reports them."""

    at: int
    frames: int
    kind: str = "DROP_BURST"


@dataclass(frozen=True)
class TimestampJump:
    """``t_capture`` / ``t_frame_available`` of frames ``>= at`` shift by ``delta_s`` (clock jump)."""

    at: int
    delta_s: float
    kind: str = "TIMESTAMP_JUMP"


@dataclass(frozen=True)
class FpsChange:
    """Frames ``[at, until)`` deliver only every ``keep_every``-th frame (native rate / keep_every).

    ``until = None`` keeps the lower rate to the end of the stream.
    """

    at: int
    keep_every: int
    until: int | None = None
    kind: str = "FPS_CHANGE"


StreamFault = Stall | DropBurst | TimestampJump | FpsChange


def apply_stream_faults(
    frames: Sequence[tuple[FrameSample, Any]], faults: Sequence[StreamFault], *, index_map: list | None = None
) -> tuple[list[tuple[FrameSample, Any]], list[FaultEvent]]:
    """Return the perturbed delivered stream (frame ids re-assigned at delivery) and the fault log.

    ``Any`` payloads (image views, observations) follow their sample; a view's embedded sample is
    replaced so perception sees the delivered timestamps. ``index_map`` (a list, if given) receives
    the original index of every delivered frame.
    """
    require_test_build()
    removed: set[int] = set()
    dropped_before: dict[int, int] = {}
    shift = [0.0] * len(frames)
    events: list[FaultEvent] = []
    for f in faults:
        if isinstance(f, (Stall, DropBurst)):
            if f.frames < 1 or not 0 < f.at < len(frames):
                raise ValueError(f"{f.kind} needs 0 < at < n and frames >= 1")
            span = range(f.at, min(len(frames), f.at + f.frames))
            removed.update(span)
            if isinstance(f, DropBurst) and span.stop < len(frames):
                dropped_before[span.stop] = dropped_before.get(span.stop, 0) + len(span)
            events.append(FaultEvent(f.kind, span.start, span.stop, params={"frames": len(span)}))
        elif isinstance(f, TimestampJump):
            for i in range(f.at, len(frames)):
                shift[i] += f.delta_s
            events.append(FaultEvent(f.kind, f.at, len(frames), params={"delta_s": f.delta_s}))
        elif isinstance(f, FpsChange):
            if f.keep_every < 2:
                raise ValueError("keep_every must be >= 2")
            stop = len(frames) if f.until is None else min(len(frames), f.until)
            for i in range(f.at, stop):
                if (i - f.at) % f.keep_every:
                    removed.add(i)
            events.append(FaultEvent(f.kind, f.at, stop, params={"keep_every": f.keep_every}))
        else:  # pragma: no cover - typing guard
            raise TypeError(f"unknown stream fault {f!r}")
    out: list[tuple[FrameSample, Any]] = []
    pending_drops = 0
    for i, (sample, payload) in enumerate(frames):
        pending_drops += dropped_before.get(i, 0)
        if i in removed:
            continue
        new = dataclasses.replace(
            sample,
            frame_id=len(out),
            t_capture=sample.t_capture + shift[i],
            t_frame_available=sample.t_frame_available + shift[i],
            dropped_since_last=sample.dropped_since_last + pending_drops,
        )
        pending_drops = 0
        if isinstance(payload, FrameView):
            payload = dataclasses.replace(payload, sample=new)
        elif isinstance(payload, Mapping):  # observations follow their (re-delivered) frame
            payload = {h: rebase(pair, new) for h, pair in payload.items()}
        out.append((new, payload))
        if index_map is not None:
            index_map.append(i)
    return out, events


def rebase(pair: tuple[HandObservation, StickObservation], sample: FrameSample):
    """Observations re-stamped onto a re-delivered frame (same content, new frame id / time)."""
    h, s = pair
    return (
        dataclasses.replace(h, frame_id=sample.frame_id, t_capture=sample.t_capture),
        dataclasses.replace(s, frame_id=sample.frame_id, t_capture=sample.t_capture),
    )


# ============================================================================ vision (replayed images)


def _box_px(view: FrameView, box: Box) -> tuple[int, int, int, int]:
    h, w = view.roi.shape[:2]
    x0, y0, x1, y1 = box
    return (
        max(0, int(math.floor(min(x0, x1) * w))),
        max(0, int(math.floor(min(y0, y1) * h))),
        min(w, int(math.ceil(max(x0, x1) * w))),
        min(h, int(math.ceil(max(y0, y1) * h))),
    )


def _copy_view(view: FrameView) -> FrameView:
    """Copy the image once; the ROI stays a slice of the full frame when there is one."""
    if view.full is None:
        return dataclasses.replace(view, roi=view.roi.copy())
    full = view.full.copy()
    x, y, w, h = view.sample.roi_px
    return dataclasses.replace(view, full=full, roi=full[y : y + h, x : x + w])


def mask_region(view: FrameView, box: Box, value: int = 0) -> FrameView:
    """Occlusion: paint an ROI-normalized box (occluder / hand leaving the visible ROI)."""
    require_test_build()
    out = _copy_view(view)
    x0, y0, x1, y1 = _box_px(out, box)
    out.roi[y0:y1, x0:x1] = value
    return out


def adjust_lighting(view: FrameView, gain: float = 1.0, gamma: float = 1.0) -> FrameView:
    """Global exposure change: ``255 * gain * (I / 255) ** gamma`` on the whole frame, clipped."""
    require_test_build()
    if gain <= 0 or gamma <= 0:
        raise ValueError("gain and gamma must be positive")
    out = _copy_view(view)
    lut = np.clip(255.0 * gain * (np.arange(256) / 255.0) ** gamma, 0, 255).astype(np.uint8)
    target = out.full if out.full is not None else out.roi
    target[...] = lut[target]
    return out


# ============================================================================ hands layer (observations)


def drop_hand(obs: Observations, hand: HandId) -> Observations:
    """No detection for ``hand`` (occlusion, hand out of the ROI, estimator failure)."""
    hand_obs, stick = obs[hand]
    out = dict(obs)
    out[hand] = (
        HandObservation.absent(hand_obs.frame_id, hand_obs.t_capture, hand, hand_obs.detector_id),
        StickObservation.absent(stick.frame_id, stick.t_capture, hand, stick.method_id),
    )
    return out


def swap_hands(obs: Observations) -> Observations:
    """Identity swap: each hand receives the other hand's observations."""
    left, right = obs[HandId.LEFT], obs[HandId.RIGHT]

    def relabel(pair, hand):
        h, s = pair
        return dataclasses.replace(h, hand_id=hand), dataclasses.replace(s, hand_id=hand)

    return {HandId.LEFT: relabel(right, HandId.LEFT), HandId.RIGHT: relabel(left, HandId.RIGHT)}


def set_confidence(obs: Observations, hand: HandId, confidence: float) -> Observations:
    """Tip confidence forced to ``confidence`` (a weak / ambiguous estimator output)."""
    hand_obs, stick = obs[hand]
    if not stick.present:
        return obs
    out = dict(obs)
    out[hand] = (
        hand_obs,
        dataclasses.replace(
            stick, tip_confidence=confidence, axis_confidence=min(stick.axis_confidence, confidence)
        ),
    )
    return out


def translate_hand(obs: Observations, hand: HandId, dx: float, dy: float) -> Observations:
    """Move a hand's landmarks, box, stick axis and tip by (dx, dy) ROI-normalized units."""
    hand_obs, stick = obs[hand]
    out = dict(obs)
    new_hand = hand_obs
    if hand_obs.present:
        x, y, w, h = hand_obs.bbox
        new_hand = dataclasses.replace(
            hand_obs,
            landmarks=tuple((p[0] + dx, p[1] + dy) for p in hand_obs.landmarks),
            bbox=(x + dx, y + dy, w, h),
        )
    new_stick = stick
    if stick.present:
        new_stick = dataclasses.replace(
            stick,
            axis_origin=(stick.axis_origin[0] + dx, stick.axis_origin[1] + dy),
            tip=(stick.tip[0] + dx, stick.tip[1] + dy),
        )
    out[hand] = (new_hand, new_stick)
    return out


def replace_hand(
    obs: Observations, hand: HandId, source: tuple[HandObservation, StickObservation]
) -> Observations:
    """A different (e.g. background) hand's observations reported as ``hand``."""
    hand_obs, _ = obs[hand]
    h, s = source
    out = dict(obs)
    out[hand] = (
        dataclasses.replace(h, frame_id=hand_obs.frame_id, t_capture=hand_obs.t_capture, hand_id=hand),
        dataclasses.replace(s, frame_id=hand_obs.frame_id, t_capture=hand_obs.t_capture, hand_id=hand),
    )
    return out


ImageFn = Callable[[FrameView, int], FrameView]
ObsFn = Callable[[Observations, int], Observations]


@dataclass
class FaultPlan:
    """Per-frame schedule of vision and hands-layer faults over ``[start, end)`` frame intervals.

    ``frame`` arguments are delivered-frame indices (after any stream fault). ``apply_image`` and
    ``apply_observations`` are pure: the replayed originals are never modified.
    """

    image_faults: list[tuple[int, int, str, ImageFn, dict[str, Any]]] = field(default_factory=list)
    observation_faults: list[tuple[int, int, str, ObsFn, dict[str, Any]]] = field(default_factory=list)

    def __post_init__(self) -> None:
        require_test_build()

    def image(self, start: int, end: int, kind: str, fn: ImageFn, **params: Any) -> FaultPlan:
        self.image_faults.append((start, end, kind, fn, params))
        return self

    def observations(self, start: int, end: int, kind: str, fn: ObsFn, **params: Any) -> FaultPlan:
        self.observation_faults.append((start, end, kind, fn, params))
        return self

    def apply_image(self, view: FrameView, frame: int) -> FrameView:
        for start, end, _kind, fn, _params in self.image_faults:
            if start <= frame < end:
                view = fn(view, frame)
        return view

    def apply_observations(self, obs: Observations, frame: int) -> Observations:
        for start, end, _kind, fn, _params in self.observation_faults:
            if start <= frame < end:
                obs = fn(obs, frame)
        return obs

    def active(self, frame: int) -> bool:
        return any(s <= frame < e for s, e, *_ in (*self.image_faults, *self.observation_faults))

    def events(self) -> list[FaultEvent]:
        out = []
        for start, end, kind, _fn, params in (*self.image_faults, *self.observation_faults):
            hand = params.get("hand")
            out.append(
                FaultEvent(
                    kind,
                    start,
                    end,
                    None if hand is None else str(hand),
                    {k: v for k, v in params.items() if k != "hand"},
                )
            )
        return out


# ============================================================================ model


class ModelFault:
    """Wraps a ``ModelArm`` adapter's ``predict``: slow / raising / non-finite after ``after_calls``."""

    def __init__(
        self,
        arm,
        *,
        kind: str,
        after_calls: int = 0,
        delay_s: float = 0.0,
        exception: type[BaseException] = RuntimeError,
        advance_clock: Callable[[float], None] | None = None,
    ) -> None:
        require_test_build()
        if kind not in ("slow", "raise", "nan", "inf"):
            raise ValueError("kind must be slow | raise | nan | inf")
        self.arm, self.kind, self.after_calls = arm, kind, int(after_calls)
        self.delay_s, self.exception, self.advance_clock = float(delay_s), exception, advance_clock
        self.calls = 0
        self.faulted = 0
        self._original = arm.adapter.predict
        arm.adapter.predict = self._predict

    def _predict(self, history, window):
        self.calls += 1
        if self.calls <= self.after_calls:
            return self._original(history, window)
        self.faulted += 1
        if self.kind == "slow":
            if self.advance_clock is not None:
                self.advance_clock(self.delay_s)
            else:
                threading.Event().wait(self.delay_s)
            return self._original(history, window)
        if self.kind == "raise":
            raise self.exception(f"injected model fault ({self.exception.__name__})")
        pred = self._original(history, window)
        if pred is None:
            return None
        bad = float("nan") if self.kind == "nan" else float("inf")
        return dataclasses.replace(pred, positions=tuple((bad, bad) for _ in pred.positions))


# ============================================================================ camera (live source)


class FaultyCamera:
    """``CameraBackend`` wrapper for the live source: timestamp anomalies, stalls and disconnects.

    ``driver_shift`` maps raw-read index -> seconds added to that read's driver timestamp from then
    on (a jump; negative = non-monotone driver clock). ``grab_shift`` does the same to
    ``t_grab_return`` (a monotonic-clock anomaly the source must survive). ``stall_at`` maps a read
    index -> seconds the read blocks. ``disconnect`` = (first read index, number of reads) returning
    ``None`` (unplugged, then re-attached).
    """

    def __init__(
        self,
        camera,
        *,
        driver_shift: Mapping[int, float] | None = None,
        grab_shift: Mapping[int, float] | None = None,
        stall_at: Mapping[int, float] | None = None,
        disconnect: tuple[int, int] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        require_test_build()
        self.camera = camera
        self.driver_shift = dict(driver_shift or {})
        self.grab_shift = dict(grab_shift or {})
        self.stall_at = dict(stall_at or {})
        self.disconnect = disconnect
        self.sleep = sleep or (lambda s: threading.Event().wait(s))
        self.reads = 0
        self._driver_offset = 0.0
        self._grab_offset = 0.0
        # ``LiveFrameSource`` stops a finite source when ``n_frames`` is set and a read returns None;
        # it stays None until the wrapped camera is really exhausted, so a disconnect is not an end.
        self.n_frames: int | None = None

    def open(self, spec: CameraOpenSpec) -> NegotiatedMode:
        return self.camera.open(spec)

    def apply_exposure(self, mode: str, value: float | None) -> dict[str, Any]:
        return self.camera.apply_exposure(mode, value)

    def close(self) -> None:
        self.camera.close()

    def read(self) -> RawFrame | None:
        i = self.reads
        self.reads += 1
        if i in self.stall_at:
            self.sleep(self.stall_at[i])
        if self.disconnect is not None and self.disconnect[0] <= i < sum(self.disconnect):
            return None
        raw = self.camera.read()
        if raw is None:
            self.n_frames = self.reads  # wrapped source exhausted: a real end of stream
            return None
        self._driver_offset += self.driver_shift.get(i, 0.0)
        self._grab_offset += self.grab_shift.get(i, 0.0)
        t_drv = None if raw.t_driver_s is None else raw.t_driver_s + self._driver_offset
        return RawFrame(
            image=raw.image, t_grab_return=raw.t_grab_return + self._grab_offset, t_driver_s=t_drv
        )


# ============================================================================ audio (fake PortAudio)


@dataclass
class _Status:
    output_underflow: bool = False


@dataclass
class _TimeInfo:
    currentTime: float  # noqa: N815 - PortAudio attribute names
    outputBufferDacTime: float  # noqa: N815


class FakeAudioBackend:
    """Stream factory standing in for ``sounddevice.OutputStream``; drives callbacks on demand.

    Tests call :meth:`pump` to run ``n`` callbacks (deterministic; no audio thread). ``remove()``
    makes the device vanish: the running stream stops calling back and opening fails until
    ``reattach()``. ``underruns(n)`` flags the next ``n`` callbacks with ``output_underflow``.
    """

    def __init__(self, clock: Callable[[], float]) -> None:
        require_test_build()
        self.clock = clock
        self.present = True
        self.streams: list[FakeOutputStream] = []
        self.opened = 0
        self.open_failures = 0
        self._underruns = 0

    def __call__(self, **kwargs: Any) -> FakeOutputStream:
        if not self.present:
            self.open_failures += 1
            raise OSError("PortAudio: device unavailable (injected)")
        self.opened += 1
        stream = FakeOutputStream(self, **kwargs)
        self.streams.append(stream)
        return stream

    def remove(self) -> None:
        self.present = False
        for s in self.streams:
            s.device_lost = True

    def reattach(self) -> None:
        self.present = True

    def underruns(self, n: int) -> None:
        self._underruns += int(n)

    def pump(self, n: int = 1) -> int:
        """Run ``n`` callbacks on every active stream; returns callbacks actually delivered."""
        delivered = 0
        for s in self.streams:
            for _ in range(n):
                delivered += s._tick()
        return delivered

    def take_underrun(self) -> bool:
        if self._underruns > 0:
            self._underruns -= 1
            return True
        return False


class FakeOutputStream:
    def __init__(self, backend: FakeAudioBackend, **kwargs: Any) -> None:
        self.backend = backend
        self.kwargs = kwargs
        self.callback = kwargs["callback"]
        self.blocksize = int(kwargs["blocksize"])
        self.samplerate = float(kwargs["samplerate"])
        self.channels = int(kwargs["channels"])
        self.active = False
        self.closed = False
        self.device_lost = False
        self.callbacks = 0
        self.frames_out: list[np.ndarray] = []

    def start(self) -> None:
        if self.device_lost:
            raise OSError("PortAudio: device unavailable (injected)")
        self.active = True

    def stop(self) -> None:
        self.active = False

    def close(self) -> None:
        self.closed = True
        self.active = False

    def _tick(self) -> int:
        if not self.active or self.device_lost or self.closed:
            return 0
        t = self.backend.clock()
        out = np.zeros((self.blocksize, self.channels), dtype=np.float32)
        status = _Status(output_underflow=self.backend.take_underrun())
        self.callback(out, self.blocksize, _TimeInfo(t, t), status)
        self.callbacks += 1
        self.frames_out.append(out.copy())
        return 1


def events_overlap(events: Iterable[FaultEvent], frame: int, margin: int = 0) -> bool:
    return any(e.start_frame - margin <= frame < e.end_frame + margin for e in events)


__all__ = [
    "ENV",
    "DropBurst",
    "FakeAudioBackend",
    "FakeOutputStream",
    "FaultEvent",
    "FaultPlan",
    "FaultyCamera",
    "FpsChange",
    "ModelFault",
    "Stall",
    "TimestampJump",
    "adjust_lighting",
    "apply_stream_faults",
    "drop_hand",
    "events_overlap",
    "mask_region",
    "replace_hand",
    "require_test_build",
    "set_confidence",
    "swap_hands",
    "translate_hand",
]
