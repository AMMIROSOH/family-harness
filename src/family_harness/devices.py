"""Native discovery; OS endpoint IDs are separate from transient PortAudio indices."""

from __future__ import annotations

import hashlib
import sys
from dataclasses import asdict, dataclass

from family_harness.errors import SetupError

RATES = (48000, 32000, 16000, 44100)


@dataclass(frozen=True)
class Device:
    id: str
    identity: str
    name: str
    direction: str
    index: int
    channels: int
    rates: tuple[int, ...]
    backend: str = "windows-wasapi"

    def public(self) -> dict:
        data = asdict(self)
        data.pop("index")
        return data

    def selection(self) -> dict:
        return {key: self.public()[key] for key in ("id", "identity", "name", "backend")}


def identify(identity: str, direction: str) -> str:
    return hashlib.sha256(f"windows-wasapi:{direction}:{identity}".encode()).hexdigest()[:24]


def map_devices(sd, endpoints: dict[str, list[tuple[str, str]]]) -> tuple[list[Device], list[str]]:
    """Never guess between two identically named OS endpoints or PortAudio devices."""
    apis = sd.query_hostapis()
    ports = sd.query_devices()
    devices = []
    warnings = []
    for direction, channel_key in (
        ("input", "max_input_channels"),
        ("output", "max_output_channels"),
    ):
        for name, identity in endpoints[direction]:
            matches = [
                (index, port)
                for index, port in enumerate(ports)
                if apis[port["hostapi"]]["name"] == "Windows WASAPI"
                and port["name"] == name
                and port[channel_key] > 0
            ]
            same_name = [item for item in endpoints[direction] if item[0] == name]
            if len(matches) != 1 or len(same_name) != 1:
                warnings.append(
                    f"Cannot safely identify {direction} device '{name}'. In Windows Sound "
                    "settings, give identical devices different names, then refresh."
                )
                continue
            index, port = matches[0]
            channels = 1 if direction == "input" else min(2, port[channel_key])
            supported = []
            check = sd.check_input_settings if direction == "input" else sd.check_output_settings
            for rate in RATES:
                try:
                    check(
                        device=index,
                        channels=channels,
                        dtype="float32",
                        samplerate=rate,
                        extra_settings=sd.WasapiSettings(auto_convert=True),
                    )
                except sd.PortAudioError:
                    continue
                supported.append(rate)
            if supported:
                devices.append(
                    Device(
                        identify(identity, direction),
                        identity,
                        name,
                        direction,
                        index,
                        channels,
                        tuple(supported),
                    )
                )
            else:
                warnings.append(
                    f"'{name}' has no usable audio format. Check Windows Sound settings."
                )
    return devices, warnings


def discover_native(sd=None) -> tuple[list[Device], list[str]]:
    if sys.platform != "win32":
        raise SetupError(
            "unsupported_os",
            "Native setup currently targets Windows WASAPI.",
            "Use Windows 10/11 x64. Other OS adapters have not been implemented.",
        )
    # Runs in a fresh child process, so hot-plug discovery cannot reuse PortAudio's cached list.
    import comtypes
    from pycaw.pycaw import AudioUtilities

    if sd is None:
        import sounddevice as sd
    comtypes.CoInitialize()
    try:
        endpoints = {
            direction: [
                (device.FriendlyName, device.id)
                for device in AudioUtilities.GetAllDevices(data_flow=flow, device_state=1)
                if device.FriendlyName
            ]
            for direction, flow in (("input", 1), ("output", 0))
        }
        return map_devices(sd, endpoints)
    finally:
        comtypes.CoUninitialize()


def resolve(devices: list[Device], device_id: str, direction: str) -> Device:
    matches = [
        device for device in devices if device.id == device_id and device.direction == direction
    ]
    if len(matches) != 1:
        raise SetupError(
            "device_missing",
            f"The selected {direction} device is missing or ambiguous.",
            "Reconnect it and refresh devices, or explicitly choose another device. "
            "Family Harness will not switch to another microphone automatically.",
        )
    return matches[0]
