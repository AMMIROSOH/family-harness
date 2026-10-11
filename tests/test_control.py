import json
import sys
import time

import pytest

from family_harness.control import AudioControl
from family_harness.errors import SetupError, audio_error


@pytest.fixture
def control(tmp_path, devices):
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import sys, time, json\nrequest = json.loads(sys.stdin.readline())\n"
        "event = {'type': 'progress', 'phase': 'microphone', 'seconds': 1, 'duration': 8}\n"
        "print(json.dumps(event), flush=True)\n"
        "time.sleep(60)\n"
    )
    audio = AudioControl(
        discovery=lambda: (devices, []), command=[sys.executable, str(worker)], lease_seconds=0.3
    )
    audio.refresh()
    yield audio
    audio.close()


def wait_until(predicate, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


def test_stop_terminates_audio_process(control, selection):
    job = control.start({**selection, "kind": "microphone"})
    process = control.process
    control.stop()
    assert process.poll() is not None
    assert control.poll(job["id"])["status"] == "cancelled"


def test_page_disconnect_automatically_stops(control, selection):
    control.start({**selection, "kind": "microphone"})
    wait_until(lambda: control.process.poll() is not None)
    assert control.job["status"] == "cancelled"
    assert "disconnected" in control.job["reason"]


def test_poll_keeps_test_alive_and_second_start_rejected(control, selection):
    job = control.start({**selection, "kind": "microphone"})
    with pytest.raises(SetupError) as error:
        control.start({**selection, "kind": "speaker"})
    assert error.value.code == "test_running"
    for _ in range(7):
        assert control.poll(job["id"])["status"] == "running"
        time.sleep(0.08)
    assert control.process.poll() is None


def test_duplex_requires_echo_confirmation(control, selection):
    with pytest.raises(SetupError) as error:
        control.start({**selection, "kind": "duplex", "echo_confirmed": False})
    assert error.value.code == "echo_owner_unconfirmed"
    assert control.process is None


def test_missing_device_rejected_before_process_start(control, selection):
    control.devices = []
    with pytest.raises(SetupError):
        control.start({**selection, "kind": "microphone"})
    assert control.process is None


def test_reconnect_requires_explicit_start_and_keeps_identity(control, selection):
    control.start({**selection, "kind": "microphone"})
    control.stop()
    original = control.devices[0].id
    control.refresh()
    assert control.process.poll() is not None
    assert control.devices[0].id == original
    control.start({**selection, "kind": "microphone"})
    assert control.process.poll() is None


def test_worker_failure_exposes_recovery(tmp_path, devices, selection):
    worker = tmp_path / "failed.py"
    worker.write_text("import sys\nsys.stdin.readline()\nsys.exit(1)\n")
    control = AudioControl(discovery=lambda: (devices, []), command=[sys.executable, str(worker)])
    try:
        control.refresh()
        control.start({**selection, "kind": "microphone"})
        wait_until(lambda: control.job["status"] != "running")
        assert control.job["status"] == "error"
        assert "permissions" in control.job["error"]["recovery"]
        assert not control.results
    finally:
        control.close()


def test_permission_denial_recovery_is_concrete():
    error = audio_error(PermissionError("access denied"))
    assert error.code == "permission_denied"
    assert "desktop apps" in error.recovery


def test_success_saves_only_completed_aggregate_results(tmp_path, devices, selection):
    worker = tmp_path / "complete.py"
    result = {"kind": "microphone", "status": "measured", "messages": []}
    worker.write_text(
        "import json,sys\nsys.stdin.readline()\nprint("
        + repr(json.dumps({"type": "result", "result": result}))
        + ",flush=True)\n"
    )
    control = AudioControl(discovery=lambda: (devices, []), command=[sys.executable, str(worker)])
    try:
        control.refresh()
        job = control.start({**selection, "kind": "microphone"})
        wait_until(lambda: control.job["status"] != "running")
        assert control.poll(job["id"])["status"] == "completed"
        assert len(control.diagnostics(selection)) == 1
        assert not control.diagnostics({**selection, "input_id": "different"})
    finally:
        control.close()


def test_voice_jobs_share_audio_exclusion_and_disconnect_cancellation(control, selection):
    control.voice_command = control.command
    job = control.start_voice({"kind": "voice_warm"})
    with pytest.raises(SetupError) as error:
        control.start({**selection, "kind": "speaker"})
    assert error.value.code == "test_running"
    with pytest.raises(SetupError):
        control.start_voice({"kind": "voice_remove"})
    wait_until(lambda: control.process.poll() is not None)
    assert control.job["status"] == "cancelled"
    assert control.poll(job["id"])["request"]["kind"] == "voice_warm"


def test_voice_trial_requires_selected_devices_and_volume_confirmation(control, selection):
    control.voice_command = control.command
    with pytest.raises(SetupError) as error:
        control.start_voice({**selection, "kind": "voice_trial", "speaker_confirmed": False})
    assert error.value.code == "speaker_unconfirmed"
    assert control.process is None
    control.devices = []
    with pytest.raises(SetupError):
        control.start_voice({**selection, "kind": "voice_trial"})
    assert control.process is None


def test_voice_transcript_is_ephemeral_and_never_added_to_room_diagnostics(
    tmp_path, devices, selection
):
    worker = tmp_path / "voice.py"
    transcript = {"type": "transcript", "text": "private", "revision": 2, "final": True}
    result = {"kind": "voice_trial", "transcript": "private", "status": "measured"}
    worker.write_text(
        "import json,sys\nsys.stdin.readline()\n"
        + f"print({json.dumps(json.dumps(transcript))}, flush=True)\n"
        + f"print({json.dumps(json.dumps({'type': 'result', 'result': result}))}, flush=True)\n"
    )
    control = AudioControl(
        discovery=lambda: (devices, []), voice_command=[sys.executable, str(worker)]
    )
    try:
        control.refresh()
        job = control.start_voice({**selection, "kind": "voice_trial"})
        wait_until(lambda: control.job["status"] != "running")
        assert control.poll(job["id"])["transcript"]["text"] == "private"
        assert control.job["status"] == "completed"
        assert not control.results and not control.diagnostics(selection)
    finally:
        control.close()
