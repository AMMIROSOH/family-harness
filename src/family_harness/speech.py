"""Replaceable local speech adapters and a single silence-based completion candidate."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import numpy as np

from family_harness.audio import Levels, dbfs
from family_harness.errors import SetupError

SPEECH_RATE = 16000
COMPLETION_SILENCE = 0.6
VAD_RELEASE_ALLOWANCE = 0.7
RECOGNIZER_LEAD_IN = 0.8
RESPONSE_TEXT = "The local English voice test is complete. Please check the transcript on screen."


@dataclass(frozen=True)
class VoiceSettings:
    """Explicit signal/decoder choices, independent of device names and identity."""

    processing: bool = True
    decoding: str = "greedy_search"
    silence: float = COMPLETION_SILENCE
    vad_threshold: float = 0.5
    gain_db: float = 0.0

    def __post_init__(self):
        if self.decoding not in ("greedy_search", "modified_beam_search"):
            raise ValueError("unsupported speech decoder")
        if not 0.3 <= self.silence <= 2 or not 0.1 <= self.vad_threshold <= 0.9:
            raise ValueError("invalid speech timing or VAD threshold")
        if not 0 <= self.gain_db <= 36:
            raise ValueError("input gain must be between zero and 36 dB")


VOICE_PRESETS = {
    "room": VoiceSettings(),
    "close-talk": VoiceSettings(processing=False),
    "room-beam": VoiceSettings(decoding="modified_beam_search"),
    "close-talk-beam": VoiceSettings(processing=False, decoding="modified_beam_search"),
    "quiet-room": VoiceSettings(processing=False, gain_db=36, silence=0.9),
    "quiet-close-talk": VoiceSettings(processing=True, gain_db=12, silence=0.9),
    "quiet-final": VoiceSettings(
        processing=False, gain_db=24, vad_threshold=0.3, silence=1.2,
    ),
}


def replay_tail_seconds(silence: float) -> float:
    # Silero can retain activity for ~560 ms after waveform silence at high gain.
    return max(1, silence + VAD_RELEASE_ALLOWANCE)


class ActivityDetector(Protocol):
    def accept(self, samples: np.ndarray) -> bool: ...


class StreamingRecognizer(Protocol):
    def accept(self, samples: np.ndarray) -> str: ...
    def finish(self) -> str: ...


class FinalRecognizer(Protocol):
    def decode(self, samples: np.ndarray) -> str: ...


class Synthesizer(Protocol):
    def synthesize(self, text: str) -> tuple[np.ndarray, int]: ...


class SpeechProcessor(Protocol):
    def process(self, samples: np.ndarray, flush: bool = False) -> np.ndarray: ...
    def diagnostics(self) -> dict: ...


class WebRtcSpeechInput:
    """Speech-only NS/AGC2; acoustic measurements keep their unmodified input.

    Buffer exact 10 ms frames so resampler chunk boundaries do not cause the
    library to insert padding between live frames. Only the final tail is padded.
    """

    def __init__(self, gain_db: float = 0):
        self.fixed_gain_db = gain_db
        try:
            from pywebrtc_audio import AudioProcessor

            self.processor = AudioProcessor(
                sample_rate=SPEECH_RATE,
                num_channels=1,
                echo_cancellation=False,
                high_pass_filter=True,
                noise_suppression=True,
                ns_level=1,
                auto_gain_control=True,
                agc_max_gain_db=30,
            )
        except (ImportError, OSError, RuntimeError) as exc:
            raise SetupError(
                "speech_processing_unavailable",
                "The local microphone level adjustment could not load.",
                "Rerun Install-Windows.cmd to repair pywebrtc-audio and retry. Audio is off.",
            ) from exc
        self.pending = np.empty(0, np.float32)
        self.raw, self.clean = Levels(), Levels()
        self.gain_db = self.max_gain_db = 0.0
        self.level_dbfs = -120.0

    def process(self, samples: np.ndarray, flush: bool = False) -> np.ndarray:
        if len(samples):
            self.raw.add(samples)
        samples = np.clip(samples * 10 ** (self.fixed_gain_db / 20), -1, 1)
        joined = np.concatenate((self.pending, samples))
        count = len(joined) if flush else len(joined) // 160 * 160
        self.pending = joined[count:]
        if not count:
            return np.empty(0, np.float32)
        # WebRTC supplies the limiter; no per-chunk peak normalization or fixed boost.
        output = np.asarray(self.processor.process(joined[:count]), np.float32)
        self.clean.add(output)
        self.level_dbfs = dbfs(float(np.mean(output**2)))
        self.gain_db = float(self.processor.gain_db)
        self.max_gain_db = max(self.max_gain_db, self.gain_db)
        return output

    def diagnostics(self) -> dict:
        return {
            "processor": "WebRTC NS + AGC2 + high-pass",
            "fixed_input_gain_db": self.fixed_gain_db,
            "max_adaptive_gain_db": 30,
            "max_observed_gain_db": round(self.max_gain_db, 1),
            "raw": self.raw.result(),
            "processed": self.clean.result(),
        }


class GainSpeechInput:
    """Explicit fixed microphone calibration with clipping diagnostics."""

    def __init__(self, gain_db: float):
        self.gain_db = gain_db
        self.raw, self.clean = Levels(), Levels()
        self.level_dbfs = -120.0

    def process(self, samples: np.ndarray, flush: bool = False) -> np.ndarray:
        if not len(samples):
            return samples
        self.raw.add(samples)
        output = np.clip(samples * 10 ** (self.gain_db / 20), -1, 1)
        self.clean.add(output)
        self.level_dbfs = dbfs(float(np.mean(output**2)))
        return output

    def diagnostics(self):
        return {
            "processor": "fixed input gain + clipping guard",
            "fixed_input_gain_db": self.gain_db,
            "raw": self.raw.result(), "processed": self.clean.result(),
        }


def speech_input(settings: VoiceSettings) -> SpeechProcessor | None:
    if settings.processing:
        return WebRtcSpeechInput(settings.gain_db)
    return GainSpeechInput(settings.gain_db) if settings.gain_db else None


class SpeechTurn:
    """One bounded test utterance. A candidate is not semantic turn understanding."""

    def __init__(
        self,
        vad: ActivityDetector,
        stt: StreamingRecognizer,
        emit: Callable,
        language: str = "en",
        processor: SpeechProcessor | None = None,
        completion_silence: float = COMPLETION_SILENCE,
        finalizer: FinalRecognizer | None = None,
        defer_finalization: bool = False,
    ):
        self.vad, self.stt, self.emit = vad, stt, emit
        self.processor = processor
        self.completion_silence = completion_silence
        self.finalizer = finalizer
        self.defer_finalization = defer_finalization
        self.final_samples: list[np.ndarray] = []
        self.final_sample_count = 0
        self.candidate_end: float | None = None
        self.processor_origin: float | None = None
        self.processed_samples = 0
        self.speech_active = False
        self.language = language
        self.utterance_id = str(uuid4())
        self.revision = 0
        self.text = ""
        self.started: float | None = None
        self.last_speech: float | None = None
        self.ended = False
        self.partial_latency: float | None = None
        self.candidate_latency: float | None = None

    def _transcript(self, text: str, end: float, final: bool, reason: str | None = None):
        if text != self.text or final or (self.finalizer is not None and not self.revision):
            self.revision += 1
            self.text = text
            self.emit(
                {
                    "type": "transcript",
                    "utterance_id": self.utterance_id,
                    "revision": self.revision,
                    "text": text,
                    "final": final,
                    "language": self.language,
                    "start": self.started,
                    "end": end,
                    "reason": reason,
                }
            )

    def _recognize(self, samples: np.ndarray, start: float) -> float:
        if self.finalizer and self.final_sample_count < SPEECH_RATE * 30:
            bounded = samples[: SPEECH_RATE * 30 - self.final_sample_count].copy()
            self.final_samples.append(bounded)
            self.final_sample_count += len(bounded)
        end = start + len(samples) / SPEECH_RATE
        speech = self.vad.accept(samples)
        self.speech_active = speech
        # Feed from sample zero, including speech before VAD confirmation. VAD
        # controls presentation/completion, never which onset audio STT receives.
        text = self.stt.accept(samples).strip()
        if speech:
            if self.started is None:
                self.started = start
                self.emit(
                    {"type": "speech_started", "at": start, "utterance_id": self.utterance_id}
                )
            self.last_speech = end
        if self.started is not None:
            if text and self.partial_latency is None:
                self.partial_latency = (end - self.started) * 1000
            self._transcript(text, end, False)
        return end

    def accept(self, samples: np.ndarray, start: float) -> bool:
        if self.ended:
            return True
        if self.candidate_end is not None:
            return True
        if self.processor:
            if self.processor_origin is None:
                self.processor_origin = start
            samples = self.processor.process(samples)
            start = self.processor_origin + self.processed_samples / SPEECH_RATE
            self.processed_samples += len(samples)
        if not len(samples):
            return False
        end = self._recognize(samples, start)
        # Streaming-only trials require words. A finalizer can recover speech
        # missing from the draft, so it can complete after VAD activity alone.
        if (
            (self.text or self.finalizer is not None)
            and self.last_speech is not None
            and end - self.last_speech >= self.completion_silence
        ):
            self.emit(
                {
                    "type": "turn_candidate",
                    "utterance_id": self.utterance_id,
                    "at": end,
                    "speech_end": self.last_speech,
                    "authority": "vad-silence",
                    "silence_seconds": self.completion_silence,
                }
            )
            before = time.perf_counter()
            self.candidate_end = end
            if not self.defer_finalization:
                self.finish(end, "silence_candidate")
            self.candidate_latency = (end - self.last_speech) * 1000 + (
                time.perf_counter() - before
            ) * 1000
            return True
        return False

    def finish(self, end: float, reason: str) -> None:
        if not self.ended:
            if self.processor:
                tail = self.processor.process(np.empty(0, np.float32), flush=True)
                if len(tail):
                    self._recognize(
                        tail, (self.processor_origin or 0) + self.processed_samples / SPEECH_RATE
                    )
                    self.processed_samples += len(tail)
            # No hallucinated transcript for a silent test.
            text = ""
            before = time.perf_counter()
            if self.started is not None:
                text = (
                    self.finalizer.decode(np.concatenate(self.final_samples)).strip()
                    if self.finalizer and self.final_sample_count
                    else self.stt.finish().strip()
                )
            self._transcript(text, end, True, reason)
            self.ended = True
            self.final_samples.clear()
            if self.defer_finalization and self.candidate_end is not None:
                self.candidate_latency = (
                    (self.candidate_end - self.last_speech) * 1000
                    + (time.perf_counter() - before) * 1000
                )


class SherpaVad:
    def __init__(self, runtime, path: Path, threshold: float = 0.5):
        config = runtime.VadModelConfig()
        config.silero_vad.model = str(path)
        config.silero_vad.threshold = threshold
        config.silero_vad.min_speech_duration = 0.1
        config.silero_vad.min_silence_duration = 0.1
        config.silero_vad.max_speech_duration = 30
        config.sample_rate = SPEECH_RATE
        config.num_threads = 1
        config.provider = "cpu"
        self.window = config.silero_vad.window_size
        # Leave room for VAD lookahead beyond the 30-second segment limit.
        self.detector = runtime.VoiceActivityDetector(config, buffer_size_in_seconds=32)
        self.pending = np.empty(0, np.float32)

    def reset(self) -> None:
        self.detector.reset()
        self.pending = np.empty(0, np.float32)

    def accept(self, samples: np.ndarray) -> bool:
        self.pending = np.concatenate((self.pending, samples))
        while len(self.pending) >= self.window:
            self.detector.accept_waveform(self.pending[: self.window])
            self.pending = self.pending[self.window :]
            # Only activity is needed here; completed audio segments are discarded.
            while not self.detector.empty():
                self.detector.pop()
        return self.detector.is_speech_detected()


class SherpaStt:
    def __init__(self, runtime, path: Path, decoding: str = "greedy_search"):
        self.recognizer = runtime.OnlineRecognizer.from_transducer(
            tokens=str(path / "tokens.txt"),
            encoder=str(path / "encoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx"),
            decoder=str(path / "decoder-epoch-99-avg-1-chunk-16-left-128.onnx"),
            joiner=str(path / "joiner-epoch-99-avg-1-chunk-16-left-128.int8.onnx"),
            num_threads=2,
            sample_rate=SPEECH_RATE,
            feature_dim=80,
            decoding_method=decoding,
            provider="cpu",
            enable_endpoint_detection=False,
        )
        self.reset()

    def reset(self) -> None:
        # Supply left context before real speech, including after warm-up. This
        # is synthetic model input, not a capture delay or a shift in VAD time.
        self.stream = self.recognizer.create_stream()
        self.accept(np.zeros(int(RECOGNIZER_LEAD_IN * SPEECH_RATE), np.float32))

    def _decode(self) -> str:
        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_stream(self.stream)
        return self.recognizer.get_result(self.stream)

    def accept(self, samples: np.ndarray) -> str:
        self.stream.accept_waveform(SPEECH_RATE, samples)
        return self._decode()

    def finish(self) -> str:
        self.stream.accept_waveform(SPEECH_RATE, np.zeros(int(0.4 * SPEECH_RATE), np.float32))
        self.stream.input_finished()
        return self._decode()


class SherpaTts:
    def __init__(self, runtime, path: Path):
        config = runtime.OfflineTtsConfig(
            model=runtime.OfflineTtsModelConfig(
                vits=runtime.OfflineTtsVitsModelConfig(
                    model=str(path / "en_US-lessac-low.onnx"),
                    tokens=str(path / "tokens.txt"),
                    data_dir=str(path / "espeak-ng-data"),
                ),
                num_threads=2,
                provider="cpu",
                debug=False,
            ),
            max_num_sentences=1,
        )
        if not config.validate():
            raise ValueError("invalid TTS configuration")
        self.engine = runtime.OfflineTts(config)

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        audio = self.engine.generate(text, sid=0, speed=1.0)
        samples = np.asarray(audio.samples, dtype=np.float32)
        if (
            not len(samples)
            or not np.isfinite(samples).all()
            or len(samples) / audio.sample_rate > 15
        ):
            raise SetupError(
                "tts_failed",
                "The test voice did not produce usable bounded audio.",
                "Repair the English CPU profile and retry.",
            )
        return np.clip(samples, -1, 1), audio.sample_rate


class LocalVoice:
    """Loads local paths only. No model SDK download helpers or network fallback."""

    def __init__(
        self, profile: Path, settings: VoiceSettings | None = None,
        finalizer: FinalRecognizer | None = None,
    ):
        self.settings = settings or VoiceSettings()
        self.finalizer = finalizer
        try:
            import sherpa_onnx

            self.runtime = sherpa_onnx
            self.vad = SherpaVad(
                sherpa_onnx, profile / "vad/silero_vad.onnx", self.settings.vad_threshold
            )
            self.stt = SherpaStt(sherpa_onnx, profile / "stt", self.settings.decoding)
            self.tts = SherpaTts(sherpa_onnx, profile / "tts")
            self.input_processor = speech_input(self.settings)
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            raise SetupError(
                "voice_load_failed",
                "The local English speech models could not load.",
                "Rerun Install-Windows.cmd with Windows x64 Python, verify the model files, "
                "and retry. Audio has not started.",
            ) from exc

    def warm(self) -> dict:
        start = time.perf_counter()
        silence = np.zeros(SPEECH_RATE, np.float32)
        self.vad.accept(silence)
        self.stt.accept(silence)
        self.stt.finish()
        if self.finalizer:
            self.finalizer.decode(silence)
        self.tts.synthesize("Ready.")
        # Discard warm-up state, retain the loaded recognizer/models.
        self.stt.reset()
        self.vad.detector.reset()
        self.vad.pending = np.empty(0, np.float32)
        return {
            "warm_seconds": round(time.perf_counter() - start, 3),
            "recognizer_lead_in_seconds": RECOGNIZER_LEAD_IN,
        }

    def resampler(self, rate: int, target: int = SPEECH_RATE):
        return StreamingResampler(rate, target)

    def reset_input(self) -> None:
        self.stt.reset()
        self.vad.reset()
        self.input_processor = speech_input(self.settings)


class StreamingResampler:
    def __init__(self, rate: int, target: int):
        import soxr

        self.stream = soxr.ResampleStream(rate, target, 1, dtype="float32", quality="LQ")

    def resample(self, samples: np.ndarray, flush: bool = False) -> np.ndarray:
        return self.stream.resample_chunk(samples, last=flush)
