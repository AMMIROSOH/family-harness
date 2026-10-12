"""Explicit setup entry point; import and installation never start audio."""

import argparse
import json
import subprocess
import sys
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="family-harness",
        description=(
            "Family Harness is under development. "
            "Configure room audio and replay the room manager locally. Live conversations "
            "are not implemented yet."
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
    setup.add_argument("--people", type=Path, help="Local enrolled voice profiles")
    setup.add_argument(
        "--recognizer",
        choices=("zipformer", "parakeet-v2", "whisper-small-en"),
        default="zipformer",
        help="Local final recognizer for deliberate voice trials",
    )
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
    for command in ("install-recognizer", "status-recognizer", "remove-recognizer"):
        action = actions.add_parser(command, help="Manage an optional local final recognizer")
        action.add_argument("recognizer", choices=("parakeet-v2", "whisper-small-en"))
        if command == "install-recognizer":
            action.add_argument("--from-directory", type=Path, help="Import pinned files offline")
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
    room = commands.add_parser("room", help="Replay the deterministic room manager without devices")
    room.add_argument("--models", type=Path, help="Alternative local model directory")
    room_actions = room.add_subparsers(dest="room_action", required=True)
    room_replay = room_actions.add_parser("replay", help="Replay continuous WAV or JSONL events")
    room_replay.add_argument("input", type=Path)
    room_replay.add_argument("--events", action="store_true", help="Read common event envelopes")
    room_replay.add_argument("--report", type=Path, help="Save a text-free replay report")
    room_replay.add_argument(
        "--participation",
        choices=("all", "enrolled", "addressed"),
        default="all",
        help="Response policy for event fixtures",
    )
    group = room_actions.add_parser("group", help="Bounded offline attributed group WAV replay")
    group.add_argument("input", type=Path)
    group.add_argument("--people", type=Path)
    group.add_argument("--seconds", type=float, help="Use this prefix, at most 300 seconds")
    group.add_argument("--report", type=Path, help="Save a report without transcripts")
    group.add_argument("--participation", choices=("all", "enrolled", "addressed"), default="all")
    group.add_argument(
        "--recognizer",
        choices=("zipformer", "parakeet-v2", "whisper-small-en"),
        default="parakeet-v2",
    )
    evaluation = room_actions.add_parser("evaluate", help="Evaluate a local DiPCo subset offline")
    evaluation.add_argument(
        "dataset", type=Path, help="Folder with DiPCo WAVs and annotation JSONs"
    )
    evaluation.add_argument(
        "--mode",
        choices=("events", "utterances", "continuous", "recognizer", "speakers", "diarization"),
        default="utterances",
    )
    evaluation.add_argument("--split", choices=("all", "dev", "eval"), default="all")
    evaluation.add_argument("--file", help="Evaluate one recording filename")
    evaluation.add_argument("--limit", type=int, help="Evenly spaced utterances per speaker/file")
    evaluation.add_argument(
        "--report", type=Path, required=True, help="Save text-free measurements"
    )
    from family_harness.identity import DEFAULT_BACKEND

    backends = ("wespeaker-resnet34", "wespeaker-campplus", "wespeaker-resnet293")
    for action in (setup, group, evaluation):
        action.add_argument("--speaker-backend", choices=backends, default=DEFAULT_BACKEND)
    for key, default in (("threshold", 0.3), ("margin", 0.08), ("minimum-seconds", 0.7)):
        evaluation.add_argument(
            "--" + key, type=float, default=default, help="Advanced speaker matching setting"
        )
    people = commands.add_parser(
        "people", help="Explicit local voice enrollment and model management"
    )
    people.add_argument("--models", type=Path)
    people.add_argument(
        "--people", type=Path, help="Local embedding file; keep outside source control"
    )
    people.add_argument("--backend", choices=backends, default=DEFAULT_BACKEND)
    people_actions = people.add_subparsers(dest="people_action", required=True)
    people_actions.add_parser("list", help="List enrolled people without loading models")
    people_actions.add_parser("status", help="Inspect speaker and segmentation installation")
    for name in ("install-model", "install-segmentation"):
        action = people_actions.add_parser(name, help="Explicit model download or offline import")
        action.add_argument("--from-directory", type=Path)
    people_actions.add_parser(
        "remove-model", help="Remove this speaker model; profiles are retained"
    )
    remove_person = people_actions.add_parser("remove", help="Remove an enrolled voice profile")
    remove_person.add_argument("person_id")
    enroll = people_actions.add_parser(
        "enroll", help="Save a consenting person's three WAV phrases"
    )
    enroll.add_argument("input", type=Path, nargs="+", help="Three to eight PCM16 mono WAVs")
    enroll.add_argument(
        "--name", required=True, help="Person's display name, including local names"
    )
    identify = people_actions.add_parser(
        "identify", help="Match a single-speaker WAV or return unknown"
    )
    identify.add_argument("input", type=Path)
    from family_harness.speech import VOICE_PRESETS

    setup.add_argument("--preset", choices=tuple(VOICE_PRESETS), default="room")
    replay.add_argument("--preset", choices=tuple(VOICE_PRESETS), default="room")
    for action in (replay, benchmark, room_replay, evaluation):
        action.add_argument(
            "--recognizer",
            choices=("zipformer", "parakeet-v2", "whisper-small-en"),
            default="zipformer",
            help="Final recognizer; streaming drafts still use Zipformer",
        )
    for action in (room_replay, evaluation):
        action.add_argument("--preset", choices=tuple(VOICE_PRESETS), default="room")
        action.add_argument("--silence", type=float, help="Completion silence, 0.3-2 seconds")
        action.add_argument("--gain-db", type=float, help="Explicit fixed input gain, 0-36 dB")
        action.add_argument("--seconds", type=float, help="Replay only this continuous WAV prefix")
    args = parser.parse_args()
    if args.command == "setup":
        if not 0 <= args.port <= 65535:
            parser.error("--port must be between 0 and 65535")
        from family_harness.errors import SetupError
        from family_harness.server import serve

        try:
            serve(
                args.port,
                args.config,
                not args.no_browser,
                args.models,
                args.recognizer,
                args.preset,
                args.people,
                args.speaker_backend,
            )
        except SetupError as exc:
            parser.exit(1, f"{exc.message}\n{exc.recovery}\n")
    elif args.command == "people":
        run_people(args, parser)
    elif args.command == "room":
        from family_harness.errors import SetupError
        from family_harness.models import ModelStore
        from family_harness.room_replay import replay_events, replay_wav
        from family_harness.speech import LocalVoice

        if getattr(args, "limit", None) is not None and args.limit < 1:
            parser.error("--limit must be positive")
        if args.seconds is not None and not 0 < args.seconds <= 3600:
            parser.error("--seconds must be between zero and 3600")
        if args.room_action == "evaluate":
            if args.limit is not None and args.mode not in ("utterances", "recognizer", "speakers"):
                parser.error("--limit applies only to utterance or recognizer evaluation")
            if args.seconds is not None and args.mode not in ("continuous", "diarization"):
                parser.error("--seconds applies only to continuous evaluation")
        try:
            settings = VOICE_PRESETS[getattr(args, "preset", "room")]
            if getattr(args, "silence", None) is not None:
                settings = replace(settings, silence=args.silence)
            if getattr(args, "gain_db", None) is not None:
                settings = replace(settings, gain_db=args.gain_db)
            if args.room_action == "evaluate":
                from family_harness.dipco import block_network, evaluate

                block_network()
                if args.mode == "speakers":
                    from family_harness.identity import MatchSettings, SherpaEmbedding
                    from family_harness.speaker_evaluation import evaluate_speakers
                    from family_harness.voice_trial import Measurements

                    metrics = Measurements()
                    try:
                        result = evaluate_speakers(
                            args.dataset,
                            SherpaEmbedding(args.speaker_backend, args.models),
                            split=args.split,
                            limit=args.limit,
                            settings=MatchSettings(
                                args.threshold, args.margin, args.minimum_seconds
                            ),
                            filename=args.file,
                            progress=lambda m: print(m, file=sys.stderr, flush=True),
                        )
                    finally:
                        measurements = metrics.finish()
                    result["measurements"] = measurements
                elif args.mode == "diarization":
                    from family_harness.speaker_evaluation import evaluate_diarization

                    result = evaluate_diarization(
                        args.dataset,
                        args.speaker_backend,
                        args.models,
                        split=args.split,
                        seconds=args.seconds or 300,
                        filename=args.file,
                    )
                else:
                    result = evaluate(
                        args.dataset,
                        args.models,
                        mode=args.mode,
                        settings=settings,
                        split=args.split,
                        filename=args.file,
                        limit=args.limit,
                        seconds=args.seconds,
                        progress=lambda message: print(message, file=sys.stderr, flush=True),
                        recognizer=args.recognizer,
                    )
            elif args.room_action == "group":
                from family_harness.asr import StreamingUtteranceRecognizer, load_recognizer
                from family_harness.group import SherpaDiarizer, group_turns
                from family_harness.identity import (
                    PeopleStore,
                    SherpaEmbedding,
                    VoiceMatcher,
                    read_voice_wav,
                )

                provider = SherpaEmbedding(args.speaker_backend, args.models)
                matcher = VoiceMatcher(provider, PeopleStore(args.people).load())
                diarizer = SherpaDiarizer(args.speaker_backend, args.models)
                if args.recognizer == "zipformer":
                    store = ModelStore(args.models)
                    store.verify()
                    recognizer = StreamingUtteranceRecognizer(store.profile)
                else:
                    recognizer = load_recognizer(args.recognizer, args.models)
                result = group_turns(
                    read_voice_wav(args.input, maximum=300, seconds=args.seconds),
                    diarizer,
                    matcher,
                    recognizer,
                    participation=args.participation,
                )
            elif args.events:
                result = replay_events(args.input, participation=args.participation)
            else:
                store = ModelStore(args.models)
                store.verify()
                from family_harness.asr import load_recognizer

                finalizer = (
                    load_recognizer(args.recognizer, store.root)
                    if args.recognizer != "zipformer"
                    else None
                )
                voice = LocalVoice(store.profile, settings, finalizer=finalizer)
                voice.warm()
                result = replay_wav(args.input, voice, seconds=args.seconds)
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                temporary = args.report.with_suffix(".tmp")
                temporary.write_text(json.dumps(result, indent=2, allow_nan=False), "utf-8")
                temporary.replace(args.report)
            summary = dict(result)
            if "recordings" in summary:
                summary["recordings"] = [
                    {**r, "score": {k: v for k, v in r["score"].items() if k != "rows"}}
                    for r in summary["recordings"]
                ]
            else:
                summary.pop("utterances", None)
                summary.pop("responses", None)
            print(json.dumps(summary, indent=2, ensure_ascii=True))
        except SetupError as exc:
            parser.exit(1, f"{exc.message}\n{exc.recovery}\n")
        except ImportError:
            parser.exit(1, "Install evaluation dependencies with uv sync --extra evaluation.\n")
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            parser.exit(1, f"Room replay failed: {exc}. Check the local files and options.\n")
        except KeyboardInterrupt:
            parser.exit(1, "Room replay stopped. Audio devices were not opened.\n")
    elif args.command == "voice":
        from family_harness.models import ModelStore

        store = ModelStore(args.models)
        if args.voice_action in ("install-recognizer", "status-recognizer", "remove-recognizer"):
            from family_harness.asr import recognizer_store

            store = recognizer_store(args.recognizer, store.root)
        if args.voice_action in ("status", "status-recognizer"):
            print(json.dumps(store.status(), indent=2))
            return
        kinds = {
            "install": "voice_install",
            "remove": "voice_remove",
            "benchmark": "voice_warm",
            "replay": "voice_replay",
            "install-recognizer": "recognizer_install",
            "remove-recognizer": "recognizer_remove",
        }
        request = {"kind": kinds[args.voice_action], "models": str(store.root)}
        if getattr(args, "recognizer", "zipformer") != "zipformer":
            request["recognizer"] = args.recognizer
        if args.voice_action == "install-recognizer":
            if args.from_directory:
                request["source"] = str(args.from_directory)
            else:
                size = sum(a["size"] for a in store.catalog["assets"]) / 2**20
                print(f"Downloading {size:.1f} MiB for local {args.recognizer}. Audio stays off.")
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
            request["preset"] = args.preset
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
                timeout=600 if args.voice_action in ("install", "install-recognizer") else 120,
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


def run_people(args, parser):
    from family_harness.errors import SetupError
    from family_harness.identity import (
        PeopleStore,
        SherpaEmbedding,
        VoiceMatcher,
        enrollment,
        read_voice_wav,
        segmentation_store,
        speaker_store,
    )

    try:
        store = PeopleStore(args.people)
        action = args.people_action
        if action == "list":
            result = store.public()
        elif action == "status":
            result = {
                "speaker_model": speaker_store(args.backend, args.models).status(),
                "segmentation_model": segmentation_store(args.models).status(),
            }
        elif action == "remove":
            store.remove(args.person_id)
            result = {"status": "removed"}
        elif action in ("install-model", "install-segmentation", "remove-model"):
            from family_harness.control import child_options

            selected = (
                segmentation_store(args.models)
                if action == "install-segmentation"
                else speaker_store(args.backend, args.models)
            )
            request = {
                "kind": {
                    "install-model": "speaker_install",
                    "install-segmentation": "segmentation_install",
                    "remove-model": "speaker_remove",
                }[action],
                "models": str(selected.root),
                "backend": args.backend,
            }
            source = getattr(args, "from_directory", None)
            if source:
                request["source"] = str(source)
            elif action != "remove-model":
                size = selected.status()["download_bytes"] / 2**20
                print(f"Downloading {size:.1f} MiB for local speaker processing. Audio stays off.")
            child = subprocess.run(
                [sys.executable, "-m", "family_harness.people_worker"],
                input=json.dumps(request) + "\n",
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=600,
                **child_options(),
            )
            events = [json.loads(line) for line in child.stdout.splitlines()]
            errors = [e["error"] for e in events if e.get("type") == "error"]
            if errors:
                parser.exit(1, f"{errors[-1]['message']}\n{errors[-1]['recovery']}\n")
            results = [e["result"] for e in events if e.get("type") == "result"]
            if child.returncode or not results:
                raise ValueError("speaker model operation could not finish")
            result = results[-1]
        else:
            provider = SherpaEmbedding(args.backend, args.models)
            if action == "enroll":
                profile, quality = enrollment(
                    provider, [read_voice_wav(p) for p in args.input], args.name
                )
                store.save(profile)
                result = {
                    "person_id": profile.person_id,
                    "name": profile.name,
                    "saved": True,
                    "quality": quality,
                }
            else:
                from dataclasses import asdict

                result = asdict(
                    VoiceMatcher(provider, store.load()).identify(read_voice_wav(args.input))
                )
        print(json.dumps(result, indent=2, ensure_ascii=True))
    except SetupError as exc:
        parser.exit(1, f"{exc.message}\n{exc.recovery}\n")
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        subprocess.TimeoutExpired,
    ) as exc:
        parser.exit(1, f"People operation failed: {exc}. Check the local files and options.\n")
    except KeyboardInterrupt:
        parser.exit(1, "People operation stopped. Audio is off.\n")
