"""The AR view: the live camera with a GPU-rendered, neon-lit 3D kit aligned to the hit zones, glow
feedback for committed strikes, stick-tip markers, and the reference HUD with its control bar.

Display only. It reads zones, endpoint evidence and the pipeline's committed strikes; it never creates,
filters or delays an event (audio is scheduled inside ``DecisionPipeline.step`` before this runs).
"""

from __future__ import annotations

from spacedrums.timing import now
from spacedrums.ui.ar.controls import Controls
from spacedrums.ui.ar.display_map import DisplayMap
from spacedrums.ui.ar.effects import Effects
from spacedrums.ui.ar.gl import GLRenderer, GLUnavailable
from spacedrums.ui.ar.hud import Hud, UiStatus
from spacedrums.ui.ar.scene import layout

GHOST_ALPHA = 0.55
BLOOM = 1.8


class ARView:
    def __init__(self, *, samples: int = 4, prefer_discrete: bool = True, renderer_factory=None, text=None):
        self.samples, self.prefer_discrete = samples, prefer_discrete
        self._factory = renderer_factory or GLRenderer
        self.renderer = None
        self.controls = Controls()
        self.effects = Effects()
        self.hud = Hud(text)
        self.camera = None
        self.pieces = []
        self._key = None
        self.timings: dict[str, float] = {}

    def renderer_for(self, dmap: DisplayMap):
        r = self.renderer
        if r is not None and (r.width, r.height) != (dmap.out_w, dmap.out_h):
            r.release()
            r = self.renderer = None
        if r is None:
            self.renderer = self._factory(
                dmap.out_w, dmap.out_h, samples=self.samples, prefer_discrete=self.prefer_discrete
            )
        return self.renderer

    def info(self) -> dict:
        return self.renderer.info() if self.renderer is not None else {}

    def _layout(self, registry, roi, dmap):
        key = (id(registry), roi.as_tuple(), dmap, self.controls.viewpoint)
        if key != self._key:
            self._key = key
            if registry is None:
                self.camera, self.pieces = layout([], roi, dmap, self.controls.viewpoint)
            else:
                self.camera, self.pieces = layout(registry, roi, dmap, self.controls.viewpoint)
            if registry is None:
                self.effects.hits.clear()

    def render(
        self,
        frame,
        roi,
        registry,
        evidence,
        result,
        *,
        t: float,
        dmap: DisplayMap,
        status: UiStatus | None = None,
        target=None,
    ):
        """``frame``: the unmirrored camera image ``dmap`` describes (native full frame or tracking frame)."""
        renderer = self.renderer_for(dmap)
        self._layout(registry, roi, dmap)
        s = self.controls.settings
        self.effects.level, self.effects.trails_on = s.effects, s.trails
        if result is not None:
            self.effects.on_commits(result.commits, evidence, self.pieces, self.camera, dmap, roi, t)
        draws = self.effects.draws(self.pieces, t, target=target)
        overlay = self.effects.overlay(evidence, roi, dmap, t)
        img = renderer.render(
            frame,
            self.camera,
            draws,
            overlay,
            bloom=BLOOM if s.bloom else 0.0,
            alpha=GHOST_ALPHA if s.ghost else 1.0,
        )
        started = now()
        self.hud.draw(
            img,
            status=status or UiStatus(),
            evidence=evidence,
            roi=roi,
            dmap=dmap,
            camera=self.camera,
            pieces=self.pieces,
            controls=self.controls,
            t=t,
        )
        self.timings = {**renderer.timings, "hud_ms": (now() - started) * 1000}
        return img

    def mouse(self, event, x, y, flags=0, param=None):
        """``cv2.setMouseCallback`` handler (image pixel coordinates)."""
        if self.hud.layout is not None:
            self.controls.mouse(event, x, y, self.hud.layout)

    def key(self, key: int) -> bool:
        return self.controls.key(key)

    def release(self):
        if self.renderer is not None:
            self.renderer.release()
            self.renderer = None


__all__ = ["ARView", "GLUnavailable", "UiStatus"]
