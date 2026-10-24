"""Procedural drum and cymbal meshes (pure NumPy, built once and uploaded to the GPU).

Every piece is modelled at unit head radius with the head (or cymbal) plane at y = 0 and y up; the scene's
model matrix scales and places it. A part is drawn with one material and one of three frames:
``model`` (tilted with the piece), ``base`` (stands: stay vertical) or ``wobble`` (cymbal parts that swing
on a hit). Vertices are interleaved float32 ``position(3) normal(3)``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

LACQUER, CHROME, HEAD, BRASS, NEON, DARK = range(6)


@dataclass(frozen=True)
class Part:
    name: str
    material: int
    frame: str  # "model" | "base" | "wobble"
    vertices: np.ndarray  # (N, 6) float32
    indices: np.ndarray  # (M,) uint32


def _grid_indices(rows, cols):
    """Quads between consecutive rings of ``cols`` vertices (the seam vertex is duplicated)."""
    r, c = np.meshgrid(np.arange(rows - 1), np.arange(cols - 1), indexing="ij")
    a = r * cols + c
    b, d = a + cols, a + 1
    e = b + 1
    return np.stack((a, b, d, d, b, e), axis=-1).reshape(-1).astype(np.uint32)


def lathe(profile, segments=96, *, normals=None):
    """Revolve ``profile`` [(r, y), ...] about y. Normals rotate the profile tangent counter-clockwise
    (r, y plane): traverse a solid from its top centre outward, down its wall, then inward along its
    bottom, so every normal points out."""
    prof = np.asarray(profile, float)
    if normals is None:
        tangent = np.gradient(prof, axis=0)
        tangent /= np.linalg.norm(tangent, axis=1, keepdims=True) + 1e-12
        normals = np.stack((-tangent[:, 1], tangent[:, 0]), axis=-1)  # CCW: (-dy, dr)
    normals = np.asarray(normals, float)
    theta = np.linspace(0, 2 * math.pi, segments + 1)
    ct, st = np.cos(theta), np.sin(theta)
    pos = np.stack(
        (prof[:, None, 0] * ct, np.repeat(prof[:, None, 1], len(theta), 1), prof[:, None, 0] * st), axis=-1
    )
    nor = np.stack(
        (normals[:, None, 0] * ct, np.repeat(normals[:, None, 1], len(theta), 1), normals[:, None, 0] * st),
        axis=-1,
    )
    verts = np.concatenate((pos.reshape(-1, 3), nor.reshape(-1, 3)), axis=1).astype(np.float32)
    return verts, _grid_indices(len(prof), len(theta))


def torus(major, minor, y=0.0, segments=96, sides=12):
    a = np.linspace(0, 2 * math.pi, sides + 1)
    profile = np.stack((major + minor * np.cos(a), y + minor * np.sin(a)), axis=-1)
    normals = np.stack((np.cos(a), np.sin(a)), axis=-1)
    return lathe(profile, segments, normals=normals)


def tube(p0, p1, radius, sides=12, caps=True):
    """Cylinder between two points."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    axis = p1 - p0
    length = np.linalg.norm(axis)
    w = axis / length
    helper = np.array([1.0, 0, 0]) if abs(w[0]) < 0.9 else np.array([0, 0, 1.0])
    u = np.cross(w, helper)
    u /= np.linalg.norm(u)
    v = np.cross(w, u)
    a = np.linspace(0, 2 * math.pi, sides + 1)
    ring = np.cos(a)[:, None] * u + np.sin(a)[:, None] * v
    pos = np.concatenate((p0 + radius * ring, p1 + radius * ring))
    nor = np.concatenate((ring, ring))
    verts = [np.concatenate((pos, nor), axis=1)]
    idx = [_grid_indices(2, sides + 1)]
    if caps:
        base = 2 * (sides + 1)
        for p, n in ((p0, -w), (p1, w)):
            fan = np.concatenate((p[None], p + radius * ring[:-1]))
            verts.append(np.concatenate((fan, np.repeat(n[None], len(fan), 0)), axis=1))
            k = np.arange(1, sides + 1)
            idx.append(np.stack((np.zeros(sides, int), k, k % sides + 1), axis=-1).reshape(-1) + base)
            base += len(fan)
    return np.concatenate(verts).astype(np.float32), np.concatenate(idx).astype(np.uint32)


def merge(*meshes):
    verts, idx, base = [], [], 0
    for v, i in meshes:
        verts.append(v)
        idx.append(i + base)
        base += len(v)
    return np.concatenate(verts).astype(np.float32), np.concatenate(idx).astype(np.uint32)


def tripod(top_y, floor_y, spread=0.75, radius=0.075, start=0.0):
    """A centre post from ``top_y`` to just above the floor, three splayed legs and their braces."""
    knee = floor_y + 0.55
    parts = [tube((0, top_y, 0), (0, knee, 0), radius)]
    for k in range(3):
        a = start + k * 2 * math.pi / 3
        foot = (spread * math.cos(a), floor_y, spread * math.sin(a))
        parts.append(tube((0, knee + 0.15, 0), foot, radius * 0.8))
        parts.append(
            tube((0, knee - 0.25, 0), (foot[0] * 0.55, floor_y + 0.18, foot[2] * 0.55), radius * 0.5)
        )
    return merge(*parts)


def _part(name, material, frame, mesh):
    return Part(name, material, frame, *mesh)


def drum(kind: str, shell_depth: float, stand_length: float) -> list[Part]:
    """Snare or tom: lacquered shell, coated head, chrome hoops, tube lugs, tension rods, a neon hoop."""
    d = shell_depth
    lugs = 10 if kind == "snare" else 8
    hardware = []
    for k in range(lugs):
        a = (k + 0.5) * 2 * math.pi / lugs
        c, s = math.cos(a), math.sin(a)
        hardware.append(tube((1.04 * c, -0.13, 1.04 * s), (1.04 * c, -d + 0.13, 1.04 * s), 0.042))
        for y in (-0.13, -d + 0.13):  # lug end blocks
            hardware.append(tube((1.0 * c, y, 1.0 * s), (1.085 * c, y, 1.085 * s), 0.05))
        hardware.append(tube((1.05 * c, 0.035, 1.05 * s), (1.05 * c, -0.13, 1.05 * s), 0.015))
        hardware.append(tube((1.05 * c, -d - 0.03, 1.05 * s), (1.05 * c, -d + 0.13, 1.05 * s), 0.015))
    floor = -stand_length
    legs = tripod(-d - 0.12, floor, spread=0.9, start=math.pi / 6)
    basket = [
        tube((0, -d - 0.16, 0), (0.75 * math.cos(a), -d - 0.01, 0.75 * math.sin(a)), 0.035)
        for a in (math.pi / 2, math.pi / 2 + 2.09, math.pi / 2 + 4.19)
    ]
    head = [(0.0, 0.012), (0.5, 0.012), (0.9, 0.011), (0.975, 0.006), (0.988, -0.02)]
    return [
        _part("shell", LACQUER, "model", lathe([(0.985, -0.02), (0.985, -d / 2), (0.985, -d + 0.02)])),
        _part("head", HEAD, "model", lathe(head, 128)),
        _part("hoop", CHROME, "model", merge(torus(1.015, 0.038, 0.014), torus(1.008, 0.034, -d))),
        _part("neon", NEON, "model", torus(1.05, 0.013, -0.04, sides=8)),
        _part("hardware", CHROME, "model", merge(*hardware, *basket)),
        _part("stand", CHROME, "base", legs),
    ]


def _cymbal_profile(bell_r=0.2, bell_h=0.11, edge_drop=0.05, samples=48):
    r = np.linspace(0.0, 1.0, samples)
    bell = bell_h * np.clip(1 - (r / bell_r) ** 2, 0, None) ** 0.6
    bow = -edge_drop * np.clip((r - bell_r) / (1 - bell_r), 0, None) ** 1.4
    return np.stack((r, 0.02 + bell + bow), axis=-1)


def cymbal_disc(flip=False, bell_r=0.2, bell_h=0.11, thickness=0.014, segments=128):
    top = _cymbal_profile(bell_r, bell_h)
    bottom = top[::-1] - [0, thickness]
    edge = np.array([top[-1], top[-1] - [0, thickness]])
    meshes = [lathe(top, segments), lathe(bottom, segments), lathe(edge, segments)]
    v, i = merge(*meshes)
    if flip:  # an upside-down cymbal (hi-hat bottom): mirror y, flip normals' y and the winding
        v = v.copy()
        v[:, 1] *= -1
        v[:, 4] *= -1
        i = i.reshape(-1, 3)[:, ::-1].reshape(-1).copy()
    return v, i


def cymbal(stand_length: float) -> list[Part]:
    """Crash/ride: brass disc with a bell, felt and wing nut, a neon edge and a chrome stand."""
    floor = -stand_length
    nut = merge(
        lathe([(0.0, 0.24), (0.05, 0.24), (0.05, 0.2), (0.0, 0.2)], 24),
        tube((-0.09, 0.225, 0), (0.09, 0.225, 0), 0.02),
    )
    return [
        _part("disc", BRASS, "wobble", cymbal_disc()),
        _part("neon", NEON, "wobble", torus(1.0, 0.012, -0.035, segments=128, sides=8)),
        _part("felt", DARK, "wobble", lathe([(0.0, 0.2), (0.075, 0.2), (0.075, 0.13), (0.0, 0.13)], 24)),
        _part("nut", CHROME, "wobble", nut),
        _part(
            "stand",
            CHROME,
            "base",
            merge(
                tube((0, 0.2, 0), (0, -0.25, 0), 0.04),
                lathe([(0.0, -0.22), (0.1, -0.25), (0.1, -0.35), (0.0, -0.38)], 24),
                tripod(-0.38, floor, spread=0.95),
            ),
        ),
    ]


def hihat(stand_length: float) -> list[Part]:
    """Two brass cymbals with a clutch and pull rod, a neon edge and a chrome stand."""
    floor = -stand_length
    bottom_v, bottom_i = cymbal_disc(flip=True, bell_r=0.18, bell_h=0.08)
    bottom_v = bottom_v.copy()
    bottom_v[:, 1] -= 0.07
    return [
        _part("disc", BRASS, "wobble", cymbal_disc(bell_r=0.18, bell_h=0.08)),
        _part("bottom", BRASS, "model", (bottom_v, bottom_i)),
        _part("neon", NEON, "wobble", torus(1.0, 0.012, -0.03, segments=128, sides=8)),
        _part("clutch", CHROME, "wobble", lathe([(0.0, 0.17), (0.055, 0.17), (0.055, 0.1), (0.0, 0.1)], 24)),
        _part(
            "stand",
            CHROME,
            "base",
            merge(
                tube((0, 0.62, 0), (0, -0.1, 0), 0.018),
                tube((0, -0.14, 0), (0, -0.7, 0), 0.06),
                tripod(-0.7, floor, spread=0.9),
            ),
        ),
    ]


def build(family: str, *, shell_depth: float = 0.0, stand_length: float = 3.0) -> list[Part]:
    if family == "cymbal":
        return cymbal(stand_length)
    if family == "hihat":
        return hihat(stand_length)
    return drum(family, shell_depth, stand_length)


__all__ = ["BRASS", "CHROME", "DARK", "HEAD", "LACQUER", "NEON", "Part", "build", "lathe", "torus", "tube"]
