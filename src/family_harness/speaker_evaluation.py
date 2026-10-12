"""Reference-bounded open-set speaker evaluation, distinct from automatic diarization."""

from __future__ import annotations

import itertools
import math
import time
import wave
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import numpy as np

from family_harness.dipco import inventory, read_utterance, select_rows
from family_harness.errors import SetupError
from family_harness.identity import MatchSettings, VoiceMatcher, enrollment
from family_harness.models import digest
from family_harness.speech import SPEECH_RATE


def enrollment_plan(item, seconds=6):
    """First available clean speech, fixed before extracting or scoring embeddings."""
    plan = {}
    for speaker in sorted({r.speaker for r in item["rows"]}):
        chosen, duration = [], 0.0
        for row in item["rows"]:
            if row.speaker != speaker or row.overlap or row.end - row.start < 0.7:
                continue
            chosen.append(row)
            duration += row.end - row.start
            if duration >= seconds:
                plan[speaker] = chosen
                break
    return plan


def probe_recording(item, provider, *, limit=None, progress=None):
    plan = enrollment_plan(item)
    protected = [r for rows in plan.values() for r in rows]
    # Also exclude other-speaker clips intersecting enrollment audio, plus a 1s guard.
    test = [
        r
        for r in item["rows"]
        if not any(r.start < p.end + 1 and r.end > p.start - 1 for p in protected)
    ]
    test = select_rows(test, limit)
    profiles, diagnostics = {}, {}
    rows = []
    before = time.perf_counter()
    audio_seconds = 0.0
    with wave.open(str(item["path"])) as recording:
        for speaker, chosen in plan.items():
            samples = np.concatenate([read_utterance(recording, r) for r in chosen])
            # Exactly three 2-second takes; annotation labels only supply enrollment supervision.
            takes = [samples[i * SPEECH_RATE * 2 : (i + 1) * SPEECH_RATE * 2] for i in range(3)]
            try:
                profile, quality = enrollment(
                    provider,
                    takes,
                    speaker,
                    person_id=str(uuid5(NAMESPACE_URL, item["session"] + ":" + speaker)),
                )
            except (SetupError, ValueError):
                profiles[speaker] = None
                diagnostics[speaker] = {"enrollment_failed": True}
                continue
            profiles[speaker], diagnostics[speaker] = profile, quality
            audio_seconds += 6
        for row in test:
            samples = read_utterance(recording, row)
            vector = None
            reason = "insufficient_audio"
            if len(samples) >= 0.7 * SPEECH_RATE:
                try:
                    vector = provider.embed(samples)
                    reason = "usable"
                except ValueError:
                    reason = "unusable_audio"
            rows.append(
                {
                    "annotation_index": row.index,
                    "speaker": row.speaker,
                    "overlap": row.overlap,
                    "seconds": row.end - row.start,
                    "vector": vector,
                    "reason": reason,
                }
            )
            audio_seconds += len(samples) / SPEECH_RATE
            if progress and len(rows) % 25 == 0:
                progress(f"{item['path'].name}: {len(rows)} speaker clips")
    return {
        "profiles": profiles,
        "rows": rows,
        "quality": diagnostics,
        "enrollment_indices": {s: [r.index for r in chosen] for s, chosen in plan.items()},
        "excluded_enrollment_or_guard": len(item["rows"])
        - len(
            [
                r
                for r in item["rows"]
                if not any(r.start < p.end + 1 and r.end > p.start - 1 for p in protected)
            ]
        ),
        "wall_seconds": time.perf_counter() - before,
        "audio_seconds": audio_seconds,
    }


def speaker_counts(rows):
    counts = Counter(r["outcome"] for r in rows)
    known = sum(r["known"] for r in rows)
    guests = len(rows) - known
    known_recall = counts["known_correct"] / known if known else None
    guest_rejection = counts["guest_rejected"] / guests if guests else None
    return {
        "trials": len(rows),
        "known_trials": known,
        "guest_trials": guests,
        **dict(counts),
        "known_recall": known_recall,
        "guest_rejection": guest_rejection,
        "balanced_accuracy": (known_recall + guest_rejection) / 2
        if known_recall is not None and guest_rejection is not None
        else None,
        "accuracy": (counts["known_correct"] + counts["guest_rejected"]) / len(rows)
        if rows
        else None,
        "assigned_precision": counts["known_correct"]
        / (counts["known_correct"] + counts["known_wrong"] + counts["guest_accepted"])
        if counts["known_correct"] + counts["known_wrong"] + counts["guest_accepted"]
        else None,
    }


def score_probe(probe, provider, settings=None):
    settings = settings or MatchSettings()
    profiles = probe["profiles"]
    if len(profiles) < 2:
        raise ValueError("this recording has insufficient clean enrollment speech for two people")
    results = []
    for pair in itertools.combinations(sorted(profiles), 2):
        selected = [profiles[s] for s in pair if profiles[s] is not None]
        matcher = VoiceMatcher(provider, selected, settings)
        for row in probe["rows"]:
            known = row["speaker"] in pair
            decision = None
            if row["vector"] is not None and row["seconds"] >= settings.minimum_seconds:
                decision = matcher.match_vector(row["vector"])
            person_id = decision.person_id if decision else None
            expected = str(uuid5(NAMESPACE_URL, "expected-failed:" + row["speaker"]))
            if known and profiles[row["speaker"]] is not None:
                expected = profiles[row["speaker"]].person_id
            if known:
                outcome = (
                    "known_correct"
                    if person_id == expected
                    else ("known_wrong" if person_id else "known_rejected")
                )
            else:
                outcome = "guest_accepted" if person_id else "guest_rejected"
            results.append(
                {
                    "annotation_index": row["annotation_index"],
                    "enrolled_pair": list(pair),
                    "known": known,
                    "overlap": row["overlap"],
                    "outcome": outcome,
                    "state": decision.state if decision else row["reason"],
                    "score": decision.score if decision else None,
                    "margin": decision.margin if decision else None,
                }
            )
    return {
        "all": speaker_counts(results),
        "nonoverlap": speaker_counts([r for r in results if not r["overlap"]]),
        "overlap": speaker_counts([r for r in results if r["overlap"]]),
        "unique_test_annotations": len(probe["rows"]),
        "enrollment_indices": probe["enrollment_indices"],
        "enrollment_quality": probe["quality"],
        "excluded_enrollment_or_guard": probe["excluded_enrollment_or_guard"],
        "rows": results,
    }


def evaluate_speakers(
    dataset: Path,
    provider,
    *,
    split="eval",
    limit=None,
    settings=None,
    progress=None,
    filename=None,
):
    settings = settings or MatchSettings()
    recordings = []
    before = time.perf_counter()
    for item in inventory(dataset):
        if (
            item["speaker"]
            or (split != "all" and item["split"] != split)
            or (filename and item["path"].name != filename)
        ):
            continue
        probe = probe_recording(item, provider, limit=limit, progress=progress)
        recordings.append(
            {
                "file": item["path"].name,
                "sha256": digest(item["path"]),
                "annotation_sha256": digest(item["annotations_path"]),
                "split": item["split"],
                "score": score_probe(probe, provider, settings),
                "wall_seconds": round(probe["wall_seconds"], 3),
                "audio_seconds": round(probe["audio_seconds"], 3),
                "real_time_factor": probe["wall_seconds"] / probe["audio_seconds"],
            }
        )
    if not recordings:
        raise ValueError("no room recordings in the selected split")
    rows = [row for item in recordings for row in item["score"]["rows"]]
    return {
        "protocol": "reference-bounded two-known open-set speaker matching; not diarization",
        "reference_boundaries": True,
        "backend": provider.backend,
        "model_sha256": provider.model_hash,
        "source_model_sha256": getattr(provider, "source_model_hash", None),
        "settings": asdict(settings),
        "enrollment_seconds_per_person": 6,
        "enrollment_guard_seconds": 1,
        "pair_policy": "all eligible two-person pairs; repeated trials are not unique sentences",
        "split": split,
        "limit": limit,
        "recordings": recordings,
        "combined": speaker_counts(rows),
        "combined_nonoverlap": speaker_counts([r for r in rows if not r["overlap"]]),
        "wall_seconds": round(time.perf_counter() - before, 3),
        "hardware_gate": "pending",
    }


def timeline_error(reference, predicted, duration, *, nonoverlap=False):
    """Duration scoring with optimal one-to-one labels and no collar.

    DiPCo utterance boundaries are coarse. This is a local diagnostic, not the
    official CHiME scorer. Overlap contributes multiple reference speaker seconds.
    """
    ref_labels = sorted({r.speaker for r in reference})
    hyp_labels = sorted({s.track for s in predicted})
    if len(ref_labels) > 8 or len(hyp_labels) > 64:
        raise ValueError("speaker scoring capacity exceeded")
    boundaries = sorted(
        {
            0.0,
            duration,
            *[max(0, min(duration, t)) for r in reference for t in (r.start, r.end)],
            *[max(0, min(duration, t)) for s in predicted for t in (s.start, s.end)],
        }
    )
    atoms = []
    weights = np.zeros((len(hyp_labels), len(ref_labels)))
    for left, right in zip(boundaries, boundaries[1:], strict=False):
        at = (left + right) / 2
        refs = {r.speaker for r in reference if r.start <= at < r.end}
        hyps = {s.track for s in predicted if s.start <= at < s.end}
        if nonoverlap and len(refs) > 1:
            continue
        atoms.append((right - left, refs, hyps))
        for h in hyps:
            for r in refs:
                weights[hyp_labels.index(h), ref_labels.index(r)] += right - left
    # Exact assignment for the small reference speaker set using subset DP.
    assignments = {0: (0.0, {})}
    for i, hypothesis in enumerate(hyp_labels):
        updated = dict(assignments)
        for mask, (weight, mapping) in assignments.items():
            for j, label in enumerate(ref_labels):
                if mask & (1 << j):
                    continue
                target = mask | (1 << j)
                candidate = weight + weights[i, j]
                if target not in updated or candidate > updated[target][0]:
                    updated[target] = (candidate, {**mapping, hypothesis: label})
        assignments = updated
    mapping = max(assignments.values(), key=lambda a: a[0])[1]
    miss = false = confusion = denominator = 0.0
    for seconds, refs, hyps in atoms:
        correct = len(refs & {mapping[h] for h in hyps if h in mapping})
        denominator += seconds * len(refs)
        miss += seconds * max(0, len(refs) - len(hyps))
        false += seconds * max(0, len(hyps) - len(refs))
        confusion += seconds * (min(len(refs), len(hyps)) - correct)
    return {
        "reference_speaker_seconds": denominator,
        "miss_seconds": miss,
        "false_alarm_seconds": false,
        "confusion_seconds": confusion,
        "speaker_error_rate": (miss + false + confusion) / denominator if denominator else None,
        "collar_seconds": 0,
        "overlap_scored": not nonoverlap,
    }


def evaluate_diarization(dataset, backend, root=None, *, split="eval", seconds=300, filename=None):
    from family_harness.group import SherpaDiarizer
    from family_harness.identity import read_voice_wav
    from family_harness.voice_trial import Measurements

    if not math.isfinite(seconds) or not 0 < seconds <= 300:
        raise ValueError("diarization evaluation is bounded to 300-second prefixes")
    metrics = Measurements()
    recordings = []
    try:
        diarizer = SherpaDiarizer(backend, root)
        for item in inventory(dataset):
            if (
                item["speaker"]
                or (split != "all" and item["split"] != split)
                or (filename and item["path"].name != filename)
            ):
                continue
            samples = read_voice_wav(item["path"], maximum=300, seconds=seconds)
            duration = len(samples) / SPEECH_RATE
            before = time.perf_counter()
            segments = diarizer.segments(samples)
            recordings.append(
                {
                    "file": item["path"].name,
                    "sha256": digest(item["path"]),
                    "annotation_sha256": digest(item["annotations_path"]),
                    "seconds": duration,
                    "tracks": len({s.track for s in segments}),
                    "segments": [asdict(s) for s in segments],
                    "all": timeline_error(item["rows"], segments, duration),
                    "nonoverlap": timeline_error(item["rows"], segments, duration, nonoverlap=True),
                    "real_time_factor": (time.perf_counter() - before) / duration,
                }
            )
    finally:
        measurements = metrics.finish()
    if not recordings:
        raise ValueError("no room recordings in the selected split")
    return {
        "protocol": "automatic diarization; coarse annotation duration diagnostic, not CHiME",
        "reference_boundaries": False,
        "backend": backend,
        "clustering_threshold": diarizer.threshold,
        "segmentation_catalog": diarizer.catalog,
        "recordings": recordings,
        "measurements": measurements,
        "hardware_gate": "pending",
    }
