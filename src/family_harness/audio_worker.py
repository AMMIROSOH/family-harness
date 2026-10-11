"""Short-lived PortAudio process. Importing the package never opens audio."""

from __future__ import annotations

import json
import platform
import sys
from importlib.metadata import version

from family_harness.devices import discover_native
from family_harness.errors import SetupError, audio_error


def emit(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=True, allow_nan=False), flush=True)


def main() -> None:
    try:
        import sounddevice as sd

        devices, warnings = discover_native(sd)
        if sys.argv[1] == "discover":
            emit({"devices": [device.public() for device in devices], "warnings": warnings})
            return
        from family_harness.audio import run_audio

        request = json.loads(sys.stdin.readline())
        result = run_audio(request, devices, sd, emit)
        result["environment"] = {
            "os": platform.platform(),
            "cpu": platform.processor(),
            "python": platform.python_version(),
            "packages": {
                name: version(name) for name in ("sounddevice", "numpy", "pywebrtc-audio")
            },
            "portaudio": sd.get_portaudio_version()[1],
        }
        emit({"type": "result", "result": result})
    except SetupError as exc:
        emit({"type": "error", "error": exc.as_dict()})
        sys.exit(1)
    except Exception as exc:
        emit({"type": "error", "error": audio_error(exc).as_dict()})
        sys.exit(1)


if __name__ == "__main__":
    main()
