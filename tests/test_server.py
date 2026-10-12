import http.client
import json
import threading

import pytest

from family_harness.config import ConfigStore
from family_harness.control import AudioControl
from family_harness.server import SetupServer, create_server


@pytest.fixture
def server(tmp_path, devices):
    audio = AudioControl(discovery=lambda: (devices, []))
    instance = SetupServer(("127.0.0.1", 0), ConfigStore(tmp_path / "room.json"), audio)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield instance
    instance.shutdown()
    instance.server_close()
    thread.join(timeout=3)


def request(server, path, body=None, headers=None, raw=None):
    connection = http.client.HTTPConnection(*server.server_address, timeout=5)
    supplied = {"Content-Type": "application/json", "X-Setup-Token": server.token}
    supplied.update(headers or {})
    if body is not None or raw is not None:
        data = raw if raw is not None else json.dumps(body)
        connection.request("POST", path, data, headers=supplied)
    else:
        connection.request("GET", path, headers=supplied)
    response = connection.getresponse()
    value = response.read()
    code, response_headers = response.status, dict(response.getheaders())
    connection.close()
    return code, response_headers, value


def test_page_and_discovery_never_start_audio(server):
    status, headers, body = request(server, "/")
    assert status == 200 and b"Room audio setup" in body
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert "microphone=()" in headers["Permissions-Policy"]
    assert request(server, "/api/devices")[0] == 200
    assert server.audio.process is None
    assert server.audio.job is None


@pytest.mark.parametrize("path", ["/app.js", "/style.css", "/api/state"])
def test_packaged_assets_and_state(server, path):
    assert request(server, path)[0] == 200


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://attacker.example"},
        {"Origin": "null"},
        {"Host": "attacker.example"},
        {"X-Setup-Token": "wrong"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
    ],
)
def test_cross_origin_or_unauthenticated_request_cannot_start_audio(server, selection, headers):
    status, _, _ = request(server, "/api/tests", {**selection, "kind": "microphone"}, headers)
    assert status == 403
    assert server.audio.process is None


def test_host_check_also_guards_read_routes(server):
    assert request(server, "/api/state", headers={"Host": "attacker.example"})[0] == 403


def test_people_route_is_authenticated_and_read_state_excludes_vectors(server):
    status, _, body = request(server, "/api/state")
    assert status == 200 and "people" in json.loads(body)
    assert "embedding" not in json.loads(body)["people"]
    assert request(server, "/api/people", {"kind": "people_enroll"},
                   headers={"X-Setup-Token": "wrong"})[0] == 403
    assert request(server, "/api/people", {"kind": "people_enroll", "name": "Name"})[0] == 400
    assert server.audio.process is None


def test_save_reload_does_not_start_audio(server, selection):
    assert request(server, "/api/devices")[0] == 200
    status, _, body = request(server, "/api/config", selection)
    assert status == 200
    saved = json.loads(body)["config"]
    assert saved["endpoint_id"] == server.audio.endpoint_id
    assert saved["room_name"] == "اتاق"
    assert saved["device_use"] == "room"
    assert server.audio.process is None
    state = json.loads(request(server, "/api/state")[2])
    assert state["config"] == saved


def test_save_revalidates_unplugged_device(server, devices, selection):
    request(server, "/api/devices")
    server.audio.discovery = lambda: (devices[:1], [])
    status, _, body = request(server, "/api/config", selection)
    assert status == 400
    assert json.loads(body)["error"]["code"] == "device_missing"
    assert server.store.load() is None


@pytest.mark.parametrize("body", ["[]", "null", "invalid-json", '{"kind": []}', '{"kind": {}}'])
def test_invalid_payload_is_rejected_without_audio(server, body):
    assert request(server, "/api/tests", raw=body)[0] == 400
    assert server.audio.process is None


def test_wrong_content_type_and_oversized_request(server):
    assert request(server, "/api/tests", {}, {"Content-Type": "text/plain"})[0] == 415
    assert request(server, "/api/tests", raw="x" * 17000)[0] == 413


def test_stop_is_safe_without_test(server):
    status, _, body = request(server, "/api/stop", {})
    assert status == 200 and json.loads(body)["status"] == "idle"


def test_occupied_port_falls_back_to_loopback(server, tmp_path, devices):
    another = create_server(
        server.server_address[1],
        tmp_path / "other.json",
        AudioControl(discovery=lambda: (devices, [])),
    )
    try:
        assert another.server_address[0] == "127.0.0.1"
        assert another.server_address[1] != server.server_address[1]
    finally:
        another.server_close()


def test_voice_catalog_is_visible_without_loading_models_or_audio(server, tmp_path):
    from family_harness.models import ModelStore

    server.audio.models = ModelStore(tmp_path / "models")
    state = json.loads(request(server, "/api/state")[2])
    assert state["voice"]["catalog"]["id"] == "english-cpu-v2"
    assert not state["voice"]["installed"]
    assert not server.audio.models.root.exists()
    assert server.audio.process is None


@pytest.mark.parametrize("kind", ["voice_install", "voice_trial", "voice_remove", "voice_import"])
def test_voice_actions_require_same_origin_and_token(server, kind):
    assert request(server, "/api/voice", {"kind": kind}, {"X-Setup-Token": "wrong"})[0] == 403
    assert (
        request(server, "/api/voice", {"kind": kind}, {"Origin": "https://attacker.example"})[0]
        == 403
    )
    assert server.audio.process is None


@pytest.mark.parametrize("body", [{"kind": []}, {"kind": "cloud"}, {"kind": "voice_import"}])
def test_invalid_voice_actions_do_not_start_a_worker(server, body):
    assert request(server, "/api/voice", body)[0] == 400
    assert server.audio.process is None
