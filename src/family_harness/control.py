"""Supervise explicit, cancellable audio jobs and fresh native discovery."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from family_harness.devices import Device, resolve
from family_harness.errors import SetupError
from family_harness.models import ModelStore

TEST_SECONDS = {"microphone": 8, "noise": 5, "speaker": 3, "duplex": 12}
LEASE_SECONDS = 3


def child_options() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


def discover() -> tuple[list[Device], list[str]]:
    try:
        child = subprocess.run(
            [sys.executable, "-m", "family_harness.audio_worker", "discover"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            **child_options(),
        )
        data = json.loads(child.stdout)
        if "error" in data:
            raise SetupError(**data["error"])
        if child.returncode:
            raise ValueError("worker exited")
        return [Device(**device, index=-1) for device in data["devices"]], data["warnings"]
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise SetupError(
            "discovery_failed",
            "Audio devices could not be discovered.",
            "Check the installation and Windows Sound settings, then refresh devices. "
            "No recording has started.",
        ) from exc


class AudioControl:
    def __init__(
        self,
        discovery: Callable = discover,
        command: list[str] | None = None,
        lease_seconds: float = LEASE_SECONDS,
        models: Path | None = None,
        voice_command: list[str] | None = None,
        recognizer: str = "zipformer",
        preset: str = "room",
        people: Path | None = None,
        speaker_backend: str | None = None,
        people_command: list[str] | None = None,
        policy_file: Path | None = None,
    ):
        self.discovery = discovery
        self.command = command or [sys.executable, "-m", "family_harness.audio_worker", "run"]
        self.voice_command = voice_command or [sys.executable, "-m", "family_harness.voice_worker"]
        self.models = ModelStore(models)
        from family_harness.identity import DEFAULT_BACKEND, PeopleStore, speaker_catalog

        self.people = PeopleStore(people)
        from family_harness.recognition_policy import RecognitionPolicies

        self.recognition_policies = RecognitionPolicies(policy_file)
        self.speaker_backend = speaker_backend or DEFAULT_BACKEND
        speaker_catalog(self.speaker_backend)
        self.people_command = people_command or [
            sys.executable, "-m", "family_harness.people_worker",
        ]
        if recognizer not in ("zipformer", "parakeet-v2", "whisper-small-en"):
            raise ValueError("unsupported local final recognizer")
        self.recognizer = recognizer
        from family_harness.speech import VOICE_PRESETS

        if preset not in VOICE_PRESETS:
            raise ValueError("unsupported microphone processing preset")
        self.preset = preset
        self.lease_seconds = lease_seconds
        self.lock = threading.RLock()
        self.devices: list[Device] = []
        self.endpoint_id = str(uuid4())
        self.warnings: list[str] = []
        self.job: dict | None = None
        self.process: subprocess.Popen | None = None
        self.results: list[dict] = []
        self.closed = threading.Event()
        self.touched = 0.0
        self.deadline = 0.0
        self.reader: threading.Thread | None = None
        self.watchdog = threading.Thread(
            target=self._watch, name="audio-test-watchdog", daemon=True
        )
        self.watchdog.start()

    def refresh(self) -> dict:
        with self.lock:
            if self.job and self.job["status"] == "running":
                raise SetupError(
                    "test_running",
                    "Stop the current test before refreshing devices.",
                    "Use Stop / mute, then refresh.",
                )
            devices, warnings = self.discovery()
            self.devices, self.warnings = devices, warnings
            return {"devices": [device.public() for device in devices], "warnings": warnings}

    def voice_status(self) -> dict:
        result = self.models.status()
        result["final_recognizer"] = self.recognizer
        result["speech_preset"] = self.preset
        if self.recognizer != "zipformer":
            from family_harness.asr import recognizer_store

            result["final_recognizer_state"] = recognizer_store(
                self.recognizer, self.models.root,
            ).status()
        return result

    def people_status(self) -> dict:
        from family_harness.identity import segmentation_store, speaker_store

        policies = self.recognition_policies.public()
        return {"people": self.people.public(), "path": str(self.people.path),
                "backend": self.speaker_backend,
                "recognition_policies": policies,
                "recognition_policy": policies["active"],
                "matching_settings": policies["active"]["settings"],
                "speaker_model": speaker_store(self.speaker_backend, self.models.root).status(),
                "segmentation_model": segmentation_store(self.models.root).status()}

    def save_recognition_policy(self, data: dict) -> dict:
        from family_harness.identity import MatchSettings
        from family_harness.recognition_policy import policy_error

        with self.lock:
            if self.closed.is_set() or (self.job and self.job["status"] == "running"):
                raise SetupError(
                    "test_running", "Stop the current operation before editing policies.",
                    "Use Stop, then save recognition settings.",
                )
            try:
                if data.get("action") == "save":
                    settings = data["settings"]
                    if not isinstance(settings, dict) or set(settings) != {
                        "threshold", "margin", "minimum_seconds"
                    }:
                        raise ValueError("invalid policy settings")
                    MatchSettings(**settings)
                    self.recognition_policies.update(data["name"], select=True, **settings)
                elif data.get("action") == "reset":
                    self.recognition_policies.reset(data["name"])
                else:
                    raise ValueError("invalid policy action")
            except (ValueError, TypeError, KeyError) as exc:
                raise policy_error("Choose a valid recognition preset and settings.") from exc
            return self.recognition_policies.public()

    def start_people(self, data: dict) -> dict:
        from family_harness.identity import VoiceProfile

        kind = data.get("kind")
        with self.lock:
            if self.closed.is_set():
                raise SetupError("setup_closed", "Setup is shutting down.", "Reopen setup.")
            if self.job and self.job["status"] == "running":
                raise SetupError("test_running", "Another setup operation is running.",
                                 "Use Stop before changing people or starting a trial.")
            if kind == "people_save":
                if (not self.job or self.job["id"] != data.get("job_id")
                        or self.job["status"] != "completed"
                        or self.job["request"]["kind"] != "people_enroll"
                        or not self.job.get("result", {}).get("candidate")):
                    raise SetupError("enrollment_missing", "This enrollment take is unavailable.",
                                     "Record the three phrases again before saving.")
                self.people.save(VoiceProfile(**self.job["result"]["candidate"]))
                self.job["result"].pop("candidate")
                self.job["result"]["saved"] = True
                return {"status": "saved"}
            if kind == "people_remove":
                try:
                    self.people.remove(data.get("person_id", ""))
                except (ValueError, TypeError, AttributeError) as exc:
                    raise SetupError("invalid_person", "Choose an enrolled person.",
                                     "Refresh setup and retry removal.") from exc
                return {"status": "removed"}
            if kind not in ("speaker_install", "speaker_remove", "segmentation_install",
                            "people_enroll", "people_trial"):
                raise SetupError("invalid_people_action", "Choose an available people action.",
                                 "Use the buttons in the people section.")
            request = {"kind": kind, "backend": self.speaker_backend,
                       "models": str(self.models.root), "people": str(self.people.path)}
            source = data.get("source")
            if source:
                if not isinstance(source, str) or len(source) > 4096:
                    raise SetupError("invalid_import", "Enter a local model folder.",
                                     "Use a folder on this PC with the pinned catalog files.")
                request["source"] = source
            if kind in ("people_enroll", "people_trial"):
                resolve(self.devices, data.get("input_id"), "input")
                request.update(input_id=data["input_id"], endpoint_id=self.endpoint_id)
            if kind == "people_enroll":
                name = data.get("name")
                if (not isinstance(name, str) or not 0 < len(name.strip()) <= 120
                        or data.get("consent") is not True):
                    raise SetupError(
                        "enrollment_consent", "Name the person and confirm consent.",
                        "The person should agree to a local voice profile before recording.",
                    )
                request["name"] = name.strip()
            if kind == "people_trial":
                policy = data.get("participation", "all")
                if policy not in ("all", "enrolled", "addressed"):
                    raise SetupError("participation_invalid", "Choose a participation policy.",
                                     "Use the participation selector.")
                request.update(participation=policy, recognizer=self.recognizer)
                # Freeze the saved settings for this job, including cross-process CLI edits.
                request["recognition_policy"] = self.recognition_policies.snapshot()
            return self._launch(request, self.people_command, 18 if kind == "people_enroll" else 30,
                                600 if kind.endswith("install") else 180)

    def start(self, data: dict) -> dict:
        kind = data.get("kind")
        if not isinstance(kind, str) or kind not in TEST_SECONDS:
            raise SetupError(
                "invalid_test",
                "Choose a microphone, speaker, noise, or duplex test.",
                "Use a test button in the setup page.",
            )
        owner = data.get("echo_owner", "software")
        if owner not in ("software", "device"):
            raise SetupError(
                "invalid_test",
                "Choose a single echo cancellation owner.",
                "Select Family Harness or your device's own echo cancellation.",
            )
        if kind == "duplex" and data.get("echo_confirmed") is not True:
            raise SetupError(
                "echo_owner_unconfirmed",
                "Confirm only one echo remover is enabled.",
                "Check Windows and device settings, then confirm in the setup page.",
            )
        position = data.get("position", "near")
        if position not in ("near", "far"):
            raise SetupError(
                "invalid_test",
                "Choose a nearby or farthest speaking position.",
                "Use the placement selector in the setup page.",
            )
        with self.lock:
            if self.closed.is_set():
                raise SetupError(
                    "setup_closed", "Setup is shutting down.", "Reopen setup to test audio."
                )
            if self.job and self.job["status"] == "running":
                raise SetupError(
                    "test_running",
                    "An audio test is already running.",
                    "Use Stop / mute before starting another test.",
                )
            if kind != "speaker":
                resolve(self.devices, data.get("input_id"), "input")
            if kind in ("speaker", "duplex"):
                resolve(self.devices, data.get("output_id"), "output")
            request = {
                "kind": kind,
                "input_id": data.get("input_id"),
                "output_id": data.get("output_id"),
                "echo_owner": owner,
                "position": position,
                "endpoint_id": self.endpoint_id,
            }
            return self._launch(request, self.command, TEST_SECONDS[kind], TEST_SECONDS[kind] + 20)

    def start_voice(self, data: dict) -> dict:
        kind = data.get("kind")
        if kind not in (
            "voice_install",
            "voice_import",
            "voice_remove",
            "voice_warm",
            "voice_trial",
        ):
            raise SetupError(
                "invalid_voice_action",
                "Choose an available voice profile action.",
                "Use a button in the voice profile section.",
            )
        with self.lock:
            if self.closed.is_set():
                raise SetupError("setup_closed", "Setup is shutting down.", "Reopen setup.")
            if self.job and self.job["status"] == "running":
                raise SetupError(
                    "test_running",
                    "Another setup operation is running.",
                    "Use Stop before starting another operation.",
                )
            request = {"kind": kind, "models": str(self.models.root)}
            if self.recognizer != "zipformer" and kind in ("voice_warm", "voice_trial"):
                request["recognizer"] = self.recognizer
            if self.preset != "room" and kind in ("voice_warm", "voice_trial"):
                request["preset"] = self.preset
            if kind == "voice_import":
                source = data.get("source")
                if not isinstance(source, str) or not source.strip() or len(source) > 4096:
                    raise SetupError(
                        "invalid_import",
                        "Enter the local model folder path.",
                        "Use a folder on this PC containing the catalog files.",
                    )
                request["source"] = source
            if kind == "voice_trial":
                resolve(self.devices, data.get("input_id"), "input")
                resolve(self.devices, data.get("output_id"), "output")
                if data.get("speaker_confirmed") is not True:
                    raise SetupError(
                        "speaker_unconfirmed",
                        "Check the speaker volume first.",
                        "Run Test speaker and confirm it was comfortable.",
                    )
                request.update(
                    {
                        "input_id": data["input_id"],
                        "output_id": data["output_id"],
                        "endpoint_id": self.endpoint_id,
                    }
                )
            return self._launch(
                request,
                self.voice_command,
                20,
                600 if kind in ("voice_install", "voice_import") else 120,
            )

    def _launch(self, request: dict, command: list[str], duration: int, timeout: int) -> dict:
        with self.lock:
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    bufsize=1,
                    **child_options(),
                )
                process.stdin.write(json.dumps(request) + "\n")
                process.stdin.flush()
                process.stdin.close()
            except (OSError, BrokenPipeError) as exc:
                if "process" in locals():
                    process.kill()
                    process.wait()
                raise SetupError(
                    "test_start_failed",
                    "The setup operation could not start.",
                    "Check the installation and try again.",
                ) from exc
            self.process = process
            self.job = {
                "id": str(uuid4()),
                "status": "running",
                "request": request,
                "progress": {
                    "phase": "starting",
                    "seconds": 0,
                    "duration": duration,
                    "level": 0,
                },
            }
            self.touched = time.monotonic()
            self.deadline = self.touched + timeout
            job = self.job
            self.reader = threading.Thread(
                target=self._read, args=(process, job), name="audio-test-results", daemon=True
            )
            self.reader.start()
            return copy.deepcopy(job)

    def _read(self, process: subprocess.Popen, job: dict) -> None:
        try:
            for line in process.stdout:
                event = json.loads(line)
                with self.lock:
                    if job["status"] != "running":
                        continue
                    if event.get("type") == "progress":
                        job["progress"].update(event)
                    elif event.get("type") == "transcript":
                        job["transcript"] = event
                    elif event.get("type") == "turn_candidate":
                        job["candidate"] = event
                    elif event.get("type") == "result":
                        job["result"] = event["result"]
                    elif event.get("type") == "error":
                        job["error"] = event["error"]
            code = process.wait()
            with self.lock:
                if job["status"] == "running":
                    if code == 0 and "result" in job and "error" not in job:
                        job["status"] = "completed"
                        result = copy.deepcopy(job["result"])
                        result["selection"] = job["request"]
                        result["tested_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                        if job["request"]["kind"] in TEST_SECONDS:
                            self.results.append(result)
                            self.results = self.results[-20:]
                    else:
                        job["status"] = "error"
                        job.setdefault(
                            "error",
                            {
                                "code": "audio_worker_failed",
                                "message": "The audio test stopped unexpectedly.",
                                "recovery": "Reconnect the device, check microphone permissions, "
                                "close other audio apps, and retry.",
                            },
                        )
        except (ValueError, OSError):
            with self.lock:
                if self.job is job:
                    self._stop_locked(
                        "The audio test returned invalid data; check the installation."
                    )
        finally:
            process.stdout.close()

    def poll(self, job_id: str) -> dict:
        with self.lock:
            if not self.job or job_id != self.job["id"]:
                raise SetupError(
                    "unknown_test",
                    "This test is no longer available.",
                    "Refresh setup and explicitly start another test.",
                )
            self.touched = time.monotonic()
            public = copy.deepcopy(self.job)
            if "result" in public:
                public["result"].pop("candidate", None)
            return public

    def _stop_locked(self, reason: str) -> None:
        if self.job and self.job["status"] == "running":
            self.job["status"] = "cancelled"
            self.job["reason"] = reason
            if self.process and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=1)

    def stop(self) -> dict:
        with self.lock:
            self._stop_locked("Stopped. Microphone and speaker are released.")
            if self.job and "result" in self.job:
                self.job["result"].pop("candidate", None)
            return copy.deepcopy(self.job) if self.job else {"status": "idle"}

    def diagnostics(self, data: dict) -> list[dict]:
        with self.lock:
            return copy.deepcopy(
                [
                    result
                    for result in self.results
                    if all(
                        result["selection"].get(key) == data.get(key)
                        for key in ("input_id", "output_id", "echo_owner")
                    )
                ]
            )

    def _watch(self) -> None:
        while not self.closed.wait(0.1):
            with self.lock:
                if self.job and self.job["status"] == "running":
                    now = time.monotonic()
                    if now - self.touched > self.lease_seconds:
                        self._stop_locked("Stopped because the setup page disconnected.")
                    elif now > self.deadline:
                        self._stop_locked("Stopped because the bounded test timed out.")

    def close(self) -> None:
        self.closed.set()
        self.stop()
        self.watchdog.join(timeout=2)
        if self.reader:
            self.reader.join(timeout=2)
