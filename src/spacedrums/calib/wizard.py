"""Calibration Wizard state machine (Phase 14, Q57; Tasks 14.2-14.6; ADR-0037).

Six steps, each ``INSTRUCT -> COUNTDOWN -> COLLECT -> REVIEW`` and then accepted, retried or (where a
documented default exists) replaced by its fallback:

1. camera check      profile / frame size / ROI confirmation, delivered-rate spot check, exposure hint
2. playing area      both hands VALID across the stand-here band; distance advice from the hand span
3. stick prior       per-hand L_prior = median axis support over a still hold; default on failure
4. zone placement    reach sweep -> percentile envelope -> scale/translate the Phase 04 template
                     (or keep it: FIXED); bounded nudges and per-zone sounds; overlap blocks accept
5. validation        cued strikes per zone under **Arm A only**; per-zone detections and flags;
                     may send the user back to placement
6. save              builds and validates the calib-v1 document

The wizard is driven by :meth:`update` with one :class:`~spacedrums.calib.steps.WizardFrame` per
delivered frame and by user actions (:meth:`begin`, :meth:`accept`, ...). It never touches a camera,
file or clock: time comes from the frames, so a run is reproducible from its frames and actions.
It keeps no model: calibration outcomes cannot depend on model behaviour. It is resumable:
:meth:`snapshot` after any accepted step, :meth:`restore` refuses a snapshot from another setup.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from spacedrums.calib.fit import (
    Box,
    FitSettings,
    LayoutError,
    ScaleTranslate,
    compose_layout,
    fit_layout,
    inside_roi_report,
    layout_bbox,
    overlap_report,
    validate_zones,
    zones_hash,
)
from spacedrums.calib.schema import (
    CALIB_ALGORITHM,
    HANDS,
    PROVENANCE_LABELS,
    SCHEMA_VERSION,
    CalibrationError,
    ProvenanceKind,
    StepStatus,
    validate_document,
)
from spacedrums.calib.steps import (
    CameraCheck,
    PlayingArea,
    ReachSweep,
    StickPrior,
    ValidationStrikes,
    WizardFrame,
)
from spacedrums.capture.roi import Roi
from spacedrums.config import config_hash
from spacedrums.contracts import schema as contract_schema
from spacedrums.geometry import GEOMETRY_VERSION
from spacedrums.hands.grip import GripSettings

TEMPLATE_PATHS = {
    "mvp4": "configs/zones/mvp4.candidate.yaml",
    "v1-7": "configs/zones/v1-7.candidate.yaml",
}


class Step(StrEnum):
    CAMERA_CHECK = "camera_check"
    PLAYING_AREA = "playing_area"
    STICK_PRIOR = "stick_prior"
    ZONE_PLACEMENT = "zone_placement"
    VALIDATION = "validation"
    SAVE = "save"


STEPS = tuple(Step)
TITLES = {
    Step.CAMERA_CHECK: "Camera check",
    Step.PLAYING_AREA: "Playing area",
    Step.STICK_PRIOR: "Stick length",
    Step.ZONE_PLACEMENT: "Zone placement",
    Step.VALIDATION: "Test strikes (Arm A)",
    Step.SAVE: "Save",
}


class Stage(StrEnum):
    INSTRUCT = "INSTRUCT"
    COUNTDOWN = "COUNTDOWN"
    COLLECT = "COLLECT"
    REVIEW = "REVIEW"
    DONE = "DONE"


@dataclass(frozen=True)
class WizardSettings:
    """Every wizard tunable. ALL VALUES ARE CANDIDATES (phase: decisions to validate experimentally)."""

    countdown_s: float = 2.0
    # step 1 - camera check
    camera_window_s: float = 3.0
    camera_min_frames: int = 20
    fps_tolerance: float = 0.15
    gray_dark: float = 50.0
    gray_bright: float = 205.0
    # step 2 - playing area (span range around the Phase 03 1.0 m observation, 28-31 px; ADR-0017)
    playing_window_s: float = 5.0
    band: tuple[float, float] = (0.45, 0.75)
    n_subregions: int = 3
    min_both_valid_fraction: float = 0.8
    min_subregion_frames: int = 5
    span_px_range: tuple[float, float] = (24.0, 38.0)
    # step 3 - stick prior (sanity range around the Phase 02 prior 0.27)
    stick_window_s: float = 3.0
    stick_min_axis_confidence: float = 0.6
    stick_max_tip_speed: float = 0.15
    stick_min_frames: int = 20
    stick_max_rel_iqr: float = 0.15
    l_prior_range: tuple[float, float] = (0.15, 0.45)
    # step 4 - zone placement
    sweep_window_s: float = 8.0
    envelope_percentiles: tuple[float, float] = (5.0, 95.0)
    envelope_min_points: int = 60
    fit: FitSettings = field(default_factory=FitSettings)
    max_nudge: float = 0.05
    nudge_step: float = 0.005
    ambiguity_gap: float = 0.01
    # step 5 - validation strikes
    strikes_per_zone: int = 5
    cue_period_s: float = 1.5
    validation_lead_in_s: float = 1.0
    min_detection_rate: float = 0.8
    max_cross_talk_rate: float = 0.2
    max_placement_attempts: int = 3

    def __post_init__(self) -> None:
        positive = (
            "camera_window_s",
            "playing_window_s",
            "stick_window_s",
            "sweep_window_s",
            "cue_period_s",
            "max_nudge",
            "nudge_step",
        )
        for name in positive:
            if not getattr(self, name) > 0:
                raise ValueError(f"{name} must be > 0")
        for name in ("countdown_s", "validation_lead_in_s", "ambiguity_gap"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")
        for name in ("band", "span_px_range", "l_prior_range", "envelope_percentiles"):
            lo, hi = getattr(self, name)
            if not lo < hi:
                raise ValueError(f"{name} needs lo < hi")
            object.__setattr__(self, name, (float(lo), float(hi)))
        if not 0 <= self.band[0] < self.band[1] <= 1:
            raise ValueError("band must lie in [0, 1]")
        for name in ("min_both_valid_fraction", "min_detection_rate", "max_cross_talk_rate", "fps_tolerance"):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} must lie in [0, 1]")
        for name in (
            "camera_min_frames",
            "n_subregions",
            "min_subregion_frames",
            "stick_min_frames",
            "envelope_min_points",
            "strikes_per_zone",
            "max_placement_attempts",
        ):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be >= 1")
        if isinstance(self.fit, Mapping):
            object.__setattr__(self, "fit", FitSettings.from_dict(self.fit))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, tuple):
                d[k] = list(v)
        d["fit"] = self.fit.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> WizardSettings:
        unknown = set(d) - {f for f in cls.__dataclass_fields__}
        if unknown:
            raise ValueError(f"unknown wizard settings {sorted(unknown)}")
        kwargs = {k: (tuple(v) if isinstance(v, list) else v) for k, v in d.items() if k != "fit"}
        if "fit" in d:
            kwargs["fit"] = FitSettings.from_dict(d["fit"])
        return cls(**kwargs)

    @classmethod
    def load(cls, path: str | Path) -> WizardSettings:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        doc.pop("meta", None)
        return cls.from_dict(doc.get("wizard", doc))


@dataclass(frozen=True)
class Template:
    """A Phase 04 layout fragment used as the fit template (zones copied exactly as loaded)."""

    layout_id: str
    source: str
    zones: tuple[dict[str, Any], ...]

    def __post_init__(self) -> None:
        validate_zones(self.zones)

    @classmethod
    def load(cls, name_or_path: str | Path, *, layout_id: str | None = None) -> Template:
        key = str(name_or_path)
        rel = TEMPLATE_PATHS.get(key, key)
        root = contract_schema.repo_root()
        path = Path(rel) if Path(rel).is_absolute() else root / rel
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or not isinstance(doc.get("zones"), list):
            raise CalibrationError(f"{path}: a layout template needs a zones list")
        try:
            source = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            source = path.as_posix()
        name = layout_id or (key if key in TEMPLATE_PATHS else path.name.split(".")[0])
        return cls(name, source, tuple(doc["zones"]))

    @property
    def zones_list(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(z) for z in self.zones]

    @property
    def zones_hash(self) -> str:
        return zones_hash(self.zones)

    def to_dict(self) -> dict[str, Any]:
        return {
            "layout_id": self.layout_id,
            "source": self.source,
            "zones_hash": self.zones_hash,
            "zones": self.zones_list,
        }


def setup_binding(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """What a calibration is valid for: camera profile (hashed), ROI and geometry semantics."""
    return {
        "camera_profile_id": cfg["camera_profile"]["profile_id"],
        "camera_profile_hash": config_hash(cfg["camera_profile"]),
        "roi_px": [int(v) for v in cfg["roi"]["px"]],
        "geometry_version": GEOMETRY_VERSION,
    }


INSTRUCTIONS = {
    Step.CAMERA_CHECK: [
        "Keep still in front of the camera for a few seconds.",
        "The wizard confirms the camera profile, frame rate and exposure.",
    ],
    Step.PLAYING_AREA: [
        "Stand so both hands and both sticks stay inside the green box.",
        "Move both hands slowly left and right through the yellow band.",
    ],
    Step.STICK_PRIOR: [
        "Hold both sticks STILL, pointing up and away from you, fully visible.",
        "Do not move until the bar is full.",
    ],
    Step.ZONE_PLACEMENT: [
        "Sweep both stick tips slowly over everything you can comfortably reach:",
        "far left to far right, high to low. The drum zones are fitted to that area.",
    ],
    Step.VALIDATION: [
        "Strike the highlighted zone once each time it lights up.",
        "Either hand may play. Detection uses the reactive arm (A) only.",
    ],
    Step.SAVE: ["Review the summary and save the calibration."],
}


CAMERA_CHECK_KEYS = (
    "frames",
    "window_s",
    "delivered_fps_median",
    "interval_p95_s",
    "dropped_total",
    "fps_relative_error",
    "roi_mean_gray",
    "exposure_advice",
    "mismatches",
    "warnings",
    "label",
)


class CalibrationWizard:
    """Driven by frames (:meth:`update`) and actions; see the module docstring."""

    def __init__(
        self,
        cfg: Mapping[str, Any],
        template: Template,
        settings: WizardSettings | None = None,
        *,
        calibration_id: str,
        created_at: str,
        provenance: Mapping[str, Any],
        app: Mapping[str, Any],
        fit_mode: str = "ENVELOPE",
        nudges: Mapping[str, Sequence[float]] | None = None,
        sample_overrides: Mapping[str, str] | None = None,
        available_samples: Iterable[str] | None = None,
        clock: str = "t_mono",
    ) -> None:
        if fit_mode not in ("ENVELOPE", "FIXED"):
            raise ValueError("fit_mode must be ENVELOPE or FIXED")
        if clock not in ("t_mono", "replay", "synthetic"):
            raise ValueError("clock must be t_mono, replay or synthetic")
        self.cfg = copy.deepcopy(dict(cfg))
        self.template = template
        self.settings = settings or WizardSettings()
        self.st = self.settings.to_dict()
        self.calibration_id = calibration_id
        self.created_at = created_at
        kind = ProvenanceKind(provenance["kind"])
        self.provenance = {
            "kind": str(kind),
            "label": PROVENANCE_LABELS[kind],
            "scope": provenance["scope"],
            "user_tag": provenance.get("user_tag"),
            "setup_tag": provenance.get("setup_tag"),
            "hardware_id": provenance.get("hardware_id", "HW-01"),
            "operator_note": provenance.get("operator_note", ""),
        }
        self.app = {**dict(app), "geometry_version": GEOMETRY_VERSION, "calib_algorithm": CALIB_ALGORITHM}
        self.fit_mode = fit_mode
        self.nudges = {k: [float(v[0]), float(v[1])] for k, v in (nudges or {}).items()}
        self.sample_overrides: dict[str, str] = dict(sample_overrides or {})
        self.available_samples = None if available_samples is None else sorted(set(available_samples))
        self.clock = clock
        self.binding = setup_binding(self.cfg)
        self.roi = Roi.from_rect(self.cfg["roi"]["px"])
        self.grip = (
            GripSettings.from_config(self.cfg["hands"])
            if "grip" in self.cfg.get("hands", {})
            else GripSettings()
        )
        self.default_l_prior = float(self.cfg["stick"]["geom"]["l_prior"])
        # validate nudges / overrides / template up front (fail before the user starts)
        compose_layout(
            template.zones,
            ScaleTranslate(),
            self.nudges,
            self.settings.max_nudge,
            self.sample_overrides,
            self.available_samples,
        )
        self.step_index = 0
        self.stage = Stage.INSTRUCT
        self.outcomes: dict[Step, dict[str, Any]] = {}
        self.pending: dict[str, Any] | None = None
        self.collector: Any = None
        self.t_collect_start: float | None = None
        self.t_first: float | None = None
        self.t_last: float | None = None
        self.step_started: float | None = None
        self.durations: dict[str, float] = {}
        self.placement_attempts = 1
        self.selected_zone = 0
        self.resumed = False
        self.document: dict[str, Any] | None = None
        self.errors: list[str] = []
        self._fixed_ok: bool | None = None

    # ------------------------------------------------------------------ state
    @property
    def step(self) -> Step:
        return STEPS[self.step_index]

    @property
    def done(self) -> bool:
        return self.stage is Stage.DONE

    def _now(self) -> float:
        return 0.0 if self.t_last is None else self.t_last

    def _advance(self) -> None:
        t = self._now()
        if self.step_started is not None:
            key = str(self.step)
            self.durations[key] = self.durations.get(key, 0.0) + max(0.0, t - self.step_started)
        self.step_index += 1
        self.stage = Stage.INSTRUCT
        self.pending = None
        self.collector = None
        self.step_started = t

    # ------------------------------------------------------------------ frames
    def update(self, frame: WizardFrame) -> None:
        t = frame.t
        if self.t_first is None:
            self.t_first = t
            self.step_started = t
        self.t_last = t
        if self.stage is Stage.COUNTDOWN and self.t_collect_start is not None and t >= self.t_collect_start:
            self.stage = Stage.COLLECT
            self.collector = self._make_collector(t)
        if self.stage is Stage.COLLECT:
            self.collector.feed(frame)
            if self.collector.done(t):
                self.pending = self._finish_collect()
                self.stage = Stage.REVIEW

    def _make_collector(self, t: float) -> Any:
        st, step = self.st, self.step
        if step is Step.CAMERA_CHECK:
            cam = self.cfg["camera_profile"]
            expected = {
                "camera_profile_id": cam["profile_id"],
                "resolution_px": list(cam["resolution_px"]),
                "roi_px": list(self.cfg["roi"]["px"]),
                "requested_fps": cam["requested_fps"],
            }
            return CameraCheck(t, expected, st)
        if step is Step.PLAYING_AREA:
            return PlayingArea(t, st, self.roi, self.grip)
        if step is Step.STICK_PRIOR:
            return StickPrior(t, st, self.default_l_prior)
        if step is Step.ZONE_PLACEMENT:
            return ReachSweep(t, st)
        if step is Step.VALIDATION:
            layout = self.outcomes[Step.ZONE_PLACEMENT]["layout"]
            return ValidationStrikes(
                t, st, [z["zone_id"] for z in layout["zones"]], layout["checks"]["overlap"]["near_pairs"]
            )
        raise CalibrationError(f"step {step} collects no frames")

    def _finish_collect(self) -> dict[str, Any]:
        if self.step is Step.ZONE_PLACEMENT:
            self._fixed_ok = None
            envelope = self.collector.envelope()
            return {"envelope": envelope, **self._placement(envelope)}
        return self.collector.result()

    # ------------------------------------------------------------------ placement
    def _placement(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        box = None if envelope["box"] is None else Box.from_list(envelope["box"])
        mode = self.fit_mode if box is not None else "FIXED"
        fallback = self.fit_mode == "ENVELOPE" and box is None
        return {"layout": self._layout(mode, box), "fallback": fallback}

    def _layout(self, mode: str, box: Box | None) -> dict[str, Any]:
        fs = self.settings.fit
        tb = layout_bbox(self.template.zones)
        if mode == "ENVELOPE":
            fit = fit_layout(self.template.zones, box, fs)
            transform, target, fitted = fit.transform, fit.target, fit.fitted_bbox
            clamped, warnings = fit.clamped, list(fit.warnings)
        else:
            transform, target, fitted, clamped, warnings = ScaleTranslate(), None, tb, False, []
        zones = compose_layout(
            self.template.zones,
            transform,
            self.nudges,
            self.settings.max_nudge,
            self.sample_overrides,
            self.available_samples,
        )
        overlap = overlap_report(zones, ambiguity_gap=self.settings.ambiguity_gap)
        inside = inside_roi_report(zones)
        if not inside["passed"]:
            outside = ", ".join(o["zone_id"] for o in inside["outside"])
            warnings.append(f"zone(s) extend past the ROI: {outside}")
        return {
            "template": self.template.to_dict(),
            "fit": {
                "mode": mode,
                **transform.to_dict(),
                "target_box": None if target is None else target.as_list(),
                "template_bbox": tb.as_list(),
                "fitted_bbox": fitted.as_list(),
                "clamped": clamped,
                "settings": fs.to_dict(),
                "warnings": warnings,
            },
            "nudges": {k: list(v) for k, v in sorted(self.nudges.items())},
            "max_nudge": self.settings.max_nudge,
            "sample_overrides": dict(sorted(self.sample_overrides.items())),
            "zones": zones,
            "zones_hash": zones_hash(zones),
            "checks": {"overlap": overlap, "inside_roi": inside},
            "attempts": self.placement_attempts,
        }

    def _refresh_placement(self) -> None:
        assert self.pending is not None
        fit = self.pending["layout"]["fit"]
        box = None if fit["target_box"] is None else self.pending["envelope"]["box"]
        self.pending["layout"] = self._layout(fit["mode"], None if box is None else Box.from_list(box))
        self._fixed_ok = None

    def _fixed_layout_ok(self) -> bool:
        """Whether the FIXED template layout (with the current nudges) passes the overlap check."""
        if self._fixed_ok is None:
            self._fixed_ok = bool(self._layout("FIXED", None)["checks"]["overlap"]["passed"])
        return self._fixed_ok

    def nudge(self, zone_id: str, dx: float, dy: float) -> None:
        """Bounded manual nudge (placement REVIEW); accumulates and clamps to +-max_nudge."""
        self._require(Step.ZONE_PLACEMENT, Stage.REVIEW)
        m = self.settings.max_nudge
        cur = self.nudges.get(zone_id, [0.0, 0.0])
        new = [min(m, max(-m, cur[0] + dx)), min(m, max(-m, cur[1] + dy))]
        if zone_id not in [z["zone_id"] for z in self.template.zones]:
            raise LayoutError(f"unknown zone {zone_id!r}")
        if new == [0.0, 0.0]:
            self.nudges.pop(zone_id, None)
        else:
            self.nudges[zone_id] = new
        self._refresh_placement()

    def set_sample(self, zone_id: str, sample_id: str) -> None:
        """Per-zone drum sound (REQ-056; placement REVIEW). Geometry is unaffected."""
        self._require(Step.ZONE_PLACEMENT, Stage.REVIEW)
        previous = self.sample_overrides.get(zone_id)
        self.sample_overrides[zone_id] = sample_id
        try:
            self._refresh_placement()
        except LayoutError:
            if previous is None:
                self.sample_overrides.pop(zone_id)
            else:
                self.sample_overrides[zone_id] = previous
            raise

    def select_next_zone(self) -> str:
        self.selected_zone = (self.selected_zone + 1) % len(self.template.zones)
        return self.template.zones[self.selected_zone]["zone_id"]

    @property
    def selected_zone_id(self) -> str:
        return self.template.zones[self.selected_zone]["zone_id"]

    # ------------------------------------------------------------------ actions
    def _require(self, step: Step | None, stage: Stage) -> None:
        if (step is not None and self.step is not step) or self.stage is not stage:
            raise CalibrationError(f"action not allowed in {self.step}/{self.stage}")

    def begin(self) -> None:
        """INSTRUCT -> COUNTDOWN (data collection starts after ``countdown_s``); SAVE builds a preview."""
        self._require(None, Stage.INSTRUCT)
        if self.step is Step.SAVE:
            try:
                self.document = self.build_document(final=False)
                self.errors = []
            except (CalibrationError, LayoutError) as exc:
                self.document, self.errors = None, [str(exc)]
            self.pending = {"passed": self.document is not None, "warnings": self.errors}
            self.stage = Stage.REVIEW
            return
        self.t_collect_start = self._now() + self.settings.countdown_s
        self.stage = Stage.COUNTDOWN

    def can_accept(self) -> bool:
        if self.stage is not Stage.REVIEW or self.pending is None:
            return False
        if self.step is Step.ZONE_PLACEMENT:
            return bool(self.pending["layout"]["checks"]["overlap"]["passed"])
        if self.step is Step.SAVE:
            return self.document is not None
        return bool(self.pending.get("acceptable", True))

    def can_fallback(self) -> bool:
        if self.stage is not Stage.REVIEW:
            return False
        if self.step is Step.STICK_PRIOR:
            return True
        if self.step is Step.ZONE_PLACEMENT:
            return self._fixed_layout_ok()
        return False

    def accept(self) -> None:
        if not self.can_accept():
            raise CalibrationError(f"cannot accept {self.step}: {self.blocking_reason()}")
        p = self.pending
        assert p is not None
        step = self.step
        if step is Step.STICK_PRIOR:
            status = StepStatus.PASSED if p["passed"] else StepStatus.FALLBACK
            self.outcomes[step] = {"status": str(status), "result": p}
        elif step is Step.ZONE_PLACEMENT:
            layout = p["layout"]
            if p["fallback"]:
                status = StepStatus.FALLBACK
            elif layout["fit"]["warnings"] or layout["checks"]["overlap"]["near_pairs"]:
                status = StepStatus.ACCEPTED_WITH_WARNINGS
            else:
                status = StepStatus.PASSED
            env_status = StepStatus.PASSED if p["envelope"]["box"] is not None else StepStatus.FALLBACK
            self.outcomes[step] = {
                "status": str(status),
                "envelope_status": str(env_status),
                "envelope": p["envelope"],
                "layout": layout,
            }
        elif step is Step.SAVE:
            self.t_last = self._now()
            self._advance_save()
            return
        else:
            status = StepStatus.PASSED if p["passed"] else StepStatus.ACCEPTED_WITH_WARNINGS
            self.outcomes[step] = {"status": str(status), "result": p}
        self._advance()

    def _advance_save(self) -> None:
        t = self._now()
        if self.step_started is not None:
            self.durations["save"] = self.durations.get("save", 0.0) + max(0.0, t - self.step_started)
        self.document = self.build_document(final=True)
        self.stage = Stage.DONE

    def retry(self) -> None:
        if self.stage is not Stage.REVIEW or self.step is Step.SAVE:
            raise CalibrationError("retry is available after a step's data window")
        self.stage, self.pending, self.collector = Stage.INSTRUCT, None, None

    def fallback(self) -> None:
        if not self.can_fallback():
            raise CalibrationError(f"no fallback for {self.step}/{self.stage}")
        p = self.pending
        assert p is not None
        if self.step is Step.STICK_PRIOR:
            forced = copy.deepcopy(p)
            for hand in HANDS:
                forced["per_hand"][hand]["source"] = "DEFAULT"
                forced["per_hand"][hand]["warnings"].append(
                    f"operator chose the layout default L_prior {self.default_l_prior:g}"
                )
                forced["l_prior"][hand] = self.default_l_prior
            self.outcomes[Step.STICK_PRIOR] = {"status": str(StepStatus.FALLBACK), "result": forced}
        else:
            layout = self._layout("FIXED", None)
            layout["fit"]["warnings"].append("operator chose the fixed template layout")
            env_status = StepStatus.PASSED if p["envelope"]["box"] is not None else StepStatus.FALLBACK
            self.outcomes[Step.ZONE_PLACEMENT] = {
                "status": str(StepStatus.FALLBACK),
                "envelope_status": str(env_status),
                "envelope": p["envelope"],
                "layout": layout,
            }
        self._advance()

    def skip_validation(self) -> None:
        if self.step is not Step.VALIDATION or self.stage not in (Stage.INSTRUCT, Stage.REVIEW):
            raise CalibrationError("only the validation step can be skipped")
        self.outcomes[Step.VALIDATION] = {"status": str(StepStatus.SKIPPED), "result": None}
        self._advance()

    def back_to_placement(self) -> None:
        """After a failed validation: repeat the placement (bounded number of attempts)."""
        if self.step is not Step.VALIDATION or self.stage not in (Stage.INSTRUCT, Stage.REVIEW):
            raise CalibrationError("back_to_placement is available in the validation step")
        if self.placement_attempts >= self.settings.max_placement_attempts:
            raise CalibrationError("maximum placement attempts reached")
        self.placement_attempts += 1
        self.outcomes.pop(Step.ZONE_PLACEMENT, None)
        t = self._now()
        if self.step_started is not None:
            spent = max(0.0, t - self.step_started)
            self.durations["validation"] = self.durations.get("validation", 0.0) + spent
        self.step_index = STEPS.index(Step.ZONE_PLACEMENT)
        self.stage, self.pending, self.collector, self.step_started = Stage.INSTRUCT, None, None, t

    def blocking_reason(self) -> str:
        if self.stage is not Stage.REVIEW:
            return f"stage is {self.stage}"
        if self.step is Step.ZONE_PLACEMENT and self.pending is not None:
            pairs = self.pending["layout"]["checks"]["overlap"]["overlapping_pairs"]
            if pairs:
                return f"zones overlap {pairs}: nudge them apart (overlap blocks save)"
        if self.step is Step.SAVE:
            return "; ".join(self.errors) or "document not built"
        if self.pending is not None and not self.pending.get("acceptable", True):
            return "; ".join(self.pending.get("mismatches", [])) + " - fix the config and restart"
        return ""

    # ------------------------------------------------------------------ what the runner needs
    def required_zones(self) -> list[dict[str, Any]]:
        """Zones the Arm-A tracking/geometry pipeline must use now (calibrated during validation)."""
        if self.step in (Step.VALIDATION, Step.SAVE) and Step.ZONE_PLACEMENT in self.outcomes:
            return copy.deepcopy(self.outcomes[Step.ZONE_PLACEMENT]["layout"]["zones"])
        return self.template.zones_list

    def required_l_prior(self) -> dict[str, float] | None:
        """Per-hand L the stick estimator must use now (after the stick-prior step is accepted)."""
        outcome = self.outcomes.get(Step.STICK_PRIOR)
        return None if outcome is None else dict(outcome["result"]["l_prior"])

    def current_cue(self) -> Any:
        if self.step is Step.VALIDATION and self.stage is Stage.COLLECT and self.collector is not None:
            return self.collector.schedule.at(self._now())
        return None

    def progress(self) -> float | None:
        if self.stage is Stage.COLLECT and self.collector is not None:
            return self.collector.progress(self._now())
        return None

    def display_zones(self) -> list[dict[str, Any]]:
        if self.step is Step.ZONE_PLACEMENT and self.stage is Stage.REVIEW and self.pending is not None:
            return copy.deepcopy(self.pending["layout"]["zones"])
        return self.required_zones()

    def view(self) -> dict[str, Any]:
        """Plain-data view model for ``spacedrums.ui.wizard_views`` (the UI never imports calib)."""
        step, stage = self.step, self.stage
        lines: list[str] = []
        keys = ""
        ok: bool | None = None
        if stage is Stage.INSTRUCT:
            lines = list(INSTRUCTIONS[step])
            keys = "SPACE start | q quit (progress is kept for --resume)"
            if step is Step.VALIDATION:
                keys = "SPACE start | v skip validation | q quit"
                n = len(self.required_zones())
                lines.append(f"{self.settings.strikes_per_zone} strikes on each of {n} zones.")
        elif stage is Stage.COUNTDOWN:
            remaining = max(0.0, (self.t_collect_start or 0.0) - self._now())
            lines = list(INSTRUCTIONS[step]) + [f"Get ready... {remaining:.1f} s"]
        elif stage is Stage.COLLECT:
            lines = list(INSTRUCTIONS[step])
            cue = self.current_cue()
            if step is Step.VALIDATION:
                lines = (
                    [f"HIT: {cue.zone_id}  ({cue.index + 1}/{self.settings.strikes_per_zone})"]
                    if cue
                    else ["Get ready for the first cue..."]
                )
        elif stage is Stage.REVIEW:
            ok = (
                bool(self.pending and self.pending.get("passed"))
                if step is not Step.ZONE_PLACEMENT
                else (self.can_accept() and not self.pending["layout"]["fit"]["warnings"])
            )
            lines = self.summary_lines()
            options = ["ENTER accept" if self.can_accept() else "(accept blocked)"]
            if step is not Step.SAVE:
                options.append("r retry")
            if self.can_fallback():
                options.append("f use default")
            if step is Step.ZONE_PLACEMENT:
                options.append("n next zone | i/j/k/l nudge | s sound")
            if step is Step.VALIDATION:
                options += ["p redo placement", "v skip"]
            keys = " | ".join(options)
        elif stage is Stage.DONE:
            lines = ["Calibration saved."]
        envelope = None
        if step is Step.ZONE_PLACEMENT and stage is Stage.REVIEW and self.pending is not None:
            envelope = self.pending["envelope"]["box"]
        cue = self.current_cue()
        return {
            "step": str(step),
            "step_number": self.step_index + 1,
            "n_steps": len(STEPS),
            "title": TITLES[step],
            "stage": str(stage),
            "lines": lines,
            "keys": keys,
            "progress": self.progress(),
            "ok": ok,
            "band": list(self.settings.band) if step is Step.PLAYING_AREA else None,
            "envelope": envelope,
            "zones": (
                self.display_zones() if step in (Step.ZONE_PLACEMENT, Step.VALIDATION, Step.SAVE) else None
            ),
            "highlight_zone": cue.zone_id
            if cue is not None
            else (self.selected_zone_id if step is Step.ZONE_PLACEMENT and stage is Stage.REVIEW else None),
        }

    def summary_lines(self) -> list[str]:
        p, step = self.pending or {}, self.step
        if step is Step.CAMERA_CHECK:
            fps = p.get("delivered_fps_median")
            profile = "profile OK" if not p.get("mismatches") else "PROFILE MISMATCH"
            head = (
                f"delivered {fps:.1f} FPS (spot check) | exposure {p.get('exposure_advice')} | {profile}"
                if fps
                else "no frames"
            )
            return [head, *p.get("mismatches", []), *p.get("warnings", [])]
        if step is Step.PLAYING_AREA:
            frac = p.get("both_valid_fraction") or 0.0
            visits = "/".join(str(s["valid_frames"]) for s in p.get("subregions", []))
            spans = ", ".join(
                f"{h} {v['median']:.0f}px"
                for h, v in p.get("hand_span_px", {}).items()
                if v["median"] is not None
            )
            return [
                f"both hands VALID {100 * frac:.0f}% | band visits {visits} | span {spans or '-'} -> "
                f"{p.get('distance_advice')}",
                *p.get("warnings", []),
            ]
        if step is Step.STICK_PRIOR:
            parts = [
                f"{h} {p['l_prior'][h]:.3f} ({r['source']}, n={r['n_accepted']})"
                for h, r in p.get("per_hand", {}).items()
            ]
            return ["L_prior " + "  ".join(parts), *p.get("warnings", [])]
        if step is Step.ZONE_PLACEMENT:
            fit = p["layout"]["fit"]
            ov = p["layout"]["checks"]["overlap"]
            return [
                f"{fit['mode']} fit: scale {fit['scale']:.3f}, shift ({fit['translate'][0]:+.3f}, "
                f"{fit['translate'][1]:+.3f}) | envelope points {p['envelope']['n_points']}",
                f"overlap {'OK' if ov['passed'] else 'BLOCKED ' + str(ov['overlapping_pairs'])} | "
                f"near pairs {len(ov['near_pairs'])} | nudges {len(self.nudges)} | sounds "
                f"{len(self.sample_overrides)} changed | selected {self.selected_zone_id}",
                *p["envelope"]["warnings"],
                *fit["warnings"],
            ]
        if step is Step.VALIDATION:
            rows = []
            for r in p.get("per_zone", []):
                flags = " " + ",".join(r["flags"]) if r["flags"] else ""
                rows.append(f"{r['zone_id']} {r['detected']}/{r['cued']}{flags}")
            verdict = "PASSED" if p.get("passed") else "FLAGGED: consider redoing the placement"
            return ["  ".join(rows), verdict]
        if step is Step.SAVE:
            if self.errors:
                return ["cannot save:", *self.errors]
            d = self.document or {}
            return [
                f"{d.get('calibration_id')} | zones {len(d.get('layout', {}).get('zones', []))} | "
                f"L_prior {d.get('stick_prior', {}).get('l_prior')}",
                f"validation {d.get('validation', {}).get('status')} "
                f"(passed={d.get('validation', {}).get('passed')})",
            ]
        return []

    # ------------------------------------------------------------------ document
    def build_document(self, *, final: bool) -> dict[str, Any]:
        missing = [str(s) for s in STEPS[:-1] if s not in self.outcomes]
        if missing:
            raise CalibrationError(f"steps not completed: {missing}")
        cam = self.outcomes[Step.CAMERA_CHECK]
        area = self.outcomes[Step.PLAYING_AREA]
        prior = self.outcomes[Step.STICK_PRIOR]
        place = self.outcomes[Step.ZONE_PLACEMENT]
        val = self.outcomes[Step.VALIDATION]
        cp = self.cfg["camera_profile"]
        c = cam["result"]
        kind = ProvenanceKind(self.provenance["kind"])
        n = self.settings.strikes_per_zone
        if val["result"] is None:
            validation = {
                "status": val["status"],
                "arm": "A",
                "strikes_per_zone": n,
                "cue_period_s": self.settings.cue_period_s,
                "per_zone": [],
                "flags": [],
                "passed": None,
                "label": "NOT_RUN",
            }
        else:
            v = val["result"]
            validation = {
                "status": val["status"],
                "arm": "A",
                "strikes_per_zone": v["strikes_per_zone"],
                "cue_period_s": v["cue_period_s"],
                "per_zone": v["per_zone"],
                "flags": v["flags"],
                "passed": v["passed"],
                "label": "SYNTHETIC" if kind is ProvenanceKind.SYNTHETIC else "MEASURED",
            }
        d = self.durations
        steps_total = sum(d.get(str(s), 0.0) for s in STEPS)
        total = steps_total if self.resumed or self.t_first is None else max(0.0, self._now() - self.t_first)
        a = area["result"]
        pr = prior["result"]
        env = place["envelope"]
        doc = {
            "schema_version": SCHEMA_VERSION,
            "calibration_id": self.calibration_id,
            "created_at": self.created_at,
            "provenance": dict(self.provenance),
            "app": dict(self.app),
            "settings": self.settings.to_dict(),
            "settings_hash": config_hash(self.settings.to_dict()),
            "camera": {
                "profile_id": cp["profile_id"],
                "profile_hash": self.binding["camera_profile_hash"],
                "resolution_px": [int(v) for v in cp["resolution_px"]],
                "requested_fps": cp["requested_fps"],
                "exposure": copy.deepcopy(cp.get("exposure", {})),
                "check": {"status": cam["status"], **{k: c[k] for k in CAMERA_CHECK_KEYS}},
            },
            "roi": {"px": list(self.binding["roi_px"]), "band": list(self.settings.band)},
            "playing_area": {
                "status": area["status"],
                **{
                    k: a[k]
                    for k in (
                        "frames",
                        "both_valid_fraction",
                        "subregions",
                        "hand_span_px",
                        "distance_advice",
                        "passed",
                        "warnings",
                    )
                },
            },
            "stick_prior": {
                "status": prior["status"],
                **{k: pr[k] for k in ("units", "l_prior", "default_l_prior", "per_hand")},
            },
            "reach_envelope": {"status": place["envelope_status"], **env},
            "layout": place["layout"],
            "validation": validation,
            "durations_s": {
                **{str(s): d.get(str(s)) for s in STEPS},
                "total": total if final else None,
                "clock": self.clock,
                "resumed": self.resumed,
            },
        }
        if not final:
            doc["durations_s"]["save"] = None
        doc = copy.deepcopy(doc)
        validate_document(doc)
        return doc

    # ------------------------------------------------------------------ resume
    def snapshot(self) -> dict[str, Any]:
        return {
            "kind": "calib-v1-partial",
            "calib_algorithm": CALIB_ALGORITHM,
            "calibration_id": self.calibration_id,
            "created_at": self.created_at,
            "binding": self.binding,
            "template_zones_hash": self.template.zones_hash,
            "settings_hash": config_hash(self.settings.to_dict()),
            "provenance_kind": self.provenance["kind"],
            "fit_mode": self.fit_mode,
            "clock": self.clock,
            "step_index": self.step_index,
            "outcomes": {str(k): v for k, v in self.outcomes.items()},
            "durations": dict(self.durations),
            "placement_attempts": self.placement_attempts,
            "nudges": self.nudges,
            "sample_overrides": self.sample_overrides,
        }

    def restore(self, snap: Mapping[str, Any]) -> None:
        """Resume after the last accepted step; refuses a snapshot made for another setup/config."""
        reasons = []
        expect = {
            "kind": "calib-v1-partial",
            "calib_algorithm": CALIB_ALGORITHM,
            "binding": self.binding,
            "template_zones_hash": self.template.zones_hash,
            "settings_hash": config_hash(self.settings.to_dict()),
            "provenance_kind": self.provenance["kind"],
            "fit_mode": self.fit_mode,
        }
        for key, value in expect.items():
            if snap.get(key) != value:
                reasons.append(f"{key} differs")
        if reasons:
            raise CalibrationError("cannot resume this calibration: " + ", ".join(reasons) + " (start again)")
        self.calibration_id = snap["calibration_id"]
        self.created_at = snap["created_at"]
        self.outcomes = {Step(k): copy.deepcopy(v) for k, v in snap["outcomes"].items()}
        self.step_index = int(snap["step_index"])
        self.durations = dict(snap["durations"])
        self.placement_attempts = int(snap["placement_attempts"])
        self.nudges = {k: list(v) for k, v in snap["nudges"].items()}
        self.sample_overrides = dict(snap["sample_overrides"])
        self.stage, self.pending, self.collector = Stage.INSTRUCT, None, None
        self.resumed = True
        self.t_first = self.t_last = self.step_started = None


def autopilot(wizard: CalibrationWizard, *, skip_validation: bool = False) -> str | None:
    """One unattended decision (SYNTHETIC self-test, headless replay): start every window, accept every
    acceptable result (failed checks become ACCEPTED_WITH_WARNINGS / FALLBACK), otherwise fall back."""
    if wizard.done:
        return None
    if wizard.step is Step.VALIDATION and skip_validation and wizard.stage in (Stage.INSTRUCT, Stage.REVIEW):
        wizard.skip_validation()
        return "skip"
    if wizard.stage is Stage.INSTRUCT:
        wizard.begin()
        return "begin"
    if wizard.stage is Stage.REVIEW:
        if wizard.can_accept():
            wizard.accept()
            return "accept"
        if wizard.can_fallback():
            wizard.fallback()
            return "fallback"
        raise CalibrationError(f"unattended run cannot continue at {wizard.step}: {wizard.blocking_reason()}")
    return None


__all__ = [
    "INSTRUCTIONS",
    "STEPS",
    "TEMPLATE_PATHS",
    "TITLES",
    "CalibrationWizard",
    "Stage",
    "Step",
    "Template",
    "WizardSettings",
    "autopilot",
    "setup_binding",
]
