# ADR-0050 — Reference four-piece arrangement in calibrated play

Date: 2026-10-24. Status: implementation candidate; synthetic calibration passes, live calibration on
this laptop pending.

The owner asked the AR view to place the drums as on the reference screen, and to do it everywhere,
calibrated play included:
- Crash / Ride outboard and high on the left, Hi-Hat outboard and high on the right;
- Tom on the inner left and Snare on the inner right, both low.

## Decisions

- **Arrangement switch.** `AutomaticCalibration(arrangement="reference")` keeps the flow:
  - the same steps: STAND, REACH, VERIFY, READY/RETRY;
  - the same target order (Crash / Ride, Hi-Hat, Snare, Tom 1);
  - the same stroke collector, the six-stroke and both-hands rules, and the verification thresholds.

  `arrangement="grid"` (the default) is unchanged, byte for byte, including its report.
- **Guide.** `geometry.reference_kit.reference_guide_pads` places the guide from the measured body:
  - drums of about 1.6 torso half-widths flank the body centre on the navel line;
  - cymbals sit outboard, one pad height plus the vertical gap floor above that line.

  The product floors are checked.
- **Fit.** `calib.reach.fit_reach_reference` fits each piece from its own strokes:
  - centre = the median end;
  - edge = the median end minus the margin;
  - width = the 10-90 % spread plus margins.

  The product pixel floors and the pairwise gap floors are hard constraints. It also checks:
  - left-to-right order;
  - drums centred on the body and on the navel band;
  - approach-margin support per piece.
- **Drums in front of the torso.** The drums are played in front of the torso, as on the reference.
  So the grid's `PADS_INTERSECT_TORSO` rule applies to the cymbals only (`CYMBAL_INTERSECTS_TORSO`).
  This is the one deliberate product-behaviour change.
- **Selection in `app.play`.** `--kit reference` (the `--view ar` default) selects this arrangement;
  `--kit four` keeps the grid in either view. Ids, names and TR-505 samples are the four-pad ones.

## Risks

Strokes in front of a dark shirt may be measured less often than strokes beside the body. The live
gate is: READY within the same number of attempts as the grid over three tries, and commits per hit
not lower than the grid's.
