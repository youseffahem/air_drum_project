"""Calibration Wizard and calibration file I/O (Phase 14, layer L7; ADR-0037).

``fit`` (deterministic layout fit and checks), ``steps`` (per-step accumulators), ``wizard`` (state
machine), ``schema`` (calib-v1 validation), ``store`` (I/O, triggers, config application) and
``synthetic`` (SYNTHETIC actor for self-tests). The live runner is ``spacedrums.app.calibrate``;
the views are ``spacedrums.ui.wizard_views`` (L7 siblings never import each other).
"""

from spacedrums.calib.fit import Box, FitSettings, LayoutError, ScaleTranslate, fit_layout, overlap_report
from spacedrums.calib.schema import CALIB_ALGORITHM, CalibrationError, ProvenanceKind, StepStatus
from spacedrums.calib.steps import StickSample, WizardFrame
from spacedrums.calib.store import (
    CALIBRATED,
    UNCALIBRATED,
    CalibratedConfig,
    Calibration,
    Trigger,
    apply_calibration,
    calibration_hash,
    load_calibrated_config,
    load_calibration,
    recalibration_triggers,
    save_calibration,
)
from spacedrums.calib.wizard import (
    CalibrationWizard,
    Stage,
    Step,
    Template,
    WizardSettings,
    autopilot,
    setup_binding,
)

__all__ = [
    "CALIBRATED",
    "CALIB_ALGORITHM",
    "UNCALIBRATED",
    "Box",
    "CalibratedConfig",
    "Calibration",
    "CalibrationError",
    "CalibrationWizard",
    "FitSettings",
    "LayoutError",
    "ProvenanceKind",
    "ScaleTranslate",
    "Stage",
    "Step",
    "StepStatus",
    "StickSample",
    "Template",
    "Trigger",
    "WizardFrame",
    "WizardSettings",
    "apply_calibration",
    "autopilot",
    "calibration_hash",
    "fit_layout",
    "load_calibrated_config",
    "load_calibration",
    "overlap_report",
    "recalibration_triggers",
    "save_calibration",
    "setup_binding",
]
