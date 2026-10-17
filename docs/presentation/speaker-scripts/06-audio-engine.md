# Audio and Music Engine

Slide 10. Target: 80–90 seconds. Purpose: explain implemented playback and the measurement boundary. Show `assets/audio-pipeline.png`, also editable in the deck.

## Spoken script

“My role is to explain how a committed strike becomes a drum sound.

Each zone maps to a sample identifier. The scheduler receives the committed event and its target time. The audio output selects a sample, applies the configured gain and places the voice in the callback mixer.

The full developer kit uses the acoustic Salamander sample bank. Other product paths use the recorded TR-505 bank. Sample hashes are checked when loading. Grouped acoustic sounds can select soft or hard layers and rotate between takes. This selection is deterministic.

The mixer supports overlapping sounds and starts them at the appropriate position inside an audio buffer. It also counts late events and clipping. The output layer monitors the stream and clears old voices before recovering from a device failure.

Our configuration uses forty-eight kilohertz and a one-hundred-and-twenty-eight-frame buffer. That buffer lasts about two-point-seven milliseconds. It is not the time from a hand movement to an audible sound.

Physical action-to-sound latency remains unmeasured. A running stream or a scheduled event cannot prove audibility or the correct sound. Our next work is a human zone-by-zone sound check and an external timing measurement with stated uncertainty.

The mobile presenter will now explain that role's current status and proposed scope.”

## Likely questions

- **Do you output MIDI?** Direct local sample playback is implemented. Core MIDI is outside the documented V1 requirements.
- **Is gain physical force?** No. It is a mapping from a motion-derived intensity proxy.
- **Is output latency zero?** No. `OutputLatency.unmeasured()` uses 0.0 as a scheduling placeholder with PENDING status.
- **Was sound heard during the presentation capture?** No. The replay screenshots use disabled audio. Earlier logs show running streams, which is a different form of evidence.

Evidence: `app/audio_out.py:AudioOutput`, `audio/scheduler.py:AudioScheduler`, `audio/variants.py:VariantSelector`, `audio/mixer.py:CallbackMixer`, `audio/device.py:SoundDeviceOutput`, both sample manifests. Dependencies: correct zone IDs/timestamps and an accepted external reference. Acceptance: correct audible sample for each zone, controlled overlap/dropout checks and independently measured physical delay.
