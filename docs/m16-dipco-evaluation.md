# M1.6 DiPCo interruption validation, 2026-10-12

M1.6 implements onset-driven cancellation, heard-chunk history, overlap recovery
and a bounded native fixed-cue trial. **The physical interruption and integrated
Milestone 1 quality gates remain pending.** The [trial guide](interruptions.md)
explains the contracts, deliberate household validation and remaining limits.

## Protocol and development selection

Validation reads the existing `E:/Datasets/DiPCo` inventory. No new data/weights
were downloaded, no inference service contacted, and no physical audio device
opened. All model evaluation blocks outbound sockets.

The detector consumes continuous ten-millisecond frames through the maintained
Silero/sherpa-onnx adapter, independently of ASR and speaker attribution. Annotations
are supplied only to the scorer. All annotation intervals remain in the reference,
including nonlexical, unintelligible and long rows, overlapping voices and other
people on close-talk recordings. No WER exclusions or normalization lower this score.

Reference intervals are merged when separated by at most 300 ms. Detected onsets
match one-to-one within 150 ms early/one second late; extra detections count as
unmatched. Precision, recall and F1 are based on raw event counts. A separate
within-300-ms count prevents the generous matching window from implying fast
interruptions. Speech activity miss/false durations use the unmerged intervals.
These coarse annotations are not exact human word onsets or official DiPCo scoring.

Development uses fixed 300-second prefixes of S02 U01, S04 U01, S05 U04, S09 U04
and S10 U04: 1,500 seconds, 121 reference onset cases. Twenty-four combinations
compare gains 0/12/24/36 dB, VAD thresholds 0.3/0.5/0.7 and extra onset holds
0/80 ms; release stays 300 ms. The objective is maximum combined development
onset F1, breaking ties by fewer missed speech seconds, shorter hold and lower gain.

The selected **36 dB gain, threshold 0.5, zero extra hold** gets 76/121 onsets,
34.5% precision, 62.8% recall and **44.6% F1**. Raw input at threshold 0.5/80-ms
hold gets 19/121, 12.5% precision, 15.7% recall and **13.9% F1**. Settings were
saved to `.local/m16/frozen.json` before any interruption evaluation split result
was scored. These evaluation recordings were used in prior speech/identity work;
they are held out from this detector selection, not newly untouched recordings.

## Complete evaluation recordings

Both configurations run the same seven complete eligible inventory files:
**13,163.5 seconds of audio, 746 recording/onset cases**. S01/S08 repeat sessions
across room/close microphones; these are correlated cases, not 746 unique turns.

| Recording | Seconds / reference onsets | Raw F1 | Selected precision | Selected recall | Selected F1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| S01 P04 close-talk | 2,844.87 / 216 | 28.5% | 37.9% | 50.0% | 43.1% |
| S01 U01.CH1 room | 2,845.21 / 216 | 13.3% | 28.7% | 47.7% | 35.8% |
| S03 U04.CH1 room | 2,796.78 / 88 | 10.5% | 23.1% | 61.4% | 33.5% |
| S06 U04.CH1 room | 1,203.96 / 43 | 13.7% | 21.9% | 58.1% | 31.8% |
| S07 U01.CH1 room | 1,575.25 / 27 | 8.2% | 9.0% | 70.4% | 15.9% |
| S08 P25 close-talk | 948.56 / 78 | 24.6% | 42.1% | 67.9% | 52.0% |
| S08 U01.CH1 room | 948.87 / 78 | 23.8% | 31.5% | 51.3% | 39.0% |

Combined raw/selected results:

| Measurement | Raw | Selected |
| --- | ---: | ---: |
| Matched / missed / unmatched onsets | 277 / 469 / 2,005 | 402 / 344 / 1,055 |
| Precision | 12.1% | 27.6% |
| Recall | 37.1% | 53.9% |
| F1 | 18.3% | **36.5%** |
| Detected within 300 ms, out of 746 | 16 | **32** |
| Matched onset latency p50 / p95 | 560 / 942 ms | 570 / 889.5 ms |
| Missed speech seconds, out of 11,715.95 | 4,694.10 | **783.51** |
| False activity seconds, out of 1,447.55 silence | 231.78 | **594.68** |

F1 roughly doubles and missed speech falls 83.3%, but false activity increases
156.6%. Only **4.3%** of reference onset cases are detected within 300 ms. The
matched latency populations differ, so their medians are not a paired latency
improvement. Close-talk S01 recall also decreases. This is the best configuration
among the tested development settings, not a successful household interruption
detector. Fragmentation inside coarse annotation spans contributes unmatched
events; they are retained rather than filtered from the score.

Selected full-recording clipping fractions are 0.116–0.330% for room channels,
2.307% for S01 close-talk and 4.211% for S08 close-talk. High gain is opt-in and
cannot restore SNR or separate overlapping voices. Native setup retains its
ordinary room preset and 80-ms extra hold. The frozen zero-hold comparison is
reproducible through CLI and does not silently change microphone defaults.

## Integration, resources and verification

A separate full worker replay uses S02 U01.CH1 seconds 300–317, preceded by three
seconds of silence, with a silent simulated duplex sink. Two TitaNet profiles use
twelve seconds of supervised clean enrollment each, entirely before the replay
window. Automatic continuation segmentation receives no reference boundaries or
speaker count. The fixed three-phrase Piper cue, streaming Silero detector,
cancellation token, room manager, Parakeet final recognizer, TitaNet matcher and
overlap recovery all execute locally.

Speech triggers cancellation at 3.24 seconds. The simulated first zero output
DAC block follows the stop request by **40 ms**. Capture closes before heavy
analysis, the same session retains complete heard chunks and ends closed, and
four continuation regions include one unresolved overlap. No identity correctness
score is inferred from accepted names. No echo is mixed into this fixture; neither
the 40-ms value nor this replay validates real speaker echo or acoustic stopping.

Host: Windows 10 19045, Intel i7-4790K, eight logical CPUs, 16,325 MiB RAM,
Python 3.12.11, sherpa-onnx/core 1.12.40. Selected detector processing RTF is
**0.0127–0.0151**, excluding model loading/hashing/scoring; full evaluation takes
190.3 seconds including those operations and samples 83.8 MiB peak RSS. These are
single-worker offline measurements, not capture scheduling guarantees. The
complete simulated trial worker samples **1,383.7 MiB** peak RSS.
Its model load adds 9.46 seconds, warm-up 0.204 seconds, and post-capture group
analysis RTF is 0.0884 on 11.24 seconds of bounded capture. Maximum sampled input
queue delay is 0.239 ms in this simulator; it is not a hardware contention bound.

Annotation-driven manager replay also passes on all **7,975 recording/turn cases
across 22 files**, including duplicate/stale-event and closure checks. Attribution
and playback in that protocol are fixtures, not automatic recognition or hardware.

Behavior checks cover immediate cancellation before words/identity, stale and
duplicate events, chunk hearing, one stop acknowledgment, overlap/repetition,
DAC progress, callback capture limit, queue contention, missing-model preflight, Stop/browser lease,
explicit restart and source gaps. The setup controls were exercised with a
simulated worker for prerequisite recovery, disabled controls, completion and
unknown continuation display. No household device was activated.

Validation: **240 behavior tests pass**, Ruff, source/wheel builds and a separate
installed-wheel help/version/assets/lazy-import check. Archive inspection excludes
recordings, weights, people files and `.local` reports. No runtime dependency was
added. Milestone 1, M1.5 identity quality and M1.6 physical quality remain pending.

## Reproduction and evidence

```sh
uv run family-harness room --models .local/m14-models evaluate E:/Datasets/DiPCo --mode interruptions --split eval --preset close-talk --report .local/m16/raw.json
uv run family-harness room --models .local/m14-models evaluate E:/Datasets/DiPCo --mode interruptions --split eval --preset close-talk --gain-db 36 --vad-threshold 0.5 --hold-seconds 0 --report .local/m16/selected.json
uv run family-harness room --models .local/m14-models evaluate E:/Datasets/DiPCo --mode events --report .local/m16/manager-events.json
```

Local text-free evidence: `.local/m16/development.json`, `frozen.json`,
`baseline-validation.json`, `selected-validation.json`, `clipping.json` and
`integration.json`. Study drivers are `.local/m16-study.py`, `m16-validate.py`,
`m16-clipping.py` and `m16-integration.py`. Public dataset enrollment profiles stay
in the ignored local folder; no embeddings, audio or transcripts are committed.
The VAD SHA-256 is
`9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6`.

DiPCo lacks assistant playback. It cannot score self-interruption rejection or
physical output stop, and speech onset alone does not detect a speaker handover
without silence. Complete the [integrated household trial](interruptions.md#integrated-household-exit-trial)
before signing off the milestone.
