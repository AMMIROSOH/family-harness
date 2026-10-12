"""Editable local recognition presets, independent of voice profiles and permissions."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

from family_harness import identity
from family_harness.errors import SetupError
from family_harness.identity import MatchSettings

DEFAULT_POLICIES = {
    "free": MatchSettings(threshold=0.2, margin=0.04),
    "balanced": MatchSettings(),
    "strict": MatchSettings(threshold=0.575, margin=0.08),
}


def policy_error(message):
    return SetupError(
        "recognition_policy_invalid", message,
        "Use similarity and ambiguity values from 0 to 1, and speech duration from "
        "0.5 to 5 seconds. For a damaged file, back it up, then run "
        "people policies reset-all with the same --policy-file. Audio is off.",
    )


def validate_name(name):
    if not isinstance(name, str) or name not in DEFAULT_POLICIES:
        raise ValueError("choose free, balanced or strict")


class RecognitionPolicies:
    def __init__(self, path: Path | None = None):
        self.path = path or identity.user_data_path(
            "FamilyHarness", appauthor=False
        ) / "recognition-policies.json"

    @staticmethod
    def defaults():
        return {"version": 1, "selected": "balanced",
                "policies": {name: asdict(settings) for name, settings in DEFAULT_POLICIES.items()}}

    def load(self):
        try:
            if not self.path.exists():
                return self.defaults()
            if self.path.stat().st_size > 16_384:
                raise ValueError("oversized policy file")
            data = json.loads(self.path.read_text("utf-8"))
            self.validate(data)
            return data
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise policy_error("The recognition policy file is damaged or unsupported.") from exc

    @staticmethod
    def validate(data):
        if (not isinstance(data, dict) or set(data) != {"version", "selected", "policies"}
                or type(data["version"]) is not int or data["version"] != 1
                or not isinstance(data["policies"], dict)
                or set(data["policies"]) != set(DEFAULT_POLICIES)):
            raise ValueError("unsupported recognition policies")
        validate_name(data["selected"])
        for settings in data["policies"].values():
            if not isinstance(settings, dict) or set(settings) != set(asdict(MatchSettings())):
                raise ValueError("invalid recognition policy settings")
            MatchSettings(**settings)

    def public(self):
        data = self.load()
        return {**data, "path": str(self.path),
                "active": self._snapshot(data),
                "defaults": {name: asdict(settings) for name, settings in DEFAULT_POLICIES.items()}}

    def snapshot(self, name=None, *, threshold=None, margin=None, minimum_seconds=None):
        return self._snapshot(self.load(), name, threshold=threshold, margin=margin,
                              minimum_seconds=minimum_seconds)

    @staticmethod
    def _snapshot(data, name=None, *, threshold=None, margin=None, minimum_seconds=None):
        name = data["selected"] if name is None else name
        validate_name(name)
        base = MatchSettings(**data["policies"][name])
        overrides = {key: value for key, value in (
            ("threshold", threshold), ("margin", margin), ("minimum_seconds", minimum_seconds)
        ) if value is not None}
        settings = replace(base, **overrides)
        return {"name": name, "settings": asdict(settings),
                "customized": base != DEFAULT_POLICIES[name], "overrides": sorted(overrides)}

    def select(self, name):
        validate_name(name)
        data = self.load()
        data["selected"] = name
        self._write(data)

    def update(self, name, *, select=False, **changes):
        validate_name(name)
        data = self.load()
        data["policies"][name] = asdict(replace(MatchSettings(**data["policies"][name]), **changes))
        if select:
            data["selected"] = name
        self._write(data)

    def reset(self, name):
        validate_name(name)
        self.update(name, **asdict(DEFAULT_POLICIES[name]))

    def reset_all(self):
        # Explicit recovery also works when the existing file cannot be read.
        self._write(self.defaults())

    def _write(self, data):
        self.validate(data)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4()}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(data, indent=2, allow_nan=False), "utf-8")
            temporary.replace(self.path)
        except OSError as exc:
            raise policy_error(
                "Recognition settings could not be saved; check folder permissions."
            ) from exc
        finally:
            temporary.unlink(missing_ok=True)
