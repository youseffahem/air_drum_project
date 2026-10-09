"""Host-API selection and low-latency stream opening, with no real audio device."""

import pytest

from spacedrums.audio import CallbackMixer
from spacedrums.audio.device import SoundDeviceOutput, resolve_output_device

HOSTAPIS = [
    {"name": "MME", "devices": [0, 1], "default_output_device": 1},
    {"name": "Windows WASAPI", "devices": [2, 3, 4], "default_output_device": 3},
]
DEVICES = [
    {"name": "Microphone (MME)", "max_output_channels": 0},
    {"name": "Speakers (Headset)", "max_output_channels": 2},
    {"name": "Microphone (WASAPI)", "max_output_channels": 0},
    {"name": "Speakers (Realtek)", "max_output_channels": 2},
    {"name": "Speakers (Headset)", "max_output_channels": 2},
]


def resolve(name, api):
    return resolve_output_device(name, api, hostapis=HOSTAPIS, devices=DEVICES)


def test_resolution_prefers_named_output_then_api_default():
    assert resolve("headset", "wasapi") == (4, "Windows WASAPI")
    assert resolve(None, "Windows WASAPI") == (3, "Windows WASAPI")
    assert resolve("nonexistent", "Windows WASAPI") == (3, "Windows WASAPI")
    assert resolve(None, "ASIO") is None
    assert resolve("headset", None) is None


class Stream:
    latency = 0.004
    active = True

    def __init__(self, fail_when=None, **kwargs):
        if fail_when is not None and fail_when(kwargs):
            raise OSError("host API refused")
        self.kwargs = kwargs

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass


def output(factory, host_api="Windows WASAPI", latency="low"):
    return SoundDeviceOutput(CallbackMixer(48000), sample_rate_hz=48000, buffer_frames=128,
                             stream_factory=factory, host_api=host_api, latency=latency)


@pytest.fixture
def fake_devices(monkeypatch):
    import sounddevice as sd

    monkeypatch.setattr(sd, "query_hostapis", lambda: HOSTAPIS)
    monkeypatch.setattr(sd, "query_devices", lambda: DEVICES)


def test_stream_opens_on_requested_host_api_with_low_latency(fake_devices):
    opened = []

    def factory(**kw):
        opened.append(kw)
        return Stream(**kw)

    out = output(factory)
    out.start()
    assert opened[0]["device"] == 3 and opened[0]["latency"] == "low"
    assert "extra_settings" in opened[0]
    assert (out.opened_host_api, out.opened_latency_s) == ("Windows WASAPI (shared)", 0.004)


def test_refused_host_api_falls_back_to_the_default_device(fake_devices):
    opened = []

    def factory(**kw):
        opened.append(kw)
        return Stream(fail_when=lambda k: "extra_settings" in k, **kw)

    out = output(factory)
    out.start()
    assert len(opened) == 2 and opened[1]["device"] is None and opened[1]["latency"] == "low"
    assert out.opened_host_api is None and out.stream is not None


def test_no_host_api_keeps_a_single_attempt_and_propagates_failure():
    attempts = []

    def factory(**kw):
        attempts.append(kw)
        return Stream(fail_when=lambda k: True, **kw)

    out = output(factory, host_api=None, latency=0.02)
    with pytest.raises(OSError):
        out.start()
    assert len(attempts) == 1 and attempts[0]["latency"] == 0.02 and out.stream is None


def test_exclusive_mode_is_tried_first_then_shared(fake_devices):
    opened = []

    def factory(**kw):
        opened.append(kw)
        return Stream(fail_when=lambda k: len(opened) == 1, **kw)  # the first (exclusive) open is refused

    out = SoundDeviceOutput(CallbackMixer(48000), sample_rate_hz=48000, buffer_frames=128,
                            stream_factory=factory, host_api="Windows WASAPI", exclusive=True)
    out.start()
    assert len(opened) == 2 and all("extra_settings" in k for k in opened)
    assert opened[0]["extra_settings"] is not opened[1]["extra_settings"]
    assert out.opened_host_api == "Windows WASAPI (shared)"
