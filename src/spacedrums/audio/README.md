# Audio

**Status:** IMPLEMENTED (Phase 04); physical output latency is **PENDING** — no accepted
post-DAC measurement exists; microphone and Stereo Mix attempts were rejected (see
`docs/audio-profile-hw01-realtek.md`).

Local WAV sample bank, monotone kinematic-proxy-to-gain mapping, device-clock regression,
sample-offset callback mixing with polyphony and late-event accounting, and time-targeted
scheduling against the Phase 01 `AudioEvent` contract.
