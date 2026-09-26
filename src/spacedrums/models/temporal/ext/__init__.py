"""Phase 12 optional trajectory extensions E1-E5 (candidates; nothing is adopted by existing here).

Each extension plugs into the Phase 10 pipeline at its declared point (``phase-12`` document,
Architecture table) and is judged against the Phase 10/11 reference by the pre-declared go/no-go
rule (``docs/experiments/phase-12-prereg.md``). Models still cannot see zones: probabilistic
geometry lives in ``spacedrums.geometry.probabilistic``.
"""

from .config import ExtensionConfig
from .model import build_extension_model, load_extension_model

__all__ = ["ExtensionConfig", "build_extension_model", "load_extension_model"]
