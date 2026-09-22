"""Offline dataset labelling (Phase 07): rules, non-causal reference smoother, label generator,
validator, review/QC, acoustic pairing, statistics.

**This package is the only place in the system where future information may be used.** The
reference trajectory it builds is smoothed over the whole recording and the labels derived from it
are offline ground truth; ``docs/architecture/causality-tests.md`` section 1.1 forbids any of it
from reaching a ``Tracker``, feature, ``Anticipator``, ``Geometry`` or ``CommitPolicy`` call.
Nothing here is imported by a runtime component - the layer contract puts ``spacedrums.data`` above
every causal stage, and ``.importlinter`` additionally forbids the causal packages from importing
``spacedrums.data.labels`` by name.

Terms kept distinct throughout (and in the artefacts):

* **observed event** - a crossing or approach seen in a trajectory;
* **annotated ground truth** - a ``LabelRecord`` (``t_impact_est``, offline, non-causal);
* **model prediction** - a ``TrajectoryPrediction`` / ``DirectPrediction`` (Phases 05, 09-13);
* **runtime strike candidate** - a ``StrikeCandidate`` produced causally during the recording;
* **committed strike** - a ``CommittedStrike``, the live system's decision.

The last two are carried inside ``LabelRecord.runtime_reference`` for cross-reference only and are
banner-labelled *REAL-TIME AVAILABLE SIGNALS (not ground truth)*.
"""

from spacedrums.data.labels.generate import (
    GenerateResult,
    LabelGenerator,
    generate_labels,
    read_label_set,
    read_labels,
    read_reference_track,
)
from spacedrums.data.labels.rules import RULES, EventEvidence, Thresholds, classify, rules_hash
from spacedrums.data.labels.schema import (
    LABELS_VERSION,
    RULES_VERSION,
    Interpolation,
    LabelClass,
    Level,
    Provenance,
    QCStatus,
    ReviewDecision,
    SmootherId,
    dataset_kind,
    evidence_label,
)
from spacedrums.data.labels.smooth import (
    LossInterval,
    Measurement,
    ReferenceSample,
    ReferenceSmoother,
    SmoothResult,
)

__all__ = [
    "LABELS_VERSION",
    "RULES",
    "RULES_VERSION",
    "EventEvidence",
    "GenerateResult",
    "Interpolation",
    "LabelClass",
    "LabelGenerator",
    "Level",
    "LossInterval",
    "Measurement",
    "Provenance",
    "QCStatus",
    "ReferenceSample",
    "ReferenceSmoother",
    "ReviewDecision",
    "SmootherId",
    "SmoothResult",
    "Thresholds",
    "classify",
    "dataset_kind",
    "evidence_label",
    "generate_labels",
    "read_label_set",
    "read_labels",
    "read_reference_track",
    "rules_hash",
]
