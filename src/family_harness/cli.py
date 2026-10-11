"""Explicit setup entry point; import and installation never start audio."""

import argparse
import json
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="family-harness",
        description=(
            "Family Harness is under development. "
            "Configure and test room audio locally. Conversations are not implemented yet."
        ),
    )
    parser.add_argument("--version", action="version", version=version("family-harness"))
    commands = parser.add_subparsers(dest="command")
    setup = commands.add_parser("setup", help="Open the localhost room audio setup wizard")
    setup.add_argument("--port", type=int, default=8765, help="Local port (0 chooses a free port)")
    setup.add_argument(
        "--no-browser", action="store_true", help="Print the address without opening it"
    )
    setup.add_argument("--config", type=Path, help="Alternative room configuration file")
    setup.add_argument("--models", type=Path, help="Alternative local model directory")
    voice = commands.add_parser("voice", help="Manage and benchmark the local English CPU profile")
    voice.add_argument("--models", type=Path, help="Alternative local model directory")
    actions = voice.add_subparsers(dest="voice_action", required=True)
    actions.add_parser(
        "status", help="Show the catalog and installation state; no models are loaded"
    )
    install = actions.add_parser("install", help="Explicitly download ~135 MiB; no audio starts")
    install.add_argument(
        "--from-directory", type=Path, help="Import catalog files without internet"
    )
    actions.add_parser("remove", help="Remove only the installed English CPU model profile")
    benchmark = actions.add_parser("benchmark", help="Load and warm models without opening audio")
    benchmark.add_argument("--report", type=Path, help="Save diagnostics without spoken text")
    replay = actions.add_parser(
        "replay", help="Transcribe a local WAV and synthesize without devices"
    )
    replay.add_argument("input", type=Path, help="PCM16 mono WAV, at most 30 seconds")
    replay.add_argument(
        "--output", type=Path, help="Explicitly save the fixed TTS response as a WAV"
    )
    replay.add_argument("--report", type=Path, help="Save diagnostics without the transcript")
    args = parser.parse_args()
    if args.command == "setup":
        if not 0 <= args.port <= 65535:
            parser.error("--port must be between 0 and 65535")
        from family_harness.errors import SetupError
        from family_harness.server import serve

        try:
            serve(args.port, args.config, not args.no_browser, args.models)
        except SetupError as exc:
            parser.exit(1, f"{exc.message}\n{exc.recovery}\n")
    elif args.command == "voice":
        from family_harness.models import ModelStore

        store = ModelStore(args.models)
        if args.voice_action == "status":
            print(json.dumps(store.status(), indent=2))
            return
        kinds = {
            "install": "voice_install",
            "remove": "voice_remove",
            "benchmark": "voice_warm",
            "replay": "voice_replay",
        }
        request = {"kind": kinds[args.voice_action], "models": str(store.root)}
        if args.voice_action == "install":
            if args.from_directory:
                request.update(kind="voice_import", source=str(args.from_directory))
            else:
                print(
                    "Downloading ~135 MiB for local English speech. No audio will start.",
                    flush=True,
                )
        if args.voice_action == "replay":
            request["source"] = str(args.input)
            if args.output:
                request["output"] = str(args.output)
        if getattr(args, "report", None):
            request["report"] = str(args.report)
        from family_harness.control import child_options

        try:
            child = subprocess.run(
                [sys.executable, "-m", "family_harness.voice_worker"],
                input=json.dumps(request) + "\n",
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=600 if args.voice_action == "install" else 120,
                **child_options(),
            )
            events = [json.loads(line) for line in child.stdout.splitlines()]
            errors = [event["error"] for event in events if event.get("type") == "error"]
            if errors:
                parser.exit(1, f"{errors[-1]['message']}\n{errors[-1]['recovery']}\n")
            results = [event["result"] for event in events if event.get("type") == "result"]
            if child.returncode or not results:
                parser.exit(1, "Voice operation failed. Repair the installation and model files.\n")
            print(json.dumps(results[-1], indent=2, ensure_ascii=True))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            parser.exit(1, "Voice operation could not finish. Check the installation and retry.\n")
        except KeyboardInterrupt:
            parser.exit(1, "Voice operation stopped. Audio is off.\n")
    else:
        parser.print_help()
