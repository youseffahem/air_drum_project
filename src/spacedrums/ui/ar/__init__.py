"""AR view (ADR-0049): a moderngl-rendered 3D kit over the live camera, with the reference HUD.

Import ``spacedrums.ui.ar.view.ARView``; moderngl is imported only when the first renderer is created, so
importing this package never needs a GPU.
"""

from spacedrums.ui.ar.display_map import DisplayMap
from spacedrums.ui.ar.gl import GLUnavailable
from spacedrums.ui.ar.hud import UiStatus
from spacedrums.ui.ar.view import ARView

__all__ = ["ARView", "DisplayMap", "GLUnavailable", "UiStatus"]
