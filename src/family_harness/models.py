"""Explicit, integrity-checked model acquisition. No network on import or inspection."""

from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from urllib.request import urlopen

from platformdirs import user_data_path

from family_harness.errors import SetupError


def catalog() -> dict:
    return json.loads(files("family_harness").joinpath("voice_catalog.json").read_text("utf-8"))


def default_model_path() -> Path:
    return user_data_path("FamilyHarness", appauthor=False) / "models"


def model_error(message: str) -> SetupError:
    return SetupError(
        "model_invalid",
        message,
        "Remove and reinstall the English CPU profile, or import its original catalog files. "
        "No microphone has been opened.",
    )


def safe_path(root: Path, relative: str) -> Path:
    name = PurePosixPath(relative)
    if name.is_absolute() or not name.parts or any(p in ("..", ".") for p in name.parts):
        raise model_error("The model contains an unsafe file path.")
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()) or ":" in relative or "\\" in relative:
        raise model_error("The model contains an unsafe file path.")
    return target


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class ModelStore:
    def __init__(self, root: Path | None = None, manifest: dict | None = None,
                 prepare: Callable | None = None):
        self.root = root or default_model_path()
        self.catalog = manifest or catalog()
        self.profile = safe_path(self.root, self.catalog["id"])
        self.prepare = prepare

    def status(self) -> dict:
        # Existence only; full hashing occurs in the worker before loading.
        installed = (self.profile / "installed.json").is_file()
        previous = self.catalog.get("replaces")
        return {
            "catalog": self.catalog,
            "download_bytes": sum(a["size"] for a in self.catalog["assets"]),
            "installed": installed,
            "upgrade_available": bool(
                not installed
                and previous
                and (safe_path(self.root, previous) / "installed.json").is_file()
            ),
            "path": str(self.profile),
        }

    def verify(self) -> dict:
        try:
            record = json.loads((self.profile / "installed.json").read_text("utf-8"))
            if record["catalog"] != self.catalog or not record["files"]:
                raise ValueError("profile version mismatch")
            for item in record["files"]:
                target = safe_path(self.profile, item["path"])
                if target.stat().st_size != item["size"] or digest(target) != item["sha256"]:
                    raise ValueError("integrity mismatch")
            return record
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise model_error(
                "The English CPU profile is missing, incomplete, or damaged."
            ) from exc

    def install(self, source: Path | None = None, emit: Callable = lambda event: None) -> dict:
        """Download only when called explicitly; import never contacts a server."""
        if source is not None:
            source = source.resolve()
            if not source.is_dir() or str(source).startswith("\\\\"):
                raise model_error("Choose a local folder containing the original model files.")
        self.root.mkdir(parents=True, exist_ok=True)
        if (self.profile / "installed.json").exists():
            self.verify()
            return {"status": "installed", **self.status()}
        # A killed worker may leave a staging folder; it is never an installed profile.
        with TemporaryDirectory(prefix=".install-", dir=self.root) as temporary:
            stage = Path(temporary)
            content = stage / "content"
            content.mkdir()
            total = sum(a["size"] for a in self.catalog["assets"])
            completed = 0
            for asset in self.catalog["assets"]:
                temporary_asset = stage / "asset"
                if source is not None:
                    incoming = safe_path(source, asset["name"])
                    if not incoming.is_file():
                        raise model_error(f"The import folder is missing {asset['name']}.")
                    if incoming.stat().st_size != asset["size"]:
                        raise model_error(f"The imported file {asset['name']} has the wrong size.")
                    shutil.copyfile(incoming, temporary_asset)
                else:
                    if not asset["url"].startswith("https://"):
                        raise model_error("Model downloads require HTTPS.")
                    with urlopen(asset["url"], timeout=30) as response:
                        if not response.url.startswith("https://"):
                            raise model_error(
                                "The model download redirected to an insecure address."
                            )
                        received = 0
                        with temporary_asset.open("wb") as output:
                            while chunk := response.read(64 * 1024):
                                received += len(chunk)
                                if received > asset["size"]:
                                    raise model_error(
                                        "The download exceeds the expected model size."
                                    )
                                output.write(chunk)
                                emit(
                                    {
                                        "phase": "installing",
                                        "bytes": completed + received,
                                        "total_bytes": total,
                                        "file": asset["name"],
                                    }
                                )
                if (
                    temporary_asset.stat().st_size != asset["size"]
                    or digest(temporary_asset) != asset["sha256"]
                ):
                    raise model_error(f"Integrity check failed for {asset['name']}.")
                destination = safe_path(content, asset["destination"])
                if "archive_prefix" in asset:
                    self._unpack(temporary_asset, destination, asset["archive_prefix"])
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(temporary_asset, destination)
                completed += asset["size"]
                emit(
                    {
                        "phase": "installing",
                        "bytes": completed,
                        "total_bytes": total,
                        "file": asset["name"],
                    }
                )
            if self.prepare:
                self.prepare(content)
            record = {
                "catalog": self.catalog,
                "files": [
                    {
                        "path": str(path.relative_to(content)).replace("\\", "/"),
                        "size": path.stat().st_size,
                        "sha256": digest(path),
                    }
                    for path in sorted(content.rglob("*"))
                    if path.is_file()
                ],
            }
            (content / "installed.json").write_text(json.dumps(record, indent=2), "utf-8")
            if self.profile.exists():
                raise model_error("An incomplete profile exists. Remove it before reinstalling.")
            content.rename(self.profile)
        return {"status": "installed", **self.status()}

    @staticmethod
    def _unpack(archive: Path, destination: Path, prefix: str) -> None:
        size = 0
        with tarfile.open(archive, "r:bz2") as bundle:
            for member in bundle:
                parts = PurePosixPath(member.name).parts
                if not parts or parts[0] != prefix or member.issym() or member.islnk():
                    raise model_error("The voice archive contains an unexpected entry.")
                if member.isdir():
                    continue
                if not member.isfile() or len(parts) < 2:
                    raise model_error("The voice archive contains an unsupported entry.")
                # Validate every path even for omitted documentation/scripts.
                target = safe_path(destination, "/".join(parts[1:]))
                size += member.size
                if size > 256 * 1024 * 1024:
                    raise model_error("The expanded voice archive is too large.")
                if not (parts[1] == "espeak-ng-data" or parts[1].endswith((".onnx", ".txt"))):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(member) as incoming, target.open("wb") as output:
                    shutil.copyfileobj(incoming, output)

    def remove(self) -> None:
        # Delete only this fixed profile; never follow a link outside the selected model root.
        target = self.root / self.catalog["id"]
        if target.resolve() != self.profile or not target.resolve().is_relative_to(
            self.root.resolve()
        ):
            raise model_error("The model folder changed. Restore it before removing the profile.")
        if target.exists():
            shutil.rmtree(target)
