import json
import sys
import wave
from types import SimpleNamespace

import numpy as np
import pytest
from conftest import FakeAudio, FakeStream
from test_speech import FakeStt, FakeVad

from family_harness.errors import SetupError
from family_harness.speech import StreamingResampler, WebRtcSpeechInput
from family_harness.voice_trial import capture, playback, replay
from family_harness.voice_worker import execute, public_report


def voice(speech_chunks=10):
    return SimpleNamespace(
        vad=FakeVad(speech_chunks),
        stt=FakeStt(),
        resampler=lambda a, b=16000: StreamingResampler(a, b),
        input_processor=WebRtcSpeechInput(),
    )


def metrics():
    return SimpleNamespace(decode_ms=[])


def test_native_capture_uses_chosen_microphone_and_closes_at_candidate(devices, selection):
    sd = FakeAudio()
    events = []
    result = capture(
        {**selection, "endpoint_id": "endpoint"}, devices, sd, voice(), events.append, metrics()
    )
    assert result["candidate"] and result["transcript"] == "hello room"
    assert sd.streams[0].options["device"] == 7
    assert sd.streams[0].kind == "input" and sd.streams[0].closed
    assert not sd.played
    assert any(e["type"] == "progress" and e["phase"] == "listening" for e in events)
    progress = next(e for e in events if e.get("phase") == "listening")
    assert "processed_level_dbfs" in progress and "speech_active" in progress
    assert result["input_levels"]["raw"]["rms_dbfs"] > -120
    assert result["recognition_status"] == "recognized"


def test_silent_capture_is_bounded_and_has_no_completed_candidate(devices, selection):
    sd = FakeAudio(input_level=0)
    result = capture(
        {**selection, "endpoint_id": "endpoint"}, devices, sd, voice(0), lambda e: None, metrics()
    )
    assert not result["candidate"] and not result["transcript"]
    assert result["audio_seconds"] == 20
    assert sd.streams[0].closed
    assert result["recognition_status"] == "no_speech_detected"
    assert result["input_levels"]["raw"]["rms_dbfs"] == -120
    assert result["input_levels"]["processed"]["peak"] == 0


@pytest.mark.parametrize("options", [{"gap_at": 4}, {"disconnect_after": 5}])
def test_audio_gap_or_disconnect_discards_incomplete_trial(devices, selection, options):
    sd = FakeAudio(**options)
    with pytest.raises(SetupError):
        capture(
            {**selection, "endpoint_id": "endpoint"},
            devices,
            sd,
            voice(),
            lambda e: None,
            metrics(),
        )
    assert sd.streams[0].closed


def test_tts_playback_uses_selected_speaker_without_microphone(devices, selection, monkeypatch):
    sd = FakeAudio()
    monkeypatch.setattr(
        FakeStream, "time", property(lambda s: len(s.backend.played) / 100), raising=False
    )
    samples = np.ones(1600, np.float32) * 0.1
    playback(selection, devices, sd, voice(), samples, 16000, lambda e: None)
    assert sd.streams[0].kind == "output" and sd.streams[0].options["device"] == 3
    assert sd.streams[0].closed
    played = np.concatenate(sd.played)
    np.testing.assert_allclose(played[:1600], 0.025)
    assert np.all(played[1600:] == 0)


def test_output_underrun_is_not_reported_as_successful_playback(devices, selection, monkeypatch):
    sd = FakeAudio(gap_at=4)
    monkeypatch.setattr(
        FakeStream, "time", property(lambda s: len(s.backend.played) / 100), raising=False
    )
    with pytest.raises(SetupError) as error:
        playback(selection, devices, sd, voice(), np.ones(1600, np.float32), 16000, lambda e: None)
    assert error.value.code == "voice_output_gap" and sd.streams[0].closed


def test_replay_uses_same_candidate_and_never_opens_devices(tmp_path, monkeypatch):
    path = tmp_path / "example.wav"
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, 16000, 0, "NONE", ""))
        output.writeframes(np.ones(1600, dtype="<i2").tobytes())
    monkeypatch.setitem(sys.modules, "sounddevice", None)
    result = replay(path, voice(), lambda e: None, metrics())
    assert result["candidate"] and result["source"] == "file"
    assert result["file_audio_seconds"] == 0.1


def test_invalid_replay_has_actionable_error_without_devices(tmp_path):
    path = tmp_path / "bad.wav"
    path.write_bytes(b"not audio")
    with pytest.raises(SetupError) as error:
        replay(path, voice(), lambda e: None, metrics())
    assert error.value.code == "invalid_replay"


def test_warm_only_verifies_before_loading_and_never_opens_audio(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("family_harness.models.ModelStore.verify", lambda s: calls.append("verify"))

    class WarmVoice:
        def __init__(self, path):
            calls.append("load")

        def warm(self):
            calls.append("warm")
            return {"warm_seconds": 0.1}

    monkeypatch.setattr("family_harness.speech.LocalVoice", WarmVoice)
    monkeypatch.setitem(sys.modules, "sounddevice", None)
    result = execute({"kind": "voice_warm", "models": str(tmp_path)}, lambda e: None)
    assert calls == ["verify", "load", "warm"]
    assert result["hardware_gate"] == "pending"
    saved = json.loads((tmp_path / "benchmark.json").read_text())
    assert saved["measurements"]["peak_sampled_rss_mb"] > 0


def test_persisted_report_excludes_personal_text_and_utterance_identity():
    result = public_report(
        {
            "transcript": "a private sentence",
            "utterance_id": "abc",
            "tts_seconds": 0.2,
            "hardware_gate": "pending",
        }
    )
    assert result == {"tts_seconds": 0.2, "hardware_gate": "pending"}
