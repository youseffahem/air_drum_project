"""AR control bar state: sliders, the Camera View menu, the Settings popup and their keyboard keys.

Pure UI state with no I/O. Mouse events arrive in composed-image pixels (HighGUI maps window coordinates
to image pixels at any window size); rectangles come from ``hud.HudLayout``. Changes that the session must
apply (volume, sensitivity, camera device, classic view) are queued as actions for ``app`` to drain; the
AR view applies its own visual settings directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from spacedrums.ui.ar.scene import VIEW_NAMES

EVENT_MOVE, EVENT_DOWN, EVENT_UP = 0, 1, 4  # cv2.EVENT_MOUSEMOVE / LBUTTONDOWN / LBUTTONUP
DEFAULT_SENSITIVITY, DEFAULT_VOLUME = 0.7, 0.8  # the values shown on the reference screen
EFFECTS = ("full", "low", "off")
STEP = 0.05


@dataclass
class Settings:
    panels: bool = True
    trails: bool = True
    effects: str = "full"
    bloom: bool = True
    ghost: bool = False  # see-through kit

    def items(self):
        """(key, label, value text) rows of the Settings popup."""
        on = {True: "On", False: "Off"}
        return [
            ("panels", "Panels  (H)", on[self.panels]),
            ("trails", "Stick trails  (T)", on[self.trails]),
            ("effects", "Hit effects  (E)", self.effects.title()),
            ("bloom", "Neon glow  (B)", on[self.bloom]),
            ("ghost", "See-through kit  (G)", on[self.ghost]),
            ("classic", "Classic view  (Esc in menu)", ""),
        ]


def _clamp(v):
    return round(min(1.0, max(0.0, v)), 2)


@dataclass
class Controls:
    sensitivity: float = DEFAULT_SENSITIVITY
    volume: float = DEFAULT_VOLUME
    viewpoint: str = "front"
    devices: list[tuple[int, str]] = field(default_factory=lambda: [(0, "Camera 0 (Default)")])
    device: int = 0
    settings: Settings = field(default_factory=Settings)
    menu: str | None = None  # "camera" | "settings"
    dragging: str | None = None
    hover: str | None = None
    actions: list[tuple[str, object]] = field(default_factory=list)

    # -- values ----------------------------------------------------------------------------------
    def set_slider(self, name, value):
        value = _clamp(value)
        if getattr(self, name) != value:
            setattr(self, name, value)
            self.actions.append((name, value))

    def set_viewpoint(self, vp):
        if vp != self.viewpoint:
            self.viewpoint = vp
            self.actions.append(("viewpoint", vp))

    def set_device(self, index):
        if index != self.device:
            self.device = index
            self.actions.append(("device", index))

    def toggle(self, key):
        s = self.settings
        if key == "effects":
            s.effects = EFFECTS[(EFFECTS.index(s.effects) + 1) % len(EFFECTS)]
            value = s.effects
        elif key == "classic":
            self.menu = None
            self.actions.append(("view", "classic"))
            return
        else:
            value = not getattr(s, key)
            setattr(s, key, value)
        self.actions.append((key, value))

    @property
    def camera_label(self) -> str:
        """The dropdown text: the viewpoint, prefixed by the device when it is not the default one."""
        if self.device == self.devices[0][0]:
            return VIEW_NAMES[self.viewpoint]
        return (
            f"{dict(self.devices).get(self.device, f'Camera {self.device}')} | {VIEW_NAMES[self.viewpoint]}"
        )

    def drain(self):
        out, self.actions = self.actions, []
        return out

    # -- input -------------------------------------------------------------------------------------
    def key(self, key: int) -> bool:
        """Handle an AR key; False leaves it to the session (Esc/Q, R, D)."""
        ch = chr(key) if 0 <= key < 256 else ""
        if ch == "h":
            self.toggle("panels")
        elif ch == "t":
            self.toggle("trails")
        elif ch == "e":
            self.toggle("effects")
        elif ch == "b":
            self.toggle("bloom")
        elif ch == "g":
            self.toggle("ghost")
        elif ch == "s":
            self.menu = None if self.menu == "settings" else "settings"
        elif ch == "c":
            self.menu = None if self.menu == "camera" else "camera"
        elif ch == "v":
            order = list(VIEW_NAMES)
            self.set_viewpoint(order[(order.index(self.viewpoint) + 1) % len(order)])
        elif ch in "[]":
            self.set_slider("sensitivity", self.sensitivity + (STEP if ch == "]" else -STEP))
        elif ch in "-=+":
            self.set_slider("volume", self.volume + (-STEP if ch == "-" else STEP))
        elif key == 27 and self.menu:
            self.menu = None
        else:
            return False
        return True

    def mouse(self, event, x, y, layout) -> bool:
        """Returns True when the event hit a control (it then never reaches anything else)."""
        if event == EVENT_UP:
            hit = self.dragging is not None
            self.dragging = None
            return hit
        if event == EVENT_MOVE:
            if self.dragging:
                self.set_slider(self.dragging, layout.slider_value(self.dragging, x))
                return True
            self.hover = layout.hit(x, y, self)
            return False
        if event != EVENT_DOWN:
            return False
        target = layout.hit(x, y, self)
        if target is None:
            self.menu = None
            return False
        kind, _, arg = target.partition(":")
        if kind in ("sensitivity", "volume"):
            self.dragging = kind
            self.set_slider(kind, layout.slider_value(kind, x))
        elif kind == "settings_button":
            self.menu = None if self.menu == "settings" else "settings"
        elif kind == "camera_button":
            self.menu = None if self.menu == "camera" else "camera"
        elif kind == "viewpoint":
            self.set_viewpoint(arg)
            self.menu = None
        elif kind == "device":
            self.set_device(int(arg))
            self.menu = None
        elif kind == "setting":
            self.toggle(arg)
        return True


__all__ = ["DEFAULT_SENSITIVITY", "DEFAULT_VOLUME", "Controls", "Settings"]
