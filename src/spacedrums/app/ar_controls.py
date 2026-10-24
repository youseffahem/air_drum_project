"""Applies the AR control bar to the running session: master volume, stick sensitivity, and the queue of
changes the play loop must make itself (camera device, classic view).

The defaults shown on the bar (sensitivity 0.7, volume 0.8, the reference screen's values) map to the
unchanged session: ``v_min`` stays the configured value and ``AudioOutput.output_scale`` stays 1.0, so
hit detection and loudness are byte-identical until the player moves a slider. Volume is applied on the
main thread before samples are enqueued (``AudioOutput.play``); the PortAudio callback is untouched.
Every change is recorded for ``report.json``.
"""

from __future__ import annotations

import threading

from spacedrums.ui.ar.controls import DEFAULT_SENSITIVITY, DEFAULT_VOLUME

V_MIN_RANGE = (0.05, 0.60)  # ROI heights per second
MAX_OUTPUT_SCALE = 1.25  # about +2 dB over today's level; the mixer still clips at +-1


def output_scale_for(volume: float) -> float:
    if volume == DEFAULT_VOLUME:
        return 1.0
    return min(MAX_OUTPUT_SCALE, max(0.0, volume / DEFAULT_VOLUME))


def v_min_for(sensitivity: float, base: float) -> float:
    """Higher sensitivity accepts slower downstrokes; every 0.3 halves or doubles the speed floor."""
    if sensitivity == DEFAULT_SENSITIVITY:
        return base
    return min(V_MIN_RANGE[1], max(V_MIN_RANGE[0], base * 2 ** ((DEFAULT_SENSITIVITY - sensitivity) / 0.3)))


class SessionControls:
    def __init__(self, base_v_min: float):
        self.base_v_min = float(base_v_min)
        self.volume = DEFAULT_VOLUME
        self.sensitivity = DEFAULT_SENSITIVITY
        self.changes: list[dict] = []

    @property
    def output_scale(self) -> float:
        return output_scale_for(self.volume)

    @property
    def v_min(self) -> float:
        return v_min_for(self.sensitivity, self.base_v_min)

    def apply_audio(self, audio):
        if audio is not None:
            audio.output_scale = self.output_scale

    def apply_pipeline(self, pipeline):
        if pipeline is not None:
            pipeline.geometry.v_min = self.v_min

    def handle(self, actions, t_capture, *, audio=None, pipeline=None) -> list[tuple[str, object]]:
        """Apply volume/sensitivity now; return the actions only the play loop can carry out."""
        pending = []
        for name, value in actions:
            self.changes.append({"t_capture": t_capture, "control": name, "value": value})
            if name == "volume":
                self.volume = float(value)
                self.apply_audio(audio)
            elif name == "sensitivity":
                self.sensitivity = float(value)
                self.apply_pipeline(pipeline)
            elif name in ("device", "view"):
                pending.append((name, value))
        return pending

    def report(self) -> dict:
        return {
            "volume": self.volume,
            "output_scale": self.output_scale,
            "sensitivity": self.sensitivity,
            "v_min": self.v_min,
            "base_v_min": self.base_v_min,
            "changes": self.changes,
        }


def camera_names(callback):
    """Look up Windows camera names in the background (PowerShell takes about a second) and call
    ``callback([(index, name), ...])``; the DirectShow index order is assumed, so names are best effort."""

    def work():
        from spacedrums.capture.device import list_pnp_cameras

        try:
            rows = list_pnp_cameras()
        except Exception:  # noqa: BLE001 - names are cosmetic; the menu keeps "Camera N"
            rows = []
        callback([(i, row["name"]) for i, row in enumerate(rows)])

    thread = threading.Thread(target=work, name="camera-names", daemon=True)
    thread.start()
    return thread


__all__ = ["SessionControls", "camera_names", "output_scale_for", "v_min_for"]
