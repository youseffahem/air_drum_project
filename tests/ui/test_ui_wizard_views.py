"""Phase 14 wizard views: pure drawing from plain data (SYNTHETIC frames)."""

import numpy as np
import yaml

from spacedrums.capture import Roi
from spacedrums.contracts import schema as contract_schema
from spacedrums.geometry import ZoneRegistry
from spacedrums.ui import WizardView, draw_wizard

ROI = Roi(40, 20, 560, 440)
ZONES = yaml.safe_load(
    (contract_schema.repo_root() / "configs/zones/mvp4.candidate.yaml").read_text(encoding="utf-8")
)["zones"]


def test_draws_on_a_copy_with_every_element():
    frame = np.full((480, 640, 3), 90, np.uint8)
    view = WizardView(
        step_number=4,
        n_steps=6,
        title="Zone placement",
        stage="REVIEW",
        lines=("scale 0.9",),
        keys="ENTER accept",
        progress=0.5,
        ok=True,
        band=(0.45, 0.75),
        envelope=(0.1, 0.25, 0.9, 0.8),
        registry=ZoneRegistry.from_config(ZONES),
        highlight_zone="snare",
        status_lines=("selected snare",),
    )
    out = draw_wizard(frame, ROI, view)
    assert out.shape == frame.shape and out is not frame and (frame == 90).all()
    assert not np.array_equal(out, frame)
    snare = (int(ROI.x + 0.40 * (ROI.w - 1)), int(ROI.y + 0.68 * (ROI.h - 1)))
    plain = draw_wizard(
        frame, ROI, WizardView(4, 6, "Zone placement", "REVIEW", registry=ZoneRegistry.from_config(ZONES))
    )
    assert not np.array_equal(out[snare[1], snare[0]], plain[snare[1], snare[0]])  # highlight fill


def test_no_frame_draws_a_canvas():
    out = draw_wizard(None, ROI, WizardView(1, 6, "Camera check", "INSTRUCT"), frame_size=(640, 480))
    assert out.shape == (480, 640, 3)
