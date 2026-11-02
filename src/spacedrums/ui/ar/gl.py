"""moderngl offscreen renderer: camera background, PBR kit, glow overlay and bloom, read back as BGR.

One standalone OpenGL 3.3 context, created and used on the calling (main) thread only. Per frame:
upload the camera frame (BGR, unmirrored) -> MSAA pass [kit meshes, additive overlay] into a
premultiplied colour and an emission target -> dual-Kawase bloom of the emission -> composite over the
mirrored camera -> RGBA8 readback. Outside the kit and its glow the result equals the camera image
(mirrored), byte for byte.

On Optimus laptops a standalone context lands on the integrated GPU; ``prefer_discrete`` sets the NVIDIA
shim variable (``SHIM_MCCOMPAT``) before the first context, which moves it to the discrete GPU.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import cv2
import numpy as np

from spacedrums.timing import now
from spacedrums.ui.ar import shaders
from spacedrums.ui.ar.meshes import HEAD, build
from spacedrums.ui.ar.scene import Piece, VirtualCamera

# Head tints (linear BGR): white coated snare, light grey tom.
HEAD_TINT = {"snare": (0.74, 0.74, 0.72), "tom": (0.46, 0.46, 0.46)}


class GLUnavailable(RuntimeError):
    """No usable OpenGL 3.3 context (moderngl missing, no driver, remote session)."""


def linear(bgr):
    return tuple((c / 255.0) ** 2.2 for c in bgr)


@dataclass
class PieceDraw:
    """Per-frame animation state of one piece (see ``effects.Effects.draws``)."""

    piece: Piece
    neon: float = 0.6
    hit: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # local impact xyz, strength
    hit_age: float = 1e3
    wobble: np.ndarray | None = None  # local 3x3 rotation of the cymbal parts


def prefer_discrete_gpu():
    """Ask the NVIDIA Optimus shim for the discrete GPU. It decides when the process first loads OpenGL
    (MediaPipe can do that while starting), so call this before any model or context is created."""
    os.environ.setdefault("SHIM_MCCOMPAT", "0x800000001")


def _mat(m) -> bytes:
    return np.asarray(m, "f4").T.tobytes()  # GLSL matrices are column-major


class GLRenderer:
    def __init__(
        self,
        width: int,
        height: int,
        *,
        samples: int = 4,
        bloom_levels: int = 5,
        prefer_discrete: bool = True,
    ):
        if bloom_levels < 2:
            raise ValueError("bloom needs at least two levels")
        if prefer_discrete:
            prefer_discrete_gpu()
        try:
            import moderngl
        except ImportError as exc:
            raise GLUnavailable("moderngl is not installed") from exc
        try:
            self.ctx = moderngl.create_standalone_context(require=330)
        except Exception as exc:  # noqa: BLE001 - any driver/context failure means "no GPU view"
            raise GLUnavailable(f"no OpenGL 3.3 context: {exc}") from exc
        self.mgl = moderngl
        self.width, self.height = width, height
        ctx = self.ctx
        prog = ctx.program
        self.kit = prog(vertex_shader=shaders.KIT_VS, fragment_shader=shaders.KIT_FS)
        self.overlay = prog(vertex_shader=shaders.OVERLAY_VS, fragment_shader=shaders.OVERLAY_FS)
        self.down = prog(vertex_shader=shaders.QUAD_VS, fragment_shader=shaders.DOWN_FS)
        self.up = prog(vertex_shader=shaders.QUAD_VS, fragment_shader=shaders.UP_FS)
        self.composite = prog(vertex_shader=shaders.QUAD_VS, fragment_shader=shaders.COMPOSITE_FS)
        quad = ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], "f4"))
        self.quads = {
            p: ctx.vertex_array(p, [(quad, "2f", "in_pos")]) for p in (self.down, self.up, self.composite)
        }
        self.samples = min(samples, ctx.max_samples)
        self.bloom_levels = bloom_levels
        self._targets = []
        self.resize(width, height)
        self.cam = None
        self.meshes = {}
        self.overlay_vbo = ctx.buffer(reserve=4096 * 7 * 4, dynamic=True)
        self.overlay_vao = ctx.vertex_array(
            self.overlay, [(self.overlay_vbo, "2f 4f 1f", "in_pos", "in_color", "in_emit")]
        )
        self.timings = {}

    # -- resources ---------------------------------------------------------------------------
    def resize(self, width: int, height: int):
        """(Re)allocate the size-dependent targets; the context, programs and meshes are kept, so a
        renderer warmed up before the camera starts never stalls the first frames."""
        for obj in self._targets:
            obj.release()
        ctx, size, samples = self.ctx, (width, height), self.samples
        self.width, self.height = width, height
        made = []

        def keep(obj):
            made.append(obj)
            return obj

        self.ms = keep(ctx.framebuffer(
            [keep(ctx.renderbuffer(size, 4, samples=samples)),
             keep(ctx.renderbuffer(size, 4, samples=samples, dtype="f2"))],
            keep(ctx.depth_renderbuffer(size, samples=samples)),
        ))
        self.color = keep(ctx.texture(size, 4))
        self.emit = keep(ctx.texture(size, 4, dtype="f2"))
        self.resolved = keep(ctx.framebuffer([self.color, self.emit]))
        self.levels = []
        w, h = width, height
        for _ in range(self.bloom_levels):
            w, h = max(1, w // 2), max(1, h // 2)
            down, up = keep(ctx.texture((w, h), 4, dtype="f2")), keep(ctx.texture((w, h), 4, dtype="f2"))
            for t in (down, up):
                t.repeat_x = t.repeat_y = False
            self.levels.append((down, keep(ctx.framebuffer([down])), up, keep(ctx.framebuffer([up]))))
        for t in (self.color, self.emit):
            t.repeat_x = t.repeat_y = False
        self.out = keep(ctx.framebuffer([keep(ctx.texture(size, 4))]))
        self.readback = bytearray(width * height * 4)
        self._targets = made

    def info(self) -> dict:
        i = self.ctx.info
        return {
            "renderer": i.get("GL_RENDERER"),
            "vendor": i.get("GL_VENDOR"),
            "version": i.get("GL_VERSION"),
            "samples": self.ms.color_attachments[0].samples,
            "size": [self.width, self.height],
        }

    def _camera_texture(self, frame):
        h, w = frame.shape[:2]
        if self.cam is None or self.cam.size != (w, h):
            if self.cam is not None:
                self.cam.release()
            self.cam = self.ctx.texture((w, h), 3)
            self.cam.filter = (self.mgl.LINEAR_MIPMAP_LINEAR, self.mgl.LINEAR)
            self.cam.repeat_x = self.cam.repeat_y = False
        self.cam.write(np.ascontiguousarray(frame))
        self.cam.build_mipmaps()
        return self.cam

    def piece_meshes(self, piece: Piece):
        key = (piece.family, round(piece.shell_depth, 3), round(piece.stand_length, 2))
        if key not in self.meshes:
            vaos = []
            for part in build(piece.family, shell_depth=piece.shell_depth, stand_length=piece.stand_length):
                vbo = self.ctx.buffer(part.vertices.tobytes())
                ibo = self.ctx.buffer(part.indices.tobytes())
                vao = self.ctx.vertex_array(self.kit, [(vbo, "3f 3f", "in_pos", "in_norm")], ibo)
                vaos.append((part, vao))
            self.meshes[key] = vaos
        return self.meshes[key]

    # -- frame ---------------------------------------------------------------------------------
    def render(
        self,
        frame,
        camera: VirtualCamera,
        draws: list[PieceDraw],
        overlay=None,
        *,
        bloom: float = 1.0,
        alpha: float = 1.0,
    ) -> np.ndarray:
        """``frame``: unmirrored BGR camera image; ``overlay``: (N*3, 7) float32 pixel-space triangles
        (x, y, b, g, r, a, emit) with 0-255 colours. Returns the mirrored, composed BGR display image
        (a new array)."""
        mgl, ctx = self.mgl, self.ctx
        t0 = now()
        cam = self._camera_texture(frame)
        t1 = now()
        self.ms.use()
        self.ms.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        ctx.disable(mgl.DEPTH_TEST | mgl.BLEND | mgl.CULL_FACE)
        if draws:
            self._draw_kit(camera, draws, alpha)
        if overlay is not None and len(overlay):
            self._draw_overlay(overlay)
        ctx.copy_framebuffer(self.resolved, self.ms)
        self._bloom()
        ctx.disable(mgl.BLEND | mgl.DEPTH_TEST)
        self.out.use()
        self.color.use(0)
        self.levels[0][2].use(1)
        cam.use(2)
        self.composite["u_color"], self.composite["u_bloom"], self.composite["u_cam"] = 0, 1, 2
        self.composite["u_bloom_k"] = bloom
        self.quads[self.composite].render(mgl.TRIANGLE_STRIP)
        t2 = now()
        self.out.read_into(self.readback, components=4)
        rgba = np.frombuffer(self.readback, np.uint8).reshape(self.height, self.width, 4)
        img = cv2.cvtColor(rgba, cv2.COLOR_BGRA2BGR)
        t3 = now()
        self.timings = {
            "upload_ms": (t1 - t0) * 1000,
            "draw_ms": (t2 - t1) * 1000,
            "readback_ms": (t3 - t2) * 1000,
        }
        return img

    def _draw_kit(self, camera, draws, alpha):
        mgl, ctx, prog = self.mgl, self.ctx, self.kit
        ctx.enable(mgl.DEPTH_TEST)
        if alpha < 1.0:  # premultiplied "ghost" kit
            ctx.enable(mgl.BLEND)
            ctx.blend_func = mgl.ONE, mgl.ONE_MINUS_SRC_ALPHA
        vp = camera.projection_matrix() @ camera.view_matrix()
        self.cam.use(0)
        prog["u_cam"] = 0
        prog["u_alpha"] = alpha
        for d in draws:
            p = d.piece
            frames = {
                "model": p.model_matrix(),
                "base": p.model_matrix(base=True),
                "wobble": p.model_matrix(extra=d.wobble) if d.wobble is not None else p.model_matrix(),
            }
            prog["u_accent"] = linear(p.accent)
            prog["u_neon"] = d.neon
            prog["u_head_tint"] = HEAD_TINT.get(p.family, HEAD_TINT["tom"])
            prog["u_hit_age"] = d.hit_age
            for part, vao in self.piece_meshes(p):
                m = frames[part.frame]
                prog["u_model"].write(_mat(m))
                prog["u_mvp"].write(_mat(vp @ m))
                prog["u_material"] = part.material
                prog["u_hit"] = d.hit if part.material == HEAD or part.frame == "wobble" else (0, 0, 0, 0)
                vao.render(mgl.TRIANGLES)
        ctx.disable(mgl.DEPTH_TEST | mgl.BLEND)

    def _draw_overlay(self, tris):
        mgl, ctx = self.mgl, self.ctx
        data = np.array(tris, "f4")
        data[:, 2:5] *= 1 / 255  # effects speak 0-255 BGR
        if data.nbytes > self.overlay_vbo.size:
            self.overlay_vbo.orphan(data.nbytes * 2)
        self.overlay_vbo.write(data.tobytes())
        ctx.enable(mgl.BLEND)
        ctx.blend_func = mgl.ONE, mgl.ONE
        self.overlay["u_screen"] = (self.width, self.height)
        self.overlay_vao.render(mgl.TRIANGLES, vertices=len(data))
        ctx.disable(mgl.BLEND)

    def _bloom(self):
        mgl = self.mgl
        self.ctx.disable(mgl.BLEND | mgl.DEPTH_TEST)
        src = self.emit
        for down, fbo, _, _ in self.levels:
            fbo.use()
            src.use(0)
            self.down["u_src"] = 0
            self.down["u_half"] = (0.5 / src.width, 0.5 / src.height)
            self.quads[self.down].render(mgl.TRIANGLE_STRIP)
            src = down
        for i in range(len(self.levels) - 2, -1, -1):  # upsample, adding the next larger level
            down, _, up, up_fbo = self.levels[i]
            small = self.levels[i + 1][0] if i == len(self.levels) - 2 else self.levels[i + 1][2]
            up_fbo.use()
            small.use(0)
            down.use(1)
            self.up["u_src"], self.up["u_add"] = 0, 1
            self.up["u_half"] = (0.5 / small.width, 0.5 / small.height)
            self.quads[self.up].render(mgl.TRIANGLE_STRIP)

    def release(self):
        try:
            self.ctx.release()
        except Exception:  # noqa: BLE001 - releasing a lost context must not mask the run's own error
            pass


__all__ = ["GLRenderer", "GLUnavailable", "PieceDraw", "linear", "prefer_discrete_gpu"]
