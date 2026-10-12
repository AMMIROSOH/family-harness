# M1.5 DiPCo speaker evaluation, 2026-10-12

M1.5's software preview implements local enrollment and attributed group turns.
**The quality and household exit gate remains pending.** The preceding
[ASR accuracy study](dipco-accuracy.md) improved transcript finals, but its speaker
labels were annotation metadata. These measurements use actual local speaker
models on `E:/Datasets/DiPCo`. They do not replace ASR WER or complete hardware,
Farsi, echo, live conversation, or interruption gates.

## Protocol and development selection

No additional dataset recordings were acquired. All six supplied recordings were
inspected; open-set identity scoring uses the four room channels, which contain
multiple participants. The two close-talk files contain only one target participant
and cannot independently establish two-known-plus-guest behavior.

For each room recording, the enrollment plan takes the first available nonoverlap
annotations of at least 0.7 seconds until six seconds of speech are available for
a participant. Their audio is concatenated and split into three fixed two-second
takes. Participants without six clean seconds are potential guests, not enrolled.
Enrollment uses reference supervision; identification does not receive the test
speaker label. Weak consistency can fail enrollment and those known-person trials
remain errors, rather than being silently dropped. The acceptance check uses mean
pairwise cosine >=0.15 and minimum >=-0.1; it is a basic quality check, not proof that
all three phrases belong to one person.

All enrollment annotation intervals, including unused trailing speech, and every
test interval intersecting them with a one-second guard are excluded. Test and
enrollment audio cannot overlap. All eligible two-person enrollment pairs are
tested; everyone else in that pair's trial is a guest. The six pairs on four-person
recordings repeat sentences and are **not** independent observations. Enrollment
may come from later in a recording; this is an offline verification protocol, not
causal recognition from the start of a meeting. Clip boundaries are reference
supplied. Existing unintelligible/nonlexical/>28-second ASR exclusions are retained.

S02/S09 development uses 96 evenly speaker/time-sampled test annotations per file:
192 unique annotations, 672 pair trials. Three maintained sherpa-onnx CPU models
were compared. Speaker input is normalized to RMS 0.05, with peak limiting, without
changing hardware settings. Thresholds 0.1/0.15/0.2/0.25/0.3/0.35/0.4/0.45/0.5/0.6,
margins 0/0.02/0.04/0.08/0.12, and minimum evidence 0.7/1.0/1.5 seconds produce 450
development configurations. Selection maximizes all-trial balanced accuracy,
averaging known-person correct recall and guest rejection; ties prefer assigned
precision. Always rejecting voices therefore scores 50%, not an apparent success.
Wrong-known assignments, rejected known people, and falsely accepted guests are
reported separately. No text normalization or label exclusions were added to
improve identity scores.

| Model, with correct feature normalization | Best development balanced accuracy | Known recall | Guest rejection | Nonoverlap balanced accuracy |
| --- | --- | --- | --- | --- |
| WeSpeaker ResNet34 LM | 63.5% | 40.2% | 86.9% | 80.2% |
| WeSpeaker CAM++ LM | 52.1% | 6.5% | 97.6% | 55.3% |
| WeSpeaker ResNet293 LM | **66.4%** | **47.3%** | 85.4% | 80.1% |

ResNet293 wins this bounded search. Its frozen identity settings are cosine
threshold **0.3**, runner-up margin **0.08**, and minimum **0.7 seconds**. Its larger
109.0 MiB weights remain optional, acquired only through a deliberate model action.
This is the best tested configuration, not a global best-model claim.

Early development probes exposed missing feature-normalization metadata in the
public WeSpeaker exports. [WeSpeaker's inference example](https://github.com/wenet-e2e/wespeaker/blob/master/wespeaker/bin/infer_onnx.py)
subtracts the feature mean. The pinned [sherpa-onnx implementation](https://github.com/k2-fsa/sherpa-onnx/blob/v1.12.40/sherpa-onnx/csrc/speaker-embedding-extractor-general-impl.h)
implements this when `feature_normalize_type=global-mean` is present. Explicit model
installation adds that metadata; original neural weights are unchanged. The
catalog retains raw artifact integrity and records installed prepared hashes. This
repair and the basic enrollment quality rule were finalized using development
audio before S06/S08 speaker accuracy was read.

## Frozen identity validation

Every eligible test annotation after enrollment/guard exclusions is evaluated on
S06 and S08, with no further identity tuning. Each has four eligible enrolled
profiles and six pair trials. No annotation overlap flag is used to force a test
decision to unknown; overlap below is a reference diagnostic only. Production
group replay separately rejects *predicted* overlap.

| Recording | Unique clips / pair trials | Balanced accuracy | Known correct / known trials | Guest rejected / guest trials | Wrong known / accepted guests |
| --- | --- | --- | --- | --- | --- |
| S06 U04.CH1 | 382 / 2,292 | 56.5% | 371 / 1,146 (32.4%) | 924 / 1,146 (80.6%) | 100 / 222 |
| S08 U01.CH1 | 261 / 1,566 | 62.2% | 346 / 783 (44.2%) | 628 / 783 (80.2%) | 60 / 155 |
| Combined | 643 / 3,858 | **58.8%** | 717 / 1,929 (37.2%) | 1,552 / 1,929 (80.5%) | 160 / 377 |

Combined assigned precision is only **57.2%**. There are 1,052 rejected known-person
trials. The result must not be summarized as “80.5% recognition accuracy”: that is
guest rejection alone, accompanied by weak known-person recall and wrong matches.

Nonoverlap balanced accuracy is 90.0% on S06 (only **5 unique clips / 30 pair
trials**) and 70.4% on S08 (**18 unique clips / 108 pair trials**). Combined is
**74.6%**, with 41/69 correct known trials and 62/69 rejected guest trials. These
tiny, correlated denominators preclude a dependable clean-room quality claim.
Enrollment/guard exclusions removed 15/28 eligible annotations respectively.

## Automatic boundaries and group replay

The maintained sherpa-onnx pyannote-3.0 segmentation/clustering adapter gets audio
only, no reference speaker count or annotation boundaries. ResNet293 embeddings
are reused. A separate bounded development search compares clustering thresholds
0.5/0.7/0.9 on fixed first-60-second S02/S09 prefixes. Threshold 0.9 wins at **63.1%
duration speaker error**. An earlier 300-second threshold-0.3 stress probe fragmented
S02 into 62 tracks; it was stopped before running the bounded comparison. Longer
whole-meeting diarization has not passed validation.

The local duration scorer uses optimal one-to-one label assignment, no collar,
and counts miss, false-alarm and confusion speaker seconds. Overlap contributes
multiple reference speaker seconds. It uses the existing eligible utterance
intervals, which are coarse rather than word-level speech boundaries, and excluded
speech remains audible. This is **not the official DiPCo/CHiME scorer**. Nonoverlap
scoring excludes reference-overlap regions but retains silence/false alarms and
can exceed 100% error.

| Fixed frozen validation prefix | Reference speaker seconds | Miss / false alarm / confusion seconds | Duration speaker error | Detected tracks | Processing RTF |
| --- | --- | --- | --- | --- | --- |
| S06 first 60 seconds | 50.40 | 22.23 / 2.69 / 6.37 | **62.1%** | 5 | 0.752 |
| S08 first 60 seconds | 40.34 | 12.94 / 12.65 / 10.63 | **89.8%** | 7 | 1.008 |

Nonoverlap diagnostic error is 61.9% / 107.4%. The adapter detects too many tracks,
misses speech, and confuses speakers. Reference-bounded identity results must not
be presented as autonomous diarization quality. This evidence leaves M1.5's real
attributed group-conversation gate pending.

An additional offline integration replay runs S02's 300–360-second audio window
through automatic segmentation, two earlier enrolled profiles, Parakeet finals,
and the actual room manager. It checks bounded buffers, attributed/unknown state,
session closure, and text-free reporting. No labels/boundaries reach the production
path; response playback is simulated. This is integration evidence, not an
additional scored meeting result.

## Reproduction and evidence

```sh
uv run family-harness people --models .local/m14-models status
uv run family-harness room --models .local/m14-models evaluate E:/Datasets/DiPCo --mode speakers --split eval --report .local/m15/speakers.json
uv run family-harness room --models .local/m14-models evaluate E:/Datasets/DiPCo --mode diarization --split eval --seconds 60 --report .local/m15/diarization.json
uv run family-harness setup --models .local/m14-models --people .local/my-people.json --recognizer parakeet-v2
```

Evaluations block outbound sockets. Models must be explicitly installed/imported
before running. Three speaker models plus segmentation total **177,118,208 bytes**
of downloads; no DiPCo audio was uploaded and no actual audio device was opened.
Source and prepared hashes, file/annotation hashes, enrollment/test indices,
pair outcomes and fixed settings are in the local numerical reports. Reports have
no reference/recognized text or embeddings. Development embedding caches are local
sensitive artifacts, excluded from source control.

Host: Windows 10 19045, Intel i7-4790K, eight logical CPUs, about 16 GiB RAM,
Python 3.12.11, sherpa-onnx/core 1.12.40, ONNX 1.19.1. Full identity evaluation
took 401 seconds, sampled peak process RSS 529.5 MiB, mean CPU 198.9% of one core,
with per-file processing RTF 0.239/0.228. Other local experiments shared the host;
these are not minimum-hardware or worst-case resource claims. Diarization RTF
excludes loading and ASR; complete native preview latency includes those stages.

Local artifacts: `.local/m15/development.json`, `frozen.json`, `validation.json`,
`diarization-development.json`, `diarization-frozen.json`,
`diarization-validation.json`, and `group-replay.json`. The [people guide](people-and-group-turns.md)
describes deliberate enrollment, uncertainty, privacy, and remaining household trials.

Verification: **191 behavior tests pass**, Ruff and Git whitespace checks pass,
source/wheel builds and installed-wheel help/version/CLI/catalog checks pass.
The wheel/source archives exclude recordings, profiles, weights and local reports.
Model preparation checks compare all three original/prepared neural graphs byte
for byte and confirm only metadata changed. A browser trial with simulated devices
checks the explicit enrollment/save flow. The real-model integration replay closes
with five final turns, four overlap rejections, known and unknown outcomes, and
text-free output; its observed complete processing RTF is 1.356, excluding loading.
These checks opened no household microphone or speaker.
