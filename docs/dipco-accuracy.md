# DiPCo accuracy study, 2026-10-12

This follow-up audits the original [Zipformer evaluation](dipco-evaluation.md)
and compares local recognizers before changing any live-room defaults. Family
Harness is still under development. Hardware, Farsi, speaker identity, echo and
live-interruption gates remain pending.

## Scope and acquisition

The original local subset contains S02 P05/U01.CH1 and S08 U01.CH1. Additional
downloads are S09 U04.CH1 (development), S06 U04.CH1 (fresh validation), S08 P25
(close-talk validation), and S09/S06 annotations. They total **112,697,364 bytes**,
below the 300 MB additional-data limit. These are complete recordings, not newly
captured household audio. The channels are single microphones, not beamformed arrays.

Dataset source: [DiPCo on Hugging Face](https://huggingface.co/datasets/huckiyang/DiPCo),
revision `e2b29d3d0d88692c744feb15e290f7316b68014e`.
The local download manifest records sizes and SHA-256 hashes. Model sources,
revisions, sizes, hashes and licenses are pinned in
[`asr_catalog.json`](../src/family_harness/asr_catalog.json).
Parakeet and Whisper together downloaded 1,036,691,592 bytes of weights/tokens;
the data limit was not a model-weight limit. No inference service or audio device
was used. Every evaluation blocks outbound sockets.

## Scoring Audit

The old utterance score mixed recognizer mistakes, VAD misses, early endpoints,
and words from neighboring context. The continuous score additionally joins
overlapping speakers in an arbitrary chronological order, while excluded reference
regions remain in the audio and can add insertions. It is a diagnostic, **not**
official DiPCo/CHiME WER or an accurate substitute for a meeting scorer.

The new `recognizer` protocol decodes exact device-specific annotation intervals,
with no adjacent-word padding, VAD suppression, or early stopping. Fresh streams
decode every eligible interval. This isolates ASR quality using oracle boundaries;
it does not measure automatic room conversation quality.

`utterances` separately runs the actual conditioned streaming/VAD/final path.
It retains 200 ms lead-in and 150 ms real trailing context. Synthetic silence is
bounded at completion silence plus 700 ms, minimum one second, to accommodate
VAD release; some trials still finalize at EOF instead of a silence candidate.
The original fixed one-second tail could not exercise longer completion settings
reliably. Candidate counts, early endings and misses remain explicit.

Both scores use unchanged strict NFKC/casefold punctuation normalization, retaining
apostrophes, and JiWER edit counts. Unintelligible, nonlexical and >28-second rows
are excluded with counts reported. WER is word weighted, not an average of clip
percentages. Any intersecting other-speaker annotation marks an interval as overlap,
including excluded rows; this coarse label is not word-level overlap timing.
Close-talk scoring targets the named participant; cross-talk may add words.
No normalization or reference removal was introduced to lower the score.

## Development Selection

S02 close/room and S09 room supplied 32 speaker/time-balanced annotations each,
667 total reference words. Raw and fixed 24 dB gain were tested through the same
exact-boundary protocol. All models used CPU sherpa-onnx 1.12.40.

| Model/input | Combined development WER | Processing RTF by recording |
| --- | --- | --- |
| Zipformer, gain 24 dB | 77.7% | 0.094-0.109 |
| Whisper small.en int8, raw | 52.2% | 0.484-0.712 |
| Whisper small.en int8, gain 24 dB | 42.4% | 0.553-0.680 |
| Parakeet TDT v2 int8, raw | 36.4% | 0.111-0.119 |
| Parakeet TDT v2 int8, gain 24 dB | **32.1%** | 0.112-0.118 |

Parakeet won this bounded comparison. Whisper remains an optional alternative,
not the selected default. There is no claim that all possible local models were
searched or that upstream GPU benchmark speed applies to this CPU.

Endpointed development trials compared gains 24/36 dB, VAD thresholds 0.3/0.5,
and silence 0.9/1.2 seconds. The 24/36 dB finalists at threshold 0.3 and 1.2-second
silence were rerun after correcting replay's VAD-release allowance. The selected
`quiet-final` preset is raw gain 24 dB, threshold 0.3, silence 1.2 seconds, with
Parakeet finals. Selection was frozen before any S08/S06 accuracy result was read.
The same settings won for the close/room development classes. Its endpointed
development WER is 39.4%, higher than its ASR-only score, as expected.

## Validation

Full eligible S08/S06 ASR and pipeline measurements are recorded in the local
text-free validation report. Pipeline development rechecks use 64 annotations
per recording; all validation annotations are evaluated. Continuous stress
checks use fixed 300-second prefixes without reference segmentation. No tuning
is performed from these validation results.

### Exact-boundary ASR

These compare the same complete reference intervals and 24 dB input gain,
without VAD or early endpoints. The all-word score includes overlap.

| Recording | Utterances / words | Zipformer WER | Parakeet WER | Nonoverlap WER, before / after (words) |
| --- | --- | --- | --- | --- |
| S08 U01.CH1 room | 289 / 1,810 | 91.7% | **56.9%** | 85.8% / 34.1% (267) |
| S06 U04.CH1 fresh room | 397 / 2,495 | 81.0% | **52.9%** | 66.2% / 31.8% (195) |
| S08 P25 close-talk | 85 / 458 | 62.2% | **29.9%** | 61.6% / 23.3% (73) |

Combined validation ASR WER is **83.3% to 52.2%** across 4,763 reference words,
a 37.3% relative error reduction. Room-only nonoverlap WER is 77.5% to 33.1%
across 462 words; those small nonoverlap denominators must remain visible.
Parakeet's observed ASR processing RTF is 0.116-0.122 versus Zipformer's
0.102-0.117. This excludes model load and is not native end-to-end latency.
Neither result is an official DiPCo benchmark.

### Endpointed Pipeline

The baseline below uses the previous microphone-specific Zipformer presets
(`quiet-room`, or `quiet-close-talk`). The improved path uses the frozen
`quiet-final` preset and Parakeet finals. Both replays use the same eligible
annotations and updated VAD-release tail rule. These are complete eligible
clip evaluations, not autonomous meeting WER.

| Recording | Baseline WER | Improved WER | Nonoverlap WER, before / after | VAD misses, before / after | Premature endings, before / after |
| --- | --- | --- | --- | --- | --- |
| S08 room | 98.3% | **63.1%** | 86.9% / 39.0% | 17 / 6 | 10 / 1 |
| S06 fresh room | 93.3% | **60.0%** | 60.0% / 40.5% | 4 / 6 | 6 / 0 |
| S08 close-talk | 72.9% | **37.1%** | 57.5% / 24.7% | 3 / 0 | 6 / 0 |

Combined endpointed validation WER falls from **93.2% to 59.0%** over 4,763
words (36.7% relative reduction). Across these three recordings, premature
endings fall from 22 to 1 and VAD misses from 24 to 12. The close-talk file's
worst processed clipping fraction rises from 0 to 3.677% with the fixed gain,
so this is not a universal device preset even where overall recognition improves.

The fresh-session gain is real, but VAD misses do **not** improve universally:
S06 loses two additional short utterances despite lower overall WER. Many trials
still finalize at EOF: 199/289 on S08 and 274/397 on S06 in the improved path.
An EOF final is not evidence of an automatically detected conversational turn.
Worst per-clip processed clipping fraction falls from 7.655% / 14.817% to
0.056% / 0.056% respectively. Gain-only calibration cannot restore SNR or
separate simultaneous speakers.

Room-file pipeline RTF increases from 0.106/0.121 to 0.201/0.205 because the
preview retains streaming drafts and also decodes a final. Completion-after-VAD
p50/p95 is 1,590/2,085 ms on S08 and 1,621/2,251 ms on S06, including final
decoding but excluding TTS/hardware. These timings are relative to detected
activity, not the last human word. Only trials with a silence candidate enter
these latency distributions.

This is the best configuration among the models and development settings tested,
**not production-quality room recognition**. Overall WER and the small clean-speech
scores remain above a dependable household target. No quality gate is signed off.

### Continuous and Manager Checks

Fixed 300-second room prefixes were replayed without reference segmentation.
Diagnostic chronological WER changed from 86.1% to 64.0% on S08, and 75.0% to
53.2% on S06. These remain affected by overlap ordering and excluded-reference
insertions and are **not** the primary accuracy result. Pipeline RTF was about
0.089 for Zipformer and 0.193 for Parakeet finals. All sessions closed. Parakeet
still required seven/six forced 30-second boundaries respectively, so it has not
solved conversational endpointing. Replay output was simulated throughout.

All **1,711 recording/annotation cases** across the six recordings assembled
their final turns exactly, preserving duplicate/stale/post-close protections.
These are not 1,711 unique sentences: sessions are repeated across microphone
recordings. Attribution was fixture-derived, not speaker recognition. The M1.4
software gate remains separate from M1.3 speech accuracy and household hardware gates.

## Resources and Verification

Host: Windows 10 19045, Intel i7-4790K, eight logical CPUs, about 16 GiB RAM,
Python 3.12.11; sherpa-onnx/core 1.12.40. No GPU or inference service was used.
An isolated, network-blocked worker benchmark loaded the baseline plus Parakeet
in 7.842 seconds and warmed them in 0.337 seconds, with sampled peak RSS
928.3 MiB. This load/warm check is not a worst-case capture RAM bound. The study
process, holding additional comparison recognizers, peaked at about 1.54 GiB.
Each preview job reloads/releases models; there is no permanent warmed listener.

Verification: **168 tests pass**, `ruff check src tests` passes, source/wheel
builds and installed-wheel help/version/catalog smoke checks pass. Packaging was
inspected to exclude WAVs, model weights and `.local` caches. Real model file
evaluation and the isolated benchmark ran with sockets blocked. Simulated
capture verifies that heavy final decoding happens only after the microphone
stream closes. No household hardware was activated or signed off.

Local text-free artifacts: `.local/asr-study/validation.json` (28 completed
recording/protocol/backend measurements), `frozen.json`, model/development
comparisons, `downloads.json`, and `parakeet-benchmark.json`. Per-row reference
and transcript text fields were checked to be absent. Reproduction commands
below use the same packaged adapters; acquisition remains a separate explicit action.

## Integration and Limits

The stronger recognizer only replaces the final transcript; streaming drafts
remain Zipformer. Audio retained for final decoding is capped at 30 seconds and
released afterward. VAD still controls whether a trial may finalize, so no-VAD
speech remains a miss and silent input cannot create a transcript. This is not
semantic endpointing or overlapping-speaker separation.

Native capture closes before final decoding and reports the finalization phase
with audio off. Heavy decoding remains outside the pure room manager. Transcript
revisions and the existing final/cancellation/session contract are preserved.
Models are opt-in, verified before audio opens, and never acquired during loading.
The wizard's Zipformer/room defaults are unchanged pending household trials.

Use the [installation guide](local-voice-profile.md#optional-higher-accuracy-finals).
For this workspace's downloaded models:

```sh
family-harness room --models .local/m14-models evaluate E:/Datasets/DiPCo --mode recognizer --recognizer parakeet-v2 --preset close-talk --gain-db 24 --split eval --report .local/asr-eval.json
family-harness room --models .local/m14-models evaluate E:/Datasets/DiPCo --recognizer parakeet-v2 --preset quiet-final --split eval --report .local/pipeline-eval.json
family-harness setup --models .local/m14-models --recognizer parakeet-v2
```

The high-gain preset is for similarly quiet recordings. Inspect clipping and
near/far recognition before using it with a device. It never changes Windows
input volume. All six recordings and their annotations now live in
`E:/Datasets/DiPCo`, including the additional S06/P25/S09 samples. Models, audio,
per-row numerical reports,
and transcripts are not committed. This study stops at bounded validation and
does not advance M1.5 or mark household exit gates complete.
