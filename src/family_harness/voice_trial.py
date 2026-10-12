"""Bounded native and file trials. Capture closes before test-response playback."""

from __future__ import annotations

import platform
import queue
import sys
import threading
import time
import wave
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path

import numpy as np
import psutil

from family_harness.audio import BUFFER_FRAMES, AudioClock, AudioFrame, dbfs, format_for
from family_harness.devices import resolve
from family_harness.errors import SetupError
from family_harness.speech import (
    COMPLETION_SILENCE,
    RESPONSE_TEXT,
    SPEECH_RATE,
    SpeechTurn,
    replay_tail_seconds,
)

CAPTURE_SECONDS = 20


def cpu_name() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            ) as key:
                return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    return platform.processor()


class Measurements:
    def __init__(self):
        self.process = psutil.Process()
        self.start = time.perf_counter()
        self.cpu_start = sum(self.process.cpu_times()[:2])
        self.peak_rss = self.process.memory_info().rss
        self.decode_ms: list[float] = []
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self._sample, daemon=True)
        self.thread.start()

    def _sample(self):
        while not self.closed.wait(0.1):
            self.peak_rss = max(self.peak_rss, self.process.memory_info().rss)

    def finish(self) -> dict:
        self.closed.set()
        self.thread.join(timeout=1)
        elapsed = time.perf_counter() - self.start
        cpu = sum(self.process.cpu_times()[:2]) - self.cpu_start
        self.peak_rss = max(self.peak_rss, self.process.memory_info().rss)
        return {
            "wall_seconds": round(elapsed, 3),
            "cpu_seconds": round(cpu, 3),
            "mean_cpu_core_percent": round(100 * cpu / max(elapsed, 1e-6), 1),
            "peak_sampled_rss_mb": round(self.peak_rss / 1024**2, 1),
            "frame_processing_ms": {
                "count": len(self.decode_ms),
                "p50": round(float(np.percentile(self.decode_ms, 50)), 2)
                if self.decode_ms
                else None,
                "p95": round(float(np.percentile(self.decode_ms, 95)), 2)
                if self.decode_ms
                else None,
                "max": round(max(self.decode_ms), 2) if self.decode_ms else None,
            },
            "environment": {
                "os": platform.platform(),
                "cpu": cpu_name(),
                "logical_cpus": psutil.cpu_count(),
                "ram_mb": round(psutil.virtual_memory().total / 1024**2),
                "python": platform.python_version(),
                "packages": {
                    name: version(name)
                    for name in (
                        "sherpa-onnx", "sherpa-onnx-core", "numpy", "sounddevice", "soxr",
                        "pywebrtc-audio",
                    )
                },
            },
        }


def process_chunk(turn, samples, start, metrics):
    before = time.perf_counter()
    ended = turn.accept(samples, start)
    metrics.decode_ms.append((time.perf_counter() - before) * 1000)
    return ended


def capture(request: dict, devices, sd, voice, emit: Callable, metrics: Measurements) -> dict:
    microphone = resolve(devices, request.get("input_id"), "input")
    rate = 16000 if 16000 in microphone.rates else format_for("microphone", microphone, None)
    resampler = voice.resampler(rate) if rate != SPEECH_RATE else None
    buffer = queue.Queue(maxsize=BUFFER_FRAMES)
    sequence = 0
    dropped = 0

    def transfer(indata, frames, timing, status):
        nonlocal sequence, dropped
        frame = AudioFrame(
            request["endpoint_id"],
            sequence,
            rate,
            timing.inputBufferAdcTime,
            timing.inputBufferAdcTime,
            indata[:, 0].copy(),
            np.zeros(frames, np.float32),
            bool(status),
        )
        try:
            buffer.put_nowait((frame, time.perf_counter()))
        except queue.Full:
            dropped += 1
        sequence += 1

    stream = sd.InputStream(
        samplerate=rate,
        blocksize=rate // 100,
        device=microphone.index,
        channels=1,
        dtype="float32",
        latency="low",
        extra_settings=sd.WasapiSettings(auto_convert=True),
        callback=transfer,
    )
    turn = SpeechTurn(
        voice.vad, voice.stt, emit, processor=voice.input_processor,
        completion_silence=getattr(getattr(voice, "settings", None), "silence", COMPLETION_SILENCE),
        finalizer=getattr(voice, "finalizer", None), defer_finalization=True,
    )
    clock = AudioClock()
    processed = 0
    lag_ms = 0.0
    last_progress = 0.0
    deadline = time.monotonic() + CAPTURE_SECONDS + 4
    try:
        with stream:
            while time.monotonic() < deadline:
                try:
                    frame, arrived = buffer.get(timeout=0.5)
                except queue.Empty as exc:
                    raise SetupError(
                        "audio_stalled",
                        "The microphone stopped sending audio.",
                        "Reconnect it, refresh devices, and start a new trial.",
                    ) from exc
                if not stream.active or clock.observe(frame) or dropped:
                    raise SetupError(
                        "voice_audio_gap",
                        "Audio was lost during the voice trial.",
                        "Close busy apps, reconnect the microphone, and retry. "
                        "Incomplete speech has been discarded.",
                    )
                samples = (
                    np.asarray(resampler.resample(frame.samples, flush=False), np.float32)
                    if resampler
                    else frame.samples
                )
                lag_ms = max(lag_ms, (time.perf_counter() - arrived) * 1000)
                done = process_chunk(turn, samples, processed / SPEECH_RATE, metrics)
                processed += len(samples)
                seconds = processed / SPEECH_RATE
                if time.monotonic() - last_progress >= 0.1:
                    energy = float(np.mean(frame.samples**2))
                    emit(
                        {
                            "type": "progress",
                            "phase": "listening",
                            "seconds": seconds,
                            "duration": CAPTURE_SECONDS,
                            "level": min(1, energy**0.5 * 10),
                            "level_dbfs": dbfs(energy),
                            "processed_level_dbfs": voice.input_processor.level_dbfs
                            if voice.input_processor else dbfs(energy),
                            "gain_db": round(voice.input_processor.gain_db, 1)
                            if voice.input_processor else 0,
                            "speech_active": turn.speech_active,
                        }
                    )
                    last_progress = time.monotonic()
                if done or seconds >= CAPTURE_SECONDS:
                    break
            else:
                raise SetupError(
                    "audio_timeout",
                    "The voice trial could not finish on time.",
                    "Close busy apps and retry.",
                )
    finally:
        stream.close()
    if not turn.ended:
        if getattr(voice, "finalizer", None):
            emit({"type": "progress", "phase": "finalizing", "seconds": 0, "duration": 1})
        before = time.perf_counter()
        turn.finish(
            processed / SPEECH_RATE,
            "silence_candidate" if turn.candidate_end is not None else "trial_limit",
        )
        metrics.decode_ms.append((time.perf_counter() - before) * 1000)
    result = turn_result(turn, processed / SPEECH_RATE, lag_ms, "native")
    result["capture_sample_rate"] = rate
    return result


def turn_result(turn: SpeechTurn, duration: float, lag_ms: float, source: str) -> dict:
    result = {
        "transcript": turn.text,
        "utterance_id": turn.utterance_id,
        "candidate": turn.candidate_latency is not None,
        "audio_seconds": round(duration, 3),
        "source": source,
        "speech_detected": turn.started is not None,
        "first_partial_audio_ms": round(turn.partial_latency, 1)
        if turn.partial_latency is not None
        else None,
        "completion_after_vad_ms": round(turn.candidate_latency + lag_ms, 1)
        if turn.candidate_latency is not None
        else None,
        "max_capture_queue_ms": round(lag_ms, 1),
        "audio_gaps": 0,
    }
    if turn.processor:
        result["input_levels"] = turn.processor.diagnostics()
    result["recognition_status"] = (
        "recognized" if turn.text else "speech_without_text" if turn.started is not None
        else "no_speech_detected"
    )
    return result


def replay(path: Path, voice, emit: Callable, metrics: Measurements) -> dict:
    # A replay is an explicit local file action; no audio device is opened.
    try:
        with wave.open(str(path), "rb") as recording:
            rate = recording.getframerate()
            if (
                recording.getnchannels() != 1
                or recording.getsampwidth() != 2
                or recording.getcomptype() != "NONE"
                or not 8000 <= rate <= 48000
                or not 0 < recording.getnframes() <= rate * 30
            ):
                raise ValueError("unsupported WAV")
            raw = recording.readframes(recording.getnframes())
            if len(raw) != recording.getnframes() * 2:
                raise ValueError("truncated WAV")
            samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
    except (OSError, ValueError, EOFError, wave.Error) as exc:
        raise SetupError(
            "invalid_replay",
            "Choose a PCM16 mono WAV of at most 30 seconds.",
            "Export it at 8–48 kHz. No microphone is needed.",
        ) from exc
    if rate != SPEECH_RATE:
        samples = np.asarray(voice.resampler(rate).resample(samples, flush=True), np.float32)
    turn = SpeechTurn(
        voice.vad, voice.stt, emit, processor=voice.input_processor,
        completion_silence=getattr(getattr(voice, "settings", None), "silence", COMPLETION_SILENCE),
        finalizer=getattr(voice, "finalizer", None),
    )
    processed = 0
    for offset in range(0, len(samples), 160):
        chunk = samples[offset : offset + 160]
        done = process_chunk(turn, chunk, offset / SPEECH_RATE, metrics)
        processed += len(chunk)
        if done:
            break
    # Trailing silence allows the same candidate detector to finish a replay.
    if not turn.ended:
        for _ in range(int(replay_tail_seconds(turn.completion_silence) * 100)):
            done = process_chunk(turn, np.zeros(160, np.float32), processed / SPEECH_RATE, metrics)
            processed += 160
            if done:
                break
    before = time.perf_counter()
    turn.finish(processed / SPEECH_RATE, "replay_eof")
    metrics.decode_ms.append((time.perf_counter() - before) * 1000)
    result = turn_result(turn, processed / SPEECH_RATE, 0, "file")
    result["file_audio_seconds"] = round(len(samples) / SPEECH_RATE, 3)
    return result


def synthesize(voice, result: dict) -> tuple[np.ndarray, int]:
    before = time.perf_counter()
    samples, rate = voice.tts.synthesize(RESPONSE_TEXT)
    result["tts_seconds"] = round(time.perf_counter() - before, 3)
    result["response_audio_seconds"] = round(len(samples) / rate, 3)
    result["response_sample_rate"] = rate
    result["tts_real_time_factor"] = round(result["tts_seconds"] / (len(samples) / rate), 3)
    return samples, rate


def playback(request, devices, sd, voice, samples, sample_rate, emit):
    speaker = resolve(devices, request.get("output_id"), "output")
    rate = sample_rate if sample_rate in speaker.rates else format_for("speaker", None, speaker)
    if rate != sample_rate:
        samples = np.asarray(
            voice.resampler(sample_rate, rate).resample(samples, flush=True), np.float32
        )
    samples = samples * 0.25  # Quiet test; user controls the device volume.
    offset = 0
    final_dac = None
    output_gap = False

    def transfer(outdata, frames, timing, status):
        nonlocal offset, final_dac, output_gap
        output_gap |= bool(status)
        outdata.fill(0)
        count = min(frames, max(0, len(samples) - offset))
        outdata[:count] = samples[offset : offset + count, None]
        offset += count
        if offset == len(samples) and final_dac is None:
            final_dac = timing.outputBufferDacTime + count / rate

    stream = sd.OutputStream(
        samplerate=rate,
        blocksize=rate // 100,
        device=speaker.index,
        channels=speaker.channels,
        dtype="float32",
        latency="low",
        extra_settings=sd.WasapiSettings(auto_convert=True),
        callback=transfer,
    )
    deadline = time.monotonic() + len(samples) / rate + 4
    try:
        with stream:
            while time.monotonic() < deadline:
                if output_gap:
                    raise SetupError(
                        "voice_output_gap",
                        "Audio was lost during test-response playback.",
                        "Close busy apps, check the speaker connection, and retry.",
                    )
                if not stream.active:
                    raise SetupError(
                        "speaker_disconnected",
                        "The speaker disconnected.",
                        "Reconnect it, refresh devices, and retry the trial.",
                    )
                emit(
                    {
                        "type": "progress",
                        "phase": "playback",
                        "seconds": offset / rate,
                        "duration": len(samples) / rate,
                        "level": 0,
                    }
                )
                if final_dac is not None and stream.time >= final_dac:
                    return
                time.sleep(0.1)
            raise SetupError(
                "playback_timeout",
                "The test response could not finish playing.",
                "Check the speaker connection and retry.",
            )
    finally:
        stream.close()
