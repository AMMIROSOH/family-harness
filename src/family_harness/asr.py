"""Replaceable local whole-utterance recognizers; no acquisition on import/load."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Protocol

import numpy as np

from family_harness.errors import SetupError
from family_harness.models import ModelStore
from family_harness.speech import SPEECH_RATE, SherpaStt


class UtteranceRecognizer(Protocol):
    def decode(self, samples: np.ndarray) -> str: ...


def bounded_audio(samples: np.ndarray) -> np.ndarray:
    samples = np.asarray(samples, np.float32)
    if (
        samples.ndim != 1 or not 0 < len(samples) <= SPEECH_RATE * 30
        or not np.isfinite(samples).all()
    ):
        raise ValueError("utterance recognition needs finite mono audio of at most 30 seconds")
    return samples


def recognizer_catalog(backend: str) -> dict:
    profiles = json.loads(files("family_harness").joinpath("asr_catalog.json").read_text("utf-8"))
    if backend not in profiles["profiles"]:
        raise ValueError("unsupported local utterance recognizer")
    return profiles["profiles"][backend]


def recognizer_store(backend: str, root: Path | None = None) -> ModelStore:
    return ModelStore(root, manifest=recognizer_catalog(backend))


def load_recognizer(backend: str, root: Path | None = None) -> UtteranceRecognizer:
    store = recognizer_store(backend, root)
    try:
        store.verify()
    except SetupError as exc:
        raise SetupError(
            "recognizer_invalid", f"The {backend} model is missing or damaged.",
            f"Run family-harness voice install-recognizer {backend}, or import its pinned files. "
            "No audio has been opened.",
        ) from exc
    try:
        return SherpaUtteranceRecognizer(store.profile, backend)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        raise SetupError(
            "recognizer_load_failed", f"The local {backend} recognizer could not load.",
            "Repair the pinned sherpa-onnx installation, close memory-heavy apps, and retry. "
            "Audio has not started.",
        ) from exc


class StreamingUtteranceRecognizer:
    """Evaluate the complete audio independently of VAD and early endpointing."""

    def __init__(self, path: Path):
        import sherpa_onnx

        self.stt = SherpaStt(sherpa_onnx, path)

    def decode(self, samples: np.ndarray) -> str:
        samples = bounded_audio(samples)
        self.stt.reset()
        for offset in range(0, len(samples), 1600):
            self.stt.accept(samples[offset : offset + 1600])
        return self.stt.finish().strip()


class SherpaUtteranceRecognizer:
    """CPU int8 Whisper/Parakeet through the maintained sherpa Python API."""

    def __init__(self, path: Path, backend: str, threads: int = 2):
        import sherpa_onnx

        if backend == "whisper-small-en":
            self.engine = sherpa_onnx.OfflineRecognizer.from_whisper(
                encoder=str(path / "small.en-encoder.int8.onnx"),
                decoder=str(path / "small.en-decoder.int8.onnx"),
                tokens=str(path / "small.en-tokens.txt"),
                language="en",
                task="transcribe",
                num_threads=threads,
                provider="cpu",
            )
        elif backend == "parakeet-v2":
            self.engine = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=str(path / "encoder.int8.onnx"),
                decoder=str(path / "decoder.int8.onnx"),
                joiner=str(path / "joiner.int8.onnx"),
                tokens=str(path / "tokens.txt"),
                num_threads=threads,
                provider="cpu",
                model_type="nemo_transducer",
            )
        else:
            raise ValueError("unsupported local utterance recognizer")

    def decode(self, samples: np.ndarray) -> str:
        samples = bounded_audio(samples)
        stream = self.engine.create_stream()
        stream.accept_waveform(SPEECH_RATE, np.asarray(samples, np.float32))
        self.engine.decode_stream(stream)
        return stream.result.text.strip()
