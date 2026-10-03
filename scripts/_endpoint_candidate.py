"""Experimental causal endpoint evidence; offline use only, not a product estimator.

Long edge pairs propose a shaft independently of the knuckle direction. A narrow
current-image colour-contrast profile checks the shaft, then its termination.
Colour means local contrast, not a prescribed wood colour or marker threshold.
No stored length ever supplies a tip. Temporal state only ranks/rejects current
measurements and expires after 120 ms.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from spacedrums.hands.grip import grip_reference


@dataclass
class Proposal:
    origin: np.ndarray
    direction: np.ndarray
    width: float
    overlap: float
    edge_far: float
    grip_distance: float
    edges: list
    source: str = "CURRENT_EDGE_PAIR"


def cross2(a, b):
    return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]


class ProfileEndpointCandidate:
    def __init__(self, grip_settings, *, temporal=False):
        self.grip_settings = grip_settings
        self.temporal = temporal
        self.detector = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD, 0.5)
        self.memory = {}
        self.last_time = None
        self.memory_s = 0.12

    def reset(self):
        self.memory.clear()
        self.last_time = None

    def _proposals(self, lines, grip, span):
        eligible = []
        # Filter all short scene edges in one vector operation before Python loops.
        lengths = np.linalg.norm(lines[:, 2:] - lines[:, :2], axis=1)
        for line in lines[lengths >= max(25, span)]:
            a, b = line[:2], line[2:]
            if np.linalg.norm(b - grip) < np.linalg.norm(a - grip):
                a, b = b, a
            length = float(np.linalg.norm(b - a))
            if length < max(25, span):
                continue
            d = (b - a) / length
            near, far = np.dot(a - grip, d), np.dot(b - grip, d)
            off = float(cross2(d, a - grip))
            if abs(off) > 0.9 * span or near > 1.8 * span or near < -2 * span or far < 1.5 * span:
                continue
            eligible.append((a, b, d, near, far, off))
        pairs = []
        for i, one in enumerate(eligible):
            a, b, d, near, far, off = one
            for aa, bb, dd, nn, ff, _oo in eligible[i + 1 :]:
                if np.dot(d, dd) < 0.996:
                    continue
                n = np.array([-d[1], d[0]])
                width = abs(np.dot((aa + bb - a - b) / 2, n))
                lo, hi = max(near, nn), min(far, ff)
                if not 2 <= width <= min(15, 0.6 * span) or hi - lo < max(25, span):
                    continue
                direction = d + dd
                direction /= np.linalg.norm(direction)
                center = (a + b + aa + bb) / 4
                origin = center + np.dot(grip - center, direction) * direction
                offset = float(np.linalg.norm(origin - grip))
                if offset > 0.8 * span:
                    continue
                pairs.append(
                    Proposal(
                        origin,
                        direction,
                        float(width),
                        float(hi - lo),
                        float(max(far, ff)),
                        offset,
                        [np.r_[a, b].tolist(), np.r_[aa, bb].tolist()],
                    )
                )
        pairs.sort(key=lambda p: p.overlap - 2 * p.grip_distance, reverse=True)
        result = []
        for p in pairs:
            if any(
                abs(cross2(p.direction, q.direction)) < 0.025
                and abs(cross2(p.direction, p.origin - q.origin)) < 3
                for q in result
            ):
                continue
            result.append(p)
            if len(result) == 12:
                break
        return result

    def _profile(self, im, p, span):
        # Reach is a search bound, never an endpoint. Require room beyond a cap.
        h, w = im.shape[:2]
        ts = np.arange(0, min(14 * span, np.hypot(w, h)), dtype=np.float32)
        normal = np.array([-p.direction[1], p.direction[0]])
        offsets = np.array(
            [
                -p.width / 2 - 5,
                -p.width / 2 - 3,
                -p.width * 0.15,
                0,
                p.width * 0.15,
                p.width / 2 + 3,
                p.width / 2 + 5,
            ],
            np.float32,
        )
        pts = p.origin[None, None, :] + ts[:, None, None] * p.direction + offsets[None, :, None] * normal
        valid = (
            (pts[:, :, 0] >= 2) & (pts[:, :, 0] < w - 2) & (pts[:, :, 1] >= 2) & (pts[:, :, 1] < h - 2)
        ).all(axis=1)
        stop = np.flatnonzero(~valid)
        if len(stop):
            ts, pts = ts[: stop[0]], pts[: stop[0]]
        if len(ts) < 45:
            return {"valid": False, "reason": "SEARCH_BOUNDARY", "proposal": p}
        samples = cv2.remap(
            im, pts[:, :, 0].astype(np.float32), pts[:, :, 1].astype(np.float32), cv2.INTER_LINEAR
        )
        samples = cv2.GaussianBlur(samples.astype(np.float32), (1, 5), 0)
        left = samples[:, :2].mean(axis=1)
        center = samples[:, 2:5].mean(axis=1)
        right = samples[:, 5:].mean(axis=1)
        dl, dr = center - left, center - right
        ml, mr = np.linalg.norm(dl, axis=1), np.linalg.norm(dr, axis=1)
        coherence = np.sum(dl * dr, axis=1) / np.maximum(1, ml * mr)
        strength = np.minimum(ml, mr) * np.clip(coherence, 0, 1)
        supported = (strength >= 12).astype(np.uint8)
        # Bridge <=4px holes only to find runs; the original evidence remains in diagnostics.
        connected = cv2.morphologyEx(supported[:, None], cv2.MORPH_CLOSE, np.ones((5, 1), np.uint8))[:, 0]
        transitions = np.diff(np.r_[0, connected, 0].astype(int))
        runs = list(zip(np.flatnonzero(transitions == 1), np.flatnonzero(transitions == -1), strict=True))
        viable = [(a, b) for a, b in runs if a <= 1.8 * span and b - a >= max(35, 1.4 * span)]
        if not viable:
            return {
                "valid": False,
                "reason": "NO_CONTINUOUS_SHAFT_PROFILE",
                "proposal": p,
                "runs": runs,
                "strength": strength,
            }
        a, b = max(viable, key=lambda ab: ab[1])
        # A component ending before a known farther edge is not a cap.
        if b < p.edge_far - 10:
            return {
                "valid": False,
                "reason": "INTERNAL_SUPPORT_BREAK",
                "proposal": p,
                "candidate": p.origin + b * p.direction,
                "runs": runs,
                "strength": strength,
            }
        if len(ts) - b < 14:
            return {
                "valid": False,
                "reason": "SEARCH_BOUNDARY",
                "proposal": p,
                "candidate": p.origin + b * p.direction,
                "runs": runs,
                "strength": strength,
            }
        before = float(np.median(strength[max(a, b - 14) : b - 2]))
        after = float(np.median(strength[b + 3 : b + 13]))
        # Both flanks must explain a narrow shaft and disappear at its distal end.
        # Demand an axial appearance transition too; mere Canny fragmentation is insufficient.
        cap_delta = float(
            np.linalg.norm(np.mean(center[b + 3 : b + 9], axis=0) - np.mean(center[b - 8 : b - 2], axis=0))
        )
        coverage = float(np.mean(supported[a:b]))
        if after > 0.55 * before or before < 14 or cap_delta < 10 or coverage < 0.8:
            return {
                "valid": False,
                "reason": "NO_OBSERVED_CAP",
                "proposal": p,
                "candidate": p.origin + b * p.direction,
                "runs": runs,
                "strength": strength,
            }
        # If another strong aligned run is nearby, abstain rather than call the gap a tip.
        if any(c > b and c - b < max(25, span) and d - c > 10 for c, d in runs):
            return {
                "valid": False,
                "reason": "DISTAL_SUPPORT_AMBIGUOUS",
                "proposal": p,
                "candidate": p.origin + b * p.direction,
                "runs": runs,
                "strength": strength,
            }
        # A wrong axis can simply walk off a still-visible shaft. Search a small
        # 2-D distal neighbourhood for continuing narrow support before calling a cap.
        lateral = np.arange(-max(8, p.width), max(8, p.width) + 1, 2, dtype=np.float32)
        distal = np.arange(b + 4, min(b + 20, len(ts)), dtype=np.float32)
        xy = (
            p.origin[None, None, None, :]
            + distal[:, None, None, None] * p.direction
            + (lateral[None, :, None, None] + offsets[None, None, :, None]) * normal
        )
        patches = (
            cv2.remap(
                im,
                xy[:, :, :, 0].reshape(len(distal), -1).astype(np.float32),
                xy[:, :, :, 1].reshape(len(distal), -1).astype(np.float32),
                cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REPLICATE,
            )
            .reshape(len(distal), len(lateral), 7, 3)
            .astype(float)
        )
        cc = patches[:, :, 2:5].mean(axis=2)
        ll = cc - patches[:, :, :2].mean(axis=2)
        rr = cc - patches[:, :, 5:].mean(axis=2)
        lm, rm = np.linalg.norm(ll, axis=2), np.linalg.norm(rr, axis=2)
        coh = np.sum(ll * rr, axis=2) / np.maximum(1, lm * rm)
        distal_strength = np.minimum(lm, rm) * np.clip(coh, 0, 1)
        continuing = float(np.mean(distal_strength.max(axis=1) > max(12, 0.45 * before)))
        if continuing > 0.5:
            return {
                "valid": False,
                "reason": "SHAFT_CONTINUES_NEAR_CAP",
                "proposal": p,
                "candidate": p.origin + b * p.direction,
                "runs": runs,
                "strength": strength,
                "distal_continuation_fraction": continuing,
            }
        tip = p.origin + (b - 1) * p.direction
        score = (b - a) + 0.25 * p.overlap - 2 * p.grip_distance + min(30, cap_delta)
        support = p.origin[None, :] + np.arange(a, b)[:, None] * p.direction
        support = support[supported[a:b].astype(bool)]
        return {
            "valid": True,
            "reason": "PROFILE_CAP",
            "proposal": p,
            "candidate": tip,
            "tip": tip,
            "start": int(a),
            "end": int(b),
            "coverage": coverage,
            "cap_delta": cap_delta,
            "before": before,
            "after": after,
            "score": float(score),
            "support": support,
            "runs": runs,
            "strength": strength,
            "distal_continuation_fraction": continuing,
        }

    def process(self, view, hands):
        t = view.sample.t_capture
        if any(h.frame_id != view.sample.frame_id or h.t_capture != t for h in hands):
            raise ValueError("hand observations must belong to the current frame")
        if self.last_time is not None and t <= self.last_time:
            raise ValueError("causal replay requires strictly increasing timestamps")
        self.last_time = t
        self.memory = {k: v for k, v in self.memory.items() if 0 < t - v["t"] <= self.memory_s}
        im = cv2.GaussianBlur(view.roi, (3, 3), 0)
        gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        detected = self.detector.detect(gray)[0]
        lines = detected.reshape(-1, 4).astype(float) if detected is not None else np.empty((0, 4))
        selected, diagnostics = {}, {}
        h, w = im.shape[:2]
        for hand in hands:
            hid = str(hand.hand_id)
            grip = grip_reference(hand, self.grip_settings, roi_aspect=w / h)
            prior = self.memory.get(hid) if self.temporal else None
            if prior and t - prior["edge_t"] > self.memory_s:
                prior = None
            diag = {
                "hand_id": hid,
                "candidates": [],
                "prior_tip": prior["tip"].tolist() if prior else None,
                "prior_age_s": t - prior["t"] if prior else None,
                "axis_prior_age_s": t - prior["edge_t"] if prior else None,
                "prior_state": "PRIOR_ONLY" if prior else "EXPIRED_OR_EMPTY",
            }
            diagnostics[hid] = diag
            if grip is None:
                diag["reason"] = "HAND_MISSING"
                continue
            anchor = np.array(grip.point) * [w, h]
            span = max(8, float(np.linalg.norm(np.array(grip.span_vec) * [w, h])))
            diag.update(grip=anchor.tolist(), span=span)
            candidates = [self._profile(im, p, span) for p in self._proposals(lines, anchor, span)]
            if (
                prior
                and not any(c["valid"] for c in candidates)
                and np.linalg.norm(anchor - prior["grip"]) < 2 * span
            ):
                # Local causal search; every hypothesis must pass fresh shaft+cap evidence.
                # No previous endpoint or length enters this image measurement.
                origin = prior["origin"] + anchor - prior["grip"]
                for angle in (0, -0.06, 0.06):
                    co, si = np.cos(angle), np.sin(angle)
                    d = np.array([[co, -si], [si, co]]) @ prior["direction"]
                    normal = np.array([-d[1], d[0]])
                    for offset in (0, -3, 3):
                        o = origin + offset * normal
                        p = Proposal(
                            o,
                            d,
                            prior["width"],
                            0,
                            0,
                            float(np.linalg.norm(o - anchor)),
                            [],
                            "TEMPORAL_AXIS_PRIOR",
                        )
                        candidates.append(self._profile(im, p, span))
            wrist = np.array(hand.landmarks[0]) * [w, h]
            outward = anchor - wrist
            for c in candidates:
                if c["valid"] and np.dot(c["proposal"].direction, outward) < -0.2 * np.linalg.norm(outward):
                    c["valid"] = False
                    c["reason"] = "SUPPORT_TOWARD_WRIST"
            diag["candidates"] = candidates
            good = [c for c in candidates if c["valid"]]
            if hand.handedness_score is None or hand.handedness_score < 0.65:
                diag["reason"] = "LOW_IDENTITY_CONFIDENCE"
                continue
            if not good:
                diag["reason"] = candidates[0]["reason"] if candidates else "NO_SHAFT_EDGE_PAIR"
                continue
            for c in good:
                c["rank"] = c["score"]
                if prior:
                    delta = np.linalg.norm((c["tip"] - anchor) - (prior["tip"] - prior["grip"]))
                    c["rank"] -= min(60, 0.4 * delta)
            good.sort(key=lambda c: c["rank"], reverse=True)
            chosen = good[0]
            if (
                len(good) > 1
                and good[1]["rank"] > chosen["rank"] - 15
                and np.linalg.norm(good[1]["tip"] - chosen["tip"]) > span
            ):
                diag["reason"] = "AMBIGUOUS_SHAFTS"
                continue
            if prior and np.linalg.norm((chosen["tip"] - anchor) - (prior["tip"] - prior["grip"])) > 2 * span:
                diag["reason"] = "TEMPORAL_DISCONTINUITY"
                continue
            selected[hid] = chosen
            diag["reason"] = "CURRENT_PROFILE_CAP"
        # Joint ownership: never assign the same shaft/tip to both hands.
        if len(selected) == 2:
            a, b = selected.values()
            same_tip = np.linalg.norm(a["tip"] - b["tip"]) < 20
            pa, pb = a["proposal"], b["proposal"]
            same_line = (
                abs(cross2(pa.direction, pb.direction)) < 0.08
                and abs(cross2(pa.direction, pa.origin - pb.origin)) < 8
            )
            if same_tip or same_line:
                for hid in selected:
                    diagnostics[hid]["reason"] = "SHARED_SHAFT_AMBIGUITY"
                selected = {}
        outputs = []
        for hand in hands:
            hid = str(hand.hand_id)
            c = selected.get(hid)
            diag = diagnostics[hid]
            outputs.append(
                {
                    "frame_id": view.sample.frame_id,
                    "t_capture": t,
                    "hand_id": hid,
                    "kind": "MEASURED" if c else "UNCERTAIN" if hand.present else "MISSING",
                    "reason": diag["reason"],
                    "tip": (c["tip"] / [w, h]).tolist() if c else None,
                    "origin": (c["proposal"].origin / [w, h]).tolist() if c else None,
                }
            )
            diag["selected"] = c
            if c and self.temporal:
                p = c["proposal"]
                self.memory[hid] = {
                    "t": t,
                    "tip": c["tip"].copy(),
                    "grip": np.array(diag["grip"]),
                    "origin": p.origin.copy(),
                    "direction": p.direction.copy(),
                    "width": p.width,
                    "edge_t": t if p.source == "CURRENT_EDGE_PAIR" else self.memory[hid]["edge_t"],
                }
        return outputs, diagnostics


def serializable(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Proposal):
        return {k: serializable(v) for k, v in vars(value).items()}
    if isinstance(value, dict):
        return {str(k): serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    return value
