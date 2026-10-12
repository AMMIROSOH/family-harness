from types import SimpleNamespace

import numpy as np
import pytest

from family_harness.speech import (
    RECOGNIZER_LEAD_IN,
    GainSpeechInput,
    LocalVoice,
    SherpaStt,
    SpeechTurn,
    StreamingResampler,
    VoiceSettings,
    WebRtcSpeechInput,
)


class FakeVad:
    def __init__(self, speech_chunks=10):
        self.remaining = speech_chunks

    def accept(self, samples):
        self.remaining -= 1
        return self.remaining >= 0


class FakeStt:
    def __init__(self):
        self.count = 0
        self.finished = 0

    def accept(self, samples):
        self.count += 1
        return "hello" if self.count < 5 else "hello room"

    def finish(self):
        self.finished += 1
        return "hello room"


def test_partial_replacements_final_revision_and_single_completion_candidate():
    events = []
    stt = FakeStt()
    turn = SpeechTurn(FakeVad(), stt, events.append)
    for i in range(100):
        if turn.accept(np.zeros(160, np.float32), i / 100):
            break
    transcripts = [e for e in events if e["type"] == "transcript"]
    assert [e["text"] for e in transcripts] == ["hello", "hello room", "hello room"]
    assert [e["revision"] for e in transcripts] == [1, 2, 3]
    assert transcripts[-1]["final"] and transcripts[-1]["reason"] == "silence_candidate"
    assert len({e["utterance_id"] for e in transcripts}) == 1
    assert len([e for e in events if e["type"] == "turn_candidate"]) == 1
    assert 600 <= turn.candidate_latency < 800
    assert turn.accept(np.ones(160, np.float32), 1)
    turn.finish(2, "end")
    assert stt.finished == 1


def test_short_pause_does_not_end_but_deadline_is_not_a_candidate():
    turn = SpeechTurn(FakeVad(), FakeStt(), lambda event: None)
    for i in range(40):
        assert not turn.accept(np.zeros(160, np.float32), i / 100)
    turn.finish(0.4, "trial_limit")
    assert turn.candidate_latency is None
    assert turn.ended


def test_silence_suppresses_recognizer_hallucinations():
    events = []
    stt = FakeStt()
    turn = SpeechTurn(FakeVad(0), stt, events.append)
    for i in range(100):
        assert not turn.accept(np.zeros(160, np.float32), i / 100)
    turn.finish(1, "trial_limit")
    assert turn.text == "" and stt.finished == 0
    assert events == [
        {
            "type": "transcript",
            "utterance_id": turn.utterance_id,
            "revision": 1,
            "text": "",
            "final": True,
            "language": "en",
            "start": None,
            "end": 1,
            "reason": "trial_limit",
        }
    ]


def test_final_recognizer_corrects_drafts_once_with_bounded_conditioned_audio():
    events, received = [], []
    finalizer = SimpleNamespace(
        decode=lambda audio: received.append(audio.copy()) or "correct final"
    )
    stt = FakeStt()
    turn = SpeechTurn(
        FakeVad(), stt, events.append, finalizer=finalizer, processor=GainSpeechInput(6),
    )
    for i in range(100):
        if turn.accept(np.full(160, .1, np.float32), i / 100):
            break
    turn.finish(2, "replay_eof")
    assert turn.text == "correct final" and stt.finished == 0
    assert len(received) == 1 and not turn.final_samples
    np.testing.assert_allclose(received[0], .1 * 10 ** (6 / 20), rtol=1e-6)
    finals = [e for e in events if e.get("final")]
    assert len(finals) == 1 and finals[0]["reason"] == "silence_candidate"


def test_final_recognizer_can_finish_without_draft_but_never_without_vad():
    for activity in (0, 10):
        received, events = [], []
        empty = SimpleNamespace(accept=lambda s: "", finish=lambda: "")
        finalizer = SimpleNamespace(decode=lambda s, r=received: r.append(s) or "recognized")
        turn = SpeechTurn(FakeVad(activity), empty, events.append, finalizer=finalizer)
        for i in range(100):
            if turn.accept(np.ones(160, np.float32), i / 100):
                break
        turn.finish(1, "replay_eof")
        assert bool(received) == bool(activity)
        assert bool(turn.text) == bool(activity)
        if activity:
            transcripts = [e for e in events if e["type"] == "transcript"]
            assert not transcripts[0]["final"] and transcripts[0]["text"] == ""
            assert transcripts[-1]["final"] and transcripts[-1]["revision"] == 2


def test_deferred_finalization_stops_accepting_until_explicit_finish():
    received = []
    turn = SpeechTurn(
        FakeVad(), FakeStt(), lambda e: None, defer_finalization=True,
        finalizer=SimpleNamespace(decode=lambda s: received.append(s) or "final"),
    )
    for i in range(100):
        if turn.accept(np.zeros(160, np.float32), i / 100):
            break
    assert not received and not turn.ended and turn.candidate_end is not None
    count = turn.final_sample_count
    assert turn.accept(np.ones(160, np.float32), 1)
    assert turn.final_sample_count == count
    turn.finish(turn.candidate_end, "silence_candidate")
    assert len(received) == 1 and turn.ended and turn.candidate_latency >= 600


def test_final_audio_memory_never_exceeds_30_seconds():
    received = []
    turn = SpeechTurn(
        FakeVad(100), FakeStt(), lambda e: None,
        finalizer=SimpleNamespace(decode=lambda s: received.append(s) or "final"),
    )
    for i in range(35):
        turn.accept(np.ones(16000, np.float32), i)
    assert turn.final_sample_count == 30 * 16000
    turn.finish(35, "segment_limit")
    assert len(received[0]) == 30 * 16000


@pytest.mark.parametrize("rate", [8000, 44100, 48000])
def test_streaming_resampler_preserves_duration_and_finite_audio(rate):
    resampler = StreamingResampler(rate, 16000)
    signal = np.sin(np.arange(rate, dtype=np.float32) * 2 * np.pi * 440 / rate) * 0.1
    output = [resampler.resample(signal[i : i + 1000]) for i in range(0, rate, 1000)]
    output.append(resampler.resample(np.empty(0, np.float32), flush=True))
    samples = np.concatenate(output)
    assert len(samples) == 16000
    assert np.isfinite(samples).all()
    assert 0.06 < np.sqrt(np.mean(samples**2)) < 0.08


def test_speech_conditioning_keeps_chunk_boundaries_and_final_tail():
    # Irregular SoXR output chunks must not be padded between live frames.
    samples = np.random.default_rng(7).normal(0, 0.003, 3207).astype(np.float32)
    reference = WebRtcSpeechInput()
    expected = np.concatenate(
        (reference.process(samples), reference.process(np.empty(0, np.float32), flush=True))
    )
    processor = WebRtcSpeechInput()
    chunks = [processor.process(samples[i : i + 97]) for i in range(0, len(samples), 97)]
    chunks.append(processor.process(np.empty(0, np.float32), flush=True))
    output = np.concatenate(chunks)
    assert len(output) == len(samples)
    np.testing.assert_allclose(output, expected, atol=1e-7)
    assert processor.raw.count == processor.clean.count == len(samples)
    assert not len(processor.process(np.empty(0, np.float32), flush=True))


def test_speech_conditioning_preserves_silence_and_limits_loud_input():
    processor = WebRtcSpeechInput()
    silent = processor.process(np.zeros(16000, np.float32))
    assert not np.any(silent)
    loud = processor.process(np.ones(16000, np.float32))
    assert np.isfinite(loud).all() and np.max(np.abs(loud)) <= 1
    diagnostics = processor.diagnostics()
    assert diagnostics["raw"]["clipping_fraction"] == 0.5
    assert diagnostics["max_observed_gain_db"] <= 30


def test_both_models_receive_conditioned_input_and_tail_on_correct_timeline():
    class Gain:
        def __init__(self):
            self.pending = np.empty(0, np.float32)

        def process(self, samples, flush=False):
            joined = np.concatenate((self.pending, samples))
            count = len(joined) if flush else len(joined) // 160 * 160
            self.pending = joined[count:]
            return joined[:count] * 10

    class Vad:
        def __init__(self):
            self.received = []

        def accept(self, samples):
            self.received.append(samples.copy())
            return np.max(np.abs(samples)) >= 0.01

    class Stt(FakeStt):
        def __init__(self):
            super().__init__()
            self.received = []

        def accept(self, samples):
            self.received.append(samples.copy())
            return "quiet speech" if np.max(np.abs(samples)) >= 0.01 else ""

    events, vad, stt = [], Vad(), Stt()
    turn = SpeechTurn(vad, stt, events.append, processor=Gain())
    samples = np.full(207, 0.002, np.float32)
    assert not turn.accept(samples[:97], 0)
    assert not turn.accept(samples[97:], 97 / 16000)
    turn.finish(207 / 16000, "replay_eof")
    np.testing.assert_allclose(np.concatenate(vad.received), samples * 10)
    np.testing.assert_allclose(np.concatenate(stt.received), samples * 10)
    assert turn.started == 0 and turn.last_speech == pytest.approx(207 / 16000)
    assert any(e.get("text") == "quiet speech" for e in events)


def test_empty_activity_does_not_end_trial_before_later_recognizable_speech():
    class Vad:
        def accept(self, samples):
            return bool(np.any(samples))

    class Stt:
        def __init__(self):
            self.text = ""

        def accept(self, samples):
            if np.max(samples) > 0.05:
                self.text = "hello room"
            return self.text

        def finish(self):
            return self.text

    events = []
    turn = SpeechTurn(Vad(), Stt(), events.append)
    for i in range(300):
        level = 0.001 if i < 10 else 0.1 if 150 <= i < 200 else 0
        done = turn.accept(np.full(160, level, np.float32), i / 100)
        if i < 200:
            assert not done
        if done:
            break
    assert turn.text == "hello room" and turn.ended
    assert len([e for e in events if e["type"] == "turn_candidate"]) == 1


def test_conditioned_replay_preserves_nonzero_source_origin():
    events = []
    turn = SpeechTurn(FakeVad(), FakeStt(), events.append, processor=WebRtcSpeechInput())
    turn.accept(np.zeros(160, np.float32), 12)
    turn.finish(12.01, "replay_eof")
    assert turn.started == 12 and turn.last_speech == pytest.approx(12.01)
    assert events[-1]["start"] == 12


def test_explicit_input_calibration_is_bounded_and_reports_clipping():
    processor = GainSpeechInput(24)
    samples = np.array([0, 0.001, 0.5], np.float32)
    output = processor.process(samples)
    assert output[0] == 0 and output[1] == pytest.approx(0.01584893)
    assert output[2] == 1
    assert processor.diagnostics()["processed"]["clipping_fraction"] == 0.33333
    with pytest.raises(ValueError):
        VoiceSettings(gain_db=100)


def test_delayed_activity_confirmation_keeps_first_word_in_recognizer_input():
    class DelayedVad:
        def __init__(self):
            self.count = 0

        def accept(self, samples):
            self.count += 1
            return 20 <= self.count <= 60

    class Recognizer:
        def __init__(self):
            self.received = []

        def accept(self, samples):
            self.received.append(samples.copy())
            return "hey" if len(self.received) < 40 else "hey how are you doing"

        def finish(self):
            return "hey how are you doing"

    events, stt = [], Recognizer()
    turn = SpeechTurn(DelayedVad(), stt, events.append)
    chunks = []
    for i in range(150):
        chunk = np.full(160, (i + 1) / 1000, np.float32)
        chunks.append(chunk)
        if turn.accept(chunk, i / 100):
            break
    assert turn.started == 0.19
    np.testing.assert_array_equal(np.concatenate(stt.received), np.concatenate(chunks))
    assert turn.text == "hey how are you doing"
    assert next(e["text"] for e in events if e["type"] == "transcript") == "hey"


def test_recognizer_lead_in_is_restored_after_warm_up_without_discarding_real_audio(tmp_path):
    from types import SimpleNamespace

    class Stream:
        def __init__(self):
            self.received = []

        def accept_waveform(self, rate, samples):
            assert rate == 16000
            self.received.append(samples.copy())

        def input_finished(self):
            pass

    class Recognizer:
        def __init__(self):
            self.streams = []

        def create_stream(self):
            stream = Stream()
            self.streams.append(stream)
            return stream

        def is_ready(self, stream):
            return False

        def get_result(self, stream):
            return ""

    recognizer = Recognizer()
    runtime = SimpleNamespace(
        OnlineRecognizer=SimpleNamespace(from_transducer=lambda **kwargs: recognizer)
    )
    stt = SherpaStt(runtime, tmp_path)
    voice = LocalVoice.__new__(LocalVoice)
    voice.finalizer = None
    voice.stt = stt
    voice.vad = SimpleNamespace(
        accept=lambda samples: None, detector=SimpleNamespace(reset=lambda: None)
    )
    voice.tts = SimpleNamespace(synthesize=lambda text: None)
    voice.warm()
    assert len(recognizer.streams) == 2
    assert stt.stream is recognizer.streams[-1]
    for stream in recognizer.streams:
        assert len(stream.received[0]) == int(RECOGNIZER_LEAD_IN * 16000)
        assert not np.any(stream.received[0])
    assert len(stt.stream.received) == 1
    onset = np.arange(160, dtype=np.float32) / 1000
    stt.accept(onset)
    np.testing.assert_array_equal(stt.stream.received[-1], onset)
