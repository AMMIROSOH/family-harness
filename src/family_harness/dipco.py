"""Local DiPCo evaluation. Annotation replay is never claimed as diarization."""

from __future__ import annotations

import json
import math
import re
import socket
import time
import unicodedata
import wave
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from family_harness.models import ModelStore, digest
from family_harness.room import RoomEvent
from family_harness.room_replay import ReplayHarness, distribution, replay_wav, wav_info
from family_harness.speech import SPEECH_RATE, LocalVoice, SpeechTurn, VoiceSettings
from family_harness.voice_trial import Measurements


def normalize(text: str) -> str:
    text = re.sub(r"\[[^\]]*\]", " ", unicodedata.normalize("NFKC", text).casefold())
    text = text.replace("\u2019", "'")
    return " ".join(
        "".join(
            c if c == "'" or not unicodedata.category(c).startswith("P") else " " for c in text
        ).split()
    )


def timestamp(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    result = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    if not math.isfinite(result) or result < 0 or not 0 <= int(minutes) < 60:
        raise ValueError("invalid annotation timestamp")
    if not 0 <= float(seconds) < 60:
        raise ValueError("invalid annotation seconds")
    return result


@dataclass(frozen=True)
class Annotation:
    index: int
    speaker: str
    start: float
    end: float
    text: str
    overlap: bool = False


def annotations(path: Path, session: str, microphone: str, speaker: str | None = None):
    rows = json.loads(path.read_text("utf-8"))
    if not isinstance(rows, list) or not 0 < len(rows) <= 10000:
        raise ValueError("invalid or oversized DiPCo annotations")
    all_rows = []
    excluded = Counter()
    for index, row in enumerate(rows):
        if row["session_id"] != session:
            raise ValueError("annotation session does not match the WAV")
        start, end = (
            timestamp(row["start_time"][microphone]),
            timestamp(row["end_time"][microphone]),
        )
        if end < start:
            raise ValueError("annotation end precedes start")
        all_rows.append(Annotation(index, row["speaker_id"], start, end, row["words"]))
    result = []
    for row in all_rows:
        if speaker and row.speaker != speaker:
            continue
        if "[unintelligible]" in row.text.casefold():
            excluded["unintelligible"] += 1
        elif not normalize(row.text):
            excluded["nonlexical"] += 1
        elif row.end - row.start > 28:
            excluded["longer_than_28_seconds"] += 1
        else:
            overlap = any(
                other.speaker != row.speaker and other.start < row.end and other.end > row.start
                for other in all_rows
            )
            result.append(Annotation(**{**asdict(row), "overlap": overlap}))
    return sorted(result, key=lambda a: (a.start, a.end, a.index)), dict(excluded)


def inventory(root: Path):
    files = []
    json_files = list(root.rglob("*.[jJ][sS][oO][nN]"))
    for wav in sorted(root.rglob("*.wav")):
        match = re.fullmatch(r"(S\d+)_(P\d+|U\d+\.CH\d+)\.wav", wav.name)
        if match is None:
            continue
        session, device = match.groups()
        candidates = [p for p in json_files if session.casefold() in p.stem.casefold()]
        if len(candidates) != 1:
            raise ValueError(f"provide exactly one annotation JSON for {session}")
        close = device.startswith("P")
        mic = "close-talk" if close else device.split(".")[0]
        with wave.open(str(wav)) as recording:
            rate, frames = wav_info(recording)
        rows, excluded = annotations(candidates[0], session, mic, device if close else None)
        if any(row.end > frames / rate + 0.1 for row in rows):
            raise ValueError(f"annotations exceed the duration of {wav.name}")
        files.append(
            {
                "path": wav,
                "annotations_path": candidates[0],
                "session": session,
                "split": "dev" if session in ("S02", "S04", "S05", "S09", "S10") else "eval",
                "microphone": mic,
                "speaker": device if close else None,
                "rows": rows,
                "excluded": excluded,
                "duration": frames / rate,
            }
        )
    if not files:
        raise ValueError("no supported DiPCo WAV/annotation pairs found")
    return files


def select_rows(rows, limit: int | None):
    if limit is None or len(rows) <= limit:
        return rows
    # Round-robin speakers; sample evenly through each speaker's recording.
    speakers = sorted({r.speaker for r in rows})
    quotas = {
        speaker: limit // len(speakers) + (i < limit % len(speakers))
        for i, speaker in enumerate(speakers)
    }
    result = []
    for speaker in speakers:
        group = [r for r in rows if r.speaker == speaker]
        count = min(len(group), quotas[speaker])
        result.extend(group[i] for i in np.linspace(0, len(group) - 1, count, dtype=int))
    return sorted(result, key=lambda a: (a.start, a.index))


def error_counts(reference, hypothesis):
    from jiwer import process_words

    score = process_words(normalize(reference), normalize(hypothesis))
    return {
        "hits": score.hits,
        "substitutions": score.substitutions,
        "deletions": score.deletions,
        "insertions": score.insertions,
    }


def aggregate(rows):
    counts = Counter()
    for row in rows:
        counts.update(row["errors"])
    words = counts["hits"] + counts["substitutions"] + counts["deletions"]
    return {
        "utterances": len(rows),
        "reference_words": words,
        **dict(counts),
        "wer": (counts["substitutions"] + counts["deletions"] + counts["insertions"]) / words
        if words
        else None,
    }


def evaluate_utterances(item, voice, limit=None):
    rows = select_rows(item["rows"], limit)
    results = []
    started = time.perf_counter()
    with wave.open(str(item["path"])) as recording:
        rate, frames = wav_info(recording)
        audio_seconds = 0.0
        for row in rows:
            voice.reset_input()
            left = max(0, int((row.start - 0.2) * rate))
            right = min(frames, int((row.end + 0.15) * rate))
            recording.setpos(left)
            raw = recording.readframes(right - left)
            if len(raw) != (right - left) * 2:
                raise ValueError("truncated WAV")
            samples = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
            if rate != SPEECH_RATE:
                samples = voice.resampler(rate).resample(samples, flush=True)
            turn = SpeechTurn(
                voice.vad,
                voice.stt,
                lambda e: None,
                processor=voice.input_processor,
                completion_silence=voice.settings.silence,
            )
            end = 0.0
            for offset in range(0, len(samples) + SPEECH_RATE, 160):
                chunk = (
                    samples[offset : offset + 160]
                    if offset < len(samples)
                    else np.zeros(160, np.float32)
                )
                done = turn.accept(chunk, offset / SPEECH_RATE)
                end = (offset + len(chunk)) / SPEECH_RATE
                if done:
                    break
            turn.finish(end, "replay_eof")
            audio_seconds += end
            results.append(
                {
                    "annotation_index": row.index,
                    "overlap": row.overlap,
                    "errors": error_counts(row.text, turn.text),
                    "speech_detected": turn.started is not None,
                    "candidate": turn.candidate_latency is not None,
                    "premature": turn.candidate_latency is not None
                    and left / rate + end < row.end - 0.1,
                    "first_partial_audio_ms": turn.partial_latency,
                    "completion_after_vad_ms": turn.candidate_latency,
                }
            )
    elapsed = time.perf_counter() - started
    return {
        "all": aggregate(results),
        "nonoverlap": aggregate([r for r in results if not r["overlap"]]),
        "overlap": aggregate([r for r in results if r["overlap"]]),
        "vad_misses": sum(not r["speech_detected"] for r in results),
        "premature_completions": sum(r["premature"] for r in results),
        "without_silence_candidate": sum(not r["candidate"] for r in results),
        "first_partial_audio_ms": distribution(
            [
                r["first_partial_audio_ms"]
                for r in results
                if r["first_partial_audio_ms"] is not None
            ]
        ),
        "completion_after_vad_ms": distribution(
            [
                r["completion_after_vad_ms"]
                for r in results
                if r["completion_after_vad_ms"] is not None
            ]
        ),
        "wall_seconds": round(elapsed, 3),
        "processed_audio_seconds": round(audio_seconds, 3),
        "real_time_factor": round(elapsed / audio_seconds, 4) if audio_seconds else None,
        "rows": results,
    }


def evaluate_events(item):
    harness = ReplayHarness(session_id=item["session"])
    harness.send("session_started", 0)
    events = []
    speakers = {
        speaker: f"track-{i + 1}"
        for i, speaker in enumerate(sorted({row.speaker for row in item["rows"]}))
    }
    for row in item["rows"]:
        data = {
            "utterance_id": f"annotation-{row.index}",
            "revision": 1,
            "text": row.text[: max(1, len(row.text) // 2)],
            "final": False,
            "start": row.start,
            "end": (row.start + row.end) / 2,
            "speaker_track": speakers[row.speaker],
            "language": "en",
        }
        events.append(
            RoomEvent(
                f"partial-{row.index}",
                item["session"],
                "annotations",
                data["end"],
                "transcript",
                data,
            )
        )
        final = {
            **data,
            "revision": 2,
            "text": row.text,
            "final": True,
            "end": row.end,
            "reason": "annotation_final",
        }
        events.append(
            RoomEvent(
                f"final-{row.index}", item["session"], "annotations", row.end, "transcript", final
            )
        )
    for event in sorted(events, key=lambda e: (e.at, e.event_id)):
        harness.tick(event.at)
        harness.apply(event)
        if event.data["final"]:
            harness.apply(event)
            harness.apply(
                RoomEvent(
                    f"late-{event.event_id}",
                    event.session_id,
                    event.source_id,
                    event.at,
                    "transcript",
                    {**event.data, "revision": 1, "final": False, "text": "late"},
                )
            )
    expected = {f"annotation-{r.index}": r.text for r in item["rows"]}
    actual = {
        uid: turn.text for uid, turn in harness.manager.utterances.items() if turn.status == "final"
    }
    harness.send("session_closed", item["duration"] + 1)
    before = harness.manager.snapshot(include_text=True)
    if events:
        final = events[-1]
        harness.apply(
            RoomEvent(
                "after-close",
                final.session_id,
                final.source_id,
                item["duration"] + 2,
                final.kind,
                final.data,
            )
        )
    after = harness.manager.snapshot(include_text=True)
    return {
        "passed": actual == expected
        and before["utterances"] == after["utterances"]
        and before["responses"] == after["responses"],
        "expected_turns": len(expected),
        "actual_turns": len(actual),
        "session_status": harness.manager.status,
        "counts": dict(harness.manager.counts),
        "commands": dict(harness.commands),
        "attribution": "annotation-derived session tracks; no speaker recognition",
        "playback": "simulated; no audio devices opened",
    }


def evaluate_continuous(item, voice, seconds=None):
    result = replay_wav(item["path"], voice, seconds=seconds, include_text=True)
    turns = [r for r in result["utterances"] if r["status"] == "final"]
    reference_rows = item["rows"]
    if item["speaker"]:
        reference_rows, _ = annotations(
            item["annotations_path"], item["session"], item["microphone"]
        )
    rows = [r for r in reference_rows if r.end <= result["file_audio_seconds"]]
    # Chronological single-stream WER is diagnostic, not CHiME/cpWER scoring.
    errors = error_counts(" ".join(r.text for r in rows), " ".join(r["text"] for r in turns))
    score = aggregate([{"errors": errors}])
    return {
        key: value
        for key, value in {
            **result,
            "chronological_wer": score,
            "recognized_turns": len(turns),
            "reference_utterances": len(rows),
            "reference_scope": "all annotated speakers; continuous replay has no identity filter",
        }.items()
        if key not in ("utterances", "responses", "session_id", "room_id")
    }


def evaluate(
    root: Path,
    models: Path | None,
    *,
    mode="utterances",
    settings=None,
    split="all",
    filename=None,
    limit=None,
    seconds=None,
    progress=print,
) -> dict:
    items = [
        item
        for item in inventory(root)
        if (split == "all" or item["split"] == split)
        and (filename is None or item["path"].name == filename)
    ]
    if not items:
        raise ValueError("no recordings match the requested split/file")
    if mode not in ("events", "utterances", "continuous"):
        raise ValueError("unsupported evaluation mode")
    metrics = Measurements()
    voice = None
    settings = settings or VoiceSettings()
    store = ModelStore(models)
    results = []
    try:
        if mode != "events":
            store.verify()
            voice = LocalVoice(store.profile, settings)
            voice.warm()
        for item in items:
            progress(f"Evaluating {item['path'].name} ({mode})")
            score = (
                evaluate_events(item)
                if mode == "events"
                else (
                    evaluate_utterances(item, voice, limit)
                    if mode == "utterances"
                    else evaluate_continuous(item, voice, seconds)
                )
            )
            results.append(
                {
                    "file": item["path"].name,
                    "split": item["split"],
                    "wav_sha256": digest(item["path"]),
                    "annotation_sha256": digest(item["annotations_path"]),
                    "file_audio_seconds": item["duration"],
                    "excluded_annotations": item["excluded"],
                    "score": score,
                }
            )
    finally:
        measurements = metrics.finish()
    return {
        "schema_version": 1,
        "dataset": "DiPCo local subset",
        "mode": mode,
        "settings": asdict(settings),
        "recordings": results,
        "measurements": measurements,
        "profile_id": store.catalog["id"] if voice else None,
        "model_assets": [
            {"name": a["name"], "sha256": a["sha256"]} for a in store.catalog["assets"]
        ]
        if voice
        else [],
        "normalization": "NFKC/casefold; remove bracketed tags and punctuation except apostrophes",
        "limitations": [
            "Annotation replay verifies manager logic, not speech or identity accuracy.",
            "Utterance mode uses reference boundaries and independent one-utterance trials.",
            "Unintelligible, nonlexical and >28-second annotations excluded from utterance WER.",
            "Continuous chronological WER includes overlap and is not official DiPCo scoring.",
            "Close-talk clip scoring uses the named speaker; cross-talk can add words.",
            "Playback is simulated. Hardware, echo and interruption gates remain pending.",
        ],
    }


def block_network():
    def denied(*args, **kwargs):
        raise RuntimeError("network access is disabled during local evaluation")

    socket.socket = denied
    socket.create_connection = denied
