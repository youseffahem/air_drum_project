"""Seven-piece kit without a kick: hi-hat, snare, three toms, crash and ride.

Pads are given in the player's mirrored display; camera coordinates are mirrored here
exactly as in ``four_pad``. No default is a calibrated layout.
"""

from __future__ import annotations

import math

from spacedrums.geometry.four_pad import pad_zone

KIT_NAMES = {
    "crash": "Crash",
    "ride": "Ride",
    "hihat": "Hi-Hat",
    "snare": "Snare",
    "tom1": "Tom 1",
    "tom2": "Tom 2",
    "floor_tom": "Floor Tom",
}
# Sample *group* ids of assets/samples/acoustic-manifest.json (acoustic Salamander Drumkit; each group has
# soft/hard layers and round-robin takes). The four-pad kit keeps its own TR-505 ids in ``four_pad``.
KIT_SAMPLES = {
    "crash": "salamander-crash",
    "ride": "salamander-ride",
    "hihat": "salamander-hihat",
    "snare": "salamander-snare",
    "tom1": "salamander-tom1",
    "tom2": "salamander-tom2",
    "floor_tom": "salamander-floor-tom",
}
CYMBALS = frozenset({"crash", "ride", "hihat", "crash_ride"})


def kit_layout(pads: list[dict], *, mirror: bool = True) -> list[dict]:
    """``pads``: dicts of zone_id, x (display centre), y (top strike edge), width, height."""
    if not pads:
        raise ValueError("a kit needs at least one pad")
    boxes, zones = [], []
    for pad in pads:
        zid = pad["zone_id"]
        if zid not in KIT_NAMES:
            raise ValueError(f"unknown kit pad {zid!r}")
        x, y, w, h = (float(pad[k]) for k in ("x", "y", "width", "height"))
        if not all(math.isfinite(v) for v in (x, y, w, h)) or min(w, h) <= 0:
            raise ValueError("pad values must be finite and positive")
        if x - w / 2 < 0 or x + w / 2 > 1 or y < 0 or y + h > 1:
            raise ValueError(f"pad {zid} must be inside the ROI")
        if any(zid == other[0] for other in boxes):
            raise ValueError(f"duplicate pad {zid}")
        for oid, ox0, oy0, ox1, oy1 in boxes:
            if x - w / 2 < ox1 and ox0 < x + w / 2 and y < oy1 and oy0 < y + h:
                raise ValueError(f"pads {zid} and {oid} overlap")
        boxes.append((zid, x - w / 2, y, x + w / 2, y + h))
        zones.append(pad_zone(zid, KIT_NAMES[zid], KIT_SAMPLES[zid], 1 - x if mirror else x, y, w, h))
    return zones


def pad_gaps_px(pads: list[dict], roi_size: tuple[int, int]) -> tuple[float, float]:
    """Smallest horizontal / vertical clearance (px) between any two pads that share the other axis."""
    w, h = roi_size
    horizontal = vertical = math.inf
    for i, a in enumerate(pads):
        for b in pads[i + 1 :]:
            dx = abs(a["x"] - b["x"]) - (a["width"] + b["width"]) / 2
            dy = max(a["y"], b["y"]) - min(a["y"] + a["height"], b["y"] + b["height"])
            if dy < 0:  # rows overlap vertically: horizontal clearance matters
                horizontal = min(horizontal, dx * w)
            if dx < 0:  # columns overlap: vertical clearance matters
                vertical = min(vertical, dy * h)
    return horizontal, vertical


def pad_clearance_px(a: dict, b: dict, roi_size: tuple[int, int]) -> tuple[float, float]:
    """Signed (horizontal, vertical) clearance in px between two pads; negative = overlap on that axis."""
    w, h = roi_size
    dx = abs(a["x"] - b["x"]) - (a["width"] + b["width"]) / 2
    dy = max(a["y"], b["y"]) - min(a["y"] + a["height"], b["y"] + b["height"])
    return dx * w, dy * h


def kit_clearance_failures(
    pads: list[dict], roi_size: tuple[int, int], horizontal_gap_px: float, vertical_gap_px: float
) -> list[tuple[str, str, float, float]]:
    """Every pair that is separated by neither the horizontal nor the vertical gap floor.

    Unlike ``pad_gaps_px`` this also judges diagonal neighbours: a pair passes if it clears the
    horizontal floor in x *or* the vertical floor in y.
    """
    failures = []
    for i, a in enumerate(pads):
        for b in pads[i + 1 :]:
            dx, dy = pad_clearance_px(a, b, roi_size)
            if dx < horizontal_gap_px and dy < vertical_gap_px:
                failures.append((a["zone_id"], b["zone_id"], dx, dy))
    return failures


def transform_pads(pads: list[dict], dx: float = 0.0, dy: float = 0.0, scale: float = 1.0) -> list[dict]:
    """Shift the whole kit by (dx, dy) ROI units and scale positions and sizes about its centroid.

    The result is only a candidate: callers validate it (``kit_layout`` / floors) and may reject it.
    """
    if scale <= 0 or not all(math.isfinite(v) for v in (dx, dy, scale)):
        raise ValueError("kit transform must be finite with a positive scale")
    cx = sum(p["x"] for p in pads) / len(pads)
    cy = sum(p["y"] + p["height"] / 2 for p in pads) / len(pads)
    out = []
    for p in pads:
        w, h = p["width"] * scale, p["height"] * scale
        x = cx + (p["x"] - cx) * scale + dx
        y = cy + (p["y"] + p["height"] / 2 - cy) * scale + dy - h / 2
        out.append({**p, "x": round(x, 4), "y": round(y, 4), "width": round(w, 4), "height": round(h, 4)})
    return out


PAD_KEYS = ("zone_id", "x", "y", "width", "height")


def save_pads(path, pads: list[dict], *, note: str = "") -> None:
    """Write pads (display coordinates) as a YAML file ``--kit-layout`` can load."""
    import yaml

    doc = {"pads": [{k: (p[k] if k == "zone_id" else round(float(p[k]), 4)) for k in PAD_KEYS} for p in pads]}
    header = "# Saved by app.play --layout-preview. Mirrored display coordinates, ROI-normalised.\n"
    header += f"# {note}\n" if note else ""
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(header + yaml.safe_dump(doc, sort_keys=False, default_flow_style=None))


def load_pads(path) -> list[dict]:
    """Read a saved pads file; shape is checked here, geometry by ``kit_layout`` and the product floors."""
    import yaml

    with open(path, encoding="utf-8") as stream:
        doc = yaml.safe_load(stream)
    pads = doc.get("pads") if isinstance(doc, dict) else None
    if not isinstance(pads, list) or not pads:
        raise ValueError(f"{path}: expected a non-empty 'pads' list")
    out = []
    for pad in pads:
        if not isinstance(pad, dict) or set(pad) != set(PAD_KEYS):
            raise ValueError(f"{path}: each pad needs exactly {', '.join(PAD_KEYS)}")
        out.append({"zone_id": str(pad["zone_id"]), **{k: float(pad[k]) for k in PAD_KEYS[1:]}})
    return out
