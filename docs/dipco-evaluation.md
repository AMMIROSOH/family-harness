# DiPCo subset evaluation, 2026-10-12

**Historical Zipformer baseline.** A subsequent [accuracy study](dipco-accuracy.md)
audits scoring, compares stronger local models and records fresh validation results.
The numbers below retain the original fixed one-second replay tail and original
presets; do not treat them as the latest best result or mix them with ASR-only WER.

This is a local development/validation result for M1.4 and the current M1.3
English CPU profile. It does not complete the household audio/voice gates.
The [evaluation guide](room-manager.md) describes commands, normalization,
reference exclusions, presets, and the distinction between simulated output and
actual playback.

## Inputs and protocol

The supplied files were `S02_P05.wav`, `S02_U01.CH1.wav`, and
`S08_U01.CH1.wav`, with their local session JSON annotations. S02 supplied
development evidence; S08 was reserved for validating the selected clip preset.
All audio is 16 kHz mono PCM16. The two S02 files are about 30 minutes each,
and S08 is about 15.8 minutes. No additional dataset audio was downloaded.
There was no microphone/speaker capture, inference service, or network fallback.

Clip tuning compared 19 explicit configurations across 29 recording trials,
each using 32 annotations sampled evenly through each speaker's recording.
Configurations covered WebRTC processing on/off, greedy/beam decoding, fixed
input gains of 0/12/24/30/36 dB, 600/900/1200 ms silence, and VAD thresholds
0.5/0.3. The best sampled all-utterance WER determined the clip preset; ties
favored fewer premature completions and shorter silence. Nonoverlap scores
were reported separately. Presets were frozen before full S08 clip validation.

The selected close-talk preset is WebRTC + 12 dB fixed gain; the selected
far-microphone clip preset is fixed 36 dB gain without WebRTC processing.
Both use greedy decoding, a 0.5 VAD threshold and 900 ms silence. These are
opt-in settings for quiet recordings, not universal microphone defaults.

## M1.4 Manager Evidence

Annotation-driven replay assembled all 794 eligible final turns correctly:
142 close-talk S02 turns, 363 room-microphone S02 turns, and 289 S08 turns.
Duplicate finals, old revisions, and post-close events could not change the
final transcripts or reopen sessions. Simulated output cancellations were
exercised 2/35/42 times respectively. Track labels came from annotations;
this is not speaker recognition evidence.

Behavior tests additionally cover delayed older finals, wrong session/source
events, monotonic playback, incomplete heard text, generation/output cancellation,
gap watermarks, session capacity, silence, and multiple utterances on one audio
timeline. The M1.4 software replay gate passes; live sessions and physical
interruptions remain later work.

## M1.3 Clip Results

WER is lower-is-better and uses all eligible words, including overlaps.
These scores use known clip boundaries and are not official DiPCo benchmarks.

| Recording | Utterances / words | Baseline WER | Selected preset WER | Premature endings, before / after | VAD misses, before / after |
| --- | --- | --- | --- | --- | --- |
| S02 P05 close-talk | 142 / 749 | 68.5% | 61.7% | 10 / 1 | 6 / 0 |
| S02 U01.CH1 room | 363 / 2,763 | 96.1% | 84.4% | 26 / 6 | 164 / 30 |
| S08 U01.CH1 room, held out | 289 / 1,810 | 96.9% | 98.3% | 14 / 10 | 65 / 17 |

Nonoverlap WER changed from 55.5% to 40.5% on S02 close-talk, 95.8% to
74.7% on S02 room audio, and 91.0% to 86.9% on S08. Overlap remains much
harder: selected-preset WER is 73.9%, 90.8%, and 100.3% respectively.

The room clip preset **did not generalize in overall WER on S08**. It detected
more speech but added incorrect words. The original wizard baseline remains
the default. Gain cannot restore signal-to-noise ratio or separate overlapping
speakers. Neither the baseline nor the selected presets provide acceptable
room transcription on this subset.

First-partial audio latency p50/p95 for the selected presets is 640/1098 ms,
600/1530 ms, and 510/1280 ms respectively. Silence-completion p50/p95 is
932/959 ms, 932/955 ms, and 933/953 ms after the last detected VAD activity.
Only 95/85/53 clips produced a silence candidate within the bounded tail;
the remaining clips were finalized at replay EOF. These are VAD-relative timings,
not last-human-word or full conversational-response latency.

## Continuous Room Replay

Full WAV replay uses no reference segmentation and leaves speaker identity
unknown. The S02 close-talk recording produced 166 final turns with 99.2%
chronological WER against all speakers, including cross-talk. The S02 room
recording produced 112 turns with 93.4% chronological WER; S08 produced 64
turns with 86.8% chronological WER.
These diagnostic scores include overlap ordering and excluded-reference
insertions, and must not be presented as official DiPCo WER. All three runs closed
their sessions successfully. Processing real-time factors were 0.089, 0.083,
and 0.087 respectively, including replay/manager processing and excluding load.
Long replays exposed the upstream VAD's soft duration limit; the room adapter
now explicitly resets VAD at forced segment boundaries. A sustained-activity
regression test and full real-model replays verify this path without buffer
expansion warnings. Processing choices stayed fixed for these final reruns.

An additional development-only continuous comparison used fixed 120-second
windows starting at 30 seconds and 1,200 seconds in S02 U01.CH1, covering
audio before and after music began. Combined chronological WER was 113.2%
for gain-only 36 dB, 127.8% for WebRTC + 12 dB, and 131.9% for WebRTC + 24 dB.
All used the same decoder/VAD/silence settings. The gain-only preset remained
the best of these tested options; no setting was tuned from S08 results.
The very high scores expose background/overlap and reference-exclusion limits,
not a functioning room assistant. Further tuning stopped after this comparison.

## Environment and Reproduction

The host was Windows 10 build 19045, Intel Core i7-4790K, 8 logical CPUs,
16,325 MiB RAM, and Python 3.12.11. Models use profile `english-cpu-v2`,
sherpa-onnx/core 1.12.40, Silero VAD, the pinned int8 English streaming Zipformer,
and Piper Lessac-low. SoXR 1.1.0 and pywebrtc-audio 0.2.0 perform input processing;
JiWER 4.0.0 provides edit counts.

Full clip replay processing factors were about 0.10-0.11, excluding initial
model loading. Sampled process RSS ranged roughly 272-508 MiB; runs shared a
process with earlier model allocations, so this is not a clean minimum-RAM
measurement. These are development-host observations, not supported hardware
specifications. Exact file/model hashes and resource measurements are in the
local reports.

Reports are in `.local/dipco/`: `baseline-full.json`,
`final-utterances-S02_P05.wav.json`, `final-utterances-S02_U01.CH1.wav.json`,
`final-utterances-S08_U01.CH1.wav.json`, and `manager-events-final.json`.
They contain numeric diagnostics and annotation indices, without reference or
recognized transcripts. Reproduce using the commands in the evaluation guide;
all recordings/models remain outside source control.

Validation completed with 148 passing behavior tests, clean Ruff lint and Git
whitespace checks, package build/install and CLI help/version checks. Packaged
web/catalog assets were present; local models, audio, caches and reports were
excluded from the wheel/source distribution. The isolated wheel check reused
the already installed speech libraries.
