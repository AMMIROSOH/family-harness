# Bounded interruptions preview (M1.6)

**Software preview implemented, 2026-10-12.** Speech onset can stop a fixed local
test response without waiting for words or identity. The localhost guide combines
duplex capture, cancellation, heard-so-far history and post-capture group analysis.
Family Harness is under development. Continuous attributed live replies, actual
household echo/stop timing and the integrated Milestone 1 quality gate remain pending.

## Try the guided trial

1. Complete the microphone, speaker-volume and duplex tests in setup. Confirm
   exactly one echo remover. Refresh and select missing devices explicitly.
2. Install/import the English CPU profile, speaker and segmentation models. An
   optional final recognizer must also already be installed if selected. Enroll
   two consenting people through the [people guide](people-and-group-turns.md).
3. Press **Try interruptions**. Loading, warm-up and synthesis happen with audio
   off. Missing/damaged models and incompatible profiles fail before capture.
4. Stay quiet for two seconds. While the fixed voice plays, one person speaks a
   sentence to interrupt it, then another person continues. The trial retains up
   to eight seconds after detection, at most twenty seconds total. Speaking early
   can cancel the cue before playback; repeat after the quiet instructions.
5. Audio closes before clustering, transcription and identity matching. Review
   the continuation, unknown identities and complete heard chunks. Detected
   overlaps remain unnamed and request repetition, one person at a time. The
   follow-up responses are withheld; this is not a continuous conversation.

The cue is explicitly started by a control event, not a fabricated human turn.
It consists of three separately synthesized phrases with known audio boundaries.
Recognition policy is frozen for the job. It does not grant permissions.

Stop releases both devices by terminating the worker. Page disconnect stops it
within the existing three-second lease; the whole job has a 180-second deadline.
The trial shares the setup operation slot with audio, model and people jobs.
Reconnecting or reopening does not restart listening. No audio, transcript or
trial history is automatically written to disk. Numeric diagnostics and resource
measurements stay in the setup session.

For this workspace's installed models:

```sh
uv run family-harness setup --models .local/m14-models --recognizer parakeet-v2
```

The ordinary `room` input preset remains the initial choice. High gain in the
DiPCo experiments is an explicit quiet-recording calibration, not a universal
microphone setting. `setup --preset quiet-room` selects 36 dB gain deliberately;
inspect clipping, quiet playback and nearby/far speech before using it.

## Cancellation and heard history contracts

`speech_started` has a source-timeline `start`, independent of an utterance,
transcript, speaker track or person. It cancels pending output through separate
`stop_playback` and `cancel_generation` commands. Duplicate, old-session,
pre-gap and older-onset events cannot cancel newer output. A delayed final from
before newer speech may finish history without requesting an outdated reply.
Any lost room input stops output, including a cue requested from a control source.

`GenerationControl.cancel(response_id)` is the replaceable provider boundary.
`GenerationToken` supplies a response-scoped cancellation event. The fixed cue is
prepared before capture, so no LLM or running generation backend is claimed.

The native output callback copies precomputed samples and the exact echo reference.
Stopping switches the next callback block to zeros without draining the response
or waiting for ASR/identity. A full input queue also aborts audio from the callback.
The callback independently aborts capture at twenty seconds even if processing stalls.
Gaps, disconnects and stalls abort the take with recovery guidance. WebRTC removes
echo when selected; device mode deliberately bypasses it.

Playback progress uses the PortAudio DAC clock, bounded by submitted audio,
not the queued sample cursor alone. The report includes capture queue delay and
stop-request-to-first-zero-DAC timing. Hardware buffering, acoustic reverberation
and what people actually heard require physical measurement.

`response_ready` optionally supplies `alignment`: an increasing list of complete
audio chunks, each containing `end` and `text`. It must cover the response and
reconstruct its full text. Only chunks ending within confirmed playback enter
`heard_text`; no fraction of an interrupted phrase is guessed. Unaligned partial
responses retain `heard_text: null`. A single terminal `playback_stopped`
acknowledgment can settle in-flight DAC progress after cancellation without
reviving the response. Late completion, generation and repeated stop results
cannot mark the remainder heard. Text-free snapshots omit aligned text too.

## DiPCo onset validation

The [M1.6 evaluation report](m16-dipco-evaluation.md) records development selection,
full evaluation results, limits and reproduction commands. The new mode reads
continuous WAV frames without reference segmentation. Annotations enter only
the scorer; all speech, including nonlexical/unintelligible/long rows and other
voices on close-talk recordings, stays in the reference.

```sh
uv run family-harness room --models .local/m14-models evaluate E:/Datasets/DiPCo --mode interruptions --split eval --preset close-talk --report .local/m16-baseline.json
uv run family-harness room --models .local/m14-models evaluate E:/Datasets/DiPCo --mode interruptions --split eval --preset close-talk --gain-db 36 --vad-threshold 0.5 --hold-seconds 0 --report .local/m16-selected.json
```

Onsets are speech runs separated by more than 300 ms in the coarse annotations.
Matching is one-to-one, allowing 150 ms early and at most one second late. Reports
include raw matched/missed/unmatched counts, speech/silence durations, false/missed
activity, detection latency and a separate count within 300 ms. Continuous
detector input and its retained VAD waveform are bounded. Reports contain file
and model hashes, settings and host resources, without reference/recognized text.
Evaluation blocks outbound sockets and opens no audio devices.

DiPCo contains no assistant playback. These measurements cannot establish
self-interruption rejection, actual output stop time or speaker changes without
silence. They are a local diagnostic, not official DiPCo/CHiME scoring. The
[previous ASR](dipco-accuracy.md) and [identity](m15-home-recognition.md) limitations
remain separate; this work does not repair separation or improve their scores.

## Integrated household exit trial

This is a deliberate user-run trial; development commands do not activate hardware.
Keep any tally or exported diagnostics in a private local file.

1. Record OS, CPU/RAM, Python/model versions, devices/rates, room placement,
   volume, echo owner, saved setup measurements and recognition settings.
2. Work offline after installation. Complete the earlier audio, voice and
   [two-person/guest quality trial](people-and-group-turns.md#household-quality-trial).
   Count missed/unknown speech and wrong names rather than only accepted results.
3. At nearby and farthest positions, run twenty interruption attempts per enrolled
   person. Alternate who interrupts and who continues; include the guest. Tally
   attempts, detections, missed interrupts, continuation words, wrong/unknown
   identities and any output continuing after interruption.
4. Run twenty quiet-playback trials at the same volume. Count false
   self-interruptions. Include an overlap trial and check the repetition path.
5. Measure physical stop delay against the last audible speaker output using a
   deliberate local measurement method. PortAudio timing cannot substitute for
   acoustic measurement. Working engineering targets are at least 95% detected
   attempts, p95 physical stop within 300 ms, zero false self-interruptions in
   those quiet trials, and the earlier identity/ASR targets. Report denominators;
   these are targets, not guarantees.
6. Repeat with busy applications. Check queue delay, stop timing, dropped audio,
   RAM and analysis time. Test Stop during loading/playback/analysis, unplugged
   devices, page closure, explicit retry and application restart.
7. Review heard chunks and discarded overlaps. Missing evidence remains
   failed/unverified. Milestone 1 requires the complete install-to-trial path and
   all earlier quality gates to pass on the target hardware.
