"""Loopback-only setup control. Cross-origin requests cannot start audio."""

from __future__ import annotations

import errno
import json
import secrets
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from family_harness.config import ConfigStore, default_config_path
from family_harness.control import AudioControl
from family_harness.dashboard import DashboardStore, defaults
from family_harness.errors import SetupError

MAX_BODY = 16_384


class SetupServer(ThreadingHTTPServer):
    daemon_threads = True
    # SO_REUSEADDR permits a second listener to hijack an occupied port on Windows.
    allow_reuse_address = False

    def __init__(self, address: tuple, store: ConfigStore, audio: AudioControl, *, overrides=None):
        self.store = store
        self.audio = audio
        self.dashboard = DashboardStore(store.path.with_name("dashboard-settings.json"), defaults(
            preset=audio.preset, recognizer=audio.recognizer, backend=audio.speaker_backend,
            policy=audio.recognition_policies.snapshot(),
        ))
        self.launch_overrides = overrides or {}
        settings = self.dashboard_state()["settings"]
        audio.preset, audio.recognizer, audio.speaker_backend = (
            settings["preset"], settings["recognizer"], settings["backend"],
        )
        self.token = secrets.token_urlsafe(32)
        self.save_lock = threading.Lock()
        super().__init__(address, SetupHandler)
        port = self.server_address[1]
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.origins = {f"http://{host}" for host in self.hosts}

    def dashboard_state(self):
        from dataclasses import asdict

        from family_harness.speech import VOICE_PRESETS

        state = self.dashboard.public()
        # The existing CLI/UI policy file remains the canonical saved recognition choice.
        policy = self.audio.recognition_policies.snapshot()
        state["settings"].update(recognition_name=policy["name"], matching=policy["settings"])
        state["settings"].update(self.launch_overrides)
        if "preset" in self.launch_overrides:
            state["settings"]["speech"] = asdict(VOICE_PRESETS[self.launch_overrides["preset"]])
        return state

    def server_close(self):
        self.audio.close()
        super().server_close()


class SetupHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, format, *args):
        pass  # No room names, requests, or personal data in HTTP logs.

    def reply(self, code: int, data, content_type: str = "application/json") -> None:
        body = (
            json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
            if (content_type == "application/json")
            else data
        )
        self.send_response(code)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; "
            "style-src 'self'; connect-src 'self'; img-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        self.send_header("Permissions-Policy", "microphone=(), camera=(), geolocation=()")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def trusted(self) -> bool:
        return (
            self.headers.get("Host") in self.server.hosts
            and self.headers.get("Origin", "") in self.server.origins | {""}
            and self.headers.get("Sec-Fetch-Site", "") not in ("cross-site", "same-site")
        )

    def do_GET(self):
        if not self.trusted():
            self.reply(403, {"error": "Use the localhost setup address printed by the launcher."})
            return
        url = urlsplit(self.path)
        assets = {
            "/": ("index.html", "text/html"),
            "/app.js": ("app.js", "text/javascript"),
            "/style.css": ("style.css", "text/css"),
            "/dashboard.js": ("dashboard.js", "text/javascript"),
        }
        try:
            if url.path in assets:
                name, content_type = assets[url.path]
                self.reply(
                    200, files("family_harness").joinpath("web", name).read_bytes(), content_type
                )
            elif url.path == "/api/state":
                config = self.server.store.load()
                if config:
                    self.server.audio.endpoint_id = config["endpoint_id"]
                self.reply(
                    200,
                    {
                        "token": self.server.token,
                        "config": config,
                        "config_path": str(self.server.store.path),
                        "devices": [d.public() for d in self.server.audio.devices],
                        "voice": self.server.audio.voice_status(),
                        "people": self.server.audio.people_status(),
                        "dashboard": self.server.dashboard_state(),
                        "job": self.server.audio.poll(
                            self.server.audio.job["id"],
                            controller=self.headers.get("X-Controller-ID"),
                            renew_legacy=False,
                        ) if self.server.audio.job else None,
                    },
                )
            elif url.path == "/api/devices":
                self.reply(200, self.server.audio.refresh())
            elif url.path == "/api/job":
                if not secrets.compare_digest(
                    self.headers.get("X-Setup-Token", ""), self.server.token
                ):
                    self.reply(403, {"error": "Reopen setup to control audio."})
                    return
                job_id = parse_qs(url.query).get("id", [""])[0]
                query = parse_qs(url.query)
                cursor = query.get("cursor", [None])[0]
                if cursor is not None and (not cursor.isdigit() or len(cursor) > 10):
                    self.reply(400, {"error": "Use a nonnegative event cursor."})
                    return
                self.reply(200, self.server.audio.poll(
                    job_id, controller=self.headers.get("X-Controller-ID"),
                    cursor=int(cursor) if cursor is not None else None,
                    renew_legacy=False,
                ))
            else:
                self.reply(404, {"error": "Page not found."})
        except SetupError as exc:
            self.reply(400, {"error": exc.as_dict()})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.reply(400, {"error": "Invalid setup request length."})
            return
        if not 0 < length <= MAX_BODY:
            # Drain small rejected bodies so Windows does not reset the connection before
            # delivering the response. Larger bodies are never buffered or parsed.
            if 0 < length <= MAX_BODY * 4:
                self.rfile.read(length)
            self.reply(413, {"error": "The setup request is too large or empty."})
            if length > MAX_BODY * 4:
                self.connection.shutdown(socket.SHUT_WR)
            return
        body = self.rfile.read(length)
        if not self.trusted() or not secrets.compare_digest(
            self.headers.get("X-Setup-Token", ""), self.server.token
        ):
            self.reply(403, {"error": "Reopen the localhost setup page to control audio."})
            return
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self.reply(415, {"error": "Use JSON from the setup page."})
            return
        try:
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError("object required")
        except (ValueError, UnicodeDecodeError):
            self.reply(400, {"error": "Invalid setup request."})
            return
        try:
            path = urlsplit(self.path).path
            # Page-created IDs are volatile and never become saved settings or diagnostics.
            if self.headers.get("X-Controller-ID"):
                data["_controller"] = self.headers["X-Controller-ID"]
            if path == "/api/tests":
                self.reply(200, self.server.audio.start(data))
            elif path == "/api/voice":
                self.reply(200, self.server.audio.start_voice(data))
            elif path == "/api/people":
                self.reply(200, self.server.audio.start_people(data))
            elif path == "/api/interruptions":
                self.reply(200, self.server.audio.start_interruption(data))
            elif path == "/api/lab":
                config = self.server.store.load()
                data["room_id"] = config["room_id"] if config else "unsaved-room"
                self.reply(200, self.server.audio.start_lab(data))
            elif path == "/api/heartbeat":
                self.reply(200, self.server.audio.heartbeat(data.get("id"),
                                                          data.get("_controller")))
            elif path == "/api/settings":
                with self.server.audio.lock:
                    if self.server.audio.job and self.server.audio.job["status"] == "running":
                        raise SetupError("test_running", "Stop before saving operational settings.",
                                         "Edit a draft during a take; save it after Stop.")
                    state = self.server.dashboard.save(data)
                    self.server.launch_overrides = {}
                    settings = state["settings"]
                    try:
                        self.server.audio.recognition_policies.update(
                            settings["recognition_name"], select=True, **settings["matching"],
                        )
                    except SetupError as exc:
                        raise SetupError("recognition_save_failed",
                                         "Dashboard saved, but voice policy could not save.",
                                         "Fix the policy folder permissions, reload saved settings "
                                         "and retry. No running take was changed.") from exc
                    self.server.audio.preset = settings["preset"]
                    self.server.audio.recognizer = settings["recognizer"]
                    self.server.audio.speaker_backend = settings["backend"]
                    self.reply(200, state)
            elif path == "/api/recognition-policies":
                self.reply(200, self.server.audio.save_recognition_policy(data))
            elif path == "/api/stop":
                self.reply(200, self.server.audio.stop())
            elif path == "/api/config":
                with self.server.save_lock, self.server.audio.lock:
                    # Fresh discovery revalidates missing devices before every save.
                    self.server.audio.refresh()
                    diagnostics = self.server.audio.diagnostics(data)
                    old = self.server.store.load()
                    if (
                        old
                        and all(
                            old[key]["id"] == data.get(f"{key}_id") for key in ("input", "output")
                        )
                        and old["echo_owner"] == data.get("echo_owner")
                    ):
                        prior = [
                            item for item in old.get("diagnostics", []) if item not in diagnostics
                        ]
                        diagnostics = (prior + diagnostics)[-20:]
                    saved = self.server.store.save(
                        data, self.server.audio.devices, diagnostics, self.server.audio.endpoint_id
                    )
                self.reply(200, {"config": saved})
            else:
                self.reply(404, {"error": "Action not found."})
        except SetupError as exc:
            self.reply(400, {"error": exc.as_dict()})


def create_server(
    port: int,
    path: Path | None = None,
    audio: AudioControl | None = None,
    models: Path | None = None,
    recognizer: str | None = None,
    preset: str | None = None,
    people: Path | None = None,
    speaker_backend: str | None = None,
    policy_file: Path | None = None,
) -> SetupServer:
    control = audio or AudioControl(models=models, recognizer=recognizer or "zipformer",
                                    preset=preset or "room",
                                    people=people, speaker_backend=speaker_backend,
                                    policy_file=policy_file)
    overrides = {key: value for key, value in (
        ("recognizer", recognizer), ("preset", preset), ("backend", speaker_backend)
    ) if value is not None}
    try:
        try:
            return SetupServer(
                ("127.0.0.1", port), ConfigStore(path or default_config_path()), control,
                overrides=overrides,
            )
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE and getattr(exc, "winerror", None) != 10048:
                raise
            return SetupServer(
                ("127.0.0.1", 0), ConfigStore(path or default_config_path()), control,
                overrides=overrides,
            )
    except SetupError:
        control.close()
        raise
    except OSError as exc:
        control.close()
        raise SetupError(
            "launch_failed",
            "The local setup page could not be started.",
            "Close another setup window and retry, or choose --port 0 for a free port.",
        ) from exc


def serve(
    port: int = 8765,
    path: Path | None = None,
    open_browser: bool = True,
    models: Path | None = None,
    recognizer: str | None = None,
    preset: str | None = None,
    people: Path | None = None,
    speaker_backend: str | None = None,
    policy_file: Path | None = None,
) -> None:
    server = create_server(port, path, models=models, recognizer=recognizer, preset=preset,
                           people=people, speaker_backend=speaker_backend, policy_file=policy_file)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Family Harness local dashboard: {url}", flush=True)
    print(
        "Audio is off. Tests start only when you press a test button. Ctrl+C closes setup.",
        flush=True,
    )
    if open_browser:
        try:
            if not webbrowser.open(url):
                print(f"Browser could not open. Click or copy this address: {url}", flush=True)
        except webbrowser.Error:
            print(f"Browser could not open. Click or copy this address: {url}", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
