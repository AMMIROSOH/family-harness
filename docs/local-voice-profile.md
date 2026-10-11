# Local English voice profile preview (M1.3)

**Implemented foundation, 2026-10-11; household hardware exit gate pending.** The profile can be
installed/imported, loaded and warmed, and used for streaming English transcription and a fixed
local synthesized test response. Real models were exercised with a public WAV replay while network
access was blocked. No household microphone or speaker was activated during development validation.
This is not a room conversation manager or a functioning home assistant.

## Try the profile

1. Close any running setup launcher, update dependencies with `Install-Windows.cmd`, and launch
   `Start-Setup.cmd`. Choose the microphone and speaker, test volume, and save your room choices.
2. In **Local English voice preview**, choose **Download English profile**. The six catalog artifacts
   total 141,181,119 bytes (about 135 MiB). Allow 400 MiB of free disk space during installation.
   This explicit action contacts Hugging Face/GitHub and downloads weights plus phonemizer data;
   it does not activate audio or contact an inference service. Import is also available offline.
3. **Check model speed** verifies file integrity, loads all three speech components, warms them
   with synthetic silence and a short synthesized phrase, and releases them. Audio remains off.
4. Explicitly choose **Start voice trial**. Loading/warm-up happens with audio off. Wait for
   **Speak now**, say one English sentence, and pause. The selected microphone captures for at most
   20 seconds. Drafts replace previous drafts of the same utterance; a final transcript is shown.
5. After words are recognized and 600 ms pass without VAD activity, a silence-based turn candidate
   finalizes the transcript. Activity with no recognized words keeps the trial open until its limit,
   giving you time to speak after a brief noise or an inaudible attempt.
   The microphone closes, then a fixed test response is synthesized and played through the selected
   speaker. Review the transcript and verify hearing/volume yourself. Silence or reaching the capture
   limit without a completion candidate does not trigger playback.

Models are warmed before each trial and stay loaded for that operation. They are released at its end;
the speed check does not leave a resident service ready for later sessions. There is no wake phrase,
automatic activation, account, cloud fallback, enrollment, speaker attribution, or LLM response.

Stop / mute terminates the current worker, including loading, downloads, capture, synthesis, and
playback. Samples already queued in hardware may finish. Closing the page stops an active worker after
three seconds without a poll, plus OS scheduling/termination time. One operation owns audio at a time.
A voice trial cannot overlap acoustic tests or model removal. Failure never switches devices or
restarts listening. Audio gaps invalidate the trial rather than joining incomplete speech.

Capture and playback are sequential in this phase. The M1.2 echo path remains available in acoustic
tests, but this voice trial does not evaluate transcription during playback or interruptions.

The voice path applies WebRTC high-pass filtering, moderate noise suppression, and automatic digital
gain (AGC2, capped at 30 dB) before both speech detection and transcription. It includes a limiter and
does not lower the VAD threshold. The live meter shows input before adjustment, the adjusted level,
and whether speech activity is currently detected. Acoustic tests retain their original signal levels.
Gain can help quiet input; it cannot recover speech removed by a device/driver or buried in room noise.
A directional headset boom should face the speaker when testing it off the head.

## Model catalog, local files, and licenses

[`voice_catalog.json`](../src/family_harness/voice_catalog.json) fixes profile ID `english-cpu-v2`,
language `en`, CPU execution, component versions, sources, sizes, SHA-256 hashes, and license provenance.
Only this profile is selectable. Default model storage is `%LOCALAPPDATA%/FamilyHarness/models`.
Use `setup --models PATH` or `voice --models PATH` for a different local directory.

Version 2 replaces the 20M recognizer from version 1, which dropped opening words even when given
the full audio without VAD or input processing. Updating requires an explicit download/import of
the current profile; setup identifies an installed older profile and offers the update. The old
`english-cpu-v1` folder is retained. No Windows microphone settings are changed. Restart setup
after updating the software so it uses the new catalog.

Each new recognizer stream also receives 800 ms of synthetic silence as initial context, including
the fresh stream created after warm-up. This happens before **Speak now**, without a live wait or
opening the microphone. It neither discards real input nor changes VAD/capture timestamps. A report
records `recognizer_lead_in_seconds` separately from capture duration and latency.

| Component | Implementation and provenance |
| --- | --- |
| Speech activity | Silero ONNX, pinned release-asset hash; [Silero code/weights are MIT](https://github.com/snakers4/silero-vad). |
| Streaming transcription | English Zipformer, 2023-06-26, chunk 16 / left context 128, int8 encoder/joiner and fp32 decoder; [model repository identifies Apache-2.0](https://huggingface.co/csukuangfj/sherpa-onnx-streaming-zipformer-en-2023-06-26). |
| Test voice | Piper `en_US-lessac-low`; [upstream voice repository declares MIT](https://huggingface.co/rhasspy/piper-voices/blob/main/README.md). Its [model card](https://huggingface.co/csukuangfj/vits-piper-en_US-lessac-low/blob/main/MODEL_CARD) separately references the [Lessac training-data research license](https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html). Training data is not downloaded. |
| Runtime | sherpa-onnx and sherpa-onnx-core 1.12.40; upstream core code is Apache-2.0, while its bundled eSpeak NG phonemizer/data has [GPL-3.0-or-later terms](https://github.com/espeak-ng/espeak-ng/blob/master/COPYING). These are separate from voice-weight licensing; distribution needs those terms respected. |
| Rate conversion | [SoXR streaming resampler](https://python-soxr.readthedocs.io/en/latest/soxr.html), keeping 8–48 kHz replay and native audio conversion behind a small adapter. |

Files are staged and verified before an atomic profile-directory rename. Incomplete/cancelled downloads
are never treated as an installed profile. Full installed-file hashes are checked before native model
loading. Unsafe archive paths, links, special files, and oversized downloads/expansion are rejected.
Original bundles remain external to the installed profile. To repair corrupted models, explicitly
remove the profile and reinstall/import it. Hard cancellation may leave a `.install-*` staging folder
in the model root; with setup closed, it can be removed to reclaim space.

For offline import, copy the six original catalog artifacts into one folder, preserving their original
filenames, including `tokens.txt` and the Piper `.tar.bz2` package. Use **Import from folder** or:

```sh
uv run family-harness voice --models .local/models install --from-directory C:\Models\English
uv run family-harness voice --models .local/models status
uv run family-harness voice --models .local/models benchmark --report .local/warm-report.json
```

Without `--from-directory`, `voice install` explicitly downloads the pinned artifacts. `voice remove`
removes only this installed profile. Room configuration, original imports, and diagnostic reports are
retained. Installation, status, benchmark, imports, and help/version never open audio.

## Offline file replay and measurements

Use a local PCM16 mono WAV, 8–48 kHz, at most 30 seconds. It runs through the same VAD, streaming
recognizer, and completion candidate. One second of silence is appended if needed to finish the first
utterance. Replay processes that one utterance; it is not a multi-turn recording transcriber.

```sh
uv run family-harness voice --models .local/models replay .local/example.wav --report .local/replay-report.json
# Optional explicit export of the fixed synthesized response; no device playback:
uv run family-harness voice --models .local/models replay .local/example.wav --output .local/test-response.wav
```

The transcript is printed to the terminal or shown on the page. Audio and transcripts are not saved by
the wizard. CLI `--output` explicitly saves only the fixed synthesized response. Reports exclude the
transcript, utterance ID, and input filename. Numeric metrics, raw/processed input levels and clipping,
observed gain, device details in native trials,
model hashes/versions, CPU/OS/RAM, and package versions are retained in the selected report or
`models/benchmark.json`. Keep models, replays, reports, and personal data out of source control.

Metrics distinguish load, warm-up, speech-frame processing, synthesis, and audio duration. CPU is
process CPU time divided by wall time expressed as percent of one core, so multiple threads can exceed
100%. RAM is sampled resident process memory, including native allocations; it is not a guaranteed
maximum. Frame processing has count/p50/p95/max; replay real-time factor excludes loading/TTS and does
not simulate wall-clock capture or resource contention. First-partial latency uses the audio timeline
from detected VAD onset. Completion latency uses the last VAD activity plus finalization and observed
queue lag; it is not measured from a human-annotated last word or a full conversational answer.
One trial's completion timing is not a p50/p95 distribution across speakers.

## Recovery

| Problem | Recovery |
| --- | --- |
| Models missing/corrupt or wrong version | Remove the installed profile and download/import the original pinned files. No audio opens before verification and warm-up succeed. |
| Download fails or is too slow | Check connectivity/free space, retry, or acquire the catalog files on another computer and import locally. No cloud inference fallback exists. |
| Native runtime cannot load | Rerun the installer using Windows x64 Python; the matching sherpa-onnx-core wheel is required. |
| Very quiet input | Check microphone selection/mute and Windows input volume or microphone boost. Face the microphone toward you. Repeat at nearby and distant positions while watching the input meter. |
| Activity detected but no words | Use an English sentence and compare the raw/adjusted levels. Reduce fans/background noise. Check whether Windows/device noise suppression removes distant speech; digital gain cannot restore removed words. |
| Opening words missing | Restart updated setup and install/import the current profile if an update is offered. Wait for **Speak now**, then speak naturally; all audio from capture start reaches STT, including samples before VAD confirmation. Check microphone orientation and review remaining recognition errors. |
| No speech activity detected | Check selection/mute, placement and input level. A headset boom has a focused pickup area; test it facing you at the intended distance. |
| Sentence ended early | A silence candidate cannot understand intent. Avoid a mid-sentence pause for this preview and review the transcript. |
| Audio lost/device disconnected | Close busy apps, reconnect, refresh, and explicitly retry. Incomplete speech is discarded. |
| Voice not heard | Retest speaker volume/selection. Software completion does not confirm human hearing. |

## Implementation

- `models.py` owns acquisition/import, safe extraction, integrity, atomic installation, and removal.
- `speech.py` provides separate input processing, VAD, streaming STT, and synthesis interfaces.
  The maintained [WebRTC processor](https://github.com/strands-labs/pywebrtc-audio) receives exact
  10 ms frames, including buffering across resampler chunks, and adjusts the shared VAD/STT input.
  Every processed sample from capture start is sent to STT even before VAD confirms speech; VAD
  gates transcript presentation and completion, not recognizer input. Transcript revisions
  replace earlier text by utterance ID. `SpeechTurn` is the single candidate authority, with no identity
  inference or conversation state. Native model constructors receive local paths and CPU execution.
- `voice_trial.py` reuses endpoint IDs and `AudioFrame`/clock-gap semantics for bounded capture, wraps
  the maintained resampler, and handles file replay, output-only playback, and resource measurements.
- `voice_worker.py` isolates native loading/inference in a killable child and writes text-free reports.
- `control.py` supervises all setup jobs through one slot, deadlines, and the existing browser lease.
  Voice text is kept in the current volatile job; it is excluded from saved room diagnostics.

## Evidence and pending exit gate

Development checks on 2026-10-11 include fake native streams, candidate/revision behavior, silence,
audio gaps/disconnects, resampling, model corruption/import/download bounds, archive-path attacks,
shared cancellation, HTTP authorization, and report privacy. The real pinned models were imported,
warmed, used to transcribe an upstream public `test_wavs/0.wav`, and used to synthesize a WAV with
outbound networking blocked. No microphone/speaker streams were opened in that validation.

A first-word regression reproduced the old 20M model dropping the opening three words even with
the complete unprocessed WAV and VAD bypassed. Its [upstream example](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-transducer/zipformer-transducer-models.html)
also shows that omission. Version 2 with recognizer lead-in retains those words and the complete
sentence at normal volume, 24 dB attenuation (about -51 dBFS), and 36 dB attenuation (about -63 dBFS).
The first two complete a silence candidate; the quietest case still does not complete within the
one-second replay tail. Silence, synthetic steady noise and a tone produce no activity, transcript,
or candidate. These checks verify a software improvement, not performance at a microphone distance.

Synthetic greetings and requests starting at file sample zero were also replayed through the same
path. The clear greeting is transcribed as “HEY HOW ARE YOU DOING”; a softer generated greeting
retains its first word as “HE”, and “Hello” can become “Hullo”. These remaining recognition errors
need actual-speaker evaluation. A behavior test independently checks every sample reaches STT even
when VAD confirms speech 190 ms later; another checks fresh-stream context survives model warm-up.

A packaged version-2 Windows 10 development-host replay measured roughly 10.6 seconds to verify/load,
0.43 seconds to warm, 290 MB peak sampled RSS, a speech-processing real-time factor of 0.20,
and 0.41 seconds to synthesize 4.24 seconds of test-response audio. Its first partial appears 380 ms
after detected VAD onset; the silence candidate/finalization is about 693 ms after last VAD activity.
These are one-run development observations, not supported minimum hardware or speech-quality claims.
Exact CPU and model hashes are included in locally generated reports.

**M1.3's hardware gate remains pending.** On the intended PC, install/import the profile, record exact
hardware/model versions, disconnect internet, and explicitly run the microphone/speaker trial. Verify
the actual English transcript and hearing of the response, cancellation/page closure, nearby/far
positions, accents/names, failures, and repeat timings under representative CPU load. Record transcript
errors and premature endings separately. Do not mark this gate complete from replay or synthetic tests.
