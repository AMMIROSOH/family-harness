"""Deterministic, device-free room state. Heavy providers execute returned commands."""

from __future__ import annotations

import math
from collections import Counter, OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class RoomEvent:
    event_id: str
    session_id: str
    source_id: str
    at: float
    kind: str
    data: dict = field(default_factory=dict)

    def validate(self) -> None:
        if not all(
            isinstance(v, str) and 0 < len(v) <= 200
            for v in (self.event_id, self.session_id, self.source_id)
        ) or not isinstance(self.data, dict):
            raise ValueError("events require bounded IDs and an object payload")
        self._time(self.at)
        required = {
            "session_started": (),
            "session_closed": (),
            "audio_gap": (),
            "transcript": ("utterance_id", "revision", "text", "final", "start", "end"),
            "turn_candidate": ("utterance_id", "authority"),
            "utterance_cancelled": ("utterance_id",),
            "response_ready": ("response_id", "text", "duration"),
            "response_cancelled": ("response_id",),
            "playback_progress": ("response_id", "played_seconds"),
            "playback_finished": ("response_id", "played_seconds"),
        }
        if not isinstance(self.kind, str) or self.kind not in required:
            raise ValueError("unsupported room event kind")
        if any(k not in self.data for k in required[self.kind]):
            raise ValueError("unsupported or incomplete room event")
        for key in ("utterance_id", "response_id", "speaker_track", "authority", "language"):
            if key in self.data and (
                not isinstance(self.data[key], str) or not 0 < len(self.data[key]) <= 200
            ):
                raise ValueError(f"invalid {key}")
        if "text" in self.data and (
            not isinstance(self.data["text"], str) or len(self.data["text"]) > 20000
        ):
            raise ValueError("invalid transcript or response text")
        if self.kind == "transcript":
            if type(self.data["revision"]) is not int or self.data["revision"] < 1:
                raise ValueError("revision must be a positive integer")
            if type(self.data["final"]) is not bool:
                raise ValueError("final must be boolean")
            self._time(self.data["start"])
            self._time(self.data["end"])
            if self.data["end"] < self.data["start"] or self.data["end"] > self.at + 1e-6:
                raise ValueError("transcript is outside its source timeline")
        for key in ("duration", "played_seconds"):
            if key in self.data:
                self._time(self.data[key])

    @staticmethod
    def _time(value):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("timestamps must be finite nonnegative seconds")


@dataclass
class Utterance:
    utterance_id: str
    source_id: str
    speaker_track: str
    start: float
    end: float
    language: str = "en"
    revision: int = 0
    text: str = ""
    status: str = "provisional"
    candidate: bool = False
    person_id: str | None = None
    identity_confidence: float | None = None


@dataclass
class Response:
    response_id: str
    utterance_id: str
    status: str = "requested"
    text: str = ""
    duration: float = 0
    played_seconds: float = 0
    # Playback duration is evidence; no word alignment is implied.
    heard_text: str | None = None


class ResponseProvider(Protocol):
    def reply(self, utterance: Utterance) -> str: ...


class DeterministicResponder:
    def reply(self, utterance: Utterance) -> str:
        return "The room replay received your turn."


class RoomManager:
    """One session, one chosen completion authority, arrival-order reduction.

    Revisions are replacements. Finals are immutable. Session IDs, source gap
    watermarks and response IDs reject stale work without calling any provider.
    """

    def __init__(self, session_id: str, room_id: str, *, max_turns: int = 4096):
        if not session_id or not room_id or max_turns < 1:
            raise ValueError("a session, room, and positive capacity are required")
        self.session_id, self.room_id = session_id, room_id
        self.max_turns = max_turns
        self.status = "idle"
        self.utterances: dict[str, Utterance] = {}
        self.responses: dict[str, Response] = {}
        self.gaps: dict[str, float] = {}
        self.seen: OrderedDict[str, None] = OrderedDict()
        self.counts: Counter = Counter()
        self.response_sequence = 0
        self.latest_final_end = -1.0

    def apply(self, event: RoomEvent) -> list[dict]:
        event.validate()
        if event.session_id != self.session_id:
            return self._ignore("wrong_session")
        if event.event_id in self.seen:
            return self._ignore("duplicate")
        self.seen[event.event_id] = None
        if len(self.seen) > 4096:
            self.seen.popitem(last=False)
        if event.kind == "session_started":
            if self.status != "idle":
                return self._ignore("lifecycle")
            self.status = "active"
            return []
        if self.status != "active":
            return self._ignore("inactive")
        self.counts["events"] += 1
        if event.kind == "session_closed":
            self.status = "closed"
            return self._cancel(None)
        if event.kind == "audio_gap":
            self.gaps[event.source_id] = max(event.at, self.gaps.get(event.source_id, 0))
            return self._cancel(event.source_id)
        if event.kind.startswith("response_") or event.kind.startswith("playback_"):
            return self._response(event)
        data = event.data
        uid = data["utterance_id"]
        turn = self.utterances.get(uid)
        if event.at <= self.gaps.get(event.source_id, -1):
            return self._ignore("before_gap")
        if event.kind != "transcript":
            if turn is None or turn.source_id != event.source_id or turn.status != "provisional":
                return self._ignore("stale_turn")
            if event.kind == "utterance_cancelled":
                turn.status = "discarded"
            elif data["authority"] == "vad-silence":
                turn.candidate = True
            else:
                return self._ignore("authority")
            return []
        if data["start"] <= self.gaps.get(event.source_id, -1):
            return self._ignore("before_gap")
        if turn is None:
            if len(self.utterances) >= self.max_turns:
                raise ValueError("room session capacity reached; close and start a new session")
            turn = Utterance(
                uid,
                event.source_id,
                data.get("speaker_track", "unknown"),
                data["start"],
                data["end"],
                data.get("language", "en"),
            )
            self.utterances[uid] = turn
        if turn.source_id != event.source_id or turn.status != "provisional":
            return self._ignore("stale_turn")
        if data["revision"] <= turn.revision or data["end"] < turn.end:
            return self._ignore("stale_revision")
        turn.revision, turn.text, turn.end = data["revision"], data["text"], data["end"]
        if not data["final"]:
            return []
        if not turn.text.strip() or data.get("reason") in ("audio_gap", "cancelled", "room_limit"):
            turn.status = "discarded"
            return []
        turn.status = "final"
        self.counts["final_turns"] += 1
        if turn.end < self.latest_final_end:
            return self._ignore("late_final_response")
        self.latest_final_end = turn.end
        commands = self._cancel_responses()
        self.response_sequence += 1
        rid = f"{self.session_id}:response:{self.response_sequence}"
        self.responses[rid] = Response(rid, uid)
        commands.append({"kind": "response_requested", "response_id": rid, "utterance_id": uid})
        return commands

    def _ignore(self, reason: str) -> list[dict]:
        self.counts[f"ignored_{reason}"] += 1
        return []

    def _cancel_responses(self, source_id: str | None = None) -> list[dict]:
        commands = []
        for response in self.responses.values():
            if response.status in ("requested", "playing") and (
                source_id is None or self.utterances[response.utterance_id].source_id == source_id
            ):
                response.status = "cancelled"
                commands.extend(
                    [
                        {"kind": "cancel_generation", "response_id": response.response_id},
                        {"kind": "stop_playback", "response_id": response.response_id},
                    ]
                )
        return commands

    def _cancel(self, source_id: str | None) -> list[dict]:
        for turn in self.utterances.values():
            if turn.status == "provisional" and (source_id is None or turn.source_id == source_id):
                turn.status = "discarded"
        return self._cancel_responses(source_id)

    def _response(self, event: RoomEvent) -> list[dict]:
        data = event.data
        response = self.responses.get(data["response_id"])
        if response is None or response.status in ("cancelled", "completed"):
            return self._ignore("stale_response")
        if event.kind == "response_cancelled":
            response.status = "cancelled"
            return [
                {"kind": "cancel_generation", "response_id": response.response_id},
                {"kind": "stop_playback", "response_id": response.response_id},
            ]
        if event.kind == "response_ready":
            if response.status != "requested":
                return self._ignore("stale_response")
            response.text, response.duration = data["text"], data["duration"]
            response.status = "playing"
            return [{"kind": "play_response", "response_id": response.response_id}]
        played = data["played_seconds"]
        if (
            response.status != "playing"
            or not response.played_seconds <= played <= response.duration
        ):
            return self._ignore("playback_progress")
        if event.kind == "playback_finished" and not math.isclose(played, response.duration):
            return self._ignore("playback_progress")
        response.played_seconds = played
        if event.kind == "playback_finished":
            response.status = "completed"
            response.heard_text = response.text
        return []

    def snapshot(self, *, include_text: bool = False) -> dict:
        turns, responses = [], []
        for turn in self.utterances.values():
            item = asdict(turn)
            if not include_text:
                item.pop("text")
            turns.append(item)
        for response in self.responses.values():
            item = asdict(response)
            if not include_text:
                item.pop("text")
                item.pop("heard_text")
            responses.append(item)
        return {
            "session_id": self.session_id,
            "room_id": self.room_id,
            "status": self.status,
            "counts": dict(self.counts),
            "utterances": turns,
            "responses": responses,
        }
