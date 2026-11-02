"""SYNTHETIC checks of the AR view: display mapping, 3D alignment with the hit zones, meshes, hit effects,
controls, HUD content and (when an OpenGL 3.3 context exists) the GPU composite. No camera or window."""

import math
import time
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from spacedrums.calib.developer_demo import check_kit_pads
from spacedrums.calib.reach import ReachSettings
from spacedrums.capture import Roi
from spacedrums.contracts import HandId
from spacedrums.contracts.perception import EndpointEvidence
from spacedrums.geometry import ZoneRegistry
from spacedrums.geometry.four_pad import NAMES, SAMPLES
from spacedrums.geometry.kit_layout import kit_layout
from spacedrums.geometry.reference_kit import REFERENCE_PADS, reference_kit_layout
from spacedrums.ui.ar import meshes
from spacedrums.ui.ar.controls import EVENT_DOWN, EVENT_MOVE, EVENT_UP, Controls
from spacedrums.ui.ar.display_map import DisplayMap
from spacedrums.ui.ar.effects import Effects
from spacedrums.ui.ar.hud import Hud, HudLayout, UiStatus
from spacedrums.ui.ar.scene import VIEWPOINTS, layout
from spacedrums.ui.stage import StageRenderer

ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
NATIVE = DisplayMap.native(1280, 720, [159, 0, 960, 720], 640)
UPSCALED = DisplayMap.upscaled(640, 480, 1.5)
ROI = Roi(0, 0, 640, 480)
FULL_PADS = yaml.safe_load((ROOT / "configs/demo.fullkit.candidate.yaml").read_text())["product"][
    "developer_demo"
]["pads"]


def reference():
    return ZoneRegistry.from_config(reference_kit_layout())


def evidence(t=1.0, kind="MEASURED", tip=(0.4, 0.3), origin=(0.42, 0.7)):
    def one(h):
        if kind == "MISSING":
            return EndpointEvidence(0, t, h, "MISSING", "SYNTHETIC")
        return EndpointEvidence(0, t, h, kind, "SYNTHETIC", tip=tip, origin=origin, confidence=0.9)

    return {h: one(h) for h in HandId}


def commit(zone, hand=HandId.RIGHT, gain=1.0):
    return SimpleNamespace(zone_id=zone, hand_id=hand, gain=gain)


# -- reference kit -----------------------------------------------------------------------------------------


def test_reference_kit_keeps_four_pad_ids_samples_and_product_floors():
    check_kit_pads(REFERENCE_PADS, (640, 480), ReachSettings())
    zones = {z["zone_id"]: z for z in reference_kit_layout()}
    assert set(zones) == set(NAMES)
    assert all(zones[z]["sample_id"] == SAMPLES[z] and zones[z]["name"] == NAMES[z] for z in zones)
    # display order left to right: crash/ride, tom, snare, hi-hat (camera x is mirrored)
    centre = {z: 1 - np.mean([p[0] for p in zones[z]["shape"]["points"]]) for z in zones}
    assert centre["crash_ride"] < centre["tom1"] < centre["snare"] < centre["hihat"]
    edge = {z: zones[z]["impact_surface"]["p0"][1] for z in zones}
    assert edge["crash_ride"] < edge["tom1"] and edge["hihat"] < edge["snare"]  # cymbals above the drums


# -- display mapping and 3D alignment -------------------------------------------------------------------


@pytest.mark.parametrize("roi", [Roi(0, 0, 640, 480), Roi(40, 20, 560, 440)])
def test_display_map_matches_the_stage_renderer_and_the_native_mirror(roi):
    stage = StageRenderer()
    for p in [(0, 0), (1, 1), (0.25, 0.7), (0.9, 0.1)]:
        assert UPSCALED.to_display(p, roi) == pytest.approx(stage.to_display(p, roi, 640))
        # native: the tracking pixel X sits at 159 + 1.5 X in the unmirrored 1280-wide frame
        x_px = roi.x + p[0] * roi.w
        assert NATIVE.to_display(p, roi)[0] == pytest.approx(1280 - 1 - (159 + 1.5 * x_px) - 0.5, abs=0.51)
        assert NATIVE.to_display(p, roi)[1] == pytest.approx((roi.y + p[1] * roi.h) * 1.5)


@pytest.mark.parametrize("dmap", [NATIVE, UPSCALED], ids=["native", "upscaled"])
@pytest.mark.parametrize("viewpoint", list(VIEWPOINTS))
@pytest.mark.parametrize("kit", ["reference", "full"])
@pytest.mark.parametrize("roi", [Roi(0, 0, 640, 480), Roi(40, 20, 560, 440)])
def test_every_head_spans_exactly_its_impact_segment(dmap, viewpoint, kit, roi):
    registry = reference() if kit == "reference" else ZoneRegistry.from_config(kit_layout(FULL_PADS))
    camera, pieces = layout(registry, roi, dmap, viewpoint)
    assert len(pieces) == len(list(registry))
    for piece, zone in zip(pieces, registry, strict=True):
        want = sorted(dmap.to_display(q, roi) for q in (zone.impact_surface.p0, zone.impact_surface.p1))
        rim = piece.rim(camera)
        lo, hi = rim[rim[:, 0].argmin()], rim[rim[:, 0].argmax()]
        assert np.abs(lo - want[0]).max() <= 1.5 and np.abs(hi - want[1]).max() <= 1.5, piece.zone_id


def test_front_view_reads_like_the_reference_and_nearer_drums_occlude_cymbals():
    camera, pieces = layout(reference(), ROI, NATIVE)
    by = {p.zone_id: p for p in pieces}
    for zid, (lo, hi) in {"tom1": (0.22, 0.38), "snare": (0.22, 0.38), "crash_ride": (0.28, 0.46)}.items():
        rim = by[zid].rim(camera)
        ratio = np.ptp(rim[:, 1]) / np.ptp(rim[:, 0])
        assert lo <= ratio <= hi, (zid, ratio)
    assert by["tom1"].depth < by["crash_ride"].depth and by["snare"].depth < by["hihat"].depth
    assert {p.zone_id for p in pieces if p.cymbal} == {"crash_ride", "hihat"}
    assert by["tom1"].label == "Tom" and by["crash_ride"].label == "Crash / Ride"


# -- meshes ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("family", ["cymbal", "hihat", "snare", "tom"])
def test_meshes_are_finite_unit_normal_and_deterministic(family):
    a = meshes.build(family, shell_depth=0.9, stand_length=4.0)
    b = meshes.build(family, shell_depth=0.9, stand_length=4.0)
    assert [p.name for p in a] == [p.name for p in b]
    for pa, pb in zip(a, b, strict=True):
        assert np.isfinite(pa.vertices).all() and pa.indices.max() < len(pa.vertices)
        assert np.allclose(np.linalg.norm(pa.vertices[:, 3:], axis=1), 1, atol=1e-3)
        assert pa.vertices.tobytes() == pb.vertices.tobytes() and pa.frame in ("model", "base", "wobble")
    assert any(p.material == meshes.NEON for p in a)


# -- effects -------------------------------------------------------------------------------------------------


def scene():
    camera, pieces = layout(reference(), ROI, NATIVE)
    return camera, pieces


def test_effects_start_only_from_committed_strikes_and_decay_to_rest():
    camera, pieces = scene()
    fx = Effects()
    rest = {d.piece.zone_id: d.neon for d in fx.draws(pieces, 1.0)}
    fx.on_commits([], evidence(), pieces, camera, NATIVE, ROI, 1.0)
    assert not fx.hits and not len(fx.sparks)
    fx.on_commits([commit("snare")], evidence(), pieces, camera, NATIVE, ROI, 1.0)
    hit = {d.piece.zone_id: d for d in fx.draws(pieces, 1.02)}
    assert hit["snare"].neon > rest["snare"] + 1 and hit["snare"].hit[3] > 0
    assert hit["tom1"].neon == rest["tom1"] and hit["tom1"].hit[3] == 0
    assert len(fx.sparks) > 0
    later = {d.piece.zone_id: d for d in fx.draws(pieces, 2.2)}
    assert later["snare"].neon == pytest.approx(rest["snare"]) and later["snare"].hit[3] == 0


def test_a_roll_animates_every_commit_and_caps_sparks():
    camera, pieces = scene()
    fx = Effects(max_sparks=400)
    for i in range(20):  # 20 commits in 2 s, plus two in one frame
        fx.on_commits([commit("snare")], evidence(), pieces, camera, NATIVE, ROI, 1.0 + i * 0.1)
    fx.on_commits(
        [commit("tom1", HandId.LEFT), commit("hihat")], evidence(), pieces, camera, NATIVE, ROI, 3.0
    )
    assert fx.total == 22 and {"tom1", "hihat", "snare"} <= set(fx.hits)
    assert len(fx.sparks) <= 400
    draws = {d.piece.zone_id: d for d in fx.draws(pieces, 3.01)}
    assert draws["tom1"].hit[3] > 0 and draws["hihat"].wobble is not None


def test_effects_level_off_keeps_the_kit_at_rest():
    camera, pieces = scene()
    fx = Effects()
    fx.level = "off"
    fx.on_commits([commit("snare")], evidence(), pieces, camera, NATIVE, ROI, 1.0)
    assert not len(fx.sparks)
    assert all(d.hit[3] == 0 for d in fx.draws(pieces, 1.01))


def test_trails_follow_measured_tips_and_clear_on_loss_or_gap():
    fx = Effects()
    for i in range(5):
        fx.overlay(evidence(1.0 + i / 30, tip=(0.4, 0.3 + 0.01 * i)), ROI, NATIVE, 1.0 + i / 30)
    assert len(fx.trails[HandId.LEFT]) == 5
    fx.overlay(evidence(1.4, tip=(0.4, 0.5)), ROI, NATIVE, 1.4)  # a 0.27 s gap breaks the trail
    assert len(fx.trails[HandId.LEFT]) == 1
    uncertain = fx.overlay(evidence(1.43, kind="UNCERTAIN"), ROI, NATIVE, 1.43)
    assert not fx.trails[HandId.LEFT] and len(uncertain)  # an amber ring, no trail
    assert not len(fx.overlay(evidence(1.46, kind="MISSING"), ROI, NATIVE, 1.46))


# -- controls --------------------------------------------------------------------------------------------


def test_keys_change_settings_and_queue_session_actions():
    c = Controls()
    assert c.key(ord("]")) and c.key(ord("-")) and c.key(ord("v")) and c.key(ord("h"))
    assert not c.key(ord("q")) and not c.key(ord("r")) and not c.key(27)  # left to the session
    assert c.sensitivity == 0.75 and c.volume == 0.75 and c.viewpoint == "high" and not c.settings.panels
    assert c.drain() == [("sensitivity", 0.75), ("volume", 0.75), ("viewpoint", "high"), ("panels", False)]
    assert c.drain() == []
    for _ in range(30):
        c.key(ord("="))
    assert c.volume == 1.0  # clamped


@pytest.mark.parametrize("size", [(1280, 720), (960, 720)])
def test_mouse_drags_sliders_and_picks_menu_items(size):
    c = Controls(devices=[(0, "Integrated (Default)"), (2, "USB Camera")])
    lay = HudLayout(*size, c)
    # the right group never runs into the camera dropdown, even on a 4:3 window
    assert lay.sens_label[0] - 100 * lay.k > lay.camera_button.x1
    t = lay.volume_track
    y = (t.y0 + t.y1) // 2
    c.mouse(EVENT_DOWN, t.x0 + t.w // 4, y, lay)
    c.mouse(EVENT_MOVE, t.x0 + t.w // 2, y, lay)
    c.mouse(EVENT_UP, t.x0 + t.w // 2, y, lay)
    assert c.volume == pytest.approx(0.5, abs=0.02) and c.dragging is None
    b = lay.camera_button
    c.mouse(EVENT_DOWN, b.x0 + 5, b.y0 + 5, lay)
    assert c.menu == "camera"
    lay = HudLayout(*size, c)
    targets = {target: rect for rect, target in lay.items}
    r = targets["device:2"]
    c.mouse(EVENT_DOWN, r.x0 + 3, r.y0 + 3, lay)
    assert c.device == 2 and c.menu is None and ("device", 2) in c.drain()
    assert c.camera_label.startswith("USB Camera")


# -- HUD -----------------------------------------------------------------------------------------------------


class Recorder:
    def __init__(self, hud):
        self.texts = []
        original = hud.text.draw

        def draw(img, text, *a, **k):
            self.texts.append(text)
            return original(img, text, *a, **k)

        hud.text.draw = draw


def hud_texts(status, ev, size=(1280, 720)):
    camera, pieces = scene()
    hud = Hud()
    rec = Recorder(hud)
    img = np.full((size[1], size[0], 3), 70, np.uint8)
    hud.draw(
        img,
        status=status,
        evidence=ev,
        roi=ROI,
        dmap=NATIVE,
        camera=camera,
        pieces=pieces,
        controls=Controls(),
        t=1.0,
    )
    return rec.texts, img


def test_status_panel_shows_measurements_and_honest_gaps():
    texts, img = hud_texts(UiStatus(fps=29.6, latency_ms=41.2), evidence())
    for want in (
        "SpaceDrums",
        "AI Air Drumming",
        "FPS",
        "30",
        "Latency",
        "41 ms",
        "Detected",
        "Active",
        "Stick Tracking",
        "Left Stick",
        "Right Stick",
        "Crash / Ride",
        "Tom",
        "Snare",
        "Hi-Hat",
        "Settings",
        "Camera View",
        "Front (Default)",
        "Sensitivity",
        "0.7",
        "Volume",
        "0.8",
    ):
        assert want in texts, want
    texts, _ = hud_texts(UiStatus(), evidence(kind="MISSING"))
    assert texts.count("—") == 2 and "Not detected" in texts and texts.count("Lost") == 2
    assert "No stick" in texts


def test_hidden_panels_leave_the_kit_labels_and_bar():
    camera, pieces = scene()
    hud, c = Hud(), Controls()
    c.settings.panels = False
    rec = Recorder(hud)
    hud.draw(
        np.zeros((720, 1280, 3), np.uint8),
        status=UiStatus(30, 20),
        evidence=evidence(),
        roi=ROI,
        dmap=NATIVE,
        camera=camera,
        pieces=pieces,
        controls=c,
        t=1.0,
    )
    assert "FPS" not in rec.texts and "Snare" in rec.texts and "Volume" in rec.texts


def test_hud_cost_stays_small():
    camera, pieces = scene()
    hud, c = Hud(), Controls()
    img = np.full((720, 1280, 3), 70, np.uint8)
    for i in range(5):
        hud.draw(
            img.copy(),
            status=UiStatus(30, 28),
            evidence=evidence(),
            roi=ROI,
            dmap=NATIVE,
            camera=camera,
            pieces=pieces,
            controls=c,
            t=1 + i / 30,
        )
    start = time.perf_counter()
    for i in range(30):
        hud.draw(
            img.copy(),
            status=UiStatus(30, 28),
            evidence=evidence(),
            roi=ROI,
            dmap=NATIVE,
            camera=camera,
            pieces=pieces,
            controls=c,
            t=2 + i / 30,
        )
    per_frame = (time.perf_counter() - start) * 1000 / 30
    assert per_frame < 10, per_frame  # generous CI bound; live reports log ar_hud_ms


# -- GPU (skipped without an OpenGL 3.3 context) ---------------------------------------------------------


@pytest.fixture(scope="module")
def renderer():
    from spacedrums.ui.ar.gl import GLRenderer, GLUnavailable

    try:
        r = GLRenderer(1280, 720)
    except GLUnavailable as exc:
        pytest.skip(f"no OpenGL 3.3 context: {exc}")
    yield r
    r.release()


def frame():
    rng = np.random.default_rng(1)
    return rng.integers(0, 255, (720, 1280, 3), dtype=np.uint8)


def test_camera_pixels_pass_through_unchanged_and_mirrored(renderer):
    from spacedrums.ui.ar.gl import PieceDraw

    f = frame()
    keep = f.copy()
    img = renderer.render(f, layout([], ROI, NATIVE)[0], [])
    assert np.array_equal(img, f[:, ::-1]) and np.array_equal(f, keep)
    camera, pieces = scene()
    img = renderer.render(f, camera, [PieceDraw(p) for p in pieces], bloom=0.0)
    top = img[:60, :]  # above every piece: still the camera exactly
    assert np.array_equal(top, f[:60, ::-1])
    for p in pieces:  # the head centre is covered by the kit
        x, y = map(round, np.mean(p.segment, axis=0))
        assert np.abs(img[y, x].astype(int) - f[y, 1279 - x].astype(int)).max() > 10, p.zone_id


def test_a_hit_lights_its_piece_on_the_gpu(renderer):
    camera, pieces = scene()
    fx = Effects()
    f = np.full((720, 1280, 3), 40, np.uint8)
    rest = renderer.render(f, camera, fx.draws(pieces, 1.0))
    fx.on_commits([commit("snare")], evidence(), pieces, camera, NATIVE, ROI, 1.0)
    hit = renderer.render(f, camera, fx.draws(pieces, 1.02), fx.overlay({}, ROI, NATIVE, 1.02))
    snare = next(p for p in pieces if p.zone_id == "snare")
    (ax, ay), (bx, _) = snare.segment
    box = (slice(round(ay) - 30, round(ay) + 30), slice(round(ax), round(bx)))
    assert hit[box].astype(int).mean() > rest[box].astype(int).mean() + 8
    tom = next(p for p in pieces if p.zone_id == "tom1")
    (ax, ay), (bx, _) = tom.segment
    box = (slice(round(ay) - 10, round(ay) + 10), slice(round(ax) + 20, round(bx) - 20))
    assert np.abs(hit[box].astype(int) - rest[box].astype(int)).mean() < 3


def test_ar_view_render_cost_within_budget(renderer):
    from spacedrums.ui.ar.view import ARView

    view = ARView(renderer_factory=lambda w, h, **k: renderer)
    registry = reference()
    f = frame()
    result = SimpleNamespace(commits=[])
    for i in range(10):
        view.render(f, ROI, registry, evidence(1 + i / 30), result, t=1 + i / 30, dmap=NATIVE)
    times = []
    for i in range(40):
        hits = SimpleNamespace(commits=[commit("snare")] if i % 8 == 0 else [])
        start = time.perf_counter()
        img = view.render(
            f, ROI, registry, evidence(2 + i / 30), hits, t=2 + i / 30, dmap=NATIVE, status=UiStatus(30, 30)
        )
        times.append((time.perf_counter() - start) * 1000)
    assert img.shape == (720, 1280, 3)
    p95 = float(np.percentile(times, 95))
    assert p95 < 25, p95  # generous: the iGPU path is ~13 ms; the live report logs every ar_*_ms
    assert math.isfinite(view.timings["readback_ms"])
