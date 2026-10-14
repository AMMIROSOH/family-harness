import sys
import threading
import time

import numpy as np
import pytest

from family_harness.control import AudioControl
from family_harness.dashboard import DashboardStore, defaults, validate_settings
from family_harness.errors import SetupError
from family_harness.group import SpeakerSegment
from family_harness.identity import IdentityDecision, MatchSettings
from family_harness.live import IncrementalAttributor, LivePipeline, LiveSession
from family_harness.live_worker import fixture
from family_harness.speech import VoiceSettings


def until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("condition did not arrive")


def test_read_settings_does_not_create_state_and_profile_save_is_versioned(tmp_path):
    store = DashboardStore(tmp_path / "settings.json", defaults())
    assert store.public()["settings"]["speech"]["silence"] == .6
    assert not store.path.exists()
    changed = defaults()
    changed["speech"]["silence"] = 1.2
    saved = store.save({"revision": 0, "settings": changed, "name": "خانه"})
    assert saved["revision"] == 1 and saved["profiles"]["خانه"] == changed
    assert DashboardStore(store.path, defaults()).load()["settings"] == changed
    with pytest.raises(SetupError, match="newer"):
        store.save({"revision": 0, "settings": defaults()})
    assert store.load()["settings"] == changed


@pytest.mark.parametrize("change", [
    {"seconds": True}, {"seconds": 181}, {"seconds": 0}, {"permission": "tools"},
    {"speech": {"processing": "yes"}}, {"recognizer": "cloud"},
    {"matching": {"threshold": float("nan"), "margin": .08, "minimum_seconds": .7}},
])
def test_bad_settings_rejected(change):
    with pytest.raises((ValueError, TypeError)):
        validate_settings({**defaults(), **change})


def test_boolean_and_nan_rejected_for_speech_and_interruption():
    for group, field, value in (("speech", "vad_threshold", True),
                                ("speech", "gain_db", float("inf")),
                                ("interruption", "hold_seconds", False)):
        settings = defaults()
        settings[group][field] = value
        with pytest.raises(ValueError):
            validate_settings(settings)


def test_unknown_settings_version_is_never_overwritten(tmp_path):
    path = tmp_path / "settings.json"
    original = '{"version":999,"secret":"untouched"}'
    path.write_text(original)
    store = DashboardStore(path, defaults())
    with pytest.raises(SetupError, match="unsupported"):
        store.save({"revision": 0, "settings": defaults()})
    assert path.read_text() == original


def test_job_snapshot_and_owner_lease_are_independent_of_observer_polling(tmp_path, devices):
    script = tmp_path / "worker.py"
    script.write_text("import sys,time,json\nr=json.loads(sys.stdin.readline())\ntime.sleep(60)\n")
    audio = AudioControl(discovery=lambda: (devices, []), command=[sys.executable, str(script)],
                         lease_seconds=.25)
    try:
        audio.refresh()
        settings = defaults()
        job = audio.start({"kind": "microphone", "input_id": "mic", "_controller": "owner-"*5,
                           "settings": settings})
        settings["speech"]["gain_db"] = 36
        assert audio.job["request"]["effective_settings"]["speech"]["gain_db"] == 0
        assert "_controller" not in audio.poll(job["id"], controller="observer")["request"]
        with pytest.raises(SetupError, match="does not own"):
            audio.heartbeat(job["id"], "observer")
        for _ in range(6):
            audio.poll(job["id"], controller="observer")
            time.sleep(.07)
        assert audio.job["status"] == "cancelled" and audio.process.poll() is not None
    finally:
        audio.close()


def test_owner_heartbeat_keeps_take_and_stop_hides_owner(tmp_path, devices):
    script = tmp_path / "wait.py"
    script.write_text("import sys,time\nsys.stdin.readline()\ntime.sleep(60)\n")
    audio = AudioControl(discovery=lambda: (devices, []), command=[sys.executable, str(script)],
                         lease_seconds=.3)
    try:
        audio.refresh()
        job = audio.start({"kind": "microphone", "input_id": "mic", "_controller": "owner-"*5})
        for _ in range(6):
            audio.heartbeat(job["id"], "owner-"*5)
            time.sleep(.07)
        assert audio.job["status"] == "running"
        audio.job["room"] = {"status": "active", "utterances": [{"status": "provisional"}],
                             "responses": [{"status": "playing", "heard_text": "confirmed"}]}
        stopped = audio.stop()
        assert "_controller" not in stopped["request"]
        assert stopped["room"]["status"] == "closed"
        assert stopped["room"]["responses"][0]["status"] == "cancelled"
        assert stopped["room"]["responses"][0]["heard_text"] == "confirmed"
        assert stopped["room"]["utterances"][0]["status"] == "discarded"
    finally:
        audio.close()


def test_bounded_event_journal_requests_reset_and_current_snapshot(tmp_path, devices):
    script = tmp_path / "events.py"
    script.write_text("import sys,json\nsys.stdin.readline()\n"
                      "for n in range(300): print(json.dumps({'type':'room_event','at':n," 
                      "'kind':'transcript'}),flush=True)\n"
                      "print(json.dumps({'type':'room_snapshot','room':{'status':'closed'}}))\n"
                      "print(json.dumps({'type':'result','result':{'kind':'lab_fixture'}}))\n")
    audio = AudioControl(discovery=lambda: (devices, []), lab_command=[sys.executable, str(script)])
    try:
        job = audio.start_lab({"kind": "lab_fixture"})
        until(lambda: audio.job["status"] == "completed")
        view = audio.poll(job["id"], cursor=0)
        assert len(view["events"]) == 256 and view["events_reset"]
        assert view["room"]["status"] == "closed"
        assert audio.poll(job["id"], cursor=299)["events"][0]["sequence"] == 300
    finally:
        audio.close()


def session(events, participation="all", replies=True):
    audio = np.full(16000, .1, np.float32)
    from family_harness.live import REPLY

    return LiveSession(events.append, audio, 16000,
                       [{"end": .5, "text": REPLY[0]}, {"end": 1, "text": REPLY[1]}],
                       participation, replies=replies)


class DraftRecognizer:
    def accept(self, samples):
        return "draft words"

    def finish(self):
        return "final streaming words"

    def reset(self):
        pass


class Attributor:
    class Matcher:
        class Provider:
            backend, model_hash = "fake", "a"*64
        provider = Provider()
    matcher = Matcher()

    def identify(self, audio):
        return IdentityDecision("known", .8, .4, "matched"), "speaker-1"


def feed_turn(pipeline, start):
    for i in range(14):
        pipeline.accept(np.ones(1600, np.float32)*.1, start+i*.1, i < 6)


def test_live_final_and_identity_arrive_before_close_and_another_turn_can_follow():
    events = []
    room = session(events, "enrolled")
    pipeline = LivePipeline(room, DraftRecognizer(), None, Attributor(), VoiceSettings())
    try:
        feed_turn(pipeline, 0)
        until(lambda: any(t.status == "final" for t in room.manager.utterances.values()))
        turn = next(iter(room.manager.utterances.values()))
        assert turn.person_id == "known" and room.manager.status == "active"
        assert len(room.manager.responses) == 1
        feed_turn(pipeline, 2)
        until(lambda: sum(t.status == "final" for t in room.manager.utterances.values()) == 2)
        assert len(room.manager.responses) == 2
        assert any(e.get("kind") == "attribution" for e in events)
    finally:
        pipeline.close()


def test_heavy_final_cannot_delay_onset_output_stop_or_revive_closed_session():
    events, entered, release = [], threading.Event(), threading.Event()

    class BlockingFinal:
        def decode(self, audio):
            entered.set()
            release.wait(3)
            return "heavy final"

    room = session(events)
    room.apply("test_cue", 0, source="control")
    output = room.output
    pipeline = LivePipeline(room, DraftRecognizer(), BlockingFinal(), Attributor(), VoiceSettings())
    try:
        feed_turn(pipeline, .1)
        assert entered.wait(2)
        room.apply("speech_started", 2, {"start": 2})
        block = np.ones((160, 2), np.float32)
        room.write(block, 160, 2.03)
        assert output.stop_requested and not block.any()
        room.apply("session_closed", 3)
        release.set()
        until(lambda: not pipeline.analysis.qsize())
        assert all(r.status == "cancelled" for r in room.manager.responses.values())
        assert room.manager.status == "closed"
    finally:
        release.set()
        pipeline.close()


def test_heard_chunks_use_confirmed_clock_and_interrupted_remainder_stays_uncertain():
    room = session([])
    room.apply("test_cue", 0, source="control")
    block = np.empty((16000, 2), np.float32)
    room.write(block, 16000, 0)
    room.tick(.6, .6)
    response = next(iter(room.manager.responses.values()))
    assert response.heard_text and response.played_seconds == .6
    room.apply("speech_started", .7, {"start": .7})
    room.write(np.empty((160, 2), np.float32), 160, .73)
    room.tick(.75, .75)
    assert response.status == "cancelled" and response.playback_stopped
    assert response.heard_text != response.text


def test_final_delayed_across_new_speech_completes_history_without_outdated_reply():
    entered, release = threading.Event(), threading.Event()

    class SlowFinal:
        def decode(self, samples):
            entered.set()
            release.wait(2)
            return "older turn"

    room = session([])
    pipeline = LivePipeline(room, DraftRecognizer(), SlowFinal(), Attributor(), VoiceSettings())
    try:
        feed_turn(pipeline, 0)
        assert entered.wait(1)
        room.apply("speech_started", .8, {"start": .8})
        release.set()
        until(lambda: any(t.status == "final" for t in room.manager.utterances.values()))
        assert not room.manager.responses
        assert room.manager.counts["ignored_late_final_response"] == 1
    finally:
        release.set()
        pipeline.close()


def test_windowed_overlap_remains_unnamed_and_unknown_track_reconciles():
    class Provider:
        def embed(self, samples):
            return np.array([1, 0], np.float32)
    class Matcher:
        settings = MatchSettings()
        provider = Provider()
        def match_vector(self, vector):
            return IdentityDecision(None, .1, .08, "unknown")
    class Diarizer:
        overlap = False
        def segments(self, audio):
            return [SpeakerSegment(0, 1, "a")] + (
                [SpeakerSegment(.2, .8, "b")] if self.overlap else [])
    diarizer = Diarizer()
    attributor = IncrementalAttributor(diarizer, Matcher())
    audio = np.ones(16000, np.float32)*.1
    first, track = attributor.identify(audio)
    assert first.person_id is None and attributor.identify(audio)[1] == track
    diarizer.overlap = True
    decision, _ = attributor.identify(audio)
    assert decision.state == "overlap" and decision.person_id is None


def test_fixture_is_explicit_device_free_and_demonstrates_duplicate_and_closure():
    events = []
    report = fixture(events.append)
    assert report["counts"]["ignored_duplicate"] == 1
    assert report["counts"]["ignored_inactive"] == 1
    assert report["room"]["status"] == "closed"
    assert report["mode"] == "device-free fixture"


def test_short_interruption_cue_does_not_fabricate_a_human_turn():
    from family_harness.interruption_trial import TrialSession

    trial = TrialSession()
    assert not trial.manager.utterances
    assert trial.response_id in trial.manager.responses


def test_matching_tuning_is_not_a_permission_and_all_ranges_reach_worker(devices, tmp_path):
    audio = AudioControl(discovery=lambda: (devices, []))
    try:
        audio.refresh()
        audio._launch = lambda request, *args: request
        draft = defaults()
        draft["speech"].update(gain_db=12, vad_threshold=.3, silence=1.2)
        draft["interruption"].update(hold_seconds=.02, release_seconds=.5)
        draft["matching"].update(threshold=.2, margin=.04)
        request = audio.start_lab({"kind": "lab_live", "input_id": "mic", "output_id": "speaker",
                                  "echo_owner": "software", "speaker_confirmed": True,
                                  "echo_confirmed": True, "settings": draft})
        assert request["speech_settings"] == draft["speech"]
        assert request["recognition_policy"]["settings"] == draft["matching"]
        assert request["interruption_settings"] == draft["interruption"]
        assert not any("permission" in k for k in request)
    finally:
        audio.close()


def test_native_live_adapter_uses_simulated_frames_and_closes_devices(devices):
    from types import SimpleNamespace

    from conftest import FakeAudio

    from family_harness.interruptions import OnsetDetector
    from family_harness.live import capture_live

    class Vad:
        def accept(self, samples):
            return bool(np.max(np.abs(samples)) > .01)
        def reset(self):
            pass

    events = []
    room = session(events, replies=False)
    voice = SimpleNamespace(settings=VoiceSettings(processing=False))
    pipeline = LivePipeline(room, DraftRecognizer(), None, None, voice.settings)
    backend = FakeAudio()
    request = {"kind": "lab_live", "input_id": "mic", "output_id": "speaker",
               "endpoint_id": "fixture", "echo_owner": "device", "scenario": "speech",
               "seconds": 3}
    report = capture_live(request, devices, backend, voice, room, pipeline,
                          OnsetDetector(Vad()), events.append)
    assert report["audio_seconds"] >= 2.9
    assert all(stream.closed for stream in backend.streams)
    assert room.manager.status == "closed"
    assert events[-1]["microphone_on"] is False


def test_native_gap_aborts_take_and_releases_simulated_stream(devices):
    from types import SimpleNamespace

    from conftest import FakeAudio

    from family_harness.interruptions import OnsetDetector
    from family_harness.live import capture_live

    class Vad:
        def accept(self, samples):
            return False
        def reset(self):
            pass

    room = session([])
    voice = SimpleNamespace(settings=VoiceSettings(processing=False))
    pipeline = LivePipeline(room, DraftRecognizer(), None, None, voice.settings)
    backend = FakeAudio(gap_at=20)
    request = {"kind": "lab_live", "input_id": "mic", "output_id": "speaker",
               "endpoint_id": "fixture", "echo_owner": "device", "scenario": "integrated",
               "seconds": 3}
    with pytest.raises(SetupError):
        capture_live(request, devices, backend, voice, room, pipeline,
                     OnsetDetector(Vad()), lambda event: None)
    assert all(stream.closed for stream in backend.streams)
    assert room.manager.status == "closed"
