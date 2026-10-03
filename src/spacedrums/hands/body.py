"""Pose model used while establishing the standing frame; no strike decisions."""

from __future__ import annotations

import cv2
import numpy as np

from spacedrums.contracts.perception import BodyReference
from spacedrums.hands.model_asset import resolve_model_asset
from spacedrums.timing import now


class BodyLandmarker:
    def __init__(self, asset_id):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        self.mp = mp
        self.asset = resolve_model_asset(asset_id)
        self.detector = vision.PoseLandmarker.create_from_options(
            vision.PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(self.asset.path)),
                running_mode=vision.RunningMode.VIDEO,
                num_poses=1,
                min_pose_detection_confidence=0.6,
                min_pose_presence_confidence=0.6,
                min_tracking_confidence=0.6,
                output_segmentation_masks=False,
            )
        )
        self.last_ms = -1
        self.processing_s = 0.0

    def detect(self, view):
        start = now()
        image = view.full if view.full is not None else view.roi
        rgb = np.ascontiguousarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        stamp = max(self.last_ms + 1, int(view.sample.t_capture * 1000))
        self.last_ms = stamp
        result = self.detector.detect_for_video(
            self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb), stamp
        )
        self.processing_s = now() - start
        if len(result.pose_landmarks) != 1:
            return None
        lm = result.pose_landmarks[0]
        points = [lm[i] for i in (11, 12, 23, 24)]
        confidence = min(min(float(p.visibility or 0), float(p.presence or 0)) for p in points)
        if confidence < 0.65 or any(not (0 < p.x < 1 and 0 < p.y < 1) for p in points):
            return None
        if view.full is None:
            xy = [(p.x, p.y) for p in points]
        else:
            x, y, w, h = view.sample.roi_px
            fw, fh = view.sample.frame_size_px
            xy = [((p.x * fw - x) / w, (p.y * fh - y) / h) for p in points]
        shoulder_y = (xy[0][1] + xy[1][1]) / 2
        hip_y = (xy[2][1] + xy[3][1]) / 2
        if hip_y - shoulder_y < 0.18:
            return None
        return BodyReference(
            view.sample.t_capture, min(p[0] for p in xy), max(p[0] for p in xy), shoulder_y, hip_y, confidence
        )

    def close(self):
        self.detector.close()
