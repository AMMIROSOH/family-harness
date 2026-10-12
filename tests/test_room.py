import json

import pytest

from family_harness.room import RoomEvent, RoomManager
from family_harness.room_replay import replay_events


def send(manager, kind, at=0, **data):
    event = RoomEvent(f"event-{len(manager.seen)}", manager.session_id, "mic", at, kind, data)
    return manager.apply(event)


def transcript(uid="u1", revision=1, text="hello", final=False, start=1, end=2):
    return dict(
        utterance_id=uid,
        revision=revision,
        text=text,
        final=final,
        start=start,
        end=end,
        speaker_track="track-1",
        language="fa",
    )


def active():
    manager = RoomManager("s1", "room")
    send(manager, "session_started")
    return manager


def test_revisions_replace_text_finalize_once_and_keep_identity_separate():
    manager = active()
    send(manager, "transcript", 2, **transcript())
    send(manager, "turn_candidate", 2.5, utterance_id="u1", authority="vad-silence")
    commands = send(
        manager, "transcript", 2.6, **transcript(revision=2, text="hello room", final=True, end=2.6)
    )
    assert [c["kind"] for c in commands] == ["response_requested"]
    send(manager, "transcript", 3, **transcript(revision=3, text="stale", final=True, end=3))
    turn = manager.utterances["u1"]
    assert turn.text == "hello room" and turn.candidate and turn.language == "fa"
    assert turn.person_id is turn.identity_confidence is None
    assert turn.speaker_track == "track-1"
    assert len(manager.responses) == manager.counts["final_turns"] == 1


def test_out_of_order_revisions_and_duplicates_do_not_append_words():
    manager = active()
    event = RoomEvent("same", "s1", "mic", 2, "transcript", transcript(revision=3))
    manager.apply(event)
    manager.apply(event)
    send(manager, "transcript", 2, **transcript(revision=2, text="wrong"))
    assert manager.utterances["u1"].text == "hello"
    assert manager.counts["ignored_duplicate"] == manager.counts["ignored_stale_revision"] == 1


def test_delayed_older_final_preserves_history_without_cancelling_current_reply():
    manager = active()
    send(manager, "transcript", 2, **transcript())
    rid = send(manager, "transcript", 4,
               **transcript(uid="new", final=True, start=3, end=4))[0]["response_id"]
    assert send(manager, "transcript", 5, **transcript(revision=2, final=True)) == []
    assert manager.utterances["u1"].status == "final"
    assert manager.responses[rid].status == "requested"
    assert len(manager.responses) == 1


def test_playback_monotonicity_partial_hearing_and_stale_results_after_cancel():
    manager = active()
    rid = send(manager, "transcript", 2, **transcript(final=True))[0]["response_id"]
    send(manager, "response_ready", 2, response_id=rid, text="reply", duration=4)
    send(manager, "playback_progress", 3, response_id=rid, played_seconds=1)
    send(manager, "playback_progress", 3, response_id=rid, played_seconds=0.5)
    send(manager, "playback_finished", 3, response_id=rid, played_seconds=1)
    assert manager.responses[rid].status == "playing"
    assert manager.responses[rid].played_seconds == 1
    assert manager.responses[rid].heard_text is None
    commands = send(manager, "response_cancelled", 3, response_id=rid)
    assert {c["kind"] for c in commands} == {"stop_playback", "cancel_generation"}
    send(manager, "playback_finished", 6, response_id=rid, played_seconds=4)
    send(manager, "response_ready", 6, response_id=rid, text="late", duration=1)
    assert manager.responses[rid].status == "cancelled"
    assert manager.responses[rid].played_seconds == 1
    assert manager.responses[rid].heard_text is None


def test_completion_marks_full_hearing_and_new_turn_cancels_old_generation():
    manager = active()
    rid1 = send(manager, "transcript", 2, **transcript(final=True))[0]["response_id"]
    commands = send(manager, "transcript", 4, **transcript(uid="u2", final=True, start=3, end=4))
    assert manager.responses[rid1].status == "cancelled"
    rid2 = commands[-1]["response_id"]
    send(manager, "response_ready", 4, response_id=rid2, text="reply", duration=1)
    send(manager, "playback_finished", 5, response_id=rid2, played_seconds=1)
    assert manager.responses[rid2].heard_text == "reply"


def test_gap_discards_provisional_turns_and_rejects_pre_gap_audio():
    manager = active()
    send(manager, "transcript", 2, **transcript())
    send(manager, "audio_gap", 2.1)
    send(manager, "transcript", 3, **transcript(final=True, revision=2, end=3))
    send(manager, "transcript", 3, **transcript(uid="late", final=True, start=1.5, end=3))
    assert manager.utterances["u1"].status == "discarded"
    assert not manager.responses and "late" not in manager.utterances
    send(manager, "transcript", 4, **transcript(uid="recovered", final=True, start=3, end=4))
    assert len(manager.responses) == 1


def test_close_cancels_pending_work_and_session_cannot_reopen():
    manager = active()
    rid = send(manager, "transcript", 2, **transcript(final=True))[0]["response_id"]
    commands = send(manager, "session_closed", 3)
    assert len(commands) == 2 and manager.responses[rid].status == "cancelled"
    before = manager.snapshot(include_text=True)
    send(manager, "session_started", 4)
    send(manager, "transcript", 5, **transcript(uid="new", final=True, start=4, end=5))
    send(manager, "response_ready", 5, response_id=rid, text="late", duration=1)
    after = manager.snapshot(include_text=True)
    assert manager.status == "closed"
    assert before["utterances"] == after["utterances"]
    assert before["responses"] == after["responses"]


def test_wrong_session_source_and_completion_authority_are_ignored():
    manager = active()
    manager.apply(RoomEvent("wrong", "old-session", "mic", 2, "transcript", transcript()))
    assert not manager.utterances
    send(manager, "transcript", 2, **transcript())
    send(manager, "turn_candidate", 2, utterance_id="u1", authority="other")
    manager.apply(
        RoomEvent(
            "other-source", "s1", "other", 2, "transcript", transcript(revision=2, final=True)
        )
    )
    assert not manager.utterances["u1"].candidate and not manager.responses


@pytest.mark.parametrize(
    "changes",
    [
        {"revision": 0},
        {"revision": True},
        {"final": "yes"},
        {"start": float("nan")},
        {"end": float("inf")},
        {"start": -1},
        {"end": 0.5},
        {"text": []},
    ],
)
def test_invalid_events_are_rejected_before_state_changes(changes):
    manager = active()
    before = manager.snapshot()
    with pytest.raises(ValueError):
        send(manager, "transcript", 2, **{**transcript(), **changes})
    assert before == manager.snapshot()


def test_capacity_is_explicit_and_empty_or_cancelled_final_does_not_reply():
    manager = RoomManager("s1", "room", max_turns=1)
    send(manager, "session_started")
    send(manager, "transcript", 2, **transcript(text="", final=True))
    assert manager.utterances["u1"].status == "discarded" and not manager.responses
    with pytest.raises(ValueError, match="capacity"):
        send(manager, "transcript", 3, **transcript(uid="u2", start=2, end=3))


def test_event_replay_requires_explicit_closure_and_reports_no_transcript(tmp_path):
    path = tmp_path / "events.jsonl"
    events = [
        RoomEvent("open", "s1", "mic", 0, "session_started"),
        RoomEvent("final", "s1", "mic", 2, "transcript", transcript(final=True)),
        RoomEvent("close", "s1", "mic", 3, "session_closed"),
    ]
    from dataclasses import asdict

    path.write_text("\n".join(json.dumps(asdict(e)) for e in events), "utf-8")
    report = replay_events(path)
    assert report["status"] == "closed"
    assert "hello" not in json.dumps(report)
    assert "simulated" in report["playback"]
    path.write_text(json.dumps(asdict(events[0])), "utf-8")
    with pytest.raises(ValueError, match="close"):
        replay_events(path)
