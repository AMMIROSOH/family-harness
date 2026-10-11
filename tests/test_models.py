import copy
import hashlib
import io
import json
import tarfile

import pytest

from family_harness.errors import SetupError
from family_harness.models import ModelStore, catalog, safe_path


@pytest.fixture
def model_bundle(tmp_path):
    source = tmp_path / "originals"
    source.mkdir()
    data = b"local-model-fixture"
    (source / "model.onnx").write_bytes(data)
    manifest = {
        "id": "test-profile",
        "schema_version": 1,
        "assets": [
            {
                "name": "model.onnx",
                "destination": "stt/model.onnx",
                "url": "https://models.example/model.onnx",
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        ],
    }
    return ModelStore(tmp_path / "models", manifest), source


def test_offline_import_is_atomic_verified_and_never_downloads(model_bundle, monkeypatch):
    store, source = model_bundle
    monkeypatch.setattr("family_harness.models.urlopen", lambda *a, **k: pytest.fail("network"))
    assert not store.status()["installed"]
    store.install(source)
    record = store.verify()
    assert store.status()["installed"]
    assert record["catalog"] == store.catalog
    assert record["files"][0]["path"] == "stt/model.onnx"
    store.remove()
    assert not store.status()["installed"] and source.exists()


def test_corrupt_import_never_commits_a_profile(model_bundle):
    store, source = model_bundle
    (source / "model.onnx").write_bytes(b"x" * store.catalog["assets"][0]["size"])
    with pytest.raises(SetupError, match="Integrity"):
        store.install(source)
    assert not store.profile.exists()
    assert not list(store.root.glob(".install-*"))


def test_missing_import_file_is_named_in_recovery(model_bundle):
    store, source = model_bundle
    (source / "model.onnx").unlink()
    with pytest.raises(SetupError, match="missing model.onnx"):
        store.install(source)
    assert not store.profile.exists()


def test_profile_upgrade_preserves_previous_files_and_requires_current_install(model_bundle):
    previous, source = model_bundle
    previous.install(source)
    old_record = previous.verify()
    updated = copy.deepcopy(previous.catalog)
    updated.update(id="test-profile-v2", replaces=previous.catalog["id"])
    current = ModelStore(previous.root, updated)
    assert current.status()["upgrade_available"]
    assert not current.status()["installed"]
    with pytest.raises(SetupError):
        current.verify()
    current.install(source)
    assert current.status()["installed"]
    assert not current.status()["upgrade_available"]
    assert current.verify()["catalog"] == updated
    assert previous.verify() == old_record
    current.remove()
    assert current.status()["upgrade_available"]
    assert previous.verify() == old_record


def test_cancelled_acquisition_never_commits_a_profile(model_bundle):
    store, source = model_bundle

    def cancel(event):
        raise RuntimeError("cancel")

    with pytest.raises(RuntimeError):
        store.install(source, cancel)
    assert not store.profile.exists()


def test_corrupt_installed_file_and_changed_catalog_are_rejected(model_bundle):
    store, source = model_bundle
    store.install(source)
    path = store.profile / "stt/model.onnx"
    path.write_bytes(b"0" * path.stat().st_size)
    with pytest.raises(SetupError):
        store.verify()
    changed = copy.deepcopy(store.catalog)
    changed["schema_version"] = 2
    with pytest.raises(SetupError):
        ModelStore(store.root, changed).verify()


@pytest.mark.parametrize("name", ["../escape", "C:/escape", "folder\\escape", "/escape"])
def test_model_paths_cannot_escape_root(tmp_path, name):
    with pytest.raises(SetupError):
        safe_path(tmp_path, name)


@pytest.mark.parametrize(
    "name,kind",
    [
        ("voice/../escape", "file"),
        ("voice/link", "symlink"),
        ("voice/link", "hardlink"),
        ("other/model.onnx", "file"),
        ("voice/fifo", "fifo"),
    ],
)
def test_unsafe_archive_members_are_rejected(tmp_path, name, kind):
    archive = tmp_path / "voice.tar.bz2"
    with tarfile.open(archive, "w:bz2") as tar:
        entry = tarfile.TarInfo(name)
        entry.type = {
            "file": tarfile.REGTYPE,
            "symlink": tarfile.SYMTYPE,
            "hardlink": tarfile.LNKTYPE,
            "fifo": tarfile.FIFOTYPE,
        }[kind]
        entry.size = 1 if kind == "file" else 0
        entry.linkname = "../escape"
        tar.addfile(entry, io.BytesIO(b"x") if kind == "file" else None)
    with pytest.raises(SetupError):
        ModelStore._unpack(archive, tmp_path / "tts", "voice")
    assert not (tmp_path / "escape").exists()


def test_pinned_catalog_has_sizes_integrity_and_license_provenance():
    profile = catalog()
    assert profile["execution"] == "local-cpu" and profile["language"] == "en"
    assert len(profile["assets"]) == 6
    assert all(len(a["sha256"]) == 64 and a["size"] > 0 for a in profile["assets"])
    assert any("GPL" in item["license"] for item in profile["licenses"])


def test_download_integrity_size_and_transport_limits(model_bundle, monkeypatch):
    store, _ = model_bundle

    class Response(io.BytesIO):
        url = "https://models.example/model.onnx"

    monkeypatch.setattr("family_harness.models.urlopen", lambda *a, **k: Response(b"bad" * 100))
    with pytest.raises(SetupError):
        store.install()
    assert not store.status()["installed"]
    store.catalog["assets"][0]["url"] = "http://models.example/model.onnx"
    with pytest.raises(SetupError, match="HTTPS"):
        store.install()


def test_explicit_download_verifies_and_installs_original_bytes(model_bundle, monkeypatch):
    store, source = model_bundle
    data = (source / "model.onnx").read_bytes()

    class Response(io.BytesIO):
        url = "https://models.example/model.onnx"

    monkeypatch.setattr("family_harness.models.urlopen", lambda *a, **k: Response(data))
    progress = []
    store.install(emit=progress.append)
    assert progress[-1]["bytes"] == len(data)
    assert store.verify()["files"][0]["sha256"] == hashlib.sha256(data).hexdigest()


def test_manifest_path_tampering_cannot_read_outside_profile(model_bundle):
    store, source = model_bundle
    store.install(source)
    path = store.profile / "installed.json"
    record = json.loads(path.read_text())
    record["files"][0]["path"] = "../../originals/model.onnx"
    path.write_text(json.dumps(record))
    with pytest.raises(SetupError):
        store.verify()
