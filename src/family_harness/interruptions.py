"""Fast speech onset and cancellable output, independent of ASR and identity."""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Protocol

import numpy as np


class GenerationControl(Protocol):
    def cancel(self, response_id: str) -> None: ...


class GenerationToken:
    """A provider can check/wait on this token without blocking the audio path."""

    def __init__(self, response_id: str):
        self.response_id = response_id
        self.cancelled = threading.Event()

    def cancel(self, response_id: str) -> None:
        if response_id == self.response_id:
            self.cancelled.set()


@dataclass(frozen=True)
class InterruptionSettings:
    hold_seconds: float = 0.08
    release_seconds: float = 0.3

    def __post_init__(self):
        if (not math.isfinite(self.hold_seconds) or not 0 <= self.hold_seconds <= 0.5
                or not math.isfinite(self.release_seconds)
                or not 0.1 <= self.release_seconds <= 1):
            raise ValueError("invalid interruption hold/release timing")


class OnsetDetector:
    """Returns one onset per speech run; no text, identity, or reference input."""

    def __init__(self, vad, settings=None, processor=None):
        self.vad = vad
        self.settings = settings or InterruptionSettings()
        self.processor = processor
        self.active_since = None
        self.silent_since = None
        self.latched = False
        self.previous_end = None
        self.vad_seconds = 0.0

    def accept(self, samples, at, rate=16000):
        if not math.isfinite(at) or at < 0 or rate <= 0:
            raise ValueError("invalid detector timeline")
        if self.previous_end is not None and not math.isclose(at, self.previous_end, abs_tol=1e-5):
            raise ValueError("audio gap: reset the detector before continuing")
        end = at + len(samples) / rate
        self.previous_end = end
        conditioned = self.processor.process(samples) if self.processor else samples
        # Upstream max_speech_duration is a soft segment bound. Reset its retained
        # waveform periodically while preserving our speech-run latch.
        if self.vad_seconds >= 30:
            self.vad.reset()
            self.vad_seconds = 0.0
        self.vad_seconds += len(conditioned) / rate
        active = self.vad.accept(conditioned)
        if active:
            self.silent_since = None
            if self.active_since is None:
                self.active_since = at
            if not self.latched and end - self.active_since + 1e-6 >= self.settings.hold_seconds:
                self.latched = True
                return {"start": self.active_since, "detected_at": end}
        else:
            self.active_since = None
            if self.silent_since is None:
                self.silent_since = at
            if end - self.silent_since + 1e-6 >= self.settings.release_seconds:
                self.latched = False
        return None

    def reset(self):
        self.vad.reset()
        self.active_since = self.silent_since = self.previous_end = None
        self.latched = False
        self.vad_seconds = 0.0


class CancellableOutput:
    """Callback only copies audio. Stop zeros the next block, without draining it.

    Progress uses the DAC clock, never the submitted buffer cursor. A stop can
    confirm queued samples that subsequently reached the DAC, but never more
    than the first zeroed block. Hardware buffering is reported separately.
    """

    def __init__(self, response_id, samples, rate, *, lead_seconds=2):
        samples = np.asarray(samples, np.float32)
        if (samples.ndim != 1 or not len(samples) or not np.isfinite(samples).all()
                or rate <= 0 or not math.isfinite(lead_seconds) or lead_seconds < 0):
            raise ValueError("invalid bounded playback audio")
        self.response_id, self.samples, self.rate = response_id, samples, rate
        self.lead_frames = round(lead_seconds * rate)
        self.cursor = 0
        self.callback_frames = 0
        self.first_dac = None
        self.zeroed_dac = None
        self.stop_requested = False
        self.lock = threading.Lock()

    def write(self, outdata, frames, dac_time):
        with self.lock:
            outdata.fill(0)
            begin = min(frames, max(0, self.lead_frames - self.callback_frames))
            if self.stop_requested:
                if self.zeroed_dac is None:
                    self.zeroed_dac = dac_time
            else:
                count = min(frames - begin, len(self.samples) - self.cursor)
                if count:
                    if self.first_dac is None:
                        self.first_dac = dac_time + begin / self.rate
                    outdata[begin:begin + count] = self.samples[
                        self.cursor:self.cursor + count, None,
                    ]
                    self.cursor += count
            self.callback_frames += frames
            return outdata[:, 0].copy()

    def stop(self, response_id):
        with self.lock:
            if response_id == self.response_id:
                self.stop_requested = True

    def confirmed_seconds(self, now):
        with self.lock:
            if self.first_dac is None:
                return 0.0
            through = min(now, self.zeroed_dac) if self.zeroed_dac is not None else now
            return min(self.cursor / self.rate, max(0, through - self.first_dac))

    @property
    def duration(self):
        return len(self.samples) / self.rate

