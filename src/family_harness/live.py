"""Bounded live diagnostics. Audio/VAD never wait for identity or whole-turn ASR."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import asdict
from uuid import uuid4

import numpy as np

from family_harness.errors import SetupError
from family_harness.group import turn_regions
from family_harness.identity import IdentityDecision, unit
from family_harness.interruptions import CancellableOutput, GenerationToken
from family_harness.room import RoomEvent, RoomManager
from family_harness.speech import SPEECH_RATE

REPLY = ("The local room test received your turn.",
         "Please interrupt my voice, or let another person continue.")


def overloaded():
    return SetupError("live_overload", "This PC cannot keep up with this live take.",
                      "Stop, select a lighter installed recognizer, shorten the take, or close "
                      "busy applications. Missing audio is discarded; listening never restarts.")


class LiveSession:
    def __init__(self, send, samples, rate, alignment, participation="all", *, replies=True,
                 room_id="live-lab"):
        self.send = send
        self.manager = RoomManager(str(uuid4()), room_id, participation=participation,
                                   max_turns=256)
        self.lock = threading.RLock()
        self.sequence = 0
        self.audio, self.rate, self.alignment = samples, rate, alignment
        self.replies = replies
        self.output = None
        self.outputs = []
        self.tokens = {}
        self.last_tick = -1.0
        self.latest_at = 0.0
        self.command_counts = {}
        self.stop_delays = []
        self.stop_clocks = {}
        self.apply("session_started", 0)

    def apply(self, kind, at, data=None, *, source="native"):
        with self.lock:
            self.latest_at = max(self.latest_at, at)
            self.sequence += 1
            event = RoomEvent(f"live-{self.sequence}", self.manager.session_id, source,
                              at, kind, data or {})
            commands = self.manager.apply(event)
            self.send({"type": "room_event", **asdict(event),
                       "processing_time": time.monotonic(), "commands": commands})
            for command in commands:
                name, rid = command["kind"], command["response_id"]
                self.command_counts[name] = self.command_counts.get(name, 0) + 1
                if name == "stop_playback":
                    for output in self.outputs:
                        output.stop(rid)
                    self.stop_clocks.setdefault(rid, self.clock if hasattr(self, "clock") else None)
                elif name == "cancel_generation" and rid in self.tokens:
                    self.tokens[rid].cancel(rid)
                elif name == "response_requested":
                    self.tokens[rid] = GenerationToken(rid)
                    if self.replies or not command["utterance_id"]:
                        output = CancellableOutput(rid, self.audio, self.rate, lead_seconds=0)
                        self.output = output
                        self.outputs.append(output)
                        self.apply("response_ready", at, {
                            "response_id": rid, "text": " ".join(REPLY),
                            "duration": output.duration, "alignment": self.alignment,
                        }, source="output")
                    else:
                        self.apply("response_cancelled", at, {"response_id": rid}, source="output")
            self.snapshot()
            return commands

    def snapshot(self):
        self.send({"type": "room_snapshot", "room": self.manager.snapshot(include_text=True)})

    def write(self, outdata, frames, dac_time):
        output = self.output  # Atomic reference read; no reducer/inference in the callback.
        if output is None:
            outdata.fill(0)
            return outdata[:, 0].copy()
        return output.write(outdata, frames, dac_time)

    def stop_output(self):
        for output in tuple(self.outputs):
            output.stop(output.response_id)

    def tick(self, clock, at):
        with self.lock:
            self.clock = clock
            if at - self.last_tick < 0.1:
                return
            self.last_tick = at
            for output in tuple(self.outputs):
                response = self.manager.responses[output.response_id]
                played = output.confirmed_seconds(clock)
                if response.status == "playing":
                    kind = "playback_finished" if played >= output.duration else "playback_progress"
                    self.apply(kind, at, {"response_id": output.response_id,
                                         "played_seconds": played}, source="output")
                elif response.status == "cancelled" and not response.playback_stopped \
                        and output.zeroed_dac is not None:
                    self.apply("playback_stopped", at, {"response_id": output.response_id,
                                                       "played_seconds": played}, source="output")
                    started = self.stop_clocks.get(output.response_id)
                    if started is not None:
                        self.stop_delays.append(max(0, (output.zeroed_dac - started) * 1000))


class IncrementalAttributor:
    """Windowed maintained segmentation, conservative identity, local track reconciliation.

    Window clustering is not continuous source separation. Mixed/overlap evidence
    stays unnamed. Track similarity is an unvalidated diagnostic heuristic.
    """

    def __init__(self, diarizer, matcher):
        self.diarizer, self.matcher = diarizer, matcher
        self.tracks = []

    def identify(self, audio):
        regions = turn_regions(self.diarizer.segments(audio))
        if not regions:
            return IdentityDecision(None, None, None, "insufficient_audio"), "unknown"
        if any(overlap for _, overlap in regions):
            return IdentityDecision(None, None, None, "overlap"), "overlap"
        if len({segment.track for segment, _ in regions}) > 1:
            return IdentityDecision(None, None, None, "ambiguous"), "mixed-voices"
        speech = np.concatenate([
            audio[int(segment.start * SPEECH_RATE):int(segment.end * SPEECH_RATE)]
            for segment, _ in regions
        ])
        if len(speech) < self.matcher.settings.minimum_seconds * SPEECH_RATE:
            return IdentityDecision(None, None, None, "insufficient_audio"), "unknown"
        try:
            vector = unit(self.matcher.provider.embed(speech))
        except ValueError:
            return IdentityDecision(None, None, None, "unusable_audio"), "unknown"
        identity = self.matcher.match_vector(vector)
        scores = [float(vector @ v) for v in self.tracks]
        if scores and max(scores) >= 0.75:
            track = int(np.argmax(scores))
        else:
            if len(self.tracks) >= 64:
                return identity, "unknown"
            track = len(self.tracks)
            self.tracks.append(vector)
        return identity, f"speaker-{track + 1}"


class LivePipeline:
    """Two bounded background lanes: streaming drafts and heavier evidence/finals."""

    def __init__(self, session, stt, finalizer, attributor, settings):
        self.session, self.stt, self.finalizer = session, stt, finalizer
        self.attributor, self.settings = attributor, settings
        self.frames = queue.Queue(maxsize=100)
        self.analysis = queue.Queue(maxsize=2)
        self.closed = threading.Event()
        self.failure = None
        self.frame_times = []
        self.analysis_times = []
        self.partial_ms, self.completion_ms, self.stream_queue_ms = [], [], []
        self.streaming = threading.Thread(target=self._stream, daemon=True, name="live-drafts")
        self.analyzing = threading.Thread(target=self._analyze, daemon=True, name="live-evidence")
        self.streaming.start()
        self.analyzing.start()

    def accept(self, audio, at, active):
        if self.failure:
            raise self.failure
        try:
            self.frames.put_nowait((audio.copy(), at, active, time.perf_counter()))
        except queue.Full as exc:
            self.session.stop_output()
            raise overloaded() from exc

    def _stream(self):
        uid, start, last_speech, last_probe = None, 0, 0, 0
        chunks, count, idle = [], 0, 0
        lead = np.empty(0, np.float32)
        speech_begin, partial_seen = 0, False
        try:
            while not self.closed.is_set():
                try:
                    audio, at, active, received = self.frames.get(timeout=0.1)
                except queue.Empty:
                    continue
                before = time.perf_counter()
                queue_ms = (before-received)*1000
                end = at + len(audio) / SPEECH_RATE
                text = self.stt.accept(audio).strip()
                if active and uid is None:
                    uid, start, last_probe = str(uuid4()), max(0, at-len(lead)/SPEECH_RATE), at
                    chunks, count = [lead.copy()] if len(lead) else [], len(lead)
                    speech_begin, partial_seen = at, False
                    # The recognizer has received all onset samples, including VAD lead-in.
                if uid is None:
                    lead = np.concatenate((lead, audio))[-int(.8 * SPEECH_RATE):]
                    idle += len(audio)
                    if idle >= 5 * SPEECH_RATE:
                        self.stt.reset()
                        idle = 0
                    continue
                if active:
                    last_speech = end
                if text and not partial_seen:
                    self.partial_ms.append((end-speech_begin)*1000+queue_ms)
                    partial_seen = True
                forced = end - start >= 30
                finished = end - last_speech >= self.settings.silence or forced
                probe = self.attributor is not None and end - last_probe >= 2
                room = self.session
                with room.lock:
                    turn = room.manager.utterances.get(uid)
                    revision = turn.revision + 1 if turn else 1
                    speech_end = max(start, last_speech)
                    if (turn is None or text != turn.text or speech_end - turn.end >= 0.5
                            or finished or probe):
                        room.apply("transcript", end, {"utterance_id": uid, "revision": revision,
                            "text": text, "final": False, "start": start, "end": speech_end})
                if count < 30 * SPEECH_RATE:
                    piece = audio[:30 * SPEECH_RATE - count]
                    chunks.append(piece)
                    count += len(piece)
                if finished:
                    draft = self.stt.finish().strip()
                    room.apply("turn_candidate", end, {"utterance_id": uid,
                                                       "authority": "vad-silence"})
                    self._submit((uid, start, end, np.concatenate(chunks), draft, True, forced,
                                  last_speech, time.perf_counter(), queue_ms))
                    self.stt.reset()
                    uid, chunks, count, idle = None, [], 0, 0
                    lead = np.empty(0, np.float32)
                elif probe and count:
                    # Bounded rolling windows; final tasks are never dropped or superseded.
                    if not self.analysis.full():
                        window = np.concatenate(chunks)[-6 * SPEECH_RATE:]
                        self._submit((uid, max(start, end-len(window)/SPEECH_RATE), end,
                                      window, text, False, False, last_speech,
                                      time.perf_counter(), queue_ms))
                        last_probe = end
                self.frame_times.append((time.perf_counter() - before) * 1000)
                self.frame_times = self.frame_times[-18000:]
                self.stream_queue_ms.append(queue_ms)
                self.stream_queue_ms = self.stream_queue_ms[-18000:]
        except Exception as exc:
            self.failure = exc
            self.session.stop_output()

    def _submit(self, task):
        try:
            self.analysis.put_nowait(task)
        except queue.Full as exc:
            raise overloaded() from exc

    def _analyze(self):
        try:
            while not self.closed.is_set():
                try:
                    (uid, start, end, audio, draft, final, forced, speech_end,
                     queued, stream_lag) = self.analysis.get(timeout=0.1)
                except queue.Empty:
                    continue
                before = time.perf_counter()
                identity, track = (self.attributor.identify(audio) if self.attributor else
                                   (IdentityDecision(None, None, None, "not_enrolled"), "unknown"))
                text = self.finalizer.decode(audio).strip() if final and self.finalizer else draft
                lag = (time.perf_counter() - before) * 1000
                self.analysis_times.append(lag)
                with self.session.lock:
                    manager = self.session.manager
                    turn = manager.utterances.get(uid)
                    if self.closed.is_set() or manager.status != "active" or turn is None:
                        continue
                    if turn.status != "provisional":
                        continue
                    self.session.apply("attribution", end, {
                        "utterance_id": uid, "revision": turn.attribution_revision + 1,
                        "speaker_track": track, "person_id": identity.person_id,
                        "score": identity.score, "state": identity.state,
                        "start": start, "end": min(end, turn.end),
                        "backend": self.attributor.matcher.provider.backend
                        if self.attributor else "none",
                        "model_hash": self.attributor.matcher.provider.model_hash
                        if self.attributor else "none",
                    })
                    self.session.send({"type": "progress", "phase": "live_listening",
                                       "identity_analysis_ms": round(lag, 1),
                                       "analysis_pending": self.analysis.qsize()})
                    if final:
                        self.session.apply("transcript", end, {
                            "utterance_id": uid, "revision": turn.revision + 1,
                            "text": "" if identity.state == "overlap" else text,
                            "final": True, "start": turn.start, "end": turn.end,
                            "reason": "room_limit" if forced else "silence_candidate",
                        })
                        if forced:
                            turn.recovery = "Thirty-second boundary reached. Pause and repeat."
                            self.session.snapshot()
                        self.completion_ms.append((end-speech_end)*1000+stream_lag
                                                  +(time.perf_counter()-queued)*1000)
        except Exception as exc:
            self.failure = exc
            self.session.stop_output()

    def close(self):
        self.closed.set()
        self.session.stop_output()
        self.streaming.join(timeout=1)
        self.analyzing.join(timeout=1)


def capture_live(request, devices, sd, voice, session, pipeline, detector, send):
    """Fast duplex lane; inference callbacks and queues have independent hard stops."""
    from family_harness.audio import BUFFER_FRAMES, AudioClock, AudioFrame, WebRtcEcho, dbfs
    from family_harness.devices import resolve
    from family_harness.speech import StreamingResampler, speech_input

    microphone = resolve(devices, request["input_id"], "input")
    speaker = resolve(devices, request["output_id"], "output")
    rate = session.rate
    echo = WebRtcEcho(rate) if request["echo_owner"] == "software" else None
    processor = speech_input(voice.settings)
    resampler = StreamingResampler(rate, SPEECH_RATE) if rate != SPEECH_RATE else None
    frames = queue.Queue(maxsize=BUFFER_FRAMES)
    fault = threading.Event()
    sequence, origin, at, max_queue, last_progress = 0, None, 0.0, 0.0, -1.0
    clock = AudioClock()
    duration = request["seconds"]

    def transfer(indata, outdata, count, timing, status):
        nonlocal sequence
        played = session.write(outdata, count, timing.outputBufferDacTime)
        frame = AudioFrame(request["endpoint_id"], sequence, rate, timing.inputBufferAdcTime,
                           timing.outputBufferDacTime, indata[:, 0].copy(), played, bool(status))
        try:
            frames.put_nowait((frame, time.perf_counter()))
        except queue.Full:
            fault.set()
        sequence += 1
        if fault.is_set() or sequence >= duration * 100:
            session.stop_output()
            outdata.fill(0)
            if hasattr(sd, "CallbackAbort"):
                raise sd.CallbackAbort

    options = sd.WasapiSettings(auto_convert=True)
    stream = sd.Stream(samplerate=rate, blocksize=rate//100,
                       device=(microphone.index, speaker.index), channels=(1, speaker.channels),
                       dtype="float32", latency="low", extra_settings=(options, options),
                       callback=transfer)
    deadline = time.monotonic() + duration + 4
    cue_sent = False
    processed = 0
    try:
        with stream:
            while at < duration and time.monotonic() < deadline:
                try:
                    frame, received = frames.get(timeout=0.5)
                except queue.Empty as exc:
                    raise SetupError("live_stalled", "The device stopped sending audio.",
                                     "Reconnect, refresh and explicitly start a new take.") from exc
                origin = frame.capture_time if origin is None else origin
                at = frame.capture_time - origin
                if (clock.observe(frame) or fault.is_set()
                        or (not stream.active and at < duration-.1)):
                    session.apply("audio_gap", max(0, at))
                    raise overloaded()
                queue_ms = (time.perf_counter() - received) * 1000
                max_queue = max(max_queue, queue_ms)
                clean = echo.process(frame.samples, frame.played,
                    round((frame.playback_time-frame.capture_time)*1000)) if echo else frame.samples
                clean = np.asarray(resampler.resample(clean), np.float32) if resampler else clean
                conditioned = processor.process(clean) if processor else clean
                if not len(conditioned):
                    continue
                timeline = processed / SPEECH_RATE
                processed += len(conditioned)
                onset = detector.accept(conditioned, timeline)
                session.clock = getattr(stream, "time", frame.capture_time)
                if onset:
                    session.apply("speech_started", onset["detected_at"], {"start": onset["start"]})
                pipeline.accept(conditioned, timeline, detector.speech_active)
                session.tick(session.clock, at)
                if (not cue_sent and at >= 2 and not detector.speech_active
                        and not detector.latched and request["scenario"] in (
                    "interruptions", "quiet-playback",
                )):
                    session.apply("test_cue", at, source="control")
                    cue_sent = True
                if at-last_progress >= 0.1:
                    send({"type": "progress", "phase": "live_listening", "seconds": at,
                          "duration": duration,
                          "level_dbfs": dbfs(float(np.mean(frame.samples**2))),
                          "processed_level_dbfs": dbfs(float(np.mean(conditioned**2))),
                          "speech_active": detector.speech_active, "capture_queue_ms": queue_ms,
                          "analysis_pending": pipeline.analysis.qsize(),
                          "microphone_on": True, "speaker_on": bool(session.output and
                          not session.output.stop_requested and
                          session.output.cursor < len(session.output.samples))})
                    last_progress = at
                if at+len(conditioned)/SPEECH_RATE >= duration:
                    break
    finally:
        session.stop_output()
        stream.abort() if hasattr(stream, "abort") else None
        stream.close()
        session.apply("session_closed", max(at, session.latest_at))
        send({"type": "progress", "phase": "releasing", "microphone_on": False,
              "speaker_on": False, "seconds": at, "duration": duration})
        pipeline.close()
    if pipeline.failure:
        raise pipeline.failure
    if time.monotonic() >= deadline:
        raise overloaded()
    return {"audio_seconds": at, "max_capture_queue_ms": max_queue, "audio_gaps": 0,
            "cue_played": cue_sent,
            "devices": {"input": microphone.public(), "output": speaker.public()}}
