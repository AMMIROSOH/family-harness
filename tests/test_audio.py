from dataclasses import replace

import numpy as np
import pytest
from conftest import FakeAudio

from family_harness.audio import AudioClock, AudioFrame, WebRtcEcho, format_for, run_audio
from family_harness.audio import test_sound as make_sound
from family_harness.errors import SetupError


def frame(sequence, capture, playback=None, discontinuity=False):
    return AudioFrame(
        "endpoint",
        sequence,
        16000,
        capture,
        capture + 0.03 if playback is None else playback,
        np.zeros(160, np.float32),
        np.zeros(160, np.float32),
        discontinuity,
    )


def test_audio_clock_detects_dropped_frames_and_clock_jumps():
    clock = AudioClock()
    assert not clock.observe(frame(0, 0))
    assert not clock.observe(frame(1, 0.01))
    assert clock.observe(frame(3, 0.03))
    assert clock.observe(frame(4, 0.08))
    assert clock.observe(frame(5, 0.09, playback=0.4))
    assert clock.observe(frame(6, 0.1, discontinuity=True))
    assert clock.gaps == 4


def test_no_duplex_format_gives_recovery(devices):
    with pytest.raises(SetupError) as error:
        format_for("duplex", replace(devices[0], rates=(44100,)), devices[1])
    assert error.value.code == "incompatible_devices"


@pytest.mark.parametrize(
    "level,expected", [(0.0, "Almost no input"), (1.0, "clipped"), (0.001, "quiet")]
)
def test_microphone_diagnoses_signal_and_closes(devices, selection, level, expected):
    sd = FakeAudio(input_level=level)
    result = run_audio(
        {**selection, "kind": "microphone", "endpoint_id": "test"}, devices, sd, lambda _: None
    )
    assert any(expected in message for message in result["messages"])
    assert result["frames"] == 800
    assert sd.streams[0].closed
    assert sd.streams[0].options["device"] == 7
    assert not sd.played


def test_noise_check_reports_noisy_room(devices, selection):
    result = run_audio(
        {**selection, "kind": "noise", "endpoint_id": "test"},
        devices,
        FakeAudio(input_level=0.05),
        lambda _: None,
    )
    assert any("Background noise" in message for message in result["messages"])


def test_speaker_test_never_opens_microphone(devices, selection):
    sd = FakeAudio()
    result = run_audio(
        {**selection, "kind": "speaker", "endpoint_id": "test"}, devices, sd, lambda _: None
    )
    assert sd.streams[0].kind == "output"
    assert sd.streams[0].options["device"] == 3
    assert result["frames"] == 300


def test_duplex_reference_is_exact_played_audio_and_gap_resets_echo(devices, selection):
    sd = FakeAudio(gap_at=510)

    class EchoSpy:
        def __init__(self, rate):
            self.far = []
            self.delays = []
            self.resets = 0

        def process(self, near, far, delay):
            self.far.append(far.copy())
            self.delays.append(delay)
            return near.copy()

        def reset(self):
            self.resets += 1

    spy = EchoSpy(48000)
    result = run_audio(
        {**selection, "kind": "duplex", "endpoint_id": "test"},
        devices,
        sd,
        lambda _: None,
        echo_factory=lambda rate: spy,
    )
    expected = make_sound(48000, 12, "duplex")
    np.testing.assert_array_equal(np.concatenate(spy.far), expected)
    np.testing.assert_array_equal(np.concatenate(sd.played)[: len(expected)], expected)
    assert set(spy.delays) == {30}
    assert spy.resets == result["audio_gaps"] == 1
    assert result["status"] == "needs_attention"


def test_device_echo_mode_does_not_enable_second_processor(devices, selection):
    def unexpected(rate):
        raise AssertionError("second echo remover")

    result = run_audio(
        {**selection, "kind": "duplex", "endpoint_id": "test", "echo_owner": "device"},
        devices,
        FakeAudio(),
        lambda _: None,
        echo_factory=unexpected,
    )
    assert result["echo_owner"] == "device"


def test_hot_unplug_releases_stream(devices, selection):
    sd = FakeAudio(disconnect_after=20)
    with pytest.raises(SetupError) as error:
        run_audio(
            {**selection, "kind": "microphone", "endpoint_id": "test"}, devices, sd, lambda _: None
        )
    assert error.value.code in ("audio_stalled", "device_disconnected")
    assert sd.streams[0].closed


def test_permission_denial_closes_created_stream(devices, selection):
    sd = FakeAudio(failure=PermissionError("access denied"))
    with pytest.raises(PermissionError):
        run_audio(
            {**selection, "kind": "microphone", "endpoint_id": "test"}, devices, sd, lambda _: None
        )
    assert sd.streams[0].closed


def test_slow_consumer_reports_bounded_buffer_drops(devices, selection):
    import time

    def slow_progress(event):
        time.sleep(0.08)

    result = run_audio(
        {**selection, "kind": "microphone", "endpoint_id": "test"},
        devices,
        FakeAudio(),
        slow_progress,
    )
    assert result["dropped_frames"] > 0
    assert result["audio_gaps"] > 0
    assert result["status"] == "needs_attention"


def test_real_webrtc_reduces_synthetic_echo_and_keeps_near_signal():
    rate = 16000
    random = np.random.default_rng(12)
    far = random.normal(0, 0.06, rate * 8).astype(np.float32)
    echo = np.zeros_like(far)
    delay_samples = 480
    echo[delay_samples:] = 0.6 * far[:-delay_samples]
    near_voice = np.zeros_like(far)
    t = np.arange(rate * 2) / rate
    near_voice[-rate * 2 :] = (0.12 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    processor = WebRtcEcho(rate)
    clean = np.concatenate(
        [
            processor.process(echo[i : i + 160] + near_voice[i : i + 160], far[i : i + 160], 30)
            for i in range(0, len(far), 160)
        ]
    )
    echo_window = slice(rate * 4, rate * 6)
    assert np.mean(clean[echo_window] ** 2) < np.mean(echo[echo_window] ** 2) * 0.1
    assert np.sqrt(np.mean(clean[-rate:] ** 2)) > 0.02
