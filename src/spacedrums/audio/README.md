# Audio

**Status:** IMPLEMENTED (Phase 04); physical output latency is **PENDING** — no accepted
post-DAC measurement exists; microphone and Stereo Mix attempts were rejected (see
`docs/audio-profile-hw01-realtek.md`).

Local WAV sample bank, monotone kinematic-proxy-to-gain mapping, device-clock regression,
sample-offset callback mixing with polyphony and late-event accounting, and time-targeted
scheduling against the Phase 01 `AudioEvent` contract.

**Layers and round robins.** A manifest entry may carry `group`, `layer` (`hard`/`soft`) and `round_robin`; a zone's `sample_id` then names the group. `SampleBank.groups` holds the takes and `bank[group]` is the first hard take, so ungrouped manifests (TR-505) behave exactly as before. `VariantSelector` (`variants.py`) picks the layer from the event's gain (soft below 0.55, a candidate) and rotates the takes deterministically per layer, so repeated hits never replay one file back to back and the same hit sequence always sounds the same. `AudioOutput.play()` enqueues the chosen take; the `AudioEvent` still names the group. The scheduler and mixer are unchanged: voices are unlimited, never cut one another off, and the sum is clipped only at the output (`AudioStats.clipped_samples`).
