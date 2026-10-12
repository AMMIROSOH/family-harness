"""Explicit event and continuous WAV replay; never opens an audio device."""

from __future__ import annotations

import json
import time
import wave
from collections import Counter
from pathlib import Path

import numpy as np

from family_harness.room import DeterministicResponder, RoomEvent, RoomManager
from family_harness.speech import SPEECH_RATE, SpeechTurn, replay_tail_seconds


class ReplayHarness:
    """Simulated playback progress is distinct from actual speaker evidence."""

    def __init__(self, session_id="replay", room_id="replay-room", responder=None):
        self.manager = RoomManager(session_id, room_id)
        self.responder = responder or DeterministicResponder()
        self.sequence = 0
        self.commands: Counter = Counter()
        self.playback_start: dict[str, float] = {}

    def send(self, kind, at, data=None, source_id="file"):
        self.sequence += 1
        return self.apply(
            RoomEvent(
                f"replay:{self.sequence}", self.manager.session_id, source_id, at, kind, data or {}
            )
        )

    def apply(self, event: RoomEvent):
        commands = self.manager.apply(event)
        for command in commands:
            self.commands[command["kind"]] += 1
            rid = command["response_id"]
            if command["kind"] == "response_requested":
                turn = self.manager.utterances[command["utterance_id"]]
                self.send(
                    "response_ready",
                    event.at,
                    {
                        "response_id": rid,
                        "text": self.responder.reply(turn),
                        "duration": 0.5,
                    },
                    "simulated-output",
                )
            elif command["kind"] == "play_response":
                self.playback_start[rid] = event.at
            elif command["kind"] == "stop_playback":
                self.playback_start.pop(rid, None)
        return commands

    def tick(self, at: float):
        for rid, start in list(self.playback_start.items()):
            response = self.manager.responses[rid]
            elapsed = min(response.duration, max(0, at - start))
            complete = elapsed == response.duration
            self.send(
                "playback_finished" if complete else "playback_progress",
                at,
                {
                    "response_id": rid,
                    "played_seconds": elapsed,
                },
                "simulated-output",
            )
            if complete:
                self.playback_start.pop(rid, None)

    def report(self, *, include_text=False):
        return {
            **self.manager.snapshot(include_text=include_text),
            "commands": dict(self.commands),
            "playback": "simulated; no microphone or speaker opened",
        }


def replay_events(path: Path) -> dict:
    harness = None
    count = 0
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            if len(line) > 100000 or count >= 100000:
                raise ValueError("event replay exceeds its bounds")
            event = RoomEvent(**json.loads(line))
            if harness is None:
                harness = ReplayHarness(event.session_id)
            harness.apply(event)
            count += 1
    if harness is None or harness.manager.status != "closed":
        raise ValueError("event replay must start and close a session explicitly")
    return harness.report()


class RoomSpeechReplay:
    """Multiple utterances on one source timeline with bounded recognizer context."""

    def __init__(self, voice, harness: ReplayHarness):
        self.voice, self.harness = voice, harness
        self.settings = voice.settings
        self.sequence = 0
        self.offset = 0
        self.turn_origin = 0.0
        self.decode_seconds = 0.0
        self.latencies: list[float] = []
        self.completion_latencies: list[float] = []
        self.final_reasons: Counter = Counter()
        self.harness.send("session_started", 0)
        voice.reset_input()
        self._new_turn(0, reset=False)

    def _new_turn(self, at, reset=True):
        if reset:
            self.voice.stt.reset()
        self.sequence += 1
        self.turn_origin = at
        self.turn = SpeechTurn(
            self.voice.vad,
            self.voice.stt,
            self._event,
            completion_silence=self.settings.silence,
            finalizer=getattr(self.voice, "finalizer", None),
        )
        self.turn.utterance_id = f"utterance-{self.sequence}"

    def _event(self, event):
        kind = event["type"]
        if kind == "transcript" and event["start"] is not None:
            data = {k: v for k, v in event.items() if k != "type"}
            data["speaker_track"] = "unknown"
            self.harness.send(kind, event["end"], data)
            if event["final"]:
                self.final_reasons[event["reason"]] += 1
        elif kind == "turn_candidate":
            self.harness.send(
                kind,
                event["at"],
                {
                    "utterance_id": event["utterance_id"],
                    "authority": event["authority"],
                },
            )

    def _record_turn(self):
        if self.turn.partial_latency is not None:
            self.latencies.append(self.turn.partial_latency)
        if self.turn.candidate_latency is not None:
            self.completion_latencies.append(self.turn.candidate_latency)

    def accept(self, samples: np.ndarray):
        before = time.perf_counter()
        for offset in range(0, len(samples), 160):
            chunk = samples[offset : offset + 160]
            at = self.offset / SPEECH_RATE
            self.harness.tick(at)
            done = self.turn.accept(chunk, at)
            self.offset += len(chunk)
            end = self.offset / SPEECH_RATE
            if done:
                self._record_turn()
                self._new_turn(end)
            elif end - self.turn_origin >= 30:
                if self.turn.started is not None:
                    self.turn.finish(end, "segment_limit")
                    self._record_turn()
                self.voice.vad.reset()
                self._new_turn(end)
            elif self.turn.started is None and end - self.turn_origin >= 5:
                self._new_turn(end)
        self.decode_seconds += time.perf_counter() - before

    def finish(self):
        # A short synthetic tail lets VAD release; it is reported separately.
        self.synthetic_tail_seconds = replay_tail_seconds(self.settings.silence)
        self.accept(np.zeros(int(SPEECH_RATE * self.synthetic_tail_seconds), np.float32))
        self.turn.finish(self.offset / SPEECH_RATE, "replay_eof")
        self._record_turn()
        self.harness.tick(self.offset / SPEECH_RATE + 0.5)
        self.harness.send("session_closed", self.offset / SPEECH_RATE + 0.5)


def wav_info(recording):
    rate, frames = recording.getframerate(), recording.getnframes()
    if (
        recording.getnchannels() != 1
        or recording.getsampwidth() != 2
        or recording.getcomptype() != "NONE"
        or not 8000 <= rate <= 48000
        or not 0 < frames <= rate * 3600
    ):
        raise ValueError("choose a PCM16 mono WAV at 8-48 kHz, at most one hour")
    return rate, frames


def replay_wav(path: Path, voice, *, seconds: float | None = None, include_text=False) -> dict:
    if seconds is not None and (not 0 < seconds <= 3600 or seconds < 1 / 8000):
        raise ValueError("replay duration must be positive and at most one hour")
    before = time.perf_counter()
    harness = ReplayHarness()
    speech = RoomSpeechReplay(voice, harness)
    with wave.open(str(path), "rb") as recording:
        rate, frames = wav_info(recording)
        frames = min(frames, int(seconds * rate)) if seconds is not None else frames
        if not frames:
            raise ValueError("replay contains no audio samples")
        converter = voice.resampler(rate) if rate != SPEECH_RATE else None
        read = 0
        while read < frames:
            count = min(rate, frames - read)
            raw = recording.readframes(count)
            if len(raw) != count * 2:
                raise ValueError("truncated WAV")
            samples = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
            if converter:
                samples = converter.resample(samples)
            if voice.input_processor:
                samples = voice.input_processor.process(samples)
            speech.accept(samples)
            read += count
        tail = (
            converter.resample(np.empty(0, np.float32), flush=True)
            if converter
            else np.empty(0, np.float32)
        )
        if voice.input_processor:
            tail = voice.input_processor.process(tail, flush=True)
        speech.accept(tail)
    speech.finish()
    return {
        **harness.report(include_text=include_text),
        "file_audio_seconds": frames / rate,
        "synthetic_tail_seconds": speech.synthetic_tail_seconds,
        "speech_processing_real_time_factor": (time.perf_counter() - before) / (frames / rate),
        "first_partial_audio_ms": distribution(speech.latencies),
        "completion_after_vad_ms": distribution(speech.completion_latencies),
        "final_reasons": dict(speech.final_reasons),
        "input_levels": voice.input_processor.diagnostics() if voice.input_processor else None,
    }


def distribution(values):
    return {
        "count": len(values),
        "p50": round(float(np.percentile(values, 50)), 2) if values else None,
        "p95": round(float(np.percentile(values, 95)), 2) if values else None,
    }
