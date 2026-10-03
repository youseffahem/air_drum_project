"""Automatic standing/reach/held-out stroke checks, no manual drum placement.

Physical movement is necessary. Failure preserves the observations and exposes
a retry; it never substitutes a template for a failed measured fit.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict

import numpy as np

from spacedrums.calib.reach import ReachSettings, StrokeCollector, fit_reach
from spacedrums.contracts.perception import BodyReference
from spacedrums.geometry.four_pad import DISPLAY_ORDER, NAMES, four_pad_layout


class AutomaticCalibration:
    def __init__(self, roi_size, *, settings=None, mirror=True, provenance="DEVELOPER_LIVE"):
        settings = settings or ReachSettings()
        if provenance not in ("SYNTHETIC", "DEVELOPER_LIVE", "DEVELOPER_REPLAY"):
            raise ValueError("product calibration supports developer evidence only")
        self.provenance = provenance
        self.roi_size, self.settings, self.mirror = roi_size, settings, mirror
        self.state = "STAND"
        self.message = "Stand in the frame, with your waist and both sticks in view"
        self.body = None
        self.bodies = deque(maxlen=16)
        self.collector = StrokeCollector(settings)
        self.verifier = StrokeCollector(settings)
        self.target_index = 0
        self.target_started = None
        self.fit = None
        self.zones = []
        self.guide_zones = []
        self.failures = []
        self.validation = {z: {"hits": 0, "wrong_zone": 0, "strokes": 0} for z in DISPLAY_ORDER}
        self.validation_hits = []
        self.verification_evidence = {z: [0, 0] for z in DISPLAY_ORDER}
        self.last_t = None
        self.started_t = None
        self._guide_epoch = None

    @property
    def target(self):
        return DISPLAY_ORDER[min(self.target_index, 3)] if self.state in ("REACH", "VERIFY") else None

    def fail(self, reason, message):
        self.state, self.message = "RETRY", message
        self.failures.append(reason)

    def update(self, t, evidence, body=None, commits=()):
        if self.last_t is not None and t <= self.last_t:
            raise ValueError("calibration frames must increase")
        self.last_t = t
        if self.started_t is None:
            self.started_t = t
        if any(e.t_capture != t for e in evidence.values()):
            raise ValueError("calibration uses current-frame evidence only")
        if self.state in ("READY", "RETRY"):
            return
        if self.state == "STAND":
            while self.bodies and t - self.bodies[0].t_capture > 3.5:
                self.bodies.popleft()
            if body is not None and body.t_capture <= t and t - body.t_capture < 0.3:
                if not self.bodies or body.t_capture - self.bodies[-1].t_capture >= 0.15:
                    self.bodies.append(body)
            if len(self.bodies) < 10 or self.bodies[-1].t_capture - self.bodies[0].t_capture < 1.5:
                return
            if {str(e.hand_id) for e in evidence.values()} != {"LEFT", "RIGHT"} or not all(
                e.kind == "MEASURED" for e in evidence.values()
            ):
                self.message = "Hold both sticks apart so their tips are visible"
                return
            values = np.array([[b.left, b.right, b.shoulder_y, b.hip_y] for b in self.bodies])
            if np.max(np.ptp(values, axis=0)) > 0.06 or t - self.bodies[-1].t_capture > 0.3:
                self.message = "Stay centered for a moment"
                return
            left, right, sy, hy = np.median(values, axis=0)
            if abs((left + right) / 2 - 0.5) > 0.08 or sy < 0.05 or hy > 0.98:
                self.message = "Center your shoulders and waist inside the frame"
                return
            self.body = BodyReference(t, left, right, sy, hy, min(b.confidence for b in self.bodies))
            w, h = self.roi_size
            width, height = self.settings.min_width_px / w, self.settings.min_height_px / h
            half = (right - left) / 2 + width / 2 + self.settings.margin_px / w + 0.02
            cols = (self.body.center_x - half, self.body.center_x + half)
            rows = (sy + 0.25 * (hy - sy), self.body.navel_y)
            try:
                self.guide_zones = four_pad_layout(cols, rows, width, height, mirror=self.mirror)
            except ValueError:
                self.fail("BODY_LEAVES_NO_PLAY_AREA", "Keep your waist visible and space beside both arms")
                return
            self.state, self.target_started = "REACH", t
            self.message = "Play relaxed strokes at Crash / Ride; alternate your hands"
            return
        target = self.target
        collector = self.collector if self.state == "REACH" else self.verifier
        before = len(collector.strokes)
        for e in evidence.values():
            collector.add(e, target)
        if self.state == "VERIFY":
            n_good, n_all = self.verification_evidence[target]
            self.verification_evidence[target] = [
                n_good + sum(e.kind == "MEASURED" for e in evidence.values()),
                n_all + len(evidence),
            ]
            for c in commits:
                self.validation_hits.append((target, str(c.hand_id), c.t_impact_target, c.zone_id))
            for stroke in collector.strokes[before:]:
                score = self.validation[target]
                score["strokes"] += 1
                # Reactive targets are scheduling instants; allow one frame of processing tail.
                matches = [
                    (i, z)
                    for i, (cue, hand, stamp, z) in enumerate(self.validation_hits)
                    if cue == target and hand == stroke.hand and stroke.t_start <= stamp <= stroke.t_end + 0.1
                ]
                correct = [(i, z) for i, z in matches if z == target]
                if correct:
                    i, _ = correct[0]
                    score["hits"] += 1
                    self.validation_hits.pop(i)
                score["wrong_zone"] += sum(z != target for _, z in matches)
        group = [s for s in collector.strokes if s.target == target]
        # Each quadrant is demonstrated with both hands; placement is never hand-assigned.
        both = all(sum(s.hand == hand for s in group) >= 2 for hand in ("LEFT", "RIGHT"))
        if len(group) >= 6 and both:
            self.target_index += 1
            self.target_started = t
            collector.clear_motion()
            if self.target_index < 4:
                self.message = f"Play relaxed strokes at {NAMES[self.target]}; alternate your hands"
                return
            if self.state == "REACH":
                self.fit = fit_reach(
                    self.collector.strokes, self.body, self.roi_size, self.settings, mirror=self.mirror
                )
                if not self.fit["passed"]:
                    self.fail(
                        "FIT_UNSUPPORTED", "I need clearer strokes across both rows. Press R to try again"
                    )
                    return
                self.zones = self.fit["zones"]
                self.state, self.target_index = "VERIFY", 0
                self.message = "Try the fitted Crash / Ride with both hands"
            else:
                valid = all(
                    v["strokes"] >= 6 and v["hits"] / v["strokes"] >= 0.9 and v["wrong_zone"] == 0
                    for v in self.validation.values()
                )
                coverage = all(g / max(1, n) >= 0.8 for g, n in self.verification_evidence.values())
                if valid and coverage and not self.validation_hits:
                    self.state, self.message = "READY", "Ready to play"
                else:
                    self.fail("VALIDATION_FAILED", "Some strokes were unclear. Press R to try again")
        elif t - self.target_started > 30:
            self.fail(
                "MEASURED_STROKES_MISSING", "Keep both tips visible during each stroke. Press R to retry"
            )
        else:
            self.message = f"{NAMES[target]} - alternate your hands ({min(6, len(group))}/6)"

    def report(self):
        points = [p for s in self.collector.strokes for p in s.points]
        envelope = None
        if points:
            pts = np.asarray(points)
            envelope = [*np.min(pts, axis=0).tolist(), *np.max(pts, axis=0).tolist()]
        return {
            "schema_version": "1.0",
            "provenance": self.provenance,
            "state": self.state,
            "participant_evidence": False,
            "settings": asdict(self.settings),
            "body": self.body.to_dict() if self.body else None,
            "roi_size": list(self.roi_size),
            "measured_reach_envelope": envelope,
            "fit": self.fit,
            "strokes": [asdict(s) for s in self.collector.strokes],
            "validation_strokes": [asdict(s) for s in self.verifier.strokes],
            "validation": self.validation,
            "validation_coverage": self.verification_evidence,
            "unmatched_validation_hits": self.validation_hits,
            "failures": self.failures,
            "elapsed_s": None if self.last_t is None else self.last_t - self.started_t,
            "limitation": "Compares measured motion with commits; independent hit truth is unavailable.",
        }
