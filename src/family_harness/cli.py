"""Explicit setup entry point; import and installation never start audio."""

import argparse
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
    args = parser.parse_args()
    if args.command == "setup":
        if not 0 <= args.port <= 65535:
            parser.error("--port must be between 0 and 65535")
        from family_harness.errors import SetupError
        from family_harness.server import serve

        try:
            serve(args.port, args.config, not args.no_browser)
        except SetupError as exc:
            parser.exit(1, f"{exc.message}\n{exc.recovery}\n")
    else:
        parser.print_help()
