"""Virtual camera and piece placement for the AR kit (pure NumPy; no GL here).

The invariant: each zone's impact segment (its top strike edge, mapped to display pixels by
``DisplayMap``) is the horizontal major axis of the drawn head or cymbal ellipse, and the head centre
projects onto the segment midpoint. A stick crossing the drawn head line is exactly a crossing of the
hit zone's edge. The renderer only reads zones; nothing here moves them.

World units are arbitrary (about metres). The camera sits at the origin and looks down ``-z`` with a
downward ``pitch``; pieces lower on the screen are nearer, so a drum occludes a cymbal behind it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from spacedrums.capture.roi import Roi
from spacedrums.ui.ar.display_map import DisplayMap
from spacedrums.ui.ar.palette import CYMBAL_FAMILIES, accent, family, label

FOV_Y_DEG = 46.0
# Camera View "viewpoint" presets: virtual camera pitch in degrees. Alignment is re-solved for each.
VIEWPOINTS = {"front": 6.0, "high": 16.0, "low": 1.0}
VIEW_NAMES = {"front": "Front (Default)", "high": "High Angle", "low": "Low Angle"}
# Pieces tilt toward the player like a real kit: cymbals more than drums. With the front viewpoint the
# heads read as ellipses of about 0.30 (drums), 0.36 (crash) and 0.26 (hi-hat), as on the reference.
TILT_DEG = {"cymbal": 17.0, "hihat": 9.0, "snare": 4.0, "tom": 4.0}
# Shell depth (drums) in head radii.
SHELL_DEPTH = {"snare": 0.85, "tom": 1.5}
D_NEAR, D_FAR = 1.6, 2.4
RIM_SAMPLES = 1440


def _rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], float)


def rot_axis(axis, a):
    x, y, z = np.asarray(axis, float) / np.linalg.norm(axis)
    c, s, t = math.cos(a), math.sin(a), 1 - math.cos(a)
    return np.array(
        [
            [t * x * x + c, t * x * y - s * z, t * x * z + s * y],
            [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
            [t * x * z - s * y, t * y * z + s * x, t * z * z + c],
        ],
        float,
    )


@dataclass(frozen=True)
class VirtualCamera:
    width: int
    height: int
    pitch_deg: float = VIEWPOINTS["front"]
    fov_y_deg: float = FOV_Y_DEG

    @property
    def fy(self) -> float:
        return self.height / 2 / math.tan(math.radians(self.fov_y_deg) / 2)

    @property
    def fx(self) -> float:
        return self.fy

    @property
    def cx(self) -> float:
        return self.width / 2

    @property
    def cy(self) -> float:
        return self.height / 2

    @property
    def basis(self):
        """(right, up, forward) world unit vectors."""
        t = math.radians(self.pitch_deg)
        return (
            np.array([1.0, 0.0, 0.0]),
            np.array([0.0, math.cos(t), -math.sin(t)]),
            np.array([0.0, -math.sin(t), -math.cos(t)]),
        )

    def project(self, points) -> np.ndarray:
        """World points (N, 3) -> display pixels (N, 2), y down."""
        r, u, f = self.basis
        p = np.asarray(points, float)
        d = p @ f
        return np.stack((self.cx + self.fx * (p @ r) / d, self.cy - self.fy * (p @ u) / d), axis=-1)

    def unproject(self, px, py, depth) -> np.ndarray:
        r, u, f = self.basis
        return ((px - self.cx) * depth / self.fx) * r + (-(py - self.cy) * depth / self.fy) * u + depth * f

    def view_matrix(self) -> np.ndarray:
        r, u, f = self.basis
        m = np.eye(4)
        m[0, :3], m[1, :3], m[2, :3] = r, u, -f
        return m

    def projection_matrix(self, near=0.05, far=50.0) -> np.ndarray:
        w, h = self.width, self.height
        return np.array(
            [
                [2 * self.fx / w, 0, -(2 * self.cx / w - 1), 0],
                [0, 2 * self.fy / h, -(1 - 2 * self.cy / h), 0],
                [0, 0, -(far + near) / (far - near), -2 * far * near / (far - near)],
                [0, 0, -1, 0],
            ]
        )


@dataclass
class Piece:
    zone_id: str
    name: str
    label: str
    family: str
    accent: tuple[int, int, int]
    segment: tuple[tuple[float, float], tuple[float, float]]  # display impact edge, left to right
    center: np.ndarray
    radius: float
    rotation: np.ndarray  # roll . tilt (3x3)
    base_rotation: np.ndarray  # roll only: stands stay vertical
    depth: float
    stand_length: float = 0.0  # local units (radii) from the centre down to below the screen
    shell_depth: float = 0.0
    zone_box: tuple[int, int, int, int] = (0, 0, 0, 0)  # display box of the hit-zone polygon
    meta: dict = field(default_factory=dict)

    @property
    def cymbal(self) -> bool:
        return self.family in CYMBAL_FAMILIES

    def model_matrix(self, *, base=False, extra=None) -> np.ndarray:
        """Local (unit radius, head plane y=0) -> world. ``extra``: a local 3x3 applied first (wobble)."""
        rot = self.base_rotation if base else self.rotation
        if extra is not None:
            rot = rot @ extra
        m = np.eye(4)
        m[:3, :3] = rot * self.radius
        m[:3, 3] = self.center
        return m

    def to_world(self, local, *, base=False) -> np.ndarray:
        rot = self.base_rotation if base else self.rotation
        return self.center + (np.asarray(local, float) @ rot.T) * self.radius

    def rim(self, camera: VirtualCamera, samples=RIM_SAMPLES) -> np.ndarray:
        phi = np.linspace(0, 2 * math.pi, samples, endpoint=False)
        circle = np.stack((np.cos(phi), np.zeros_like(phi), np.sin(phi)), axis=-1)
        return camera.project(self.to_world(circle))

    def head_point(self, camera: VirtualCamera, display_xy) -> np.ndarray:
        """Local head-plane point (x, 0, z) seen at ``display_xy`` (ray / plane intersection)."""
        r, u, f = camera.basis
        ray = (
            ((display_xy[0] - camera.cx) / camera.fx) * r - ((display_xy[1] - camera.cy) / camera.fy) * u + f
        )
        normal = self.rotation[:, 1]
        denom = ray @ normal
        if abs(denom) < 1e-9:
            return np.zeros(3)
        world = ray * ((self.center @ normal) / denom)
        local = (world - self.center) @ self.rotation / self.radius
        local[1] = 0.0
        n = np.linalg.norm(local)
        return local if n <= 0.95 else local * (0.95 / n)


def _extremes(rim):
    i, j = int(np.argmin(rim[:, 0])), int(np.argmax(rim[:, 0]))
    return rim[i], rim[j]


def place(camera: VirtualCamera, a, b, depth, tilt_deg) -> tuple[np.ndarray, float, np.ndarray, np.ndarray]:
    """Centre, radius, rotation, base rotation so the head's horizontal extremes land on ``a`` and ``b``."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if a[0] > b[0]:
        a, b = b, a
    mid = (a + b) / 2
    _, _, f = camera.basis
    center = camera.unproject(mid[0], mid[1], depth)
    radius = (b[0] - a[0]) / 2 * depth / camera.fx
    tilt = _rot_x(math.radians(tilt_deg))
    roll = 0.0
    want = math.atan2(b[1] - a[1], b[0] - a[0])
    phi = np.linspace(0, 2 * math.pi, RIM_SAMPLES, endpoint=False)
    circle = np.stack((np.cos(phi), np.zeros_like(phi), np.sin(phi)), axis=-1)

    def extremes(c, rad, rl):
        rot = rot_axis(f, rl) @ tilt
        return _extremes(camera.project(c + (circle @ rot.T) * rad))

    for _ in range(12):
        lo, hi = extremes(center, radius, roll)
        radius *= (b[0] - a[0]) / max(1e-9, hi[0] - lo[0])
        lo, hi = extremes(center, radius, roll)
        err = mid - (lo + hi) / 2
        d = (center - 0) @ f
        r_, u_, _ = camera.basis
        center = center + (err[0] * d / camera.fx) * r_ + (-err[1] * d / camera.fy) * u_
        lo, hi = extremes(center, radius, roll)
        got = math.atan2(hi[1] - lo[1], hi[0] - lo[0])
        # d(angle)/d(roll) is about +0.8 for a roll about the camera axis; a plain step converges.
        roll -= got - want
        if abs(got - want) < 1e-5 and np.abs(err).max() < 0.05:
            break
    rot_roll = rot_axis(f, roll)
    return center, radius, rot_roll @ tilt, rot_roll


def depth_for(y_px: float, height: int) -> float:
    """Lower on the screen = nearer."""
    k = min(1.0, max(0.0, y_px / height))
    return D_FAR + (D_NEAR - D_FAR) * k


def layout(
    registry, roi: Roi, dmap: DisplayMap, viewpoint: str = "front"
) -> tuple[VirtualCamera, list[Piece]]:
    """One ``Piece`` per zone, aligned to its impact segment, plus the camera they were solved for."""
    camera = VirtualCamera(dmap.out_w, dmap.out_h, VIEWPOINTS[viewpoint])
    ids = [z.zone_id for z in registry]
    pieces = []
    for zone in registry:
        a = dmap.to_display(zone.impact_surface.p0, roi)
        b = dmap.to_display(zone.impact_surface.p1, roi)
        a, b = sorted((a, b))
        fam = family(zone.zone_id)
        depth = depth_for((a[1] + b[1]) / 2, dmap.out_h)
        center, radius, rot, base = place(camera, a, b, depth, TILT_DEG[fam])
        pts = np.array([dmap.to_display(p, roi) for p in zone.shape.points])
        box = (
            int(pts[:, 0].min()),
            int(pts[:, 1].min()),
            int(np.ceil(pts[:, 0].max())),
            int(np.ceil(pts[:, 1].max())),
        )
        pieces.append(
            Piece(
                zone.zone_id,
                zone.name,
                label(zone.zone_id, zone.name, ids),
                fam,
                accent(zone.zone_id),
                (tuple(a), tuple(b)),
                center,
                radius,
                rot,
                base,
                depth,
                shell_depth=SHELL_DEPTH.get(fam, 0.0),
                zone_box=box,
            )
        )
    # Stands reach below the bottom of the screen: a common floor under the lowest visible point.
    floor = min(camera.unproject(camera.cx, dmap.out_h * 1.25, p.depth)[1] for p in pieces) if pieces else 0
    for p in pieces:
        p.stand_length = max(0.5, (p.center[1] - floor) / p.radius)
    return camera, pieces


__all__ = ["VIEWPOINTS", "VIEW_NAMES", "Piece", "VirtualCamera", "depth_for", "layout", "place", "rot_axis"]
