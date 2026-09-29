"""Display-space drawing of camera-space overlays (live mirror previews).

``Canvas`` draws on an image through the horizontal map ``x' = sign * x + offset``. The camera
canvas is the identity, so offline renderers, exports and replay windows stay pixel-identical.
``Canvas.for_display(image, mirror=True)``, on an image already mirrored by ``mirror_preview``,
reflects scene overlays (ROI box, zones, hands, sticks, predictions) onto the mirrored pixels they
describe. Text is never reflected: :meth:`Canvas.put_text` draws normal glyphs in the reflected
footprint of the camera-space text box, and :meth:`Canvas.upright` returns an unreflected surface for
HUD content anchored to a container such as the ROI. Full-frame HUD (panels, status bars) keeps
drawing with ``cv2`` in screen coordinates. Only display pixels change: zones, the ROI and records
keep camera coordinates.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np

from spacedrums.capture.roi import Roi

Point = tuple[int, int]
Color = tuple[int, int, int]


@dataclass(frozen=True, eq=False)
class Canvas:
    image: np.ndarray
    sign: int = 1
    offset: int = 0

    @classmethod
    def of(cls, surface: np.ndarray | Canvas) -> Canvas:
        """Camera canvas for an image; a canvas passes through unchanged."""
        return surface if isinstance(surface, Canvas) else cls(surface)

    @classmethod
    def for_display(cls, image: np.ndarray, mirror: bool) -> Canvas:
        """Camera canvas, or a reflecting canvas for an image mirrored by ``mirror_preview``."""
        return cls(image, -1, image.shape[1] - 1) if mirror else cls(image)

    @property
    def mirrored(self) -> bool:
        return self.sign < 0

    @property
    def width(self) -> int:
        return self.image.shape[1]

    @property
    def height(self) -> int:
        return self.image.shape[0]

    def point(self, p: Point) -> Point:
        if self.sign == 1 and self.offset == 0:
            return p
        return (self.sign * p[0] + self.offset, p[1])

    def points(self, pts: np.ndarray) -> np.ndarray:
        if self.sign == 1 and self.offset == 0:
            return pts
        mapped = np.array(pts, copy=True)
        mapped[..., 0] = self.sign * mapped[..., 0] + self.offset
        return mapped

    def span(self, x0: int, x1: int) -> slice:
        """Display columns showing camera columns ``[x0, x1)``."""
        if self.mirrored:
            return slice(self.offset - x1 + 1, self.offset - x0 + 1)
        return slice(x0 + self.offset, x1 + self.offset)

    def region(self, x0: int, y0: int, x1: int, y1: int) -> Canvas:
        """Canvas over the display pixels of a camera rectangle, in rectangle-local coordinates."""
        view = self.image[y0:y1, self.span(x0, x1)]
        return Canvas(view, -1, x1 - x0 - 1) if self.mirrored else Canvas(view)

    def roi(self, roi: Roi) -> Canvas:
        return self.region(roi.x, roi.y, roi.x1, roi.y1)

    def upright(self, x0: int, x1: int) -> Canvas:
        """Unreflected canvas whose camera columns ``[x0, x1)`` land on their display footprint."""
        return Canvas(self.image, 1, self.span(x0, x1).start - x0)

    def line(
        self, p0: Point, p1: Point, color: Color, thickness: int = 1, line_type: int = cv2.LINE_8
    ) -> None:
        cv2.line(self.image, self.point(p0), self.point(p1), color, thickness, line_type)

    def arrowed_line(
        self,
        p0: Point,
        p1: Point,
        color: Color,
        thickness: int = 1,
        line_type: int = cv2.LINE_8,
        tip_length: float = 0.1,
    ) -> None:
        cv2.arrowedLine(
            self.image, self.point(p0), self.point(p1), color, thickness, line_type, 0, tip_length
        )

    def circle(
        self, center: Point, radius: int, color: Color, thickness: int = 1, line_type: int = cv2.LINE_8
    ) -> None:
        cv2.circle(self.image, self.point(center), radius, color, thickness, line_type)

    def rectangle(
        self, p0: Point, p1: Point, color: Color, thickness: int = 1, line_type: int = cv2.LINE_8
    ) -> None:
        cv2.rectangle(self.image, self.point(p0), self.point(p1), color, thickness, line_type)

    def polylines(
        self,
        polygons: Sequence[np.ndarray],
        closed: bool,
        color: Color,
        thickness: int = 1,
        line_type: int = cv2.LINE_8,
    ) -> None:
        cv2.polylines(self.image, [self.points(p) for p in polygons], closed, color, thickness, line_type)

    def fill_poly(self, polygons: Sequence[np.ndarray], color: Color, line_type: int = cv2.LINE_8) -> None:
        cv2.fillPoly(self.image, [self.points(p) for p in polygons], color, line_type)

    def ellipse(
        self,
        center: Point,
        axes: tuple[int, int],
        angle: float,
        start: float,
        end: float,
        color: Color,
        thickness: int = 1,
        line_type: int = cv2.LINE_8,
    ) -> None:
        if self.mirrored:  # a reflection negates the rotation and maps parameter t to 180 - t
            angle, start, end = -angle, 180 - end, 180 - start
        cv2.ellipse(self.image, self.point(center), axes, angle, start, end, color, thickness, line_type)

    def marker(
        self,
        position: Point,
        color: Color,
        marker_type: int,
        size: int,
        thickness: int = 1,
        line_type: int = cv2.LINE_8,
    ) -> None:
        """The cross, tilted-cross and star markers used by the overlays are mirror-symmetric."""
        cv2.drawMarker(self.image, self.point(position), color, marker_type, size, thickness, line_type)

    def put_text(
        self,
        text: str,
        org: Point,
        font: int,
        scale: float,
        color: Color,
        thickness: int = 1,
        line_type: int = cv2.LINE_8,
    ) -> None:
        if self.mirrored:
            width = cv2.getTextSize(text, font, scale, thickness)[0][0]
            self.upright(org[0], org[0] + width).put_text(text, org, font, scale, color, thickness, line_type)
            return
        cv2.putText(self.image, text, self.point(org), font, scale, color, thickness, line_type)


__all__ = ["Canvas"]
