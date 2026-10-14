"""Killable, explicit speaker model jobs and bounded microphone previews."""

from __future__ import annotations

import json
import queue
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from family_harness.audio import BUFFER_FRAMES, AudioClock, AudioFrame, dbfs, format_for
from family_harness.devices import resolve
from family_harness.errors import SetupError, audio_error
from family_harness.identity import (
    MatchSettings,
    PeopleStore,
    SherpaEmbedding,
    VoiceMatcher,
    enrollment,
    segmentation_store,
    speaker_store,
)
from family_harness.speech import SPEECH_RATE, StreamingResampler
from family_harness.voice_trial import Measurements
from family_harness.voice_worker import emit


def capture_samples(request, devices, sd, send, *, duration):
    microphone = resolve(devices, request.get("input_id"), "input")
    rate = 16000 if 16000 in microphone.rates else format_for("microphone", microphone, None)
    converter = StreamingResampler(rate, SPEECH_RATE) if rate != SPEECH_RATE else None
    buffer = queue.Queue(maxsize=BUFFER_FRAMES)
    sequence, dropped = 0, 0

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
            buffer.put_nowait(frame)
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
    chunks, processed = [], 0
    clock = AudioClock()
    last_progress = 0.0
    deadline = time.monotonic() + duration + 4
    try:
        with stream:
            while processed < duration * SPEECH_RATE and time.monotonic() < deadline:
                try:
                    frame = buffer.get(timeout=0.5)
                except queue.Empty as exc:
                    raise SetupError(
                        "audio_stalled",
                        "Microphone audio stopped.",
                        "Reconnect, refresh devices, and explicitly retry.",
                    ) from exc
                if not stream.active or clock.observe(frame) or dropped:
                    raise SetupError(
                        "people_audio_gap",
                        "Audio was lost; this take was discarded.",
                        "Close busy apps, reconnect the microphone, and retry.",
                    )
                samples = converter.resample(frame.samples) if converter else frame.samples
                remaining = int(duration * SPEECH_RATE - processed)
                samples = samples[:remaining]
                chunks.append(samples)
                processed += len(samples)
                if time.monotonic() - last_progress >= 0.1:
                    send(
                        {
                            "type": "progress",
                            "phase": "enrollment_listening"
                            if request["kind"] == "people_enroll"
                            else "group_listening",
                            "seconds": processed / SPEECH_RATE,
                            "duration": duration,
                            "phrase": min(3, int(processed / SPEECH_RATE / 6) + 1),
                            "level_dbfs": dbfs(float(np.mean(frame.samples**2))),
                        }
                    )
                    last_progress = time.monotonic()
            if processed < duration * SPEECH_RATE:
                raise SetupError(
                    "audio_timeout",
                    "The bounded microphone test timed out.",
                    "Close busy apps and retry; incomplete audio was discarded.",
                )
    finally:
        stream.close()
    return np.concatenate(chunks), microphone.public()


def enrollment_takes(samples, diarizer):
    segments = diarizer.segments(samples)
    if any(
        a.track != b.track and a.start < b.end and b.start < a.end
        for i, a in enumerate(segments)
        for b in segments[i + 1 :]
    ):
        raise ValueError("overlapping voices detected; enroll one person at a time")
    takes = []
    for take in range(3):
        pieces = []
        for segment in segments:
            start, end = max(segment.start, take * 6), min(segment.end, (take + 1) * 6)
            if end > start:
                pieces.append(samples[int(start * SPEECH_RATE) : int(end * SPEECH_RATE)])
        if not pieces or sum(len(p) for p in pieces) < 4 * SPEECH_RATE:
            raise ValueError(
                "speak for at least four seconds in each of the three six-second windows"
            )
        takes.append(np.concatenate(pieces))
    return takes


def execute(request, send=emit):
    from family_harness.group import SherpaDiarizer, group_turns

    kind, backend = request["kind"], request["backend"]
    root = Path(request["models"])
    if kind in ("speaker_install", "segmentation_install", "speaker_remove"):
        store = (
            segmentation_store(root)
            if kind == "segmentation_install"
            else speaker_store(backend, root)
        )
        if kind == "speaker_remove":
            store.remove()
            return {"status": "removed", "kind": kind}
        result = store.install(
            Path(request["source"]) if request.get("source") else None,
            lambda e: send({"type": "progress", **e}),
        )
        return {"kind": kind, "status": result["status"]}
    if kind not in ("people_enroll", "people_trial"):
        raise ValueError("unsupported people operation")
    metrics = Measurements()
    try:
        send({"type": "progress", "phase": "loading", "seconds": 0, "duration": 1})
        provider = SherpaEmbedding(backend, root)
        diarizer = SherpaDiarizer(backend, root)
        recognizer, matcher = None, None
        if kind == "people_trial":
            policy = request["recognition_policy"]
            matcher = VoiceMatcher(provider, PeopleStore(Path(request["people"])).load(),
                                   MatchSettings(**policy["settings"]))
            from family_harness.asr import StreamingUtteranceRecognizer, load_recognizer
            from family_harness.models import ModelStore

            selected = request.get("recognizer", "zipformer")
            if selected == "zipformer":
                speech = ModelStore(root)
                speech.verify()
                recognizer = StreamingUtteranceRecognizer(speech.profile / "stt")
            else:
                recognizer = load_recognizer(selected, root)
        import sounddevice as sd

        from family_harness.devices import discover_native

        devices, _ = discover_native(sd)
        samples, device = capture_samples(
            request,
            devices,
            sd,
            send,
            duration=18 if kind == "people_enroll" else 30,
        )
        send(
            {
                "type": "progress",
                "phase": "enrollment_analyzing" if kind == "people_enroll" else "group_decoding",
                "seconds": 0,
                "duration": 1,
            }
        )
        if kind == "people_enroll":
            profile, quality = enrollment(
                provider, enrollment_takes(samples, diarizer), request["name"]
            )
            # Parent holds this in volatile RAM until the user explicitly saves it.
            result = {
                "kind": kind,
                "candidate": asdict(profile),
                "quality": quality,
                "saved": False,
                "audio_seconds": 18,
            }
        else:
            result = {
                "kind": kind,
                "recognition_policy": policy,
                **group_turns(
                    samples,
                    diarizer,
                    matcher,
                    recognizer,
                    participation=request["participation"],
                    include_text=True,
                    progress=send,
                ),
            }
        result.update(
            input_device=device,
            backend=backend,
            model_sha256=provider.model_hash,
            hardware_gate="pending",
        )
    finally:
        measured = metrics.finish()
    result["measurements"] = measured
    return result


def main():
    try:
        result = execute(json.loads(sys.stdin.readline()))
        emit({"type": "result", "result": result})
    except SetupError as exc:
        emit({"type": "error", "error": exc.as_dict()})
        sys.exit(1)
    except ValueError as exc:
        emit(
            {
                "type": "error",
                "error": SetupError(
                    "people_trial_invalid",
                    str(exc),
                    "Retry in a quiet room, with one person at a time. Check the local models.",
                ).as_dict(),
            }
        )
        sys.exit(1)
    except Exception as exc:
        emit({"type": "error", "error": audio_error(exc).as_dict()})
        sys.exit(1)


if __name__ == "__main__":
    main()
