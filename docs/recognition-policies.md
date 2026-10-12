# Editable voice recognition policies

M1.5 provides three local recognition presets: **Free, Balanced and Strict**.
Balanced is the initial selection. They share the same TitaNet embeddings,
enrolled people and matching method; switching or editing a policy requires no
reenrollment. These presets make the recognition tradeoff manageable. They do
not establish reliable household identification or complete M1.5's quality gate.

| Preset | Intended use | Similarity threshold | Runner-up gap | Minimum speech |
| --- | --- | ---: | ---: | ---: |
| Free | Favor recognizing enrolled speech; expect more wrong names | 0.20 | 0.04 | 0.7 s |
| Balanced | Current home preview compromise; initial default | 0.30 | 0.08 | 0.7 s |
| Strict | Prefer leaving uncertain names unknown | 0.575 | 0.08 | 0.7 s |

The new Strict preset retains an ambiguity gap; the historical strict experiment
used gap zero. Its name is a recognition preference, not a security guarantee.
All presets keep exact ties ambiguous, reject short/unusable audio, and leave
detected overlaps unnamed. Similarity is a cosine comparison, not a probability
of correctness. Raising the minimum duration suppresses more short turns; the
underlying provider may also reject audio without enough usable speech.

Voice identity is a personalization signal. Policy edits never grant access to
private memories or tools. Participation settings (`all`, `enrolled`, `addressed`)
remain a separate choice about simulated preview responses. Live replies,
memory and tool authorization remain planned.

## Manage policies

Run `family-harness setup`. In **People and group turns**, choose the recognition
preset, optionally expand **Customize this recognition preset**, and press
**Save and use this policy**. Saved settings apply to the next group trial.
**Restore this preset's defaults** resets only that preset; the active selection
stays unchanged. Unsaved edits are discarded when switching presets or refreshing
the page. Controls are disabled during an operation; stop it before editing.

Settings persist in `%LOCALAPPDATA%/FamilyHarness/recognition-policies.json`,
separately from the people file. Merely reading defaults creates no file and
loads no models. Saving performs an atomic local replacement. Concurrent edits
use the last completed save; a running job retains its settings snapshot.
`setup`, `people` and `room` accept `--policy-file PATH` for an alternative file.
Do not put local settings or voice profiles into source control.

```sh
family-harness people policies list
family-harness people policies select free
family-harness people policies update free --threshold 0.2 --margin 0.04
family-harness people policies reset free
family-harness people policies reset-all

# Use a saved preset for one run, without changing the saved selection.
family-harness people identify phrase.wav --policy balanced
family-harness room group conversation.wav --policy strict --report group.json

# Explicit numeric overrides take priority for this run only.
family-harness people identify phrase.wav --policy balanced --threshold 0.25
```

CLI `update` edits a preset without selecting it; `select` changes the selection.
`people identify`, `room group` and speaker evaluation use the saved selection
unless `--policy` is supplied. Numeric overrides have final priority. Reports
include the policy name, actual settings, customization and overridden fields.
Low-level `VoiceMatcher` callers must explicitly pass settings to use a saved
policy; their library default remains Balanced.

Invalid values, unexpected permission fields and damaged files fail visibly.
No policy is silently substituted. To recover a damaged file, back it up, then
run `family-harness people --policy-file PATH policies reset-all`. This replaces
only recognition settings with the three defaults and selects Balanced.

These numerical defaults were investigated with TitaNet on English DiPCo audio.
Other backends accept the same configurable comparison settings, but that is not
evidence of equivalent calibration. Farsi and first-household quality still need
deliberate validation.

## DiPCo regression comparison, 2026-10-12

Using `E:/Datasets/DiPCo`, all three presets were scored on identical profiles and
**192 evenly sampled test annotations** across S01 U01.CH1, S03 U04.CH1 and S07
U01.CH1: 64 per recording, **1,152 repeated pair trials** (576 known, 576 guest).
Each person has twelve seconds of clean reference-supervised enrollment, excluded
from testing with a one-second guard. All six intended two-person pairs stay in
the denominator, including unavailable enrollment and short/unusable clips.

| Preset | Known recall | Guest rejection | Assignment precision | Balanced accuracy |
| --- | ---: | ---: | ---: | ---: |
| Free | 42.4% | 58.3% | 42.7% | 50.3% |
| Balanced | 30.2% | 79.9% | 51.6% | 55.0% |
| Strict | 8.3% | 98.6% | 80.0% | 53.5% |

Free gets 244 known trials correct, makes 87 wrong-known assignments and accepts
240 guests. Balanced gets 174 correct, 47 wrong-known and 116 guest accepts.
Strict gets 48 correct, four wrong-known and eight guest accepts. Free therefore
increases recognition while often misnaming guests. Balanced remains the initial
default; Strict's low coverage makes it a poor default for casual home use.

Only **14 unique clips** are wholly nonoverlapping. On that small diagnostic,
Free recall is 85.7% with 64.3% guest rejection; Balanced is 71.4% with 100%; Strict
is 7.1% with 100%. Those correlated, small counts cannot establish reliability.
These are regression results on previously inspected sessions, with reference
test boundaries, not fresh validation or automatic diarization measurements.
They supplement the larger [home tuning study](m15-home-recognition.md).

Local reproduction artifacts: `.local/m15d-presets.py`,
`.local/m15d/presets.json` and private per-recording probe caches. The report
records audio/annotation hashes, enrollment intervals, counts and model SHA-256
`d51abcf31717ef28162f26acb9d44dd4127c3d44c9b8624f699f3425daca8e77`.
No hardware capture, playback, extra downloads or uploads were used for this
comparison. The setup controls were also exercised with simulated devices for
selection, customization, reload and reset; these checks do not sign off hardware.

Validation: **212 behavior tests passed**, lint and diff whitespace checks passed.
Source/wheel builds and a separate installed-wheel check passed, including the
CLI help/version entry points, policy listing, packaged assets and lazy model
imports. Distributions exclude local recordings, weights, profiles and reports.
