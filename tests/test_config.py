import json

import pytest

from family_harness.config import ConfigStore
from family_harness.errors import SetupError


def test_local_names_and_stable_ids_survive_reopen(tmp_path, devices, selection):
    store = ConfigStore(tmp_path / "config" / "room.json")
    first = store.save(selection, devices, [])
    reopened = ConfigStore(store.path).load()
    assert reopened == first
    assert first["room_name"] == "اتاق"
    assert first["input"]["identity"] == "os-mic"
    assert "index" not in first["input"]
    second = store.save({**selection, "room_name": "Living room"}, devices, [])
    for field in ("room_id", "space_id", "endpoint_id"):
        assert first[field] == second[field]
    assert list(store.path.parent.iterdir()) == [store.path]


@pytest.mark.parametrize("text", [None, "", "   ", "x" * 121, 123])
def test_invalid_room_names_do_not_write(tmp_path, devices, selection, text):
    store = ConfigStore(tmp_path / "room.json")
    with pytest.raises(SetupError):
        store.save({**selection, "room_name": text}, devices, [])
    assert not store.path.exists()


def test_missing_selected_device_cannot_be_saved(tmp_path, devices, selection):
    store = ConfigStore(tmp_path / "room.json")
    with pytest.raises(SetupError):
        store.save(selection, devices[:1], [])
    assert not store.path.exists()


@pytest.mark.parametrize(
    "contents", ['{"schema_version": 9}', "broken", "[]", '{"schema_version": 1}']
)
def test_unreadable_configuration_is_preserved(tmp_path, devices, selection, contents):
    store = ConfigStore(tmp_path / "room.json")
    store.path.write_text(contents)
    with pytest.raises(SetupError) as error:
        store.save(selection, devices, [])
    assert error.value.code == "configuration_unreadable"
    assert store.path.read_text() == contents


def test_failed_atomic_replace_keeps_previous_file(tmp_path, devices, selection, monkeypatch):
    store = ConfigStore(tmp_path / "room.json")
    first = store.save(selection, devices, [])

    def deny(*args):
        raise PermissionError("denied")

    monkeypatch.setattr("family_harness.config.os.replace", deny)
    with pytest.raises(SetupError):
        store.save({**selection, "room_name": "New room"}, devices, [])
    assert json.loads(store.path.read_text(encoding="utf-8")) == first
    assert len(list(tmp_path.iterdir())) == 1
