import json
import sys
from dataclasses import asdict
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest

from family_harness.cli import main
from family_harness.errors import SetupError
from family_harness.identity import MatchSettings, PeopleStore, VoiceMatcher, VoiceProfile
from family_harness.recognition_policy import DEFAULT_POLICIES, RecognitionPolicies


def test_presets_change_recognition_without_forcing_ties_or_overlap():
    provider = SimpleNamespace(backend="titanet-large", model_hash="a" * 64)
    person = VoiceProfile(str(uuid4()), "Person", provider.backend, provider.model_hash, [1, 0], 3)
    for name, settings in DEFAULT_POLICIES.items():
        matcher = VoiceMatcher(provider, [person], settings)
        for score, accepted in ((0.25, name == "free"), (0.4, name != "strict"), (0.7, True)):
            decision = matcher.match_vector([score, np.sqrt(1 - score**2)])
            assert (decision.person_id == person.person_id) == accepted
        assert matcher.match_vector([0, 1]).person_id is None
        assert matcher.identify(np.ones(100)).state == "insufficient_audio"
        assert matcher.identify(np.ones(16000), overlap=True).state == "overlap"
        twin = VoiceProfile(str(uuid4()), "Twin", provider.backend, provider.model_hash, [1, 0], 3)
        tied = VoiceMatcher(provider, [person, twin], settings).match_vector([1, 0])
        assert tied.state == "ambiguous"


def test_policy_edits_survive_restart_and_do_not_reenroll_people(tmp_path):
    policies = RecognitionPolicies(tmp_path / "policies.json")
    assert policies.snapshot()["name"] == "balanced"
    assert not policies.path.exists()  # Reading defaults has no installation side effects.
    people = PeopleStore(tmp_path / "people.json")
    people.save(VoiceProfile(str(uuid4()), "Person", "fake", "a" * 64, [1, 0], 3))
    before = people.path.read_bytes()
    policies.update("free", select=True, threshold=0.15, minimum_seconds=1.2)
    snapshot = RecognitionPolicies(policies.path).snapshot()
    assert snapshot["name"] == "free" and snapshot["customized"]
    assert snapshot["settings"]["minimum_seconds"] == 1.2
    override = policies.snapshot("strict", threshold=0.6)
    assert override["overrides"] == ["threshold"] and override["settings"]["threshold"] == 0.6
    assert policies.snapshot() == snapshot  # One-run override never persists.
    policies.reset("free")
    assert policies.snapshot()["name"] == "free"
    assert not policies.snapshot()["customized"]
    assert people.path.read_bytes() == before


@pytest.mark.parametrize("changes", [
    {"threshold": True}, {"threshold": float("nan")}, {"margin": float("inf")},
    {"minimum_seconds": 0.1}, {"threshold": "0.3"}, {"threshold": 10**400},
    {"permission": "private-memory"},
])
def test_invalid_policy_edits_leave_saved_settings_intact(tmp_path, changes):
    policies = RecognitionPolicies(tmp_path / "policies.json")
    policies.select("strict")
    before = policies.path.read_bytes()
    with pytest.raises((TypeError, ValueError)):
        policies.update("free", **changes)
    assert policies.path.read_bytes() == before


def test_damaged_policies_fail_with_explicit_recovery(tmp_path):
    policies = RecognitionPolicies(tmp_path / "policies.json")
    policies.path.write_text('{"version": 2}')
    with pytest.raises(SetupError, match="damaged"):
        policies.snapshot()
    policies.reset_all()
    assert policies.snapshot()["name"] == "balanced"


def test_cli_saved_selection_one_run_override_and_management(tmp_path, monkeypatch, capsys):
    path = tmp_path / "policies.json"
    base = ["family-harness", "people", "--policy-file", str(path)]

    def invoke(tail):
        monkeypatch.setattr(sys, "argv", base + tail)
        main()
        return json.loads(capsys.readouterr().out)

    invoke(["policies", "update", "free", "--threshold", "0.15"])
    invoke(["policies", "select", "free"])
    people = PeopleStore(tmp_path / "people.json")
    person = VoiceProfile(str(uuid4()), "Person", "titanet-large", "a" * 64, [1, 0], 3)
    people.save(person)
    vector = np.array([0.25, np.sqrt(1 - 0.25**2)])
    provider = SimpleNamespace(backend=person.backend, model_hash=person.model_hash,
                               embed=lambda samples: vector)
    monkeypatch.setattr("family_harness.identity.SherpaEmbedding", lambda *args: provider)
    monkeypatch.setattr("family_harness.identity.read_voice_wav", lambda *args: np.ones(16000))
    base += ["--people", str(people.path)]
    assert invoke(["identify", "unused.wav"])["person_id"] == person.person_id
    result = invoke(["identify", "unused.wav", "--policy", "strict", "--threshold", "0.2"])
    assert result["person_id"] == person.person_id
    assert result["recognition_policy"]["overrides"] == ["threshold"]
    assert invoke(["identify", "unused.wav", "--policy", "strict"])["person_id"] is None
    assert RecognitionPolicies(path).snapshot()["name"] == "free"


def test_worker_uses_frozen_policy_settings_and_reports_them(tmp_path, monkeypatch, devices):
    from family_harness import people_worker

    provider = SimpleNamespace(backend="titanet-large", model_hash="a" * 64,
                               embed=lambda samples: np.array([0.4, np.sqrt(1 - 0.4**2)]))
    people = PeopleStore(tmp_path / "people.json")
    people.save(VoiceProfile(
        str(uuid4()), "Person", provider.backend, provider.model_hash, [1, 0], 3
    ))
    policy = {"name": "strict", "settings": asdict(MatchSettings(0.575, 0.08)),
              "customized": False, "overrides": []}
    monkeypatch.setattr(people_worker, "SherpaEmbedding", lambda *a: provider)
    monkeypatch.setattr("family_harness.group.SherpaDiarizer", lambda *a: object())
    monkeypatch.setattr("family_harness.asr.load_recognizer", lambda *a: object())
    monkeypatch.setattr("family_harness.devices.discover_native", lambda *a: (devices, []))
    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace())
    monkeypatch.setattr(people_worker, "capture_samples", lambda *a, **k: (np.ones(16000), {}))

    def trial(samples, diarizer, matcher, recognizer, **kwargs):
        assert matcher.settings == MatchSettings(0.575, 0.08)
        assert matcher.identify(samples).person_id is None
        return {"matching_settings": asdict(matcher.settings)}

    monkeypatch.setattr("family_harness.group.group_turns", trial)
    result = people_worker.execute({"kind": "people_trial", "backend": provider.backend,
                                   "models": str(tmp_path), "people": str(people.path),
                                   "recognition_policy": policy, "participation": "all",
                                   "recognizer": "parakeet-v2"}, send=lambda event: None)
    assert result["recognition_policy"] == policy
