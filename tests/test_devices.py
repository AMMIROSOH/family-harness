from types import SimpleNamespace

import pytest

from family_harness.devices import identify, map_devices, resolve
from family_harness.errors import SetupError


def backend(names):
    return SimpleNamespace(
        query_devices=lambda: [
            {"name": name, "hostapi": 0, "max_input_channels": 1, "max_output_channels": 2}
            for name in names
        ],
        query_hostapis=lambda: [{"name": "Windows WASAPI"}],
        check_input_settings=lambda **kwargs: None,
        check_output_settings=lambda **kwargs: None,
        WasapiSettings=lambda **kwargs: kwargs,
        PortAudioError=RuntimeError,
    )


def test_device_reordering_preserves_identity():
    endpoints = {"input": [("Microphone", "guid-mic")], "output": [("Speaker", "guid-spk")]}
    first, _ = map_devices(backend(["Microphone", "Speaker"]), endpoints)
    second, _ = map_devices(backend(["Speaker", "Microphone"]), endpoints)
    assert first[0].id == second[0].id
    assert first[0].index != second[0].index
    assert "index" not in first[0].public()
    assert "index" not in first[0].selection()


def test_same_name_replacement_does_not_inherit_room():
    assert identify("old-guid", "input") != identify("new-guid", "input")
    assert identify("old-guid", "input") != identify("old-guid", "output")


@pytest.mark.parametrize(
    "ports,endpoints",
    [
        (["Microphone", "Microphone"], [("Microphone", "id1")]),
        (["Microphone"], [("Microphone", "id1"), ("Microphone", "id2")]),
    ],
)
def test_ambiguous_devices_are_not_guessed(ports, endpoints):
    devices, warnings = map_devices(backend(ports), {"input": endpoints, "output": []})
    assert not devices
    assert "different names" in warnings[0]


def test_missing_device_does_not_default(devices):
    with pytest.raises(SetupError, match="missing") as error:
        resolve(devices, "unplugged", "input")
    assert error.value.code == "device_missing"
    assert "not switch" in error.value.recovery


def test_input_cannot_resolve_as_output(devices):
    with pytest.raises(SetupError):
        resolve(devices, "mic", "output")
