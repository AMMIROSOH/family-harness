"""Local voice profiles and open-set matching. Voice similarity never authorizes tools."""

from __future__ import annotations

import json
import math
import wave
from dataclasses import asdict, dataclass, replace
from importlib.resources import files
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

import numpy as np
from platformdirs import user_data_path

from family_harness.errors import SetupError
from family_harness.models import ModelStore
from family_harness.speech import SPEECH_RATE, StreamingResampler

DEFAULT_BACKEND = "titanet-large"


def speaker_catalog(backend: str = DEFAULT_BACKEND) -> dict:
    catalog = json.loads(
        files("family_harness").joinpath("speaker_catalog.json").read_text("utf-8")
    )
    return catalog["profiles"][backend]


def speaker_backends() -> tuple[str, ...]:
    catalog = json.loads(
        files("family_harness").joinpath("speaker_catalog.json").read_text("utf-8")
    )
    return tuple(catalog["profiles"])


def speaker_store(backend=DEFAULT_BACKEND, root=None) -> ModelStore:
    manifest = speaker_catalog(backend)
    prepare = prepare_wespeaker if manifest.get("preparation") else None
    return ModelStore(root, manifest=manifest, prepare=prepare)


def prepare_wespeaker(content: Path):
    """Tell maintained sherpa-onnx to perform WeSpeaker's required feature CMN.

    Only metadata changes. Original download hashes and installed-file hashes are
    recorded separately. This runs during explicit installation, never loading.
    """
    try:
        import onnx
    except ImportError as exc:
        raise identity_error(
            "Repair the installation with uv sync, then retry the model install."
        ) from exc
    model = onnx.load(str(content / "model.onnx"))
    metadata = {p.key: p.value for p in model.metadata_props}
    if metadata.get("framework") != "wespeaker":
        raise ValueError("speaker model is not a WeSpeaker export")
    metadata["feature_normalize_type"] = "global-mean"
    onnx.helper.set_model_props(model, metadata)
    onnx.save(model, str(content / "model.onnx"))


def segmentation_store(root=None) -> ModelStore:
    catalog = json.loads(
        files("family_harness").joinpath("segmentation_catalog.json").read_text("utf-8")
    )
    return ModelStore(root, manifest=catalog)


def identity_error(message: str) -> SetupError:
    return SetupError(
        "voice_identity_invalid",
        message,
        "Use one speaker in a quiet room, record three different phrases, and retry. "
        "Check the selected people file and install the matching speaker model. Audio is off.",
    )


def unit(vector) -> np.ndarray:
    vector = np.asarray(vector, np.float32)
    if vector.ndim != 1 or not 2 <= len(vector) <= 2048 or not np.isfinite(vector).all():
        raise ValueError("invalid voice embedding")
    norm = float(np.linalg.norm(vector))
    if norm < 1e-8:
        raise ValueError("empty voice embedding")
    return vector / norm


def speaker_audio(samples, *, minimum=0.7, maximum=30) -> np.ndarray:
    samples = np.asarray(samples, np.float32)
    if (
        samples.ndim != 1
        or not minimum * SPEECH_RATE <= len(samples) <= maximum * SPEECH_RATE
        or not np.isfinite(samples).all()
        or np.max(np.abs(samples)) > 1.001
    ):
        raise ValueError(f"use finite mono audio lasting {minimum}-{maximum} seconds")
    rms = float(np.sqrt(np.mean(samples**2)))
    if rms < 1e-5:
        raise ValueError("audio is silent or too quiet; check microphone level")
    if np.mean(np.abs(samples) >= 0.999) > 0.01:
        raise ValueError("audio is clipped; lower microphone volume and retry")
    # Normalize quiet files consistently, without clipping or device-setting changes.
    return samples * min(0.05 / rms, 0.95 / float(np.max(np.abs(samples))))


def read_voice_wav(path: Path, *, maximum=30, seconds=None) -> np.ndarray:
    with wave.open(str(path), "rb") as recording:
        rate = recording.getframerate()
        if (
            recording.getnchannels() != 1
            or recording.getsampwidth() != 2
            or recording.getcomptype() != "NONE"
            or not 8000 <= rate <= 48000
        ):
            raise ValueError("choose a PCM16 mono WAV at 8-48 kHz")
        count = recording.getnframes()
        if seconds is not None:
            if not math.isfinite(seconds) or not 0 < seconds <= maximum:
                raise ValueError("invalid audio prefix duration")
            count = min(count, int(rate * seconds))
        if not 0 < count <= rate * maximum:
            raise ValueError(f"choose at most {maximum} seconds of audio")
        raw = recording.readframes(count)
        if len(raw) != count * 2:
            raise ValueError("truncated WAV")
    samples = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
    if rate != SPEECH_RATE:
        samples = StreamingResampler(rate, SPEECH_RATE).resample(samples, flush=True)
    return samples


class EmbeddingProvider(Protocol):
    backend: str
    model_hash: str

    def embed(self, samples: np.ndarray) -> np.ndarray: ...


class SherpaEmbedding:
    def __init__(self, backend=DEFAULT_BACKEND, root=None):
        import sherpa_onnx

        store = speaker_store(backend, root)
        try:
            record = store.verify()
        except SetupError as exc:
            raise identity_error(
                f"Install the {backend} speaker model with people install-model first."
            ) from exc
        self.backend = backend
        self.source_model_hash = store.catalog["assets"][0]["sha256"]
        self.model_hash = next(
            item["sha256"] for item in record["files"] if item["path"] == "model.onnx"
        )
        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(store.profile / "model.onnx"),
            num_threads=2,
            provider="cpu",
        )
        self.engine = sherpa_onnx.SpeakerEmbeddingExtractor(config)

    def embed(self, samples: np.ndarray) -> np.ndarray:
        samples = speaker_audio(samples)
        stream = self.engine.create_stream()
        stream.accept_waveform(SPEECH_RATE, samples)
        stream.input_finished()
        if not self.engine.is_ready(stream):
            raise ValueError("not enough usable speech for speaker matching")
        return unit(self.engine.compute(stream))


@dataclass(frozen=True)
class VoiceProfile:
    person_id: str
    name: str
    backend: str
    model_hash: str
    embedding: list[float]
    samples: int

    def validate(self):
        if not isinstance(self.person_id, str):
            raise ValueError("invalid person ID")
        UUID(self.person_id)
        if (
            not isinstance(self.name, str)
            or not 0 < len(self.name.strip()) <= 120
            or not isinstance(self.backend, str)
            or not 0 < len(self.backend) <= 100
            or not isinstance(self.model_hash, str)
            or len(self.model_hash) != 64
            or any(c not in "0123456789abcdef" for c in self.model_hash)
            or type(self.samples) is not int
            or not 3 <= self.samples <= 8
        ):
            raise ValueError("invalid voice profile")
        unit(self.embedding)


class PeopleStore:
    """Explicit saves of embeddings only; no audio/transcript retention or model migration."""

    def __init__(self, path: Path | None = None):
        self.path = path or user_data_path("FamilyHarness", appauthor=False) / "people.json"

    def load(self) -> list[VoiceProfile]:
        try:
            if not self.path.exists():
                return []
            if self.path.stat().st_size > 2_000_000:
                raise ValueError("oversized people file")
            data = json.loads(self.path.read_text("utf-8"))
            if data["version"] != 1 or not isinstance(data["people"], list):
                raise ValueError("unsupported people file")
            if len(data["people"]) > 64:
                raise ValueError("too many profiles")
            profiles = [VoiceProfile(**item) for item in data["people"]]
            for profile in profiles:
                profile.validate()
            if len({p.person_id for p in profiles}) != len(profiles):
                raise ValueError("duplicate person IDs")
            return profiles
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise identity_error("The local people file is damaged or unsupported.") from exc

    def public(self) -> list[dict]:
        return [{k: v for k, v in asdict(p).items() if k != "embedding"} for p in self.load()]

    def save(self, profile: VoiceProfile):
        profile.validate()
        profiles = self.load()
        prior = next((p for p in profiles if p.person_id == profile.person_id), None)
        if prior and (prior.backend, prior.model_hash) != (profile.backend, profile.model_hash):
            raise identity_error("Remove the previous profile before changing its model.")
        profiles = [p for p in profiles if p.person_id != profile.person_id] + [profile]
        if len(profiles) > 64:
            raise identity_error("Remove an unused person before enrolling another.")
        self._write(profiles)

    def remove(self, person_id: str):
        UUID(person_id)
        self._write([p for p in self.load() if p.person_id != person_id])

    def _write(self, profiles):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Unique same-directory temporary avoids collisions between explicit CLI/UI saves.
        temporary = self.path.with_name(f".{self.path.name}.{uuid4()}.tmp")
        try:
            temporary.write_text(
                json.dumps(
                    {"version": 1, "people": [asdict(p) for p in profiles]},
                    ensure_ascii=False,
                    allow_nan=False,
                ),
                "utf-8",
            )
            temporary.replace(self.path)
        except OSError as exc:
            raise identity_error(
                "The people file could not be saved; check folder permissions."
            ) from exc
        finally:
            temporary.unlink(missing_ok=True)


def enrollment(provider, samples, name: str, *, person_id=None) -> tuple[VoiceProfile, dict]:
    if not isinstance(name, str) or not 0 < len(name.strip()) <= 120:
        raise ValueError("enter a person name, at most 120 characters")
    if not 3 <= len(samples) <= 8:
        raise ValueError("record three to eight different phrases")
    vectors = [provider.embed(speaker_audio(s, minimum=2)) for s in samples]
    if len({len(v) for v in vectors}) != 1:
        raise ValueError("inconsistent embedding dimensions")
    similarities = [float(a @ b) for i, a in enumerate(vectors) for b in vectors[i + 1 :]]
    if float(np.mean(similarities)) < 0.15 or min(similarities) < -0.1:
        raise identity_error("The phrases do not consistently sound like one speaker.")
    profile = VoiceProfile(
        person_id or str(uuid4()),
        name.strip(),
        provider.backend,
        provider.model_hash,
        unit(np.mean(vectors, axis=0)).tolist(),
        len(vectors),
    )
    profile.validate()
    return profile, {
        "phrases": len(vectors),
        "phrase_seconds": [round(len(s) / SPEECH_RATE, 3) for s in samples],
        "minimum_similarity": round(min(similarities), 4),
        "mean_similarity": round(float(np.mean(similarities)), 4),
    }


@dataclass(frozen=True)
class MatchSettings:
    threshold: float = 0.3
    margin: float = 0.08
    minimum_seconds: float = 0.7

    def __post_init__(self):
        if (
            any(type(value) not in (int, float)
                for value in (self.threshold, self.margin, self.minimum_seconds))
            or not 0 <= self.threshold <= 1
            or not 0 <= self.margin <= 1
            or not 0.5 <= self.minimum_seconds <= 5
        ):
            raise ValueError("invalid speaker matching settings")


def matching_settings(backend, *, threshold=None, margin=None, minimum_seconds=None):
    # Home preview: restore recognition coverage; uncertainty still uses a runner-up margin.
    # Development sessions S02/S04/S05/S09/S10. Strict TitaNet remains an explicit override.
    base = MatchSettings()
    overrides = {
        name: value
        for name, value in (
            ("threshold", threshold), ("margin", margin), ("minimum_seconds", minimum_seconds)
        )
        if value is not None
    }
    return replace(base, **overrides)


@dataclass(frozen=True)
class IdentityDecision:
    person_id: str | None
    score: float | None
    margin: float | None
    state: str


class VoiceMatcher:
    def __init__(self, provider, profiles, settings=None):
        self.provider, self.settings = provider, settings or matching_settings(provider.backend)
        self.profiles = list(profiles)
        if len(self.profiles) > 64 or len({p.person_id for p in self.profiles}) != len(
            self.profiles
        ):
            raise ValueError("invalid profile set")
        for profile in self.profiles:
            profile.validate()
            if (profile.backend, profile.model_hash) != (provider.backend, provider.model_hash):
                raise identity_error(
                    "An enrolled voice uses a different speaker model. Re-enroll it."
                )

    def match_vector(self, vector) -> IdentityDecision:
        vector = unit(vector)
        if not self.profiles:
            return IdentityDecision(None, None, None, "not_enrolled")
        scores = sorted(
            ((float(vector @ unit(p.embedding)), p.person_id) for p in self.profiles), reverse=True
        )
        score, person_id = scores[0]
        margin = score - scores[1][0] if len(scores) > 1 else score + 1
        score = max(-1.0, min(1.0, score))
        if score < self.settings.threshold:
            return IdentityDecision(None, score, margin, "unknown")
        if margin <= 0 or margin < self.settings.margin:
            return IdentityDecision(None, score, margin, "ambiguous")
        return IdentityDecision(person_id, score, margin, "matched")

    def identify(self, samples, *, overlap=False) -> IdentityDecision:
        if overlap:
            return IdentityDecision(None, None, None, "overlap")
        if len(samples) < self.settings.minimum_seconds * SPEECH_RATE:
            return IdentityDecision(None, None, None, "insufficient_audio")
        try:
            return self.match_vector(self.provider.embed(samples))
        except ValueError:
            return IdentityDecision(None, None, None, "unusable_audio")
