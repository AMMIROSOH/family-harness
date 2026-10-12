"""Explicit bounded native duplex trial; heavy group analysis runs with audio off."""

from __future__ import annotations

import queue
import threading
import time
from collections import Counter
from dataclasses import asdict
from uuid import uuid4

import numpy as np

from family_harness.audio import BUFFER_FRAMES, AudioClock, AudioFrame, WebRtcEcho, dbfs, format_for
from family_harness.devices import resolve
from family_harness.errors import SetupError
from family_harness.interruptions import CancellableOutput, GenerationToken, OnsetDetector
from family_harness.room import RoomEvent, RoomManager
from family_harness.speech import SPEECH_RATE, StreamingResampler, speech_input

TRIAL_SECONDS = 20
CONTINUATION_SECONDS = 8
REPLY_CHUNKS = (
    "This is the local interruption trial.",
    "Please interrupt my voice by speaking a sentence.",
    "Then let another person continue, one person at a time.",
)


def trial_reply(tts):
    parts, alignment, rate = [], [], None
    for text in REPLY_CHUNKS:
        samples, current_rate = tts.synthesize(text)
        samples = np.asarray(samples, np.float32)
        if (rate is not None and current_rate != rate) or not len(samples):
            raise ValueError("the trial voice must produce consistent audio chunks")
        rate = current_rate
        parts.append(samples)
        alignment.append({"end": sum(len(p) for p in parts) / rate, "text": text})
    if alignment[-1]["end"] > 15:
        raise ValueError("the trial response exceeds fifteen seconds")
    return np.concatenate(parts) * 0.25, rate, alignment


class TrialSession:
    """Common reducer and cancellation boundary for native and dataset trials."""

    def __init__(self):
        self.manager = RoomManager(str(uuid4()), "interruption-trial")
        self.sequence = 0
        self.commands = Counter()
        self.output = None
        self.send("session_started", 0)
        requested = self.send("transcript", 0, {
            "utterance_id": "trial-control", "revision": 1, "text": "Begin the guided trial",
            "final": True, "start": 0, "end": 0,
        }, source="control")
        self.response_id = requested[-1]["response_id"]
        self.generation = GenerationToken(self.response_id)

    def send(self, kind, at, data=None, *, source="native"):
        self.sequence += 1
        commands = self.manager.apply(RoomEvent(
            f"trial-{self.sequence}", self.manager.session_id, source, at, kind, data or {},
        ))
        for command in commands:
            self.commands[command["kind"]] += 1
            if command["kind"] == "cancel_generation" and hasattr(self, "generation"):
                self.generation.cancel(command["response_id"])
            if command["kind"] == "stop_playback" and self.output:
                self.output.stop(command["response_id"])
        return commands

    def ready(self, samples, rate, alignment):
        self.output = CancellableOutput(self.response_id, samples, rate)
        self.send("response_ready", 0, {
            "response_id": self.response_id, "text": " ".join(REPLY_CHUNKS),
            "duration": self.output.duration, "alignment": alignment,
        }, source="output")


def capture_interruption(request, devices, sd, voice, session, send, echo_factory=WebRtcEcho):
    microphone = resolve(devices, request.get("input_id"), "input")
    speaker = resolve(devices, request.get("output_id"), "output")
    rate = format_for("duplex", microphone, speaker)
    samples, tts_rate, alignment = trial_reply(voice.tts)
    if rate != tts_rate:
        samples = np.asarray(StreamingResampler(tts_rate, rate).resample(samples, flush=True))
        # Preserve exact chunk boundaries on the resampled DAC timeline.
        factor = len(samples) / (alignment[-1]["end"] * rate)
        alignment = [{**c, "end": c["end"] * factor} for c in alignment]
    session.ready(samples, rate, alignment)
    output = session.output
    echo = echo_factory(rate) if request["echo_owner"] == "software" else None
    converter = StreamingResampler(rate, SPEECH_RATE) if rate != SPEECH_RATE else None
    detector = OnsetDetector(voice.vad, processor=speech_input(voice.settings))
    buffer = queue.Queue(maxsize=BUFFER_FRAMES)
    sequence, dropped = 0, 0
    capture_limit = threading.Event()
    origin = None
    clock = AudioClock()
    chunks = []
    processed = 0
    interruption = None
    finish_at = TRIAL_SECONDS
    max_queue_ms, stop_request_clock, silence_clock = 0.0, None, None
    last_progress = 0.0

    def transfer(indata, outdata, frames, timing, status):
        nonlocal sequence, dropped
        played = output.write(outdata, frames, timing.outputBufferDacTime)
        frame = AudioFrame(request["endpoint_id"], sequence, rate, timing.inputBufferAdcTime,
                           timing.outputBufferDacTime, indata[:, 0].copy(), played, bool(status))
        try:
            buffer.put_nowait((frame, time.perf_counter()))
        except queue.Full:
            # Callback can stop output even when inference cannot keep up.
            dropped += 1
            output.stop(session.response_id)
        sequence += 1
        if sequence >= TRIAL_SECONDS * 100:
            capture_limit.set()
            output.stop(session.response_id)
        if (dropped or capture_limit.is_set()) and hasattr(sd, "CallbackAbort"):
            # PortAudio stops capture/output even if the processing worker stalls.
            raise sd.CallbackAbort

    settings = sd.WasapiSettings(auto_convert=True)
    stream = sd.Stream(samplerate=rate, blocksize=rate // 100,
                       device=(microphone.index, speaker.index), channels=(1, speaker.channels),
                       dtype="float32", latency="low", extra_settings=(settings, settings),
                       callback=transfer)
    deadline = time.monotonic() + TRIAL_SECONDS + 4
    try:
        with stream:
            while time.monotonic() < deadline:
                try:
                    frame, arrived = buffer.get(timeout=0.5)
                except queue.Empty as exc:
                    raise trial_gap("The selected device stopped sending audio.") from exc
                origin = frame.capture_time if origin is None else origin
                at = frame.capture_time - origin
                if (not stream.active and not capture_limit.is_set()) or clock.observe(frame) \
                        or dropped:
                    session.send("audio_gap", max(0, at))
                    raise trial_gap("Audio was lost; the interrupted take was discarded.")
                max_queue_ms = max(max_queue_ms, (time.perf_counter() - arrived) * 1000)
                clean = echo.process(frame.samples, frame.played,
                                     round((frame.playback_time - frame.capture_time) * 1000)) \
                    if echo else frame.samples
                clean = np.asarray(converter.resample(clean), np.float32) if converter else clean
                onset = detector.accept(clean, processed / SPEECH_RATE)
                chunks.append(clean)
                processed += len(clean)
                now = getattr(stream, "time", frame.capture_time)
                played = output.confirmed_seconds(now)
                response = session.manager.responses[session.response_id]
                if response.status == "playing":
                    session.send("playback_progress", processed / SPEECH_RATE, {
                        "response_id": session.response_id, "played_seconds": played,
                    }, source="output")
                if onset and interruption is None:
                    interruption = onset
                    stop_request_clock = now
                    session.send("speech_started", onset["detected_at"], {"start": onset["start"]})
                    finish_at = min(TRIAL_SECONDS, onset["detected_at"] + CONTINUATION_SECONDS)
                if output.zeroed_dac is not None and silence_clock is None:
                    silence_clock = output.zeroed_dac
                if interruption is None and played >= output.duration:
                    session.send("playback_finished", processed / SPEECH_RATE, {
                        "response_id": session.response_id, "played_seconds": output.duration,
                    }, source="output")
                    break
                seconds = processed / SPEECH_RATE
                if time.monotonic() - last_progress >= 0.1:
                    send({"type": "progress", "phase": "interruption_continuation"
                          if interruption else "interruption_playback" if at >= 2 else "quiet",
                          "seconds": seconds, "duration": finish_at,
                          "level_dbfs": dbfs(float(np.mean(frame.samples**2)))})
                    last_progress = time.monotonic()
                if seconds >= finish_at:
                    break
            else:
                raise trial_gap("The bounded interruption trial timed out.")
    finally:
        output.stop(session.response_id)
        stream.abort() if hasattr(stream, "abort") else None
        stream.close()
    if interruption:
        session.send("playback_stopped", processed / SPEECH_RATE, {
            "response_id": session.response_id,
            "played_seconds": output.confirmed_seconds(silence_clock or stop_request_clock),
        }, source="output")
    begin = max(0, interruption["start"] - 0.8) if interruption else 0
    return np.concatenate(chunks)[int(begin * SPEECH_RATE):], begin, {
        "interrupted": interruption is not None, "onset": interruption,
        "audio_seconds": processed / SPEECH_RATE, "capture_sample_rate": rate,
        "max_capture_queue_ms": max_queue_ms, "audio_gaps": 0,
        "stop_to_first_zero_dac_ms": max(0, (silence_clock - stop_request_clock) * 1000)
        if silence_clock is not None and stop_request_clock is not None else None,
        "detector_settings": asdict(detector.settings),
        "speech_settings": asdict(voice.settings), "echo_owner": request["echo_owner"],
        "devices": {"input": microphone.public(), "output": speaker.public()},
        "playback_evidence": "PortAudio DAC clock; electrical/acoustic stop requires measurement",
    }


def trial_gap(message):
    return SetupError("interruption_audio_gap", message,
                      "Close busy apps, reconnect devices, refresh, and explicitly retry. "
                      "Output stops and incomplete speech is discarded.")
