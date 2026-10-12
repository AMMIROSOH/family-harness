"""Explicit model jobs and voice trials in a killable process."""

from __future__ import annotations

import json
import sys
import time
import wave
from pathlib import Path

from family_harness.errors import SetupError, audio_error
from family_harness.models import ModelStore


def emit(event: dict) -> None:
    print(json.dumps(event, ensure_ascii=True, allow_nan=False), flush=True)


def public_report(result: dict) -> dict:
    """Persist only diagnostics; spoken text, source file paths, and utterance IDs stay in RAM."""
    return {
        key: value for key, value in result.items() if key not in ("transcript", "utterance_id")
    }


def execute(request: dict, send=emit) -> dict:
    store = ModelStore(Path(request["models"]))
    kind = request["kind"]
    if kind in ("recognizer_install", "recognizer_remove"):
        from family_harness.asr import recognizer_store

        selected = recognizer_store(request["recognizer"], store.root)
        try:
            if kind == "recognizer_remove":
                selected.remove()
                return {"kind": kind, "status": "removed"}
            source = Path(request["source"]) if request.get("source") else None
            result = selected.install(source, lambda event: send({"type": "progress", **event}))
            return {"kind": kind, **result}
        except SetupError as exc:
            raise SetupError(
                "recognizer_invalid", f"The {request['recognizer']} model operation failed.",
                "Check disk space, permissions and the pinned import files. "
                f"Retry voice install-recognizer {request['recognizer']} in the same --models "
                "directory. The baseline English profile is unchanged; audio is off.",
            ) from exc
    if kind in ("voice_install", "voice_import"):
        source = Path(request["source"]) if kind == "voice_import" else None
        result = store.install(source, lambda event: send({"type": "progress", **event}))
        return {"kind": kind, **result}
    if kind == "voice_remove":
        store.remove()
        return {"kind": kind, "status": "removed"}
    from family_harness.speech import VOICE_PRESETS, LocalVoice
    from family_harness.voice_trial import Measurements, capture, playback, replay, synthesize

    measurements = Measurements()
    try:
        send({"type": "progress", "phase": "loading", "seconds": 0, "duration": 1})
        before = time.perf_counter()
        store.verify()
        if "preset" in request:
            voice = LocalVoice(store.profile, VOICE_PRESETS[request["preset"]])
        else:
            voice = LocalVoice(store.profile)
        backend = request.get("recognizer", "zipformer")
        if backend != "zipformer":
            from family_harness.asr import load_recognizer, recognizer_catalog

            voice.finalizer = load_recognizer(backend, store.root)
            result_catalog = recognizer_catalog(backend)
        else:
            result_catalog = None
        result = {"kind": kind, "load_seconds": round(time.perf_counter() - before, 3)}
        result.update(recognizer=backend, recognizer_catalog=result_catalog)
        send({"type": "progress", "phase": "warming", "seconds": 0, "duration": 1})
        result.update(voice.warm())
        if "preset" in request:
            from dataclasses import asdict

            result["speech_settings"] = asdict(voice.settings)
        if kind == "voice_trial":
            import sounddevice as sd

            from family_harness.devices import discover_native

            devices, _ = discover_native(sd)
            # Revalidate both endpoints before opening either one.
            from family_harness.devices import resolve

            microphone = resolve(devices, request.get("input_id"), "input")
            speaker = resolve(devices, request.get("output_id"), "output")
            result["devices"] = {"input": microphone.public(), "output": speaker.public()}
            result.update(capture(request, devices, sd, voice, send, measurements))
            if result["candidate"] and result["transcript"]:
                send({"type": "progress", "phase": "synthesizing", "seconds": 0, "duration": 1})
                samples, rate = synthesize(voice, result)
                playback(request, devices, sd, voice, samples, rate, send)
                result["playback_completed"] = True
            else:
                result["playback_completed"] = False
        elif kind == "voice_replay":
            result.update(replay(Path(request["source"]), voice, send, measurements))
            samples, rate = synthesize(voice, result)
            if request.get("output"):
                import numpy as np

                with wave.open(str(request["output"]), "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(rate)
                    output.writeframes((samples * 32767).astype(np.dtype("<i2")).tobytes())
            result["playback_completed"] = False
        result.update(
            {
                "profile_id": store.catalog["id"],
                "models": store.catalog["components"],
                "model_assets": [
                    {"name": a["name"], "sha256": a["sha256"]} for a in store.catalog["assets"]
                ],
                "status": "measured",
                "hardware_gate": "pending",
                "limitation": "A silence candidate can end speech early. Review the transcript. "
                "This test does not validate group conversations or interruptions.",
            }
        )
    finally:
        metrics = measurements.finish()
    result["measurements"] = metrics
    if result.get("audio_seconds"):
        result["speech_processing_real_time_factor"] = round(
            sum(measurements.decode_ms) / (result["audio_seconds"] * 1000), 3
        )
    report = Path(request["report"]) if request.get("report") else store.root / "benchmark.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    temporary = report.with_suffix(".tmp")
    temporary.write_text(json.dumps(public_report(result), indent=2), "utf-8")
    temporary.replace(report)
    return result


def main() -> None:
    request = json.loads(sys.stdin.readline())
    try:
        result = execute(request)
        emit({"type": "result", "result": result})
    except SetupError as exc:
        emit({"type": "error", "error": exc.as_dict()})
        sys.exit(1)
    except Exception as exc:
        if request.get("kind") in (
            "voice_install", "voice_import", "voice_remove",
            "recognizer_install", "recognizer_remove",
        ):
            error = SetupError(
                "model_install_failed",
                "The model operation could not finish.",
                "Check internet access, free disk space, and the local folder permissions. "
                "Retry the installation or import the original model files. Audio is off.",
            )
        else:
            error = audio_error(exc)
        emit({"type": "error", "error": error.as_dict()})
        sys.exit(1)


if __name__ == "__main__":
    main()
