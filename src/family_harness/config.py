"""Versioned, atomic local room configuration. No recordings are persisted."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

from platformdirs import user_config_path

from family_harness.devices import resolve
from family_harness.errors import SetupError


def default_config_path() -> Path:
    return user_config_path("FamilyHarness", appauthor=False) / "room.json"


def text_field(data: dict, key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 120:
        raise SetupError(
            "invalid_configuration",
            f"Enter a {key.replace('_', ' ')} (1–120 characters).",
            "Use a short name; local names and Farsi text are supported.",
        )
    return value.strip()


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("schema_version") != 1:
                raise ValueError("schema")
            for key in ("space_name", "room_name", "space_id", "room_id", "endpoint_id"):
                text_field(data, key)
            for key in ("input", "output"):
                if not isinstance(data.get(key), dict):
                    raise ValueError("selection")
                for field in ("id", "identity", "name", "backend"):
                    text_field(data[key], field)
            if data.get("echo_owner") not in ("software", "device"):
                raise ValueError("echo owner")
            return data
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError, SetupError) as exc:
            raise SetupError(
                "configuration_unreadable",
                "The saved room configuration cannot be read.",
                f"Back up {self.path}, move it aside, then reopen setup to create a room. "
                "Unknown configuration versions are never overwritten.",
            ) from exc

    def save(
        self, data: dict, devices: list, diagnostics: list[dict], endpoint_id: str | None = None
    ) -> dict:
        previous = self.load()
        echo_owner = data.get("echo_owner")
        if echo_owner not in ("software", "device"):
            raise SetupError(
                "invalid_configuration",
                "Choose who removes speaker echo.",
                "Use Family Harness, or choose the device only if its echo "
                "cancellation is enabled and confirmed by its documentation.",
            )
        device_use = data.get("device_use", "room")
        if device_use not in ("room", "headset", "conference"):
            raise SetupError(
                "invalid_configuration",
                "Choose the intended microphone use.",
                "Select a shared room, personal headset, or conference device.",
            )
        microphone = resolve(devices, data.get("input_id"), "input")
        speaker = resolve(devices, data.get("output_id"), "output")
        value = {
            "schema_version": 1,
            "space_id": previous["space_id"] if previous else str(uuid4()),
            "room_id": previous["room_id"] if previous else str(uuid4()),
            "endpoint_id": previous["endpoint_id"] if previous else endpoint_id or str(uuid4()),
            "space_name": text_field(data, "space_name"),
            "room_name": text_field(data, "room_name"),
            "connection": "host",
            "playback_location": "host",
            "device_use": device_use,
            "input": microphone.selection(),
            "output": speaker.selection(),
            "echo_owner": echo_owner,
            "speaker_confirmed": data.get("speaker_confirmed") is True,
            "diagnostics": diagnostics,
        }
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=".room-",
                suffix=".tmp",
                delete=False,
            ) as file:
                temporary = file.name
                json.dump(value, file, ensure_ascii=False, indent=2, allow_nan=False)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            raise SetupError(
                "configuration_not_saved",
                "The room configuration could not be saved.",
                f"Check write access and free space for {self.path.parent}, then retry.",
            ) from exc
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        return value
