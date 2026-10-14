"""Explicit live/replay/fixture jobs; no model or device activity on import."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from family_harness.errors import SetupError, audio_error
from family_harness.voice_worker import emit


def fixture(send):
    from family_harness.room import RoomEvent, RoomManager

    manager = RoomManager("fixture", "manager-fixture")
    events = [
        RoomEvent("open", "fixture", "fixture", 0, "session_started"),
        RoomEvent("draft", "fixture", "fixture", 1, "transcript", {
            "utterance_id": "turn", "revision": 1, "text": "Fixture draft", "final": False,
            "start": 0.1, "end": 1,
        }),
        RoomEvent("final", "fixture", "fixture", 2, "transcript", {
            "utterance_id": "turn", "revision": 2, "text": "Fixture final", "final": True,
            "start": 0.1, "end": 2,
        }),
        RoomEvent("draft", "fixture", "fixture", 1, "transcript", {
            "utterance_id": "turn", "revision": 1, "text": "Fixture draft", "final": False,
            "start": 0.1, "end": 1,
        }),
        RoomEvent("close", "fixture", "fixture", 3, "session_closed"),
        RoomEvent("late", "fixture", "fixture", 4, "test_cue"),
    ]
    for event in events:
        commands = manager.apply(event)
        send({"type": "room_event", **asdict(event), "commands": commands,
              "processing_time": time.monotonic()})
        send({"type": "room_snapshot", "room": manager.snapshot(include_text=True)})
    return {"kind": "lab_fixture", "mode": "device-free fixture", "hardware_gate": "pending",
            "counts": dict(manager.counts), "room": manager.snapshot(include_text=True)}


def execute(request, send=emit):
    if request["kind"] == "lab_fixture":
        return fixture(send)
    from family_harness.asr import StreamingUtteranceRecognizer, load_recognizer
    from family_harness.dashboard import worker_settings
    from family_harness.group import SherpaDiarizer, group_turns
    from family_harness.identity import MatchSettings, PeopleStore, SherpaEmbedding, VoiceMatcher
    from family_harness.models import ModelStore
    from family_harness.voice_trial import Measurements

    root = Path(request["models"])
    input_hash = None
    if request.get("source"):
        import hashlib

        source = Path(request["source"])
        if not source.is_file() or source.stat().st_size > 346_624_000:
            raise SetupError("replay_invalid", "Choose a bounded local mono WAV.",
                             "Speech replay accepts at most one hour; group replay at most 300 s.")
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for block in iter(lambda: stream.read(1048576), b""):
                digest.update(block)
        input_hash = digest.hexdigest()
    metrics = Measurements()
    try:
        send({"type": "progress", "phase": "loading", "seconds": 0, "duration": 1})
        before = time.perf_counter()
        store = ModelStore(root)
        store.verify()
        selected = request["recognizer"]
        finalizer = load_recognizer(selected, root) if selected != "zipformer" else None
        if request["kind"] == "lab_replay":
            from family_harness.room_replay import replay_wav
            from family_harness.speech import LocalVoice

            voice = LocalVoice(store.profile, worker_settings(request), finalizer=finalizer)
            result = replay_wav(Path(request["source"]), voice,
                                seconds=request.get("effective_settings", {}).get("seconds", 60),
                                include_text=True)
            send({"type": "room_snapshot", "room": result})
            result.update(kind="lab_replay", source_sha256=input_hash, hardware_gate="pending")
            return result
        provider = matcher = diarizer = None
        scenario = request.get("scenario", "integrated")
        if scenario != "speech":
            provider = SherpaEmbedding(request["backend"], root)
            diarizer = SherpaDiarizer(request["backend"], root)
            matcher = VoiceMatcher(provider, PeopleStore(Path(request["people"])).load(),
                                   MatchSettings(**request["recognition_policy"]["settings"]))
        if request["kind"] == "group_replay":
            from family_harness.identity import read_voice_wav

            recognizer = finalizer or StreamingUtteranceRecognizer(store.profile / "stt")
            result = group_turns(read_voice_wav(Path(request["source"]), maximum=300),
                                 diarizer, matcher, recognizer,
                                 participation=request["participation"], include_text=True,
                                 progress=send)
            send({"type": "room_snapshot", "room": result})
            result.update(kind="group_replay", source_sha256=input_hash)
            return result
        from family_harness.audio import format_for
        from family_harness.devices import discover_native, resolve
        from family_harness.interruptions import InterruptionSettings, OnsetDetector
        from family_harness.live import (
            REPLY,
            IncrementalAttributor,
            LivePipeline,
            LiveSession,
            capture_live,
        )
        from family_harness.speech import LocalVoice, StreamingResampler

        voice = LocalVoice(store.profile, worker_settings(request))
        load_seconds = time.perf_counter()-before
        send({"type": "progress", "phase": "warming", "seconds": 0, "duration": 1})
        warm = voice.warm()
        parts, alignment, tts_rate = [], [], None
        for text in REPLY:
            samples, rate = voice.tts.synthesize(text)
            if tts_rate is not None and tts_rate != rate:
                raise ValueError("inconsistent test voice sample rates")
            tts_rate = rate
            parts.append(np.asarray(samples, np.float32))
            alignment.append({"end": sum(len(p) for p in parts)/rate, "text": text})
        if not 0 < alignment[-1]["end"] <= 15:
            raise ValueError("test voice must be bounded to fifteen seconds")
        import sounddevice as sd

        devices, _ = discover_native(sd)
        microphone = resolve(devices, request["input_id"], "input")
        speaker = resolve(devices, request["output_id"], "output")
        rate = format_for("duplex", microphone, speaker)
        audio = np.concatenate(parts)*0.25
        if rate != tts_rate:
            audio = np.asarray(StreamingResampler(tts_rate, rate).resample(audio, flush=True))
            factor = len(audio)/(alignment[-1]["end"]*rate)
            alignment = [{**c, "end": c["end"]*factor} for c in alignment]
        session = LiveSession(send, audio, rate, alignment, request["participation"],
                              replies=scenario in ("integrated", "interruptions"),
                              room_id=request.get("room_id", "unsaved-room"))
        attributor = IncrementalAttributor(diarizer, matcher) if matcher else None
        pipeline = LivePipeline(session, voice.stt, finalizer, attributor, voice.settings)
        detector = OnsetDetector(voice.vad, InterruptionSettings(
            **request.get("interruption_settings", {}),
        ))
        result = capture_live(request, devices, sd, voice, session, pipeline, detector, send)
        metrics.decode_ms = pipeline.frame_times
        result.update(kind="lab_live", load_seconds=load_seconds, **warm,
                      room=session.manager.snapshot(include_text=True),
                      commands=session.command_counts, identity_analysis_ms=pipeline.analysis_times,
                      stop_to_first_zero_dac_ms=session.stop_delays,
                      first_partial_latency_ms=pipeline.partial_ms,
                      completion_latency_ms=pipeline.completion_ms,
                      stream_queue_ms=pipeline.stream_queue_ms,
                      recognition_policy=request["recognition_policy"],
                      speech_settings=asdict(voice.settings), hardware_gate="pending",
                      speaker_model_hash=provider.model_hash if provider else None,
                      model_assets=[{"name": a["name"], "sha256": a["sha256"]}
                                    for a in store.catalog["assets"]],
                      limitation="Bounded diagnostic session; windowed attribution is provisional. "
                      "Physical stop, echo, identity and household quality need local validation.")
    finally:
        measured = metrics.finish()
        if "result" in locals():
            result["measurements"] = measured
    result["measurements"] = measured
    return result


def main():
    try:
        emit({"type": "result", "result": execute(json.loads(sys.stdin.readline()))})
    except SetupError as exc:
        emit({"type": "error", "error": exc.as_dict()})
        sys.exit(1)
    except Exception as exc:
        emit({"type": "error", "error": audio_error(exc).as_dict()})
        sys.exit(1)


if __name__ == "__main__":
    main()
