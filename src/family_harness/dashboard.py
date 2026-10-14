"""Versioned local dashboard settings. Reading never creates files or loads models."""

from __future__ import annotations

import copy
import json
import math
import threading
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from family_harness.errors import SetupError
from family_harness.identity import DEFAULT_BACKEND, MatchSettings, speaker_catalog
from family_harness.interruptions import InterruptionSettings
from family_harness.speech import VOICE_PRESETS, VoiceSettings

RECOGNIZERS = ("zipformer", "parakeet-v2", "whisper-small-en")
SCENARIOS = ("integrated", "speech", "people", "interruptions", "quiet-playback")


def defaults(*, preset="room", recognizer="zipformer", backend=DEFAULT_BACKEND, policy=None):
    policy = policy or {"name": "balanced", "settings": asdict(MatchSettings())}
    return {"preset": preset, "recognizer": recognizer, "backend": backend,
            "speech": asdict(VOICE_PRESETS[preset]), "interruption": asdict(InterruptionSettings()),
            "recognition_name": policy["name"], "matching": policy["settings"],
            "participation": "all", "seconds": 60}


def validate_settings(value):
    expected = set(defaults())
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("use the complete supported settings object")
    if value["preset"] not in VOICE_PRESETS or value["recognizer"] not in RECOGNIZERS:
        raise ValueError("choose an available speech preset and final recognizer")
    speaker_catalog(value["backend"])
    if value["recognition_name"] not in ("free", "balanced", "strict"):
        raise ValueError("choose Free, Balanced or Strict")
    if value["participation"] not in ("all", "enrolled", "addressed"):
        raise ValueError("choose a supported participation rule")
    for group, cls in (("speech", VoiceSettings), ("interruption", InterruptionSettings),
                       ("matching", MatchSettings)):
        fields = asdict(cls())
        data = value[group]
        if not isinstance(data, dict) or set(data) != set(fields):
            raise ValueError(f"invalid {group} fields")
        for key, default in fields.items():
            item = data[key]
            if type(default) is bool:
                if type(item) is not bool:
                    raise ValueError(f"{key} must be boolean")
            elif type(default) in (int, float):
                if type(item) not in (int, float) or not math.isfinite(item):
                    raise ValueError(f"{key} must be a finite number")
            elif type(item) is not str:
                raise ValueError(f"{key} must be text")
        cls(**data)
    if type(value["seconds"]) is not int or not 10 <= value["seconds"] <= 180:
        raise ValueError("live tests last 10–180 seconds")
    return copy.deepcopy(value)


def settings_error(message):
    return SetupError("settings_invalid", message,
                      "Restore supported defaults or correct the highlighted values. "
                      "An active take keeps its original settings; audio has not started.")


class DashboardStore:
    def __init__(self, path: Path, initial: dict):
        self.path, self.initial = path, validate_settings(initial)
        self.lock = threading.RLock()

    def load(self):
        try:
            if not self.path.exists():
                return {"version": 1, "revision": 0, "settings": copy.deepcopy(self.initial),
                        "profiles": {}}
            if self.path.stat().st_size > 65536:
                raise ValueError("settings file is too large")
            data = json.loads(self.path.read_text("utf-8"))
            if (not isinstance(data, dict) or set(data) != {
                "version", "revision", "settings", "profiles"
            } or type(data["version"]) is not int or data["version"] != 1
                    or type(data["revision"]) is not int or data["revision"] < 0
                    or not isinstance(data["profiles"], dict) or len(data["profiles"]) > 12):
                raise ValueError("unsupported settings version")
            validate_settings(data["settings"])
            for name, settings in data["profiles"].items():
                self.validate_name(name)
                validate_settings(settings)
            return data
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise SetupError("settings_unreadable",
                             "Dashboard settings are damaged or unsupported.",
                             "Back up dashboard-settings.json beside your room configuration, "
                             "move it aside and reopen. Unknown versions are never overwritten.") \
                from exc

    @staticmethod
    def validate_name(name):
        if not isinstance(name, str) or not 0 < len(name.strip()) <= 80 or name != name.strip():
            raise ValueError("use a profile name of 1–80 characters")

    def public(self):
        return {**self.load(), "defaults": copy.deepcopy(self.initial),
                "presets": {k: asdict(v) for k, v in VOICE_PRESETS.items()},
                "recognizers": list(RECOGNIZERS), "scenarios": list(SCENARIOS),
                "speaker_backends": self._backends()}

    @staticmethod
    def _backends():
        from importlib.resources import files

        catalog = json.loads(files("family_harness").joinpath("speaker_catalog.json")
                             .read_text("utf-8"))
        return list(catalog["profiles"])

    def save(self, request):
        with self.lock:
            data = self.load()
            if type(request.get("revision")) is not int or request["revision"] != data["revision"]:
                raise SetupError("settings_conflict", "Another tab saved newer settings.",
                                 "Reload saved settings, review your draft, then save again.")
            try:
                settings = validate_settings(request["settings"])
                name = request.get("name")
                if name is not None:
                    self.validate_name(name)
                    if name not in data["profiles"] and len(data["profiles"]) >= 12:
                        raise ValueError("at most twelve named profiles can be saved")
                    data["profiles"][name] = settings
                data["settings"] = settings
                data["revision"] += 1
            except (ValueError, TypeError, KeyError) as exc:
                raise settings_error(str(exc)) from exc
            temporary = self.path.with_name(f".{self.path.name}.{uuid4()}.tmp")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), "utf-8")
                temporary.replace(self.path)
            except OSError as exc:
                raise settings_error(
                    "Settings could not be saved; check folder access/disk space.",
                ) from exc
            finally:
                temporary.unlink(missing_ok=True)
            return self.public()


def worker_settings(request):
    return VoiceSettings(**request["speech_settings"]) if "speech_settings" in request \
        else VOICE_PRESETS[request.get("preset", "room")]
