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
    ):
        self.discovery = discovery
        self.command = command or [sys.executable, "-m", "family_harness.audio_worker", "run"]
        self.voice_command = voice_command or [sys.executable, "-m", "family_harness.voice_worker"]
        self.models = ModelStore(models)
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
                        if not job["request"]["kind"].startswith("voice_"):
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
            return copy.deepcopy(self.job)

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
