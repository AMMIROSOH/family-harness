import json
import shutil
import wave
from types import SimpleNamespace

import numpy as np
import pytest

from family_harness.dipco import (
    aggregate,
    annotations,
    error_counts,
    evaluate,
    evaluate_continuous,
    evaluate_events,
    evaluate_recognizer,
    evaluate_utterances,
    inventory,
    normalize,
    select_rows,
    timestamp,
)
from family_harness.room_replay import replay_wav
from family_harness.speech import VoiceSettings


class FakeStt:
    def reset(self):
        self.text = ""

    def accept(self, samples):
        if np.any(samples):
            self.text = "hello room"
        return self.text

    def finish(self):
        return self.text


class FakeVoice:
    settings = VoiceSettings(processing=False)
    input_processor = None

    def __init__(self):
        self.stt = FakeStt()
        self.vad_resets = 0
        self.vad = SimpleNamespace(
            accept=lambda samples: bool(np.any(samples)), reset=self.reset_vad
        )

    def reset_vad(self):
        self.vad_resets += 1

    def reset_input(self):
        self.stt.reset()


def write_wav(path, samples, rate=16000):
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, rate, 0, "NONE", ""))
        output.writeframes((samples * 32767).astype("<i2").tobytes())


def fixture_dataset(tmp_path):
    samples = np.zeros(16000 * 4, np.float32)
    samples[16000:19200] = 0.1
    samples[40000:43200] = 0.1
    write_wav(tmp_path / "S02_U01.CH1.wav", samples)
    rows = [
        {
            "session_id": "S02",
            "speaker_id": speaker,
            "start_time": {"U01": start, "close-talk": start},
            "end_time": {"U01": end, "close-talk": end},
            "words": text,
        }
        for speaker, start, end, text in [
            ("P05", "00:00:01.00", "00:00:01.20", "hello room"),
            ("P06", "00:00:02.50", "00:00:02.70", "hello room"),
            ("P05", "00:00:03.00", "00:00:03.10", "[noise]"),
            ("P05", "00:00:03.20", "00:00:03.30", "[unintelligible] word"),
        ]
    ]
    (tmp_path / "transcriptions_dev_S02.JSON").write_text(json.dumps(rows), "utf-8")
    return inventory(tmp_path)[0]


def test_annotation_times_microphone_and_speaker_filters_and_exclusions(tmp_path):
    item = fixture_dataset(tmp_path)
    assert len(item["rows"]) == 2 and item["split"] == "dev"
    assert item["excluded"] == {"nonlexical": 1, "unintelligible": 1}
    rows, excluded = annotations(item["annotations_path"], "S02", "close-talk", "P05")
    assert len(rows) == 1 and rows[0].speaker == "P05"
    assert timestamp("00:02:12.79") == 132.79
    assert excluded == item["excluded"]


@pytest.mark.parametrize("value", ["00:00:nan", "00:00:inf", "00:61:00", "-1:00:00"])
def test_invalid_annotation_timestamps(value):
    with pytest.raises(ValueError):
        timestamp(value)


def test_overlap_and_even_sampling_are_explicit(tmp_path):
    item = fixture_dataset(tmp_path)
    path = item["annotations_path"]
    rows = json.loads(path.read_text())
    rows[1]["start_time"]["U01"] = "00:00:01.10"
    path.write_text(json.dumps(rows), "utf-8")
    selected = inventory(tmp_path)[0]["rows"]
    assert all(r.overlap for r in selected)
    assert len(select_rows(selected, 1)) == 1


def test_wer_uses_word_counts_and_keeps_apostrophes():
    assert normalize("[noise] HELLO, don't [laugh]!") == "hello don't"
    result = aggregate(
        [
            {"errors": error_counts("one two three", "one four")},
            {"errors": error_counts("five", "five six")},
        ]
    )
    assert result["reference_words"] == 4 and result["wer"] == 0.75
    assert result["substitutions"] == result["deletions"] == result["insertions"] == 1


def test_annotation_replay_preserves_tracks_final_turns_and_closure(tmp_path):
    report = evaluate_events(fixture_dataset(tmp_path))
    assert report["passed"] and report["actual_turns"] == report["expected_turns"] == 2
    assert report["session_status"] == "closed"
    assert report["counts"]["ignored_duplicate"] == 2
    assert report["counts"]["ignored_stale_turn"] == 2
    assert report["counts"]["ignored_inactive"] == 1


def test_continuous_replay_keeps_multiple_utterances_on_source_timeline(tmp_path):
    item = fixture_dataset(tmp_path)
    report = replay_wav(item["path"], FakeVoice(), include_text=True)
    turns = [turn for turn in report["utterances"] if turn["status"] == "final"]
    assert len(turns) == 2 and all(t["text"] == "hello room" for t in turns)
    assert turns[0]["start"] == 1 and turns[1]["start"] == 2.5
    assert all(t["speaker_track"] == "unknown" and t["person_id"] is None for t in turns)
    assert report["commands"]["response_requested"] == 2
    assert report["status"] == "closed" and report["file_audio_seconds"] == 4


def test_batch_finals_replace_drafts_through_the_room_event_contract(tmp_path):
    item = fixture_dataset(tmp_path)
    voice = FakeVoice()
    audio = []
    voice.finalizer = SimpleNamespace(decode=lambda s: audio.append(s.copy()) or "better final")
    report = replay_wav(item["path"], voice, include_text=True)
    assert len(audio) == 2
    assert all(t["text"] == "better final" for t in report["utterances"])
    assert report["commands"]["response_requested"] == 2
    assert all(t["candidate"] for t in report["utterances"])


def test_silent_replay_cannot_make_a_turn_and_utterance_report_excludes_text(tmp_path):
    item = fixture_dataset(tmp_path)
    report = evaluate_utterances(item, FakeVoice())
    assert report["all"]["wer"] == 0
    assert report["premature_completions"] == report["vad_misses"] == 0
    assert "hello" not in json.dumps(report)
    write_wav(item["path"], np.zeros(16000, np.float32))
    replay = replay_wav(item["path"], FakeVoice())
    assert not replay["utterances"] and not replay["responses"]


def test_recognizer_scoring_uses_full_exact_bounds_without_vad_or_neighbor_audio(tmp_path):
    item = fixture_dataset(tmp_path)
    received = []
    engine = SimpleNamespace(decode=lambda samples: received.append(samples.copy()) or "hello room")
    report = evaluate_recognizer(item, engine)
    assert report["all"]["wer"] == 0
    assert len(received) == 2 and all(len(s) == 3200 for s in received)
    assert not report["vad_gating"] and not report["early_endpointing"]
    assert report["context_seconds"] == 0
    assert "hello" not in json.dumps(report)


def test_recognizer_evaluation_dispatch_needs_no_baseline_voice_or_devices(tmp_path, monkeypatch):
    fixture_dataset(tmp_path)
    engine = SimpleNamespace(decode=lambda s: "hello room")
    monkeypatch.setattr("family_harness.asr.load_recognizer", lambda backend, root: engine)
    result = evaluate(
        tmp_path, tmp_path / "models", mode="recognizer", recognizer="parakeet-v2",
        limit=1, settings=VoiceSettings(processing=False), progress=lambda s: None,
    )
    assert result["recognizer"] == "parakeet-v2" and result["schema_version"] == 2
    assert result["profile_id"] is None and result["model_assets"] == []
    assert result["recordings"][0]["score"]["all"]["utterances"] == 1
    assert result["recordings"][0]["score"]["all"]["wer"] == 0


def test_replay_detects_truncated_or_unsupported_audio(tmp_path):
    path = tmp_path / "bad.wav"
    write_wav(path, np.ones(16000, np.float32))
    path.write_bytes(path.read_bytes()[:-100])
    with pytest.raises(ValueError, match="truncated"):
        replay_wav(path, FakeVoice())


def test_continuous_prefix_has_explicit_duration_and_closes_session(tmp_path):
    item = fixture_dataset(tmp_path)
    report = replay_wav(item["path"], FakeVoice(), seconds=2)
    assert report["file_audio_seconds"] == 2 and report["status"] == "closed"
    assert len(report["utterances"]) == 1
    with pytest.raises(ValueError, match="duration"):
        replay_wav(item["path"], FakeVoice(), seconds=0)


def test_long_silence_preset_extends_bounded_replay_tail(tmp_path):
    item = fixture_dataset(tmp_path)
    voice = FakeVoice()
    voice.settings = VoiceSettings(processing=False, silence=2)
    result = replay_wav(item["path"], voice)
    assert result["synthetic_tail_seconds"] == 2.7
    assert result["file_audio_seconds"] == 4 and result["status"] == "closed"


def test_continuous_close_talk_does_not_claim_identity_filtering(tmp_path):
    item = fixture_dataset(tmp_path)
    shutil.copyfile(item["path"], tmp_path / "S02_P05.wav")
    item = next(i for i in inventory(tmp_path) if i["speaker"] == "P05")
    assert len(item["rows"]) == 1
    result = evaluate_continuous(item, FakeVoice())
    assert result["reference_utterances"] == 2
    assert result["chronological_wer"]["wer"] == 0
    assert "no identity filter" in result["reference_scope"]


def test_long_activity_resets_vad_at_forced_segment_boundary(tmp_path):
    path = tmp_path / "continuous.wav"
    write_wav(path, np.full(16000 * 35, 0.1, np.float32))
    voice = FakeVoice()
    result = replay_wav(path, voice)
    assert voice.vad_resets == 1
    assert result["final_reasons"]["segment_limit"] == 1
    assert len(result["utterances"]) == 2 and result["status"] == "closed"
