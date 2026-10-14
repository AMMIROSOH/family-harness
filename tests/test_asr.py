from types import SimpleNamespace

import numpy as np
import pytest

from family_harness.asr import (
    SherpaUtteranceRecognizer,
    StreamingUtteranceRecognizer,
    load_recognizer,
    recognizer_catalog,
)
from family_harness.errors import SetupError


def test_whole_utterance_adapter_passes_exact_audio_and_uses_fresh_stream():
    received = []

    class Stream:
        result = SimpleNamespace(text="correct final")

        def accept_waveform(self, rate, samples):
            assert rate == 16000
            received.append(samples.copy())

    streams = []
    engine = SimpleNamespace(
        create_stream=lambda: streams.append(Stream()) or streams[-1],
        decode_stream=lambda stream: None,
    )
    recognizer = SherpaUtteranceRecognizer.__new__(SherpaUtteranceRecognizer)
    recognizer.engine = engine
    audio = np.linspace(-0.1, 0.1, 3200, dtype=np.float32)
    assert recognizer.decode(audio) == recognizer.decode(audio) == "correct final"
    assert len(streams) == 2 and streams[0] is not streams[1]
    np.testing.assert_array_equal(received[0], audio)


@pytest.mark.parametrize("samples", [
    np.empty(0, np.float32), np.full(160, np.nan, np.float32),
    np.ones(16000 * 30 + 1, np.float32),
    np.ones((160, 2), np.float32), np.array(.1, np.float32),
])
def test_whole_utterance_input_is_bounded_and_validated_before_native_decode(samples):
    recognizer = SherpaUtteranceRecognizer.__new__(SherpaUtteranceRecognizer)
    with pytest.raises(ValueError):
        recognizer.decode(samples)


def test_optional_catalog_is_pinned_and_missing_models_are_actionable(tmp_path):
    for backend in ("parakeet-v2", "whisper-small-en"):
        catalog = recognizer_catalog(backend)
        assert catalog["language"] == "en" and catalog["execution"] == "local-cpu"
        assert all(len(a["sha256"]) == 64 and a["size"] > 0 for a in catalog["assets"])
        assert all("/resolve/main/" not in a["url"] for a in catalog["assets"])
        with pytest.raises(SetupError) as error:
            load_recognizer(backend, tmp_path)
        assert error.value.code == "recognizer_invalid"
        assert f"install-recognizer {backend}" in error.value.recovery
    with pytest.raises(ValueError):
        recognizer_catalog("unknown")


def test_zipformer_load_failure_is_a_model_error_not_a_microphone_error(tmp_path, monkeypatch):
    def missing_files(*args):
        raise AssertionError("tokens.txt does not exist")

    monkeypatch.setattr("family_harness.asr.SherpaStt", missing_files)
    with pytest.raises(SetupError) as error:
        StreamingUtteranceRecognizer(tmp_path / "stt")
    assert error.value.code == "recognizer_load_failed"
    assert "Quick Setup > Models" in error.value.recovery
    assert "microphone has not started" in error.value.recovery
