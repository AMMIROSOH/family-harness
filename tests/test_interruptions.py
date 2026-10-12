import json
import threading
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from conftest import FakeAudio, FakeStream
from test_control import wait_until
from test_room import active, attribution, send, transcript

from family_harness.control import AudioControl
from family_harness.errors import SetupError
from family_harness.interruption_evaluation import reference_activity, score_activity
from family_harness.interruption_trial import TrialSession, capture_interruption
from family_harness.interruptions import (
    CancellableOutput,
    GenerationToken,
    InterruptionSettings,
    OnsetDetector,
)
from family_harness.room import RoomEvent
from family_harness.speech import VoiceSettings


def test_onset_stops_generation_and_output_before_words_or_identity():
    manager = active()
    rid = send(manager, "transcript", 2, **transcript(final=True))[0]["response_id"]
    send(manager, "response_ready", 2, response_id=rid, text="reply", duration=4)
    commands = send(manager, "speech_started", 2.4, start=2.2)
    assert {c["kind"] for c in commands} == {"stop_playback", "cancel_generation"}
    assert len(manager.utterances) == 1
    send(manager, "response_ready", 3, response_id=rid, text="late", duration=4)
    assert manager.responses[rid].text == "reply"
    assert manager.responses[rid].status == "cancelled"
    assert send(manager, "speech_started", 3, start=2.2) == []
    assert manager.counts["interruptions"] == 1


def test_older_onset_and_final_cannot_cancel_a_newer_response():
    manager = active()
    rid = send(manager, "transcript", 4,
               **transcript(final=True, start=3, end=4))[0]["response_id"]
    assert send(manager, "speech_started", 5, start=2.5) == []
    assert manager.responses[rid].status == "requested"
    send(manager, "speech_started", 5.5, start=5)
    assert send(manager, "transcript", 6,
                **transcript(uid="old", final=True, start=2, end=3)) == []
    assert len(manager.responses) == 1


def test_heard_history_uses_complete_chunks_and_one_terminal_stop_ack():
    manager = active()
    rid = send(manager, "transcript", 2, **transcript(final=True))[0]["response_id"]
    send(manager, "response_ready", 2, response_id=rid, text="First. Second.", duration=4,
         alignment=[{"text": "First.", "end": 2}, {"text": "Second.", "end": 4}])
    send(manager, "playback_progress", 3, response_id=rid, played_seconds=1)
    assert manager.responses[rid].heard_text == ""
    send(manager, "speech_started", 4.1, start=4)
    send(manager, "playback_stopped", 4.2, response_id=rid, played_seconds=2.1)
    assert manager.responses[rid].heard_text == "First."
    send(manager, "playback_stopped", 8, response_id=rid, played_seconds=4)
    send(manager, "playback_finished", 8, response_id=rid, played_seconds=4)
    assert manager.responses[rid].heard_text == "First."
    assert "First." not in json.dumps(manager.snapshot())
    assert manager.responses[rid].status == "cancelled"


@pytest.mark.parametrize("alignment", [
    [], [{"text": "wrong", "end": 4}], [{"text": "reply", "end": float("nan")}],
    [{"text": "reply", "end": 2}], [{"text": "reply", "end": 5}],
])
def test_invalid_alignment_is_rejected_before_state_change(alignment):
    manager = active()
    rid = send(manager, "transcript", 2, **transcript(final=True))[0]["response_id"]
    before = manager.snapshot()
    with pytest.raises(ValueError):
        send(manager, "response_ready", 2, response_id=rid, text="reply", duration=4,
             alignment=alignment)
    assert manager.snapshot() == before


def test_overlap_requests_repetition_and_never_answers_mixed_words():
    manager = active()
    send(manager, "transcript", 2, **transcript())
    send(manager, "attribution", 2, **attribution(person_id=None, state="overlap"))
    assert send(manager, "transcript", 2, **transcript(revision=2, final=True)) == []
    turn = manager.utterances["u1"]
    assert turn.person_id is None and "one person" in turn.recovery
    send(manager, "transcript", 4, **transcript(uid="continuation", start=3, end=4, final=True))
    assert len(manager.responses) == 1


def test_output_stop_zeros_next_block_and_confirms_dac_not_submission():
    output = CancellableOutput("r1", np.ones(1600, np.float32), 16000, lead_seconds=0)
    out = np.empty((160, 2), np.float32)
    output.write(out, 160, 10.03)
    assert output.confirmed_seconds(10.02) == 0
    assert output.confirmed_seconds(10.035) == pytest.approx(0.005)
    output.stop("other")
    output.write(out, 160, 10.04)
    assert out.any()
    output.stop("r1")
    output.write(out, 160, 10.05)
    assert not out.any()
    assert output.confirmed_seconds(20) == pytest.approx(0.02)


def test_cancel_token_releases_blocked_provider_and_is_response_scoped():
    token = GenerationToken("r1")
    result = []
    worker = threading.Thread(target=lambda: result.append(token.cancelled.wait(1)))
    worker.start()
    token.cancel("old")
    assert not token.cancelled.is_set()
    token.cancel("r1")
    worker.join(1)
    assert result == [True]


class Vad:
    def __init__(self):
        self.calls = 0

    def accept(self, samples):
        self.calls += 1
        return self.calls >= 350

    def reset(self):
        self.calls = 0


class Tts:
    def synthesize(self, text):
        return np.full(16000, 0.1, np.float32), 16000


def test_bounded_duplex_stops_and_closes_before_continuation_analysis(devices, selection):
    devices = [replace(d, rates=(16000,)) for d in devices]
    voice = SimpleNamespace(tts=Tts(), vad=Vad(), settings=VoiceSettings(processing=False))
    session = TrialSession()
    sd = FakeAudio()
    audio, offset, result = capture_interruption(
        {**selection, "endpoint_id": "trial"}, devices, sd, voice, session, lambda _: None,
        echo_factory=lambda rate: SimpleNamespace(process=lambda near, far, delay: near),
    )
    assert sd.streams[0].closed
    assert result["interrupted"] and 0 < result["audio_seconds"] <= 20
    assert session.generation.cancelled.is_set()
    response = session.manager.responses[session.response_id]
    assert response.status == "cancelled" and response.playback_stopped
    assert response.heard_text == "This is the local interruption trial."
    assert 1 <= response.played_seconds < 2
    assert result["stop_to_first_zero_dac_ms"] < 100
    assert len(audio) <= 10 * 16000 and offset > 0
    assert not any(block.any() for block in sd.played[-50:])


def test_gap_stops_native_output_and_discards_take(devices, selection):
    voice = SimpleNamespace(tts=Tts(), vad=Vad(), settings=VoiceSettings(processing=False))
    session = TrialSession()
    sd = FakeAudio(gap_at=210)
    with pytest.raises(SetupError, match="Audio was lost"):
        capture_interruption({**selection, "endpoint_id": "trial"}, devices, sd, voice, session,
                             lambda _: None, echo_factory=lambda rate: SimpleNamespace(
                                 process=lambda near, far, delay: near))
    assert sd.streams[0].closed and session.output.stop_requested
    assert session.generation.cancelled.is_set()


def test_callback_aborts_capture_at_hard_limit_without_waiting_for_processing(devices, selection):
    class Abort(Exception):
        pass

    class BoundedStream(FakeStream):
        def _produce(self):
            try:
                super()._produce()
            except Abort:
                self.active = False
                self.backend.callback_aborted = True

    class BoundedAudio(FakeAudio):
        CallbackAbort = Abort
        callback_aborted = False

        def _stream(self, kind, **options):
            stream = BoundedStream(self, kind, **options)
            self.streams.append(stream)
            return stream

    class LongCue(Tts):
        def synthesize(self, text):
            return np.full(80000, 0.1, np.float32), 16000

    class LateVad(Vad):
        def accept(self, samples):
            self.calls += 1
            return self.calls >= 1650

    sd = BoundedAudio()
    voice = SimpleNamespace(tts=LongCue(), vad=LateVad(), settings=VoiceSettings(processing=False))
    _, _, result = capture_interruption(
        {**selection, "endpoint_id": "trial"}, [replace(d, rates=(16000,)) for d in devices],
        sd, voice, TrialSession(), lambda _: None,
        echo_factory=lambda rate: SimpleNamespace(process=lambda near, far, delay: near),
    )
    assert result["audio_seconds"] == 20 and result["interrupted"]
    assert sd.callback_aborted and sd.streams[0].closed


def test_detector_debounces_rearms_and_rejects_gap():
    class Activity:
        def accept(self, samples):
            return bool(samples[0])

        def reset(self):
            pass

    detector = OnsetDetector(Activity())
    onsets = []
    for i in range(80):
        onset = detector.accept(np.full(160, i < 10 or i >= 50, np.float32), i / 100)
        if onset:
            onsets.append(onset)
    assert len(onsets) == 2
    assert onsets[0]["detected_at"] == pytest.approx(0.08)
    with pytest.raises(ValueError, match="gap"):
        detector.accept(np.ones(160), 1)
    detector.reset()
    detector.accept(np.ones(160), 1)


def test_all_reference_speech_is_scored_without_text_exclusion(tmp_path):
    path = tmp_path / "annotations.json"
    path.write_text(json.dumps([
        {"words": "[unintelligible]", "start_time": {"U01": "00:00:01.00"},
         "end_time": {"U01": "00:00:02.00"}},
        {"words": "[laugh]", "start_time": {"U01": "00:00:01.50"},
         "end_time": {"U01": "00:00:03.00"}},
    ]))
    spans, runs = reference_activity({"annotations_path": path, "microphone": "U01"}, 5)
    assert runs == [(1, 3)] and len(spans) == 2
    score = score_activity([{"detected_at": 1.2}, {"detected_at": 1.3}],
                           [False] * 500, spans, runs)
    assert score["onset_recall"] == 1 and score["onset_precision"] == 0.5
    assert score["missed_speech_seconds"] == 2


def test_trial_requires_confirmation_and_contends_with_other_jobs(devices, selection, tmp_path):
    control = AudioControl(discovery=lambda: (devices, []), models=tmp_path / "models")
    try:
        control.refresh()
        with pytest.raises(SetupError, match="Check speaker"):
            control.start_interruption({**selection, "echo_confirmed": False})
        control.job = {"status": "running"}
        with pytest.raises(SetupError, match="Another setup"):
            control.start_interruption(selection)
    finally:
        control.job = None
        control.close()


def test_contended_capture_queue_stops_output_before_worker_failure(devices, selection):
    import time

    class SlowEcho:
        def __init__(self, rate):
            pass

        def process(self, near, far, delay):
            time.sleep(0.05)  # Simulated callbacks outpace the processing worker.
            return near

    voice = SimpleNamespace(tts=Tts(), vad=Vad(), settings=VoiceSettings(processing=False))
    session = TrialSession()
    sd = FakeAudio()
    with pytest.raises(SetupError, match="Audio was lost"):
        capture_interruption({**selection, "endpoint_id": "trial"}, devices, sd, voice, session,
                             lambda _: None, echo_factory=SlowEcho)
    assert session.output.stop_requested and sd.streams[0].closed
    assert session.generation.cancelled.is_set()


def test_missing_models_fail_before_native_audio_or_downloads(tmp_path, monkeypatch):
    import sys

    from family_harness.interruption_worker import execute

    def unexpected(**kwargs):
        raise AssertionError("audio must not open without verified models")

    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(Stream=unexpected))
    with pytest.raises(SetupError):
        execute({"kind": "interruption_trial", "echo_owner": "software", "echo_confirmed": True,
                 "speaker_confirmed": True, "models": str(tmp_path / "missing-models")},
                lambda _: None)


def test_wrong_session_onset_does_not_stop_current_reply():
    session = TrialSession()
    session.manager.apply(RoomEvent("old", "old-session", "native", 3,
                                    "speech_started", {"start": 3}))
    assert not session.generation.cancelled.is_set()


def test_interruption_worker_lease_stop_and_explicit_restart(devices, selection, tmp_path):
    import sys

    worker = tmp_path / "worker.py"
    worker.write_text("import sys,time\nsys.stdin.readline()\ntime.sleep(60)\n")
    control = AudioControl(discovery=lambda: (devices, []), models=tmp_path / "models",
                           interruption_command=[sys.executable, str(worker)], lease_seconds=0.2)
    try:
        control.refresh()
        first = control.start_interruption(selection)
        process = control.process
        wait_until(lambda: process.poll() is not None)
        assert control.poll(first["id"])["status"] == "cancelled"
        assert "disconnected" in control.job["reason"]
        control.refresh()  # Reconnection does not restart listening.
        assert process.poll() is not None
        second = control.start_interruption(selection)
        assert second["id"] != first["id"]
        control.stop()
        assert control.process.poll() is not None
        assert control.poll(second["id"])["status"] == "cancelled"
    finally:
        control.close()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True])
def test_invalid_onset_rejected(value):
    manager = active()
    with pytest.raises(ValueError):
        send(manager, "speech_started", 3, start=value)


@pytest.mark.parametrize("value", [float("nan"), -0.1, 1])
def test_invalid_interruption_settings(value):
    with pytest.raises(ValueError):
        InterruptionSettings(hold_seconds=value)
