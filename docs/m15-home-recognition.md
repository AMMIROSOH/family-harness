# M1.5 home recognition tuning, 2026-10-12

The default TitaNet matcher now favors usable recognition coverage: **threshold
0.3, runner-up margin 0.08, minimum evidence 0.7 seconds**. The previous strict
threshold rejected too much enrolled speech for the intended home preview.
Exact ties and insufficient evidence still remain unresolved. **M1.5's quality
and household gate remains pending.** More accepted names also means more wrong
names; this is not reliable personalization yet.

The [editable policy follow-up](recognition-policies.md) adds Free, Balanced and
Strict presets. The home settings below are the initial Balanced values; setup
and CLI now use the user's saved selection. The follow-up compares all three on
the same smaller regression sample and records their different error tradeoffs.

## Changes

- Guided enrollment still captures three six-second windows, but requires at
  least **four seconds of speech in each**, for at least twelve seconds total.
  The UI and recovery message explain the requirement. Capture closes before
  inference. File enrollment retains support for older two-second phrases;
  four seconds or more is recommended. Quality reports show phrase durations.
- Existing TitaNet profiles work with the new matching defaults. No recordings,
  weights, model fingerprints or people files are converted automatically.
- Speaker evaluation supports `--enrollment-seconds 6/12/18`, default twelve.
  Test audio intersecting enrollment and its one-second guard remains excluded.
- Evaluation now supports `--enrollment-regions clean/utterances`, default clean.
  Previously any overlap anywhere in an annotation excluded its entire span
  from enrollment. The new method retains single-speaker portions. A sweep of
  **all** annotations, including excluded nonlexical/unintelligible other voices,
  prevents those audible overlaps from being mislabeled as clean. Training reads
  are bounded; reports include the actual supervised enrollment intervals.

Clean enrollment uses reference supervision only to construct evaluation
profiles. Test utterance boundaries are still reference supplied. Neither
automatic group replay nor microphone enrollment receives dataset annotations,
test identities or an oracle speaker count. This evaluator repair is not an
automatic-diarization improvement.

## Development experiments

Added **283,804,651 bytes** to `E:/Datasets/DiPCo`: S10 U04.CH1 and P29/P30/P31/P32,
S03 U04.CH1, and their annotation JSONs. The public
[Hugging Face copy](https://huggingface.co/datasets/huckiyang/DiPCo) is pinned at
`e2b29d3d0d88692c744feb15e290f7316b68014e`. Sizes and LFS SHA-256 hashes are checked
before a file enters the dataset inventory. The preceding report's incorrect
distribution link was corrected. No hardware audio was captured or uploaded.

Development uses S02/S04/S05/S09/S10. The compared enrollment recipes reserve the
union of their training intervals and guards before selecting test clips. All
six intended two-person pairs are evaluated; failed or unavailable profiles stay
in the known denominator. Repeated pair trials are correlated observations.

Comparing per-phrase templates, maximum similarity, top-two similarity and mixed
centroid/template scoring did not produce enough improvement to justify a
profile-format change. The existing normalized mean embedding is retained.
Longer and clearer samples helped more. A separate S10 close-talk to S09 room
experiment avoids shared enrollment/test recordings, but reaches only 26.8% recall
over all clips and 41.2% on 17 nonoverlap clips. It is a diagnostic, not a gate pass.

At fixed home settings, the clean-subregion enrollment repair creates valid
profiles for all **20 development participants**. On **602 shared test clips /
3,612 pair trials**, known recall rises from **29.2% to 38.3%** compared with
twelve-second whole-utterance enrollment. Guest rejection falls from 87.6% to
81.5%; assignment precision falls from 63.8% to 61.6%. Nonoverlap recall rises
from 64.4% to 68.2%, on only 44 unique clips. These tradeoffs are retained in the
report rather than scoring only accepted identities.

## Frozen home settings and validation

The home matching settings and twelve-second enrollment recommendation were
frozen before first scoring S03. The whole-utterance experiment uses **959 shared
S03 clips / 5,754 pair trials**, excluding both six- and twelve-second training
plans. Six-second strict matching recognizes **1.0%** of intended known trials;
twelve-second home matching recognizes **25.8%**. Guest rejection is 81.7% and
assignment precision only 49.6% over all clips. On the **16 unique nonoverlap
clips**, home recall is 60.4%, guest rejection 95.8%, and precision 93.5%.
The small clean subset cannot establish household reliability.

The clean-subregion enrollment refinement was then selected on development
audio. Subsequent S01/S03/S07 measurements are explicitly **regression results**;
S03 is not claimed as untouched a second time. Comparisons use exactly the same
test annotations after excluding every compared enrollment plan and guard.

On S01/S07, **1,121 shared clips / 6,726 pair trials**:

| Configuration | Known recall | Guest rejection | Assignment precision | Balanced accuracy |
| --- | ---: | ---: | ---: | ---: |
| Previous strict, 6s whole-utterance enrollment | 4.9% | 99.6% | 88.7% | 52.2% |
| Home settings, same 6s enrollment | 20.0% | 91.6% | 61.9% | 55.8% |
| Home settings, 12s whole-utterance enrollment | 20.7% | 91.5% | 63.0% | 56.1% |
| Home settings, 12s clean-subregion enrollment | **27.0%** | **85.0%** | **55.8%** | **56.0%** |

The final row gets 907/3,363 known trials correct, rejects 2,243 known trials,
makes 213 wrong-known assignments and accepts 505/3,363 guests. The strict control
gets 165 known trials correct, with seven wrong-known and fourteen guest accepts.
This is about **5.5 times the recall**, with substantially more false assignments.
These percentages differ slightly from the previous 5.1% result because the
shared test set excludes the additional enrollment audio for a fair comparison.

Across all three regression sessions, **2,046 shared clips / 12,276 pair trials**,
the final configuration gets **26.5% known recall, 83.1% guest rejection, 52.2%
assignment precision and 54.8% balanced accuracy**. The strict control gets 3.1%
recall on that same expanded set. On **106 unique wholly nonoverlap clips**, final
recall is **50.3%**, guest rejection **94.9%**, assignment precision **88.9%**, and
balanced accuracy **72.6%**. No failed enrollment or short test clip was removed
to inflate recall. Overlap is a reference diagnostic, not a supplied test decision.

Recognition coverage improves, but whole-room identity remains unreliable.
Most test annotations overlap other speech, and automatic boundaries remain poor.
The earlier conservative result was not a solved recognition problem; lowering
the threshold does not solve separation either. The first household's deliberately
enrolled voices and automatic sequential turns still require validation.

An unscored complete replay of S02's 300–360-second window uses two twelve-second
profiles enrolled entirely before that window, automatic tracks, home matching,
Parakeet finals and the room manager. It closes with nine regions (two overlap
regions), four accepted identities, and **processing RTF 0.410**; model loading
adds 5.43 seconds. No correctness score is inferred from the four accepted names.
Audio devices remain off, responses are simulated, and the report omits text.

## Reproduction and use

```sh
uv run family-harness setup --models .local/m14-models --people .local/home-people.json
uv run family-harness room --models .local/m14-models evaluate E:/Datasets/DiPCo --mode speakers --speaker-backend titanet-large --file S03_U04.CH1.wav --enrollment-seconds 12 --enrollment-regions clean --report .local/m15c/S03-current.json
```

The ordinary CLI evaluation excludes its own selected enrollment plan. The paired
tables above additionally intersect test sets from all compared plans; their
shared denominators and per-pair outcomes are in the local reports. For historical
strict reproduction set `--threshold 0.575 --margin 0 --enrollment-seconds 6
--enrollment-regions utterances`. This remains an explicit choice, not the default.

Existing profiles need no replacement just to use the home threshold. For new
enrollment, speak alone for four or more seconds per take with the intended
microphone. If replacing an existing profile, remove the old one before saving
the replacement so two copies of the same voice do not compete. Reenrollment
currently creates a new UUID; rename/restart of an existing profile preserves it.
Use the [household quality trial](people-and-group-turns.md#household-quality-trial)
to tally correct, wrong and unknown outcomes at intended speaking distances.

Local evidence: `.local/m15c/downloads.json`, `template-grid.json`,
`enrollment-grid.json`, `clean-enrollment-dev.json`, `cross-session.json`,
`frozen.json`, `validation.json`, and `clean-validation.json`.
The complete replay report is `.local/m15c/group-replay.json`. No new runtime
dependency, weight download, live listener, tool access or memory behavior is
introduced. Inference and evaluation remain local; datasets/profiles/caches stay
outside source control.

Validation: **198 behavior tests**, Ruff, source/wheel builds, installed-wheel
help/version/assets and lazy-import checks. Household hardware and automatic
speaker-attribution quality gates remain pending.
