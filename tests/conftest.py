from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from family_harness.devices import Device


@pytest.fixture(autouse=True)
def isolated_local_data(tmp_path, monkeypatch):
    # Behavior checks never inspect a household's installed models or enrolled voices.
    monkeypatch.setattr("family_harness.models.default_model_path", lambda: tmp_path / "models")
    monkeypatch.setattr("family_harness.identity.user_data_path", lambda *a, **k: tmp_path)


@pytest.fixture
def devices():
    return [
        Device("mic", "os-mic", "Room microphone", "input", 7, 1, (48000, 16000)),
        Device("speaker", "os-speaker", "Room speaker", "output", 3, 2, (48000, 16000)),
    ]


@pytest.fixture
def selection():
    return {
        "space_name": "خانه",
        "room_name": "اتاق",
        "input_id": "mic",
        "output_id": "speaker",
        "echo_owner": "software",
        "device_use": "room",
        "speaker_confirmed": True,
        "echo_confirmed": True,
        "position": "near",
    }


class FakeStream:
    def __init__(self, backend, kind, **options):
        self.backend = backend
        self.kind = kind
        self.options = options
        self.active = False
        self.closed = False
        self.stop = threading.Event()
        self.thread = None

    def __enter__(self):
        if self.backend.failure:
            raise self.backend.failure
        self.active = True
        self.thread = threading.Thread(target=self._produce, daemon=True)
        self.thread.start()
        return self

    def _produce(self):
        number = 0
        size = self.options["blocksize"]
        while not self.stop.is_set():
            t = number / 100
            if (
                self.backend.disconnect_after is not None
                and number >= self.backend.disconnect_after
            ):
                self.active = False
                return
            raw = np.full((size, 1), self.backend.input_level, dtype=np.float32)
            output = np.zeros((size, 2), dtype=np.float32)
            timing = SimpleNamespace(inputBufferAdcTime=t, outputBufferDacTime=t + 0.03)
            callback = self.options["callback"]
            status = number == self.backend.gap_at
            if self.kind == "input":
                callback(raw, size, timing, status)
            elif self.kind == "output":
                callback(output, size, timing, status)
            else:
                callback(raw, output, size, timing, status)
            if self.kind != "input":
                self.backend.played.append(output[:, 0].copy())
                np.testing.assert_array_equal(output[:, 0], output[:, 1])
            number += 1
            time.sleep(0.0008)

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.stop.set()
        self.active = False
        self.closed = True
        if self.thread:
            self.thread.join(timeout=2)


class FakeAudio:
    def __init__(self, input_level=0.02, gap_at=None, disconnect_after=None, failure=None):
        self.input_level = input_level
        self.gap_at = gap_at
        self.disconnect_after = disconnect_after
        self.failure = failure
        self.played = []
        self.streams = []

    def WasapiSettings(self, **options):
        return options

    def _stream(self, kind, **options):
        stream = FakeStream(self, kind, **options)
        self.streams.append(stream)
        return stream

    def InputStream(self, **options):
        return self._stream("input", **options)

    def OutputStream(self, **options):
        return self._stream("output", **options)

    def Stream(self, **options):
        return self._stream("duplex", **options)
