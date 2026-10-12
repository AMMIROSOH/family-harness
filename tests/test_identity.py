import json
import wave
from dataclasses import asdict
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest
from conftest import FakeAudio

from family_harness.errors import SetupError
from family_harness.group import SpeakerSegment, group_turns, turn_regions
from family_harness.identity import (
    IdentityDecision,
    MatchSettings,
    PeopleStore,
    VoiceMatcher,
    VoiceProfile,
    enrollment,
    matching_settings,
    speaker_audio,
)
from family_harness.people_worker import capture_samples, enrollment_takes
from family_harness.speaker_evaluation import (
    clean_enrollment_regions,
    enrollment_plan,
    probe_recording,
    score_probe,
    speaker_counts,
    timeline_error,
)


class Embeddings:
    backend = "fake"
    model_hash = "a" * 64

    def embed(self, samples):
        return np.array([1.0, 0.0], np.float32)


def profile(vector, name="نام"):
    return VoiceProfile(str(uuid4()), name, "fake", "a" * 64, vector, 3)


def test_unknown_ambiguity_and_short_speech_do_not_force_identity():
    p = profile([1, 0])
    matcher = VoiceMatcher(Embeddings(), [p], MatchSettings(0.6, 0.08))
    assert matcher.match_vector([0, 1]).person_id is None
    assert matcher.match_vector([1, 0]).person_id == p.person_id
    assert matcher.identify(np.ones(100, np.float32)).state == "insufficient_audio"
    assert matcher.identify(np.ones(16000), overlap=True).state == "overlap"
    ambiguous = VoiceMatcher(Embeddings(), [p, profile([0.999, 0.01])])
    assert ambiguous.match_vector([1, 0]).state == "ambiguous"
    assert ambiguous.match_vector([1, 0]).person_id is None


def test_tied_voices_stay_ambiguous_even_with_zero_margin():
    matcher = VoiceMatcher(Embeddings(), [profile([1, 0]), profile([1, 0])],
                           MatchSettings(0.3, 0))
    assert matcher.match_vector([1, 0]).state == "ambiguous"
    assert matcher.match_vector([1, 0]).person_id is None


def test_home_matching_recognizes_more_evidence_and_retains_strict_override():
    settings = matching_settings("titanet-large")
    assert settings == MatchSettings(0.3, 0.08, 0.7)
    assert matching_settings("wespeaker-resnet293") == MatchSettings(0.3, 0.08, 0.7)
    assert matching_settings("titanet-large", threshold=0.575, margin=0) == MatchSettings(0.575, 0)
    person = profile([1, 0])
    person = VoiceProfile(**{**asdict(person), "backend": "titanet-large"})
    provider = SimpleNamespace(backend="titanet-large", model_hash="a" * 64)
    home = VoiceMatcher(provider, [person])
    strict = VoiceMatcher(provider, [person], matching_settings(
        "titanet-large", threshold=0.575, margin=0,
    ))
    evidence = [0.4, np.sqrt(1-0.4**2)]
    assert home.match_vector(evidence).person_id == person.person_id
    assert strict.match_vector(evidence).person_id is None
    assert home.match_vector([0.1, np.sqrt(1-0.1**2)]).person_id is None
    with pytest.raises(ValueError):
        matching_settings("titanet-large", threshold=float("nan"))


def test_profiles_survive_restart_and_removal_without_audio(tmp_path):
    store = PeopleStore(tmp_path / "people.json")
    person = profile([1, 0])
    store.save(person)
    assert PeopleStore(store.path).load() == [person]
    assert "embedding" not in store.public()[0]
    person = VoiceProfile(**{**asdict(person), "name": "Another name"})
    store.save(person)
    assert len(store.load()) == 1
    text = store.path.read_text("utf-8")
    assert "audio" not in text and "transcript" not in text
    store.remove(person.person_id)
    assert store.load() == []


def test_wrong_model_and_damaged_profiles_require_reenrollment(tmp_path):
    with pytest.raises(SetupError):
        VoiceMatcher(SimpleNamespace(backend="different", model_hash="a" * 64), [profile([1, 0])])
    store = PeopleStore(tmp_path / "people.json")
    store.path.write_text(json.dumps({"version": 2, "people": []}))
    with pytest.raises(SetupError):
        store.load()
    with pytest.raises(ValueError):
        VoiceMatcher(Embeddings(), [profile([float("nan"), 0])])


def test_enrollment_rejects_silence_clipping_and_inconsistent_people():
    for samples in (np.zeros(32000), np.ones(32000), np.full(32000, np.nan)):
        with pytest.raises(ValueError):
            speaker_audio(samples, minimum=2)
    with pytest.raises(ValueError):
        enrollment(Embeddings(), [np.full(32000, 0.02)] * 2, "Name")
    candidate, quality = enrollment(Embeddings(), [np.full(32000, 0.02)] * 3, "Name")
    assert candidate.samples == 3 and quality["mean_similarity"] == 1
    assert quality["phrase_seconds"] == [2, 2, 2]
    vectors = iter(([1, 0], [-1, 0], [0, 1]))
    provider = SimpleNamespace(
        backend="fake",
        model_hash="a" * 64,
        embed=lambda samples: np.array(next(vectors), np.float32),
    )
    with pytest.raises(SetupError):
        enrollment(provider, [np.full(32000, 0.02)] * 3, "Name")


def test_native_capture_is_bounded_input_only_and_discards_gaps(devices):
    audio = FakeAudio()
    request = {"kind": "people_enroll", "input_id": "mic", "endpoint_id": "endpoint"}
    samples, device = capture_samples(request, devices, audio, lambda e: None, duration=0.1)
    assert len(samples) == 1600 and device["id"] == "mic"
    assert len(audio.streams) == 1 and audio.streams[0].closed
    assert not audio.played
    broken = FakeAudio(gap_at=2)
    with pytest.raises(SetupError, match="lost"):
        capture_samples(request, devices, broken, lambda e: None, duration=0.1)
    assert broken.streams[0].closed


def test_enrollment_requires_speech_in_each_guided_window():
    samples = np.full(18 * 16000, 0.02, np.float32)
    diarizer = SimpleNamespace(segments=lambda audio: [SpeakerSegment(0, 3, "s0")])
    with pytest.raises(ValueError, match="each"):
        enrollment_takes(samples, diarizer)
    diarizer.segments = lambda audio: [
        SpeakerSegment(1, 5, "s0"),
        SpeakerSegment(7, 11, "s0"),
        SpeakerSegment(13, 17, "s0"),
    ]
    assert len(enrollment_takes(samples, diarizer)) == 3
    diarizer.segments = lambda audio: [
        SpeakerSegment(0, 3, "s0"), SpeakerSegment(6, 9, "s0"), SpeakerSegment(12, 15, "s0"),
    ]
    with pytest.raises(ValueError, match="four seconds"):
        enrollment_takes(samples, diarizer)
    diarizer.segments = lambda audio: [SpeakerSegment(0, 18, "s0")]
    assert [len(t) for t in enrollment_takes(samples, diarizer)] == [6 * 16000] * 3


def test_group_handover_unknown_and_overlap_are_separate_from_asr():
    segments = [
        SpeakerSegment(0, 2, "s0"),
        SpeakerSegment(2, 4, "s1"),
        SpeakerSegment(4, 6, "s2"),
        SpeakerSegment(6, 8, "s0"),
        SpeakerSegment(7, 9, "s2"),
    ]
    diarizer = SimpleNamespace(segments=lambda audio: segments)
    people = [profile([1, 0]), profile([0, 1])]
    decisions = iter(
        (
            IdentityDecision(people[0].person_id, 0.8, 0.3, "matched"),
            IdentityDecision(people[1].person_id, 0.9, 0.4, "matched"),
            IdentityDecision(None, 0.1, 0.02, "unknown"),
            IdentityDecision(people[0].person_id, 0.8, 0.3, "matched"),
            IdentityDecision(None, 0.1, 0.02, "unknown"),
        )
    )
    matcher = SimpleNamespace(
        provider=Embeddings(),
        identify=lambda audio, overlap: (
            IdentityDecision(None, None, None, "overlap") if overlap else next(decisions)
        ),
    )
    decoded = []
    recognizer = SimpleNamespace(decode=lambda audio: decoded.append(len(audio)) or "Hello")
    report = group_turns(np.full(9 * 16000, 0.02), diarizer, matcher, recognizer)
    turns = report["utterances"]
    assert [t["person_id"] for t in turns[:3]] == [p.person_id for p in people] + [None]
    assert [t["speaker_track"] for t in turns[:3]] == ["s0", "s1", "s2"]
    assert len(decoded) == 5 and report["overlap_turns"] == 1
    assert turns[4]["identity_state"] == "overlap"
    assert turns[3]["person_id"] == people[0].person_id
    assert turns[5]["person_id"] is None
    assert report["recovery"] and report["status"] == "closed"
    assert all("text" not in t for t in turns)
    assert all("embedding" not in t for t in turns)


def test_brief_overlap_preserves_clean_speech_and_chronological_regions():
    regions = turn_regions([SpeakerSegment(0, 10, "a"), SpeakerSegment(4, 4.3, "b")])
    assert [(r.start, r.end, overlap) for r, overlap in regions] == [
        (0, 4, False), (4, 4.3, True), (4.3, 10, False),
    ]
    assert sum(r.end-r.start for r, overlap in regions if not overlap) == pytest.approx(9.7)
    assert turn_regions([SpeakerSegment(0, 2, "a"), SpeakerSegment(1, 3, "a")]) == [
        (SpeakerSegment(0, 3, "a"), False),
    ]


def test_nested_overlap_reaches_manager_in_source_order_and_silence_is_safe():
    diarizer = SimpleNamespace(segments=lambda audio: [
        SpeakerSegment(0, 10, "a"), SpeakerSegment(4, 4.3, "b"),
    ])
    matcher = VoiceMatcher(Embeddings(), [profile([1, 0])])
    decoded = []
    recognizer = SimpleNamespace(decode=lambda audio: decoded.append(len(audio)) or "Hello")
    report = group_turns(np.full(10 * 16000, 0.02), diarizer, matcher, recognizer)
    assert [u["start"] for u in report["utterances"]] == [0, 4, 4.3]
    assert len(report["utterances"]) == 3 and report["overlap_turns"] == 1
    assert len(decoded) == 2
    report = group_turns(np.zeros(10 * 16000), diarizer, matcher, recognizer)
    assert report["status"] == "closed" and len(decoded) == 2


def test_duration_score_mapping_overlap_and_unknown_accounting():
    refs = [
        SimpleNamespace(start=0, end=2, speaker="a"),
        SimpleNamespace(start=2, end=4, speaker="b"),
    ]
    segments = [SpeakerSegment(0, 2, "s1"), SpeakerSegment(2, 4, "s0")]
    assert timeline_error(refs, segments, 4)["speaker_error_rate"] == 0
    score = timeline_error(refs, [], 4)
    assert score["miss_seconds"] == 4 and score["speaker_error_rate"] == 1
    counts = speaker_counts(
        [{"known": True, "outcome": "known_correct"}, {"known": False, "outcome": "guest_accepted"}]
    )
    assert counts["balanced_accuracy"] == 0.5 and counts["guest_rejection"] == 0


def test_enrollment_plan_is_fixed_before_model_scoring():
    rows = [
        SimpleNamespace(speaker="p", overlap=False, start=0, end=3, index=0),
        SimpleNamespace(speaker="p", overlap=True, start=4, end=8, index=1),
        SimpleNamespace(speaker="p", overlap=False, start=9, end=12, index=2),
    ]
    assert [r.index for r in enrollment_plan({"rows": rows})["p"]] == [0, 2]


def test_unavailable_enrollment_stays_in_known_trial_denominator(tmp_path):
    path = tmp_path / "room.wav"
    with wave.open(str(path), "wb") as recording:
        recording.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        recording.writeframes(np.full(16 * 16000, 655, dtype="<i2").tobytes())
    rows = [
        SimpleNamespace(speaker="a", overlap=False, start=0, end=6, index=0),
        SimpleNamespace(speaker="b", overlap=False, start=7, end=8, index=1),
        SimpleNamespace(speaker="c", overlap=False, start=9, end=11, index=2),
        SimpleNamespace(speaker="a", overlap=True, start=14, end=16, index=3),
    ]
    item = {"path": path, "session": "S", "rows": rows}
    probe = probe_recording(item, Embeddings())
    assert probe["profiles"]["b"] is None and probe["profiles"]["c"] is None
    score = score_probe(probe, Embeddings())
    assert score["all"]["known_trials"] == 6
    assert score["all"]["guest_trials"] == 3
    assert set(probe_recording(item, Embeddings(), enrollment_pairs="eligible")["profiles"]) == {
        "a",
    }


def test_longer_evaluation_enrollment_uses_three_four_second_phrases(tmp_path):
    path = tmp_path / "room.wav"
    with wave.open(str(path), "wb") as recording:
        recording.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        recording.writeframes(np.full(22 * 16000, 655, dtype="<i2").tobytes())
    rows = [
        SimpleNamespace(speaker="a", overlap=False, start=0, end=12, index=0),
        SimpleNamespace(speaker="b", overlap=False, start=13, end=14, index=1),
        SimpleNamespace(speaker="c", overlap=False, start=16, end=18, index=2),
        SimpleNamespace(speaker="a", overlap=True, start=20, end=22, index=3),
    ]
    lengths = []
    provider = Embeddings()
    provider.embed = lambda audio: lengths.append(len(audio)) or np.array([1., 0.])
    item = {"path": path, "session": "S", "rows": rows}
    probe = probe_recording(item, provider, enrollment_seconds=12)
    assert lengths[:3] == [4 * 16000] * 3
    assert probe["quality"]["a"]["phrase_seconds"] == [4, 4, 4]
    assert probe["quality"]["b"]["required_seconds"] == 12
    assert [r["annotation_index"] for r in probe["rows"]] == [1, 2, 3]
    with pytest.raises(ValueError, match="6, 12 or 18"):
        probe_recording(item, provider, enrollment_seconds=10)


def test_clean_enrollment_preserves_speech_around_excluded_other_voice(tmp_path):
    path = tmp_path / "annotations.json"
    path.write_text(json.dumps([
        {"speaker_id": "a", "start_time": {"U01": "00:00:00"},
         "end_time": {"U01": "00:00:10"}},
        # This nonlexical row is absent from eligible test rows, but its audio still overlaps.
        {"speaker_id": "b", "start_time": {"U01": "00:00:04"},
         "end_time": {"U01": "00:00:04.5"}},
    ]))
    item = {"annotations_path": path, "microphone": "U01", "rows": [
        SimpleNamespace(speaker="a", overlap=True, start=0, end=10, index=0),
    ]}
    assert enrollment_plan(item, 6) == {}
    regions = clean_enrollment_regions(item)
    assert [(r.start, r.end, r.speaker) for r in regions] == [(0, 4, "a"), (4.5, 10, "a")]
    assert sum(r.end-r.start for r in regions) == 9.5
    assert enrollment_plan(item, 6, regions="clean")["a"] == regions
