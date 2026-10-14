"""Killable M1.6 trial worker. No models or devices open on import."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from family_harness.errors import SetupError, audio_error
from family_harness.voice_worker import emit


def execute(request, send=emit):
    from family_harness.asr import StreamingUtteranceRecognizer, load_recognizer
    from family_harness.dashboard import worker_settings
    from family_harness.group import SherpaDiarizer, group_turns
    from family_harness.identity import MatchSettings, PeopleStore, SherpaEmbedding, VoiceMatcher
    from family_harness.interruption_trial import TrialSession, capture_interruption
    from family_harness.models import ModelStore
    from family_harness.speech import LocalVoice
    from family_harness.voice_trial import Measurements

    if request.get("kind") != "interruption_trial":
        raise ValueError("choose the bounded interruption trial")
    if (request.get("echo_confirmed") is not True or request.get("speaker_confirmed") is not True
            or request.get("echo_owner") not in ("software", "device")):
        raise ValueError("confirm comfortable volume and exactly one echo owner before the trial")
    metrics = Measurements()
    try:
        before = time.perf_counter()
        send({"type": "progress", "phase": "loading", "seconds": 0, "duration": 1})
        root = Path(request["models"])
        store = ModelStore(root)
        store.verify()
        voice = LocalVoice(store.profile, worker_settings(request))
        provider = SherpaEmbedding(request["backend"], root)
        policy = request["recognition_policy"]
        matcher = VoiceMatcher(provider, PeopleStore(Path(request["people"])).load(),
                               MatchSettings(**policy["settings"]))
        diarizer = SherpaDiarizer(request["backend"], root)
        backend = request.get("recognizer", "zipformer")
        recognizer = StreamingUtteranceRecognizer(store.profile / "stt") if backend == "zipformer" \
            else load_recognizer(backend, root)
        load_seconds = time.perf_counter() - before
        send({"type": "progress", "phase": "warming", "seconds": 0, "duration": 1})
        warm = voice.warm()
        import sounddevice as sd

        from family_harness.devices import discover_native

        devices, _ = discover_native(sd)
        session = TrialSession()
        samples, offset, result = capture_interruption(request, devices, sd, voice, session, send)
        send({"type": "progress", "phase": "group_decoding", "seconds": 0, "duration": 1})
        # The duplex stream has closed. ASR, clustering and identity cannot delay interruption.
        if result["interrupted"]:
            group = group_turns(samples, diarizer, matcher, recognizer, include_text=True,
                                session=session, time_offset=offset, progress=send)
            result.update(group=group)
        else:
            session.send("session_closed", result["audio_seconds"])
            result["group"] = session.manager.snapshot(include_text=True)
        result.update(
            kind=request["kind"], load_seconds=load_seconds, **warm,
            recognition_policy=policy, recognizer=backend, hardware_gate="pending",
            profile_id=store.catalog["id"],
            model_assets=[{"name": a["name"], "sha256": a["sha256"]}
                          for a in store.catalog["assets"]],
            speaker_backend=provider.backend, speaker_model_hash=provider.model_hash,
            recovery=result["group"].get("recovery") or (
                "Repeat the trial and speak while the fixed voice is playing."
                if not result["interrupted"] else
                "Review the continuation. Unknown names remain uncertain; repeat overlaps alone."
            ),
            limitation="Bounded fixed cue and post-capture group analysis. "
                       "Physical stop, echo and household identity quality require a human trial.",
        )
    finally:
        measurements = metrics.finish()
    result["measurements"] = measurements
    return result  # In-memory only: never automatically write captured speech or text.


def main():
    request = json.loads(sys.stdin.readline())
    try:
        emit({"type": "result", "result": execute(request)})
    except SetupError as exc:
        emit({"type": "error", "error": exc.as_dict()})
        sys.exit(1)
    except Exception as exc:
        emit({"type": "error", "error": audio_error(exc).as_dict()})
        sys.exit(1)


if __name__ == "__main__":
    main()
