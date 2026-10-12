"""Bounded offline group turns through maintained local segmentation and ASR adapters."""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from typing import Protocol

import numpy as np

from family_harness.errors import SetupError
from family_harness.identity import identity_error, segmentation_store, speaker_audio, speaker_store
from family_harness.room_replay import ReplayHarness
from family_harness.speech import SPEECH_RATE


@dataclass(frozen=True)
class SpeakerSegment:
    start: float
    end: float
    track: str


class DiarizationProvider(Protocol):
    def segments(self, samples: np.ndarray) -> list[SpeakerSegment]: ...


def turn_regions(segments: list[SpeakerSegment]) -> list[tuple[SpeakerSegment, bool]]:
    """Keep clean speech around an overlap instead of discarding its entire track segment."""
    boundaries = sorted({t for s in segments for t in (s.start, s.end)})
    regions = []
    for start, end in zip(boundaries, boundaries[1:], strict=False):
        tracks = sorted({s.track for s in segments if s.start < end and s.end > start})
        if not tracks:
            continue
        overlap = len(tracks) > 1
        track = "+".join(tracks) if overlap else tracks[0]
        if regions and regions[-1][0].track == track and regions[-1][1] == overlap \
                and regions[-1][0].end == start:
            prior, _ = regions.pop()
            start = prior.start
        regions.append((SpeakerSegment(start, end, track), overlap))
    return regions


class SherpaDiarizer:
    def __init__(self, backend, root=None, *, threshold=0.9):
        import sherpa_onnx as sherpa

        if not math.isfinite(threshold) or not 0.1 <= threshold <= 0.9:
            raise ValueError("clustering threshold must be 0.1-0.9")
        segmentation, embedding = segmentation_store(root), speaker_store(backend, root)
        try:
            segmentation.verify()
            embedding.verify()
        except SetupError as exc:
            raise identity_error(
                "Install segmentation and speaker models before a group trial."
            ) from exc
        config = sherpa.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model=str(segmentation.profile / "segmentation" / "model.onnx"),
                ),
                num_threads=2,
                provider="cpu",
            ),
            embedding=sherpa.SpeakerEmbeddingExtractorConfig(
                model=str(embedding.profile / "model.onnx"),
                num_threads=2,
                provider="cpu",
            ),
            # No reference speaker count or enrolled-person count is supplied to clustering.
            clustering=sherpa.FastClusteringConfig(num_clusters=-1, threshold=threshold),
            min_duration_on=0.3,
            min_duration_off=0.2,
        )
        self.engine = sherpa.OfflineSpeakerDiarization(config)
        self.catalog = segmentation.catalog
        self.threshold = threshold

    def segments(self, samples):
        samples = np.asarray(samples, np.float32)
        if (
            samples.ndim != 1
            or not 0 < len(samples) <= 300 * SPEECH_RATE
            or not np.isfinite(samples).all()
        ):
            raise ValueError("group replay is bounded to 300 seconds of finite mono audio")
        if float(np.sqrt(np.mean(samples**2))) < 1e-5:
            return []
        conditioned = speaker_audio(samples, minimum=0.1, maximum=300)
        results = self.engine.process(conditioned).sort_by_start_time()
        return [
            SpeakerSegment(
                float(r.start),
                min(float(r.end), len(samples) / SPEECH_RATE),
                f"speaker-{r.speaker}",
            )
            for r in results
            if r.end > r.start
        ]


def group_turns(
    samples,
    diarizer,
    matcher,
    recognizer,
    *,
    participation="all",
    include_text=False,
    progress=None,
    session=None,
    time_offset=0.0,
):
    """Reference-free boundaries and session tracks. Output playback remains simulated."""
    samples = np.asarray(samples, np.float32)
    if (
        samples.ndim != 1
        or not 0 < len(samples) <= 300 * SPEECH_RATE
        or not np.isfinite(samples).all()
    ):
        raise ValueError("group replay needs at most 300 seconds of mono audio")
    before = time.perf_counter()
    segments = diarizer.segments(samples)
    duration = len(samples) / SPEECH_RATE
    for segment in segments:
        if (
            not 0 <= segment.start < segment.end <= duration
            or not segment.track
            or not math.isfinite(segment.start)
            or not math.isfinite(segment.end)
        ):
            raise ValueError("diarizer returned invalid source timestamps")
    harness = session or ReplayHarness(participation=participation)
    if session is None:
        harness.send("session_started", 0)
    sequence = 0
    overlap_turns = 0
    for segment, overlap in turn_regions(segments):
        # Long segments are bounded before ASR/identity. Tracks remain session-local.
        for start in np.arange(segment.start, segment.end, 28):
            end = min(float(start) + 28, segment.end)
            chunk = samples[int(start * SPEECH_RATE) : int(end * SPEECH_RATE)]
            if not len(chunk):
                continue
            sequence += 1
            uid = f"group-{sequence}"
            identity = matcher.identify(chunk, overlap=overlap)
            conditioned = None
            if not overlap:
                try:
                    conditioned = speaker_audio(chunk, minimum=0.01)
                except ValueError:
                    pass
            text = recognizer.decode(conditioned) if conditioned is not None else ""
            data = {
                "utterance_id": uid,
                "revision": 1,
                "text": "",
                "final": False,
                "start": float(start),
                "end": end,
                "speaker_track": segment.track,
            }
            data["start"] += time_offset
            data["end"] += time_offset
            event_at = end + time_offset
            if session is None:
                harness.tick(event_at)
            harness.send("transcript", event_at, data)
            harness.send(
                "attribution",
                event_at,
                {
                    "utterance_id": uid,
                    "revision": 1,
                    "speaker_track": segment.track,
                    "person_id": identity.person_id,
                    "score": identity.score,
                    "state": identity.state,
                    "start": float(start) + time_offset,
                    "end": event_at,
                    "backend": matcher.provider.backend,
                    "model_hash": matcher.provider.model_hash,
                },
            )
            # Overlap remains visible as discarded input with a recovery message in the report.
            harness.send("transcript", event_at,
                         {**data, "revision": 2, "text": text, "final": True})
            overlap_turns += overlap
            if progress:
                progress(
                    {
                        "type": "progress",
                        "phase": "group_decoding",
                        "seconds": end,
                        "duration": duration,
                    }
                )
    if session is None:
        harness.tick(duration + time_offset + 0.5)
    harness.send("session_closed", duration + time_offset + 0.5)
    report = harness.report(include_text=include_text) if session is None else {
        **harness.manager.snapshot(include_text=include_text),
        "commands": dict(harness.commands),
        "playback": "native fixed cue; continuation responses withheld after capture",
    }
    return {
        **report,
        "audio_seconds": duration,
        "matching_settings": asdict(matcher.settings) if getattr(matcher, "settings", None)
        else None,
        "segments": [asdict(s) for s in segments],
        "overlap_turns": overlap_turns,
        "recovery": "Overlapping voices need repetition, one person at a time."
        if overlap_turns
        else None,
        "real_time_factor": (time.perf_counter() - before) / duration,
        "reference_boundaries": False,
        "hardware_gate": "pending",
        "limitation": "Offline bounded preview; no live replies or physical interruptions.",
    }
