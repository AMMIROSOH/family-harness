"""Bounded host audio tests and duplex frames; no recognition or stored audio."""

from __future__ import annotations

import math
import queue
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from family_harness.devices import Device, resolve
from family_harness.errors import SetupError

TEST_SECONDS = {"microphone": 8, "noise": 5, "speaker": 3, "duplex": 12}
BUFFER_FRAMES = 20  # At most 200 ms, never an unbounded recording.


class EchoProcessor(Protocol):
    def process(self, near: np.ndarray, far: np.ndarray, delay_ms: int) -> np.ndarray: ...
    def reset(self) -> None: ...


class WebRtcEcho:
    """One DSP owner, one worker thread. Keep OS/device AEC disabled for this mode."""

    def __init__(self, rate: int):
        try:
            from pywebrtc_audio import AudioProcessor

            self.processor = AudioProcessor(
                sample_rate=rate,
                num_channels=1,
                echo_cancellation=True,
                noise_suppression=False,
                auto_gain_control=False,
            )
        except (ImportError, OSError) as exc:
            raise SetupError(
                "echo_unavailable",
                "The local echo remover could not load.",
                "Rerun Install-Windows.cmd to repair the installation. "
                "Select device echo removal only if your device provides it.",
            ) from exc

    def process(self, near: np.ndarray, far: np.ndarray, delay_ms: int) -> np.ndarray:
        self.processor.stream_delay_ms = max(0, min(500, delay_ms))
        return self.processor.process(near, far)

    def reset(self) -> None:
        self.processor.reset()


@dataclass(frozen=True)
class AudioFrame:
    endpoint_id: str
    sequence: int
    sample_rate: int
    capture_time: float
    playback_time: float
    samples: np.ndarray
    played: np.ndarray  # The exact mono samples written into every output channel.
    discontinuity: bool = False
    clock: str = "portaudio-stream"


class AudioClock:
    def __init__(self):
        self.previous: AudioFrame | None = None
        self.gaps = 0

    def observe(self, frame: AudioFrame) -> bool:
        previous = self.previous
        gap = frame.discontinuity
        if previous:
            duration = len(previous.samples) / previous.sample_rate
            gap |= frame.sequence != previous.sequence + 1
            gap |= abs(frame.capture_time - previous.capture_time - duration) > duration / 2
            gap |= abs(frame.playback_time - previous.playback_time - duration) > duration / 2
        self.previous = frame
        self.gaps += int(gap)
        return gap


def dbfs(energy: float) -> float:
    return round(10 * math.log10(max(energy, 1e-12)), 1)


class Levels:
    def __init__(self):
        self.count = 0
        self.energy = 0.0
        self.clipped = 0
        self.peak = 0.0

    def add(self, samples: np.ndarray) -> None:
        self.count += samples.size
        self.energy += float(np.dot(samples, samples))
        self.clipped += int(np.count_nonzero(np.abs(samples) >= 0.99))
        self.peak = max(self.peak, float(np.max(np.abs(samples))))

    @property
    def mean_energy(self) -> float:
        return self.energy / max(1, self.count)

    def result(self) -> dict:
        return {
            "rms_dbfs": dbfs(self.mean_energy),
            "peak": round(self.peak, 4),
            "clipping_fraction": round(self.clipped / max(1, self.count), 5),
        }


def phase_at(kind: str, seconds: float) -> str:
    if kind != "duplex":
        return kind
    if seconds < 2:
        return "quiet"
    if seconds < 7:
        return "echo_only"
    if seconds < 11:
        return "speak_during_playback"
    return "tail"


def test_sound(rate: int, duration: int, kind: str) -> np.ndarray:
    t = np.arange(rate * duration, dtype=np.float64) / rate
    # Quiet, varied notes with soft attacks. No files, voice models, or downloads.
    signal = (
        np.sin(2 * np.pi * 330 * t)
        + 0.5 * np.sin(2 * np.pi * 523 * t)
        + 0.3 * np.sin(2 * np.pi * 787 * t)
    ) / 1.8
    envelope = np.sin(np.pi * np.minimum((t % 0.7) / 0.08, 1) / 2) ** 2
    envelope *= np.minimum((0.7 - t % 0.7) / 0.08, 1)
    signal *= 0.08 * envelope
    if kind == "duplex":
        signal[(t < 2) | (t >= 11)] = 0
    elif kind != "speaker":
        signal[:] = 0
    return signal.astype(np.float32)


def format_for(kind: str, microphone: Device | None, speaker: Device | None) -> int:
    rates = set(microphone.rates) if microphone else set(speaker.rates)
    if kind == "duplex":
        rates &= set(speaker.rates)
        # WebRTC works on integer 10 ms frames at its native processing rates.
        rates &= {16000, 32000, 48000}
    for rate in (48000, 32000, 16000, 44100):
        if rate in rates:
            return rate
    raise SetupError(
        "incompatible_devices",
        "These devices have no shared duplex audio format.",
        "In Windows Sound settings set both devices to 48 kHz, then refresh. "
        "Alternatively select a wired microphone/speaker or a conference device.",
    )


def summarize(
    kind: str, phases: dict, clock: AudioClock, dropped: int, echo_owner: str, frames: int
) -> dict:
    messages = []
    results = {
        name: {"raw": pair[0].result(), "clean": pair[1].result()} for name, pair in phases.items()
    }
    if frames == 0:
        messages.append("No audio arrived. Reconnect the selected device and check permissions.")
    if clock.gaps or dropped:
        messages.append("Audio gaps occurred. Close busy apps, try a wired device, and retest.")
    if any(pair[0].clipped for pair in phases.values()):
        messages.append("The microphone clipped. Lower its input gain or move farther away.")
    if kind in ("microphone", "noise"):
        raw = phases.get(kind, (Levels(), Levels()))[0]
        if raw.mean_energy < 1e-8:
            messages.append(
                "Almost no input was heard. Check mute, permissions, and device selection."
            )
        elif kind == "noise" and dbfs(raw.mean_energy) > -40:
            messages.append(
                "Background noise is high. Move away from fans/traffic and retest quietly."
            )
        elif kind == "microphone" and dbfs(raw.mean_energy) < -45:
            messages.append(
                "Input is quiet. Move the microphone nearer the intended speaking position."
            )
    echo_reduction = None
    speech_above_residual = None
    if kind == "duplex" and "echo_only" in phases and "quiet" in phases:
        raw, clean = phases["echo_only"]
        baseline = phases["quiet"][0].mean_energy
        if raw.mean_energy > max(1e-8, baseline * 4):
            echo_reduction = round(dbfs(raw.mean_energy) - dbfs(clean.mean_energy), 1)
            if echo_reduction < 6:
                messages.append(
                    "Speaker echo remains. Reduce speaker volume, separate the devices, "
                    "and verify only the chosen echo remover is enabled."
                )
        else:
            messages.append(
                "Speaker echo was too quiet to measure. Confirm you heard the sound; "
                "this test cannot verify echo cancellation for this placement."
            )
        if "speak_during_playback" in phases:
            speech = phases["speak_during_playback"][1].mean_energy
            speech_above_residual = round(dbfs(speech) - dbfs(clean.mean_energy), 1)
            if speech_above_residual < 6:
                messages.append(
                    "Speech during playback was not clearly above residual sound. "
                    "Speak nearer the microphone and repeat the duplex test."
                )
    return {
        "kind": kind,
        "status": "needs_attention" if messages else "measured",
        "messages": messages,
        "phases": results,
        "audio_gaps": clock.gaps,
        "dropped_frames": dropped,
        "frames": frames,
        "echo_owner": echo_owner,
        "echo_reduction_db": echo_reduction,
        "speech_above_residual_db": speech_above_residual,
        "limitation": "These are audio energy measurements, not a room-readiness guarantee. "
        "Human transcription and false-interruption validation require M1.3–M1.6.",
    }


def run_audio(
    request: dict, devices: list[Device], sd, emit: Callable[[dict], None], echo_factory=WebRtcEcho
) -> dict:
    """Called only in an explicitly launched child process. Stop kills that process."""
    kind = request["kind"]
    duration = TEST_SECONDS[kind]
    microphone = resolve(devices, request.get("input_id"), "input") if kind != "speaker" else None
    speaker = (
        resolve(devices, request.get("output_id"), "output")
        if kind in ("speaker", "duplex")
        else None
    )
    rate = format_for(kind, microphone, speaker)
    block = rate // 100
    sound = test_sound(rate, duration, kind)
    processor = (
        echo_factory(rate) if kind == "duplex" and request["echo_owner"] == "software" else None
    )
    buffer = queue.Queue(maxsize=BUFFER_FRAMES)
    sequence = 0
    dropped = 0
    sample_offset = 0

    def transfer(indata, outdata, frames, timing, status):
        nonlocal sequence, dropped, sample_offset
        played = np.zeros(frames, dtype=np.float32)
        if outdata is not None:
            available = min(frames, max(0, len(sound) - sample_offset))
            played[:available] = sound[sample_offset : sample_offset + available]
            outdata[:] = played[:, None]
            # Read back exactly what was submitted, including end padding and volume envelope.
            played = outdata[:, 0].copy()
        near = indata[:, 0].copy() if indata is not None else np.zeros(frames, np.float32)
        capture_time = (
            timing.inputBufferAdcTime if indata is not None else timing.outputBufferDacTime
        )
        playback_time = timing.outputBufferDacTime if outdata is not None else capture_time
        frame = AudioFrame(
            request["endpoint_id"],
            sequence,
            rate,
            capture_time,
            playback_time,
            near,
            played,
            bool(status),
        )
        try:
            buffer.put_nowait(frame)
        except queue.Full:
            dropped += 1
        sequence += 1
        sample_offset += frames

    options = dict(samplerate=rate, blocksize=block, dtype="float32", latency="low")
    settings = sd.WasapiSettings(auto_convert=True)
    if kind == "speaker":
        stream = sd.OutputStream(
            device=speaker.index,
            channels=speaker.channels,
            extra_settings=settings,
            callback=lambda out, n, t, s: transfer(None, out, n, t, s),
            **options,
        )
    elif kind == "duplex":
        stream = sd.Stream(
            device=(microphone.index, speaker.index),
            channels=(1, speaker.channels),
            extra_settings=(settings, settings),
            callback=transfer,
            **options,
        )
    else:
        stream = sd.InputStream(
            device=microphone.index,
            channels=1,
            extra_settings=settings,
            callback=lambda inp, n, t, s: transfer(inp, None, n, t, s),
            **options,
        )
    phases = {}
    clock = AudioClock()
    last_progress = 0.0
    frame_count = 0
    deadline = time.monotonic() + duration + 4
    try:
        with stream:
            while time.monotonic() < deadline:
                try:
                    frame = buffer.get(timeout=0.5)
                except queue.Empty as exc:
                    raise SetupError(
                        "audio_stalled",
                        "The selected audio device stopped sending audio.",
                        "Reconnect the device, refresh, and explicitly start a new test.",
                    ) from exc
                if not stream.active:
                    raise SetupError(
                        "device_disconnected",
                        "The audio device disconnected during the test.",
                        "Reconnect it, refresh devices, and start the test again.",
                    )
                gap = clock.observe(frame)
                if processor and gap:
                    processor.reset()
                delay = round((frame.playback_time - frame.capture_time) * 1000)
                clean = (
                    processor.process(frame.samples, frame.played, delay)
                    if processor
                    else frame.samples
                )
                seconds = frame.sequence / 100
                phase = phase_at(kind, seconds)
                raw_levels, clean_levels = phases.setdefault(phase, (Levels(), Levels()))
                raw_levels.add(frame.samples)
                clean_levels.add(clean)
                frame_count += 1
                now = time.monotonic()
                if now - last_progress >= 0.1:
                    rms = float(np.sqrt(np.mean(frame.samples**2)))
                    emit(
                        {
                            "type": "progress",
                            "phase": phase,
                            "seconds": round(seconds, 1),
                            "duration": duration,
                            "level_dbfs": dbfs(rms * rms),
                            "level": min(1.0, rms * 10),
                            "audio_gaps": clock.gaps,
                            "dropped_frames": dropped,
                            "sample_rate": rate,
                        }
                    )
                    last_progress = now
                if frame.sequence >= duration * 100 - 1:
                    break
            else:
                raise SetupError(
                    "audio_timeout",
                    "The test could not finish on time.",
                    "Close busy apps, refresh the selected devices, and retry.",
                )
    finally:
        stream.close()
    result = summarize(kind, phases, clock, dropped, request["echo_owner"], frame_count)
    result["sample_rate"] = rate
    return result
