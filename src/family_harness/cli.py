"""Minimal package entry point; voice and setup features are not implemented yet."""

import argparse
from importlib.metadata import version


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="family-harness",
        description=(
            "Family Harness is under development. "
            "This initial scaffold does not yet record audio or run an agent."
        ),
    )
    parser.add_argument("--version", action="version", version=version("family-harness"))
    parser.parse_args()
    parser.print_help()
