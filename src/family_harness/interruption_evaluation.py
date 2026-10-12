"""Reference-free DiPCo onset replay; annotations enter only the numeric scorer."""

from __future__ import annotations

import json
import math
import time
import wave
from dataclasses import asdict

import numpy as np

from family_harness.dipco import block_network, inventory, timestamp
from family_harness.interruptions import InterruptionSettings, OnsetDetector
from family_harness.models import ModelStore, digest
from family_harness.room_replay import distribution
from family_harness.speech import (
    SPEECH_RATE,
    SherpaVad,
    StreamingResampler,
    VoiceSettings,
    speech_input,
)
from family_harness.voice_trial import Measurements


def reference_activity(item, duration, *, merge_seconds=0.3):
    """All annotations, including nonlexical/unintelligible/long speech and overlap.

    Close-talk activity also includes other voices audible in the recording. No
    reference, speaker label or participant count reaches the detector.
    """
    rows = json.loads(item["annotations_path"].read_text("utf-8"))
    spans = []
    for row in rows:
        start = timestamp(row["start_time"][item["microphone"]])
        end = min(duration, timestamp(row["end_time"][item["microphone"]]))
        if 0 <= start < end:
            spans.append((start, end))
    spans.sort()
    runs = []
    for start, end in spans:
        if runs and start - runs[-1][1] <= merge_seconds:
            runs[-1] = (runs[-1][0], max(end, runs[-1][1]))
        else:
            runs.append((start, end))
    return spans, runs


def score_activity(onsets, activity, spans, runs):
    """One-to-one onset matching; coarse annotation timing is not word timing."""
    matched = set()
    latencies = []
    false_onsets = 0
    for onset in onsets:
        detected = onset["detected_at"]
        candidates = [i for i, (start, _) in enumerate(runs)
                      if i not in matched and -0.15 <= detected - start <= 1.0]
        if candidates:
            index = min(candidates, key=lambda i: abs(detected - runs[i][0]))
            matched.add(index)
            latencies.append((detected - runs[index][0]) * 1000)
        else:
            false_onsets += 1
    times = np.arange(len(activity)) * 0.01
    truth = np.zeros(len(times), bool)
    for start, end in spans:
        truth |= (times + 0.01 > start) & (times < end)
    activity = np.asarray(activity, bool)
    correct = len(matched)
    precision = correct / len(onsets) if onsets else 0.0
    recall = correct / len(runs) if runs else 0.0
    speech_seconds = float(np.count_nonzero(truth) * 0.01)
    silence_seconds = float(np.count_nonzero(~truth) * 0.01)
    return {
        "reference_onsets": len(runs), "detected_onsets": len(onsets), "matched_onsets": correct,
        "missed_onsets": len(runs) - correct, "unmatched_onsets": false_onsets,
        "onset_precision": precision, "onset_recall": recall,
        "onset_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "detected_within_300ms": sum(-150 <= ms <= 300 for ms in latencies),
        "latency_ms": distribution(latencies),
        "latencies_ms": latencies,
        "reference_speech_seconds": speech_seconds, "reference_silence_seconds": silence_seconds,
        "missed_speech_seconds": float(np.count_nonzero(truth & ~activity) * 0.01),
        "false_activity_seconds": float(np.count_nonzero(~truth & activity) * 0.01),
    }


def detect_file(path, detector, *, seconds=None):
    before = time.perf_counter()
    onsets, activity = [], []
    with wave.open(str(path), "rb") as recording:
        rate = recording.getframerate()
        frames = recording.getnframes()
        if seconds is not None:
            if not math.isfinite(seconds) or seconds <= 0:
                raise ValueError("evaluation seconds must be finite and positive")
            frames = min(frames, int(seconds * rate))
        converter = StreamingResampler(rate, SPEECH_RATE) if rate != SPEECH_RATE else None
        pending = np.empty(0, np.float32)
        processed = read = 0
        while read < frames:
            count = min(rate, frames - read)
            raw = recording.readframes(count)
            if len(raw) != count * 2:
                raise ValueError("truncated DiPCo WAV")
            chunk = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
            read += count
            if converter:
                chunk = converter.resample(chunk, flush=read == frames)
            pending = np.concatenate((pending, chunk))
            while len(pending) >= 160:
                onset = detector.accept(pending[:160], processed / SPEECH_RATE)
                pending = pending[160:]
                processed += 160
                if onset:
                    onsets.append(onset)
                activity.append(detector.latched)
    duration = processed / SPEECH_RATE
    return onsets, activity, duration, (time.perf_counter() - before) / max(duration, 0.01)


def summarize(scores):
    sums = {key: sum(s[key] for s in scores) for key in (
        "reference_onsets", "detected_onsets", "matched_onsets", "missed_onsets",
        "unmatched_onsets", "detected_within_300ms", "reference_speech_seconds",
        "reference_silence_seconds", "missed_speech_seconds", "false_activity_seconds",
    )}
    precision = sums["matched_onsets"] / max(1, sums["detected_onsets"])
    recall = sums["matched_onsets"] / max(1, sums["reference_onsets"])
    return {**sums, "onset_precision": precision, "onset_recall": recall,
            "onset_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
            "latency_ms": distribution([ms for s in scores for ms in s["latencies_ms"]])}


def evaluate_interruptions(dataset, root=None, *, settings=None, split="all", filename=None,
                           seconds=None, hold_seconds=0.08, progress=None):
    import sherpa_onnx

    block_network()
    store = ModelStore(root)
    store.verify()
    vad_path = store.profile / "vad/silero_vad.onnx"
    settings = settings or VoiceSettings(processing=False)
    detector_settings = InterruptionSettings(hold_seconds=hold_seconds)
    items = [i for i in inventory(dataset) if (split == "all" or i["split"] == split)
             and (not filename or i["path"].name == filename)]
    if not items:
        raise ValueError("no recordings match the requested split/file")
    measurements = Measurements()
    results = []
    try:
        for item in items:
            if progress:
                progress(f"Interruption onset replay: {item['path'].name}")
            detector = OnsetDetector(
                SherpaVad(sherpa_onnx, vad_path, settings.vad_threshold), detector_settings,
                speech_input(settings),
            )
            onsets, activity, duration, rtf = detect_file(item["path"], detector, seconds=seconds)
            spans, runs = reference_activity(item, duration)
            score = score_activity(onsets, activity, spans, runs)
            results.append({"file": item["path"].name, "session": item["session"],
                            "split": item["split"], "microphone": item["microphone"],
                            "file_sha256": digest(item["path"]),
                            "annotation_sha256": digest(item["annotations_path"]),
                            "audio_seconds": duration, "real_time_factor": rtf, "score": score,
                            "onsets": onsets,
                            "input_levels": detector.processor.diagnostics()
                            if detector.processor else None})
    finally:
        metrics = measurements.finish()
    return {
        "protocol": "continuous speech onset; all annotated voices; no text exclusions",
        "reference_merge_seconds": 0.3, "onset_early_tolerance_seconds": 0.15,
        "onset_late_tolerance_seconds": 1.0,
        "settings": {"processing": settings.processing, "gain_db": settings.gain_db,
                     "vad_threshold": settings.vad_threshold,
                     **asdict(detector_settings)},
        "model_sha256": digest(vad_path), "recordings": results,
        "summary": summarize([r["score"] for r in results]), "measurements": metrics,
        "hardware_gate": "pending", "network": "blocked", "audio_devices": "not opened",
        "limitation": "Local onset diagnostic, not official DiPCo scoring. "
                      "DiPCo has no assistant playback: self-interruptions, echo, actual output "
                      "stop and speaker changes without silence require separate trials.",
    }
