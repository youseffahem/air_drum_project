"""Layer L8 (composition root): the playable prototype (Phase 05, Task 05.5; Phase 13 adds arm C).

``DecisionPipeline`` (observations -> tracking -> geometry A / rule B -> commit per arm -> audio ->
timing), ``AudioOutput``, ``SessionRecorder`` (record mode), ``session_summary`` (Phase 05 developer
summaries), ``synthetic`` (labelled SYNTHETIC observation sequences) and ``main`` (CLI: live /
replay / dev-capture / synthetic sources, keyboard arm switch). May import everything.
"""

from spacedrums.app.audio_out import AudioOutput, OutputLatency
from spacedrums.app.pipeline import HANDS, SUPPORTED_ARMS, DecisionPipeline, FrameResult, HandFrame
from spacedrums.app.recorder import RECORD_TYPES, SessionRecorder

__all__ = [
    "HANDS",
    "RECORD_TYPES",
    "SUPPORTED_ARMS",
    "AudioOutput",
    "DecisionPipeline",
    "FrameResult",
    "HandFrame",
    "OutputLatency",
    "SessionRecorder",
]
