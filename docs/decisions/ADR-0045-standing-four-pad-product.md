# ADR-0045 — Standing four-pad product path

Date: 2026-10-03. Status: implemented candidate; live acceptance has not passed.

The owner's execution directive fixes V1 at four pads in a clear 2x2. The recorded
GEOM estimator places its tip at a length prior even when an axis is found. Old
calibration therefore cannot establish measured endpoint reachability. Run4/5
observer traces and the Run1 replay are development evidence, not participant data.

## Decisions

- Preserve historical configurations, schemas, recordings, research arms and gates.
  Add a product entry point and an explicitly versioned product configuration.
- Preserve ROI-normalized, camera-space coordinates and the validated display-only
  mirror. Product names are assigned in **display space**: Crash/Ride upper left,
  Hi-Hat upper right, Snare lower left, Tom 1 lower right.
- Use equal rounded polygon pads with flat top impact segments. Candidate dimensions
  have a pixel floor and visible gaps. Fit the two columns and rows jointly from
  measured strokes; reject inadequate evidence instead of shrinking below the floor.
- Use pose shoulders/hips only to establish the standing reference and torso exclusion.
  Navel height is an anatomical approximation, not a depth measurement. Actual pad
  placement requires observed endpoints through strike-like motion near each target.
- Keep endpoint evidence separate from guessed and predicted positions. Product
  estimation emits AXIS_REFINED observations only for visible endpoints; no length
  fallback. A companion evidence record records rejection reasons and provenance.
- If the hand prior clips a supported line, refine the search along that line from
  the current image. The first current-setup replay recovered 134 more endpoint
  observations (875 versus 741 of 1,286); this is coverage, not labelled accuracy.
- Use the full 640x480 capture ROI in the product. The historical bottom margin
  excluded the waist reference in the first guided run. Preserve old recordings and
  their ROI; replaying that crop requires the explicit `--recorded-roi` option.
- Reuse the existing geometry/candidate/commit/audio contracts. Product stroke
  geometry requires measured causal approach, supports complete between-frame
  crossings, and re-arms on a measured rebound. Independent state for each hand;
  either hand can reach every zone. No future-frame access or one-shot B6 rule.
- Additive config changes use schema 1.11. Historical absent options retain their
  behavior. New calibration evidence has its own versioned schema and cannot be
  substituted for calib-v1 or participant validation.
- Benchmark current perception, endpoint candidates, hand inputs and supported
  inference delegates on existing developer recordings. No untrained temporal model
  is eligible for live anticipation. A larger model needs quality and cost evidence.

## Hardware and acceptance

The execution host reports Quadro M620 (2 GB), driver 581.15, torch 2.14.0+cpu,
and ONNX Runtime CPU/Azure providers. It does not report the directive's RTX 3050.
The current camera placement (owner: lens approximately 1.50 m, chest distance
approximately 1.20 m) is distinct from historical captures. Those captures cannot
validate reachability at the current placement.

Synthetic tests establish behavior on specified inputs. Replay establishes cost and
observable coverage on recorded frames. Neither establishes physical reachability,
tip accuracy without labels, live strike recall, or action-to-sound latency.
Phase 18 remains blocked and participant collection is outside this change.
