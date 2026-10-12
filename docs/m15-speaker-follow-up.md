# M1.5 speaker follow-up, 2026-10-12

**Historical strict preview.** The [home tuning follow-up](m15-home-recognition.md)
records the current 0.3/0.08 defaults and longer enrollment after the strict
recall loss proved impractical. The settings and results below are preserved
with explicit reproduction options.

**The quality and household gate is still pending.** This follow-up fixes overlap
handling, adds three local model choices, and changes the default to a faster,
conservative TitaNet preview. It reduces false assignments substantially, but
rejects most enrolled voices. It does **not** deliver reliable room recognition.
The [earlier study](m15-dipco-evaluation.md) remains historical evidence.

## Implemented repairs

Group replay previously marked an entire segment as overlap when any other track
intersected it. A 0.3-second interruption could discard ten seconds of clean
speech. It now partitions the predicted timeline at every boundary, retaining
clean speech before and after the overlap. Duplicate intervals of the same track
merge. Events reach the room manager in source order: a nested short interruption
no longer arrives after the enclosing segment's later end. Unusable/silent spans
skip ASR safely; decoder failures still surface as errors.

Identical competing profiles now stay ambiguous even when the requested runner-up
margin is zero. Matching settings are visible in people status and group reports.
CLI evaluation, group replay, and identification accept the same explicit
threshold/margin/minimum-duration overrides and use the selected model's defaults.

Evaluation now keeps intended participants with unavailable enrollment in the
known-person denominator. Otherwise, a person lacking six clean enrollment
seconds could silently become a guest in every pair. `--enrollment-pairs eligible`
retains the historical protocol; the new default is `all`. Failed enrollment is
visible and does not count as a successfully enrolled person.

## Models and acquired data

The catalog now offers six explicit, integrity-checked CPU models:

| Added model | Download bytes | Weight license | Preparation |
| --- | ---: | --- | --- |
| NVIDIA TitaNet-Large | 101,405,493 | CC-BY-4.0 | Original NeMo metadata/frontend retained |
| 3D-Speaker English CAM++ | 29,596,978 | Apache-2.0 | Original export retained |
| 3D-Speaker English ERes2Net | 26,485,263 | Apache-2.0 | Original export retained |

The three WeSpeaker choices remain available and retain their explicit feature
mean-subtraction repair. That preparation now runs only for catalogs requiring
it; importing a NeMo or 3D-Speaker model no longer attempts a WeSpeaker conversion.
The [catalog](../src/family_harness/speaker_catalog.json) pins original URLs,
sizes, SHA-256 fingerprints, and attribution. TitaNet's license is from its
[official model card](https://huggingface.co/nvidia/speakerverification_en_titanet_large);
the exact English 3D-Speaker model metadata was checked with ModelScope's official
API. No new runtime library was added to the project.

Downloaded **849,061,303 bytes** of additional DiPCo audio/annotations into
`E:/Datasets/DiPCo`, from the public Hugging Face
[dataset copy](https://huggingface.co/datasets/huckiyang/DiPCo), pinned revision
`e2b29d3d0d88692c744feb15e290f7316b68014e`:

- Development: S04 U01.CH1 plus P13/P14/P15/P16 close-talk; S05 U04.CH1 plus P17.
- Fresh evaluation: S01 U01.CH1 plus P04; S07 U01.CH1.
- Matching development/evaluation annotation JSONs for those four sessions.

Original S02/S09 remain development recordings. S06/S08 are previous evaluation
sessions and cannot be called fresh again. S01/S07 identity results were first
read after freezing the candidate. Their close-talk audio was not used for the
primary validation. Local download manifests retain every source path, byte
count and SHA-256. No dataset audio was uploaded or recorded from hardware.

## Development search and limitations

The initial same-protocol S02/S09 comparison, with 96 sampled annotations per
recording, gave TitaNet **84.8% nonoverlap balanced accuracy**, against the previous
ResNet293 result of about 80.1%. This is a small development subset, not a fresh
quality result. The added 3D-Speaker models performed worse.

A broader search uses S02/S04/S05/S09, **512 unique test annotations**, four intended
participants per session, and all six two-person pairs: **3,072 correlated trials**.
Every unavailable or failed intended enrollment remains an error for known trials.
Only **39 unique test annotations / 234 pair trials** are wholly nonoverlapping.
Test selection is fixed across models and enrollment lengths. It excludes the
union of all 6/12/18-second enrollment annotation intervals with a one-second
guard, including unused trailing speech. Models get reference-bounded audio, not
test identity labels; these are not automatic group-turn measurements.

The search covers 23 cosine thresholds (0.2 through 0.75, step 0.025), four margins
(0/0.04/0.08/0.12), and three minimum durations (0.7/1.5/2 seconds). TitaNet gets
6/12/18-second enrollment; ResNet293 gets the six-second control: **1,104
configurations**. Longer samples help some profiles, but several participants
lack enough clean speech or fail consistency checks. Missing samples were not
invented or removed from the denominator.

For the fixed six-second enrollment comparison, the selected TitaNet settings
are **threshold 0.575, margin 0, minimum 0.7 seconds**. Selection maximizes known
recall subject to at least 95% guest rejection and assigned precision. Development
recall is only **4.3%**, guest rejection **99.9%**, and assigned precision **95.7%**.
This is an abstention-heavy preview, not an acceptance result. A twelve-second
alternative reaches only 4.7% recall at those precision/rejection floors. No
searched configuration meets the proposed recall target.

Additional development experiments were not promoted into the application:

- WeSpeaker Hamming-filterbank/frontend audit: small changes, no quality solution.
- Close-talk/longer enrollment and embedding fusion: insufficient room utility.
  Exploratory atomic-region results are not substituted for original clip scores.
- Silero VAD plus 1.5/3-second embedding windows detects changes without requiring
  silence, but fragments tracks. Best duration error is **87.3%**, versus **74.2%**
  for the existing TitaNet diarizer on the same three 60-second development prefixes.
- VAD trimming at thresholds 0.3/0.5 does not resolve recognition quality.
- Raw, fixed 24/36 dB, and clipped RMS conditioning were compared separately.
  Best development duration error was 70.0% with raw input, still poor; the existing
  conditioning is retained. A large transient can limit global gain, but the tests
  do not support treating that as the main remaining cause or changing household
  microphone settings automatically.
- Stricter enrollment consistency thresholds did not improve the measured
  recognition/precision tradeoff enough to justify changing that rule.

## Fresh S01/S07 identity validation

Frozen settings and all eligible test annotations are used, with no retuning from
these scores. S01 has **726** test annotations and S07 **478**: **1,204 unique clips,
7,224 pair trials**, split equally into 3,612 known and guest trials. Six-second
enrollment plus the one-second guard is identical between the model comparisons.
S07 P22/P23 have insufficient clean enrollment; their intended known trials remain
errors. Reference-overlap flags only stratify scores and never force a decision.

| Configuration on the same fresh clips | Known recall | Guest rejection | Assigned precision | Balanced accuracy |
| --- | ---: | ---: | ---: | ---: |
| Old ResNet293, 0.3 / 0.08 | 25.4% | 85.8% | 55.2% | 55.6% |
| TitaNet, predeclared 0.3 / 0.08 comparison | 20.9% | 91.4% | 62.7% | 56.2% |
| **TitaNet conservative default, 0.575 / 0** | **5.1%** | **99.6%** | **89.9%** | **52.4%** |

The conservative candidate gets **186/3,612** known trials correct, rejects
**3,419** known trials, makes **7** wrong-known assignments and accepts **14** guests.
The old baseline makes 231 wrong-known assignments and accepts 512 guests on the
same protocol. Fewer wrong assignments comes with a substantial recall loss.
The default favors uncertainty; the balanced-accuracy score does not improve.

Wholly nonoverlapping speech comprises **100 unique clips / 600 pair trials**
(98 clips from S01, only two from S07). Conservative known recall is **7.0%**,
guest rejection **100%**, precision **100%** on only 21 accepted trials, and balanced
accuracy **53.5%**. The old baseline scores 67.3% balanced accuracy on that same
subset. High rejection or precision with so little accepted speech cannot pass
the sequential conversation gate. Repeated pair trials and two sessions do not
provide thousands of independent household observations.

## Automatic boundaries and complete processing

Automatic diarization uses only audio, no annotation boundaries or oracle speaker
count. Threshold 0.9 was selected on development. The duration metric remains the
earlier local diagnostic: coarse eligible utterance intervals, optimal one-to-one
track mapping, no collar, and overlap scored. Excluded speech remains audible;
this is not official DiPCo/CHiME DER and error can exceed 100%.

| First 60 seconds | TitaNet duration error / tracks / RTF | ResNet293 duration error / tracks / RTF |
| --- | --- | --- |
| Fresh S01 | 97.8% / 4 / 0.058 | 97.8% / 4 / 0.139 |
| Fresh S07 | 100.5% / 5 / 0.234 | 101.5% / 5 / 1.096 |

TitaNet is faster, but autonomous attribution remains poor. These timing
comparisons shared the host with other experiments and exclude model loading
and ASR. They are not worst-case live latency guarantees.

An uncontended complete integration replay uses the same S02 300–360-second
window as the previous study, two earlier enrolled profiles, automatic pyannote
tracks, TitaNet matching, Parakeet finals and the room manager. It produces nine
final regions, including two overlap regions; it preserves clean contributions
and closes normally. **Zero identities are accepted** at the frozen threshold.
This is integration/throughput evidence, not recognition success.

Processing takes **20.02 seconds for 60 seconds of audio (RTF 0.334)**, versus the
earlier full replay's RTF 1.356. Model loading adds **4.47 seconds**. Sampled peak
RSS is **1,465 MiB** and mean CPU is about **181% of one core**. Model, conditioning,
overlap handling and decoded-region count changed, so this is a complete-configuration
comparison rather than an isolated model speed claim. Playback is simulated;
no live room or interruption gate was exercised.

## Reproduction, upgrade and household work

The [people guide](people-and-group-turns.md) describes deliberate local installation
and reenrollment. Existing ResNet293 profiles require that explicit backend or a
separate people file for TitaNet. Changing the default does not convert or delete
profiles, download weights on startup, or activate audio.

```sh
uv run family-harness people --models .local/m14-models --backend titanet-large status
uv run family-harness room --models .local/m14-models evaluate E:/Datasets/DiPCo --mode speakers --speaker-backend titanet-large --threshold 0.575 --margin 0 --enrollment-seconds 6 --enrollment-regions utterances --split eval --file S01_U01.CH1.wav --enrollment-pairs all --report .local/m15b/reproduced-S01.json
uv run family-harness room --models .local/m14-models evaluate E:/Datasets/DiPCo --mode speakers --speaker-backend titanet-large --threshold 0.575 --margin 0 --enrollment-seconds 6 --enrollment-regions utterances --split eval --file S07_U01.CH1.wav --enrollment-pairs all --report .local/m15b/reproduced-S07.json
```

For the old control, set `--speaker-backend wespeaker-resnet293 --threshold 0.3
--margin 0.08 --minimum-seconds 0.7`. Historical S06/S08 reproduction additionally
uses `--enrollment-pairs eligible`. Evaluations block outbound sockets. Downloaded
models, development embeddings, profiles and reports stay in ignored local storage.

Local evidence includes `.local/m15b/downloads.json`, `model-comparison.json`,
`calibration-grid.json`, `calibration-vad-grid.json`, `quality-calibration.json`,
`frozen.json`, `fresh-validation.json`, `fresh-automatic.json`,
`sequential-boundaries-dev.json`, `level-diarizer-dev.json`, and `group-replay.json`.
The frozen manifest's selection statement applies to the fixed six-second
comparison; longer enrollment experiments did not supply the final default.

Verification: **196 behavior tests**, Ruff, Git whitespace checks, source/wheel
builds, installed-wheel CLI/help/version, catalog and lazy-import checks. Archives
exclude recordings, weights, voice profiles, embedding caches and local reports.
All hardware checks remain pending.

Before signing off M1.5, run the [deliberate household trial](people-and-group-turns.md#household-quality-trial)
with two consenting enrolled people and an unenrolled guest. The suggested
85% known recall, 95% guest rejection/assignment precision, 90% nonoverlap balanced
accuracy and processing RTF below 1 are engineering targets, not official DiPCo
standards. This work meets the measured throughput target on one replay, but
does not meet the identity or automatic-boundary quality targets.
