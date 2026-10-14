# People and group turns preview (M1.5)

**Implemented bounded preview, 2026-10-12.** Local enrollment, stable person IDs,
voice similarity with explicit unknown states, attributed group WAV replay,
participation policy, and attribution revisions are available. The localhost page
also offers an explicit bounded enrollment and group microphone trial. Family
Harness is still under development. Continuous live conversations, memory and tools remain planned.
[M1.6](interruptions.md) adds a bounded physical interruption preview; its hardware gate remains pending. The M1.5 household/quality exit gate is pending;
see the [current home recognition results](m15-home-recognition.md). Home defaults
recognize more enrolled speech, with more false assignments; personalization
quality is still insufficient.

## Try enrollment and a group trial

1. Install/update the Python package with `uv sync` or the Windows installer.
   Installation opens no devices and acquires no voice weights.
2. Run `family-harness setup`. Choose/test the room microphone. In **People and
   group turns**, explicitly download the TitaNet speaker model (96.7 MiB) and speech
   segmentation (6.6 MiB). A local folder can supply the original catalog files
   offline. Allow about 400 MiB of free staging space. Missing/corrupt models fail
   before capture, with recovery instructions; inference never downloads models.
3. With the person's agreement, enter their name and confirm consent. Start
   **Record three phrases**. During each of three six-second windows, speak a
   different sentence for at least four seconds. Other people should stay quiet.
4. Capture closes before segmentation/embedding inference. The speech in each
   window must be long enough; silence, gaps, excessive clipping, detected overlap,
   and weak consistency fail the take. Review who spoke and the result, then press
   **Save this voice profile**. Repeating or stopping discards an unsaved candidate.
5. Install the English CPU profile in **Quick Setup > Models** for Zipformer
   transcription, or install the selected optional final recognizer. The speaker
   and segmentation models alone do not provide speech transcription.
6. Enroll a second person. Choose participation, then deliberately start **Try
   group turns**. Speak in turn, including an unenrolled guest. Capture closes
   after 30 seconds; attribution/transcription then run locally. Review the names,
   session speaker tracks, uncertain states, and transcripts. Test responses are
   simulated and silent. This is an offline analysis of bounded captured audio,
   not a live conversational assistant.

Failed previews show the specific error and recovery steps beside the trial
button. Model-loading failures happen before microphone capture and should be
repaired through Models rather than Windows microphone permissions.

Use Stop any time. Enrollment/group jobs share the acoustic/voice operation slot,
killable worker, deadlines, and three-second browser lease. No speaker opens in
these people previews. Audio is retained only in the bounded worker's RAM and is
discarded when it exits. Household hardware has **not** been exercised in the
development validation. A successful job is not a quality gate.

Names accept Farsi and other local text; UUID person IDs survive restart and name
changes. These evaluated weights are English/VoxCeleb profiles. Farsi speaker and
speech quality is unverified. Profiles are ordinary local sensitive files, not
encrypted biometric vaults. They contain embeddings, names, model fingerprint,
and sample count, without recordings or transcripts. Default storage is
`%LOCALAPPDATA%/FamilyHarness/people.json`; use `setup --people PATH` or
`people --people PATH` to select a private alternative. Removal deletes the
selected profile from this file; it does not delete backups or the installed model.

## File enrollment and replay

```sh
family-harness people install-model
family-harness people install-segmentation
family-harness people status
family-harness people enroll phrase1.wav phrase2.wav phrase3.wav --name "Person name"
family-harness people list
family-harness people identify another-phrase.wav
family-harness room group conversation.wav --report .local/group.json
```

File enrollment is an explicit save action for a consenting speaker. Supply three
to eight separate single-speaker PCM16 mono phrases at 8–48 kHz, each 2–30 seconds.
Four or more seconds of clear speech per phrase is recommended; older short
profiles remain readable. Guided capture requires four seconds per window.
Unlike guided capture, the generic file enrollment adapter checks signal/embedding
quality but does not prove that every sample contains only one voice. Inspect your
files first. The native guide additionally uses automatic speech segmentation.
Choose `--from-directory PATH` on either install command for offline import.
`people --backend wespeaker-resnet34` selects a smaller comparison model; all
profiles in one matching operation must use the selected backend and identical
prepared model fingerprint. There is no silent profile/model migration.

The default changed from ResNet293 to TitaNet. To keep existing profiles, select
`setup --speaker-backend wespeaker-resnet293`, `people --backend
wespeaker-resnet293`, or `room group --speaker-backend wespeaker-resnet293`.
To try TitaNet without mixing incompatible profiles, use a separate private file:
`setup --people .local/titanet-people.json --speaker-backend titanet-large` and
deliberately install/enroll there. Existing profiles and models are retained.

The initial Balanced recognition policy uses cosine threshold 0.3, margin 0.08,
and minimum 0.7 seconds. Setup and CLI provide editable Free, Balanced and Strict
presets with a saved selection; see [recognition policies](recognition-policies.md).
Exact ties remain ambiguous. The previous conservative threshold
0.575/margin 0 remains available through explicit overrides. CLI `people identify`, `room group` and
speaker evaluation accept `--threshold`, `--margin` and `--minimum-seconds`
overrides for one run. A score is not a probability. Lowering thresholds can increase false
assignments; it does not establish a successful quality trial.

For this workspace's installed models, put `--models .local/m14-models` immediately
after `people` or `room`. `room group` defaults to Parakeet finals; explicitly
install `voice install-recognizer parakeet-v2` first, or select `--recognizer
zipformer` with the baseline profile. Group WAVs are bounded to 300 seconds; use
`--seconds 60` to analyze a prefix of a longer recording. No annotation boundaries
or participant count reach the diarizer. Overlapping predicted tracks stay unknown
and request repetition in the report; short acknowledgments can retain a session
track while their person remains unknown. Speaker separation is not implemented.
Reports omit transcripts and embeddings. Local recordings, profiles, and reports
must remain outside source control.

## Contracts and policy

The room manager stays a pure reducer; maintained sherpa-onnx embedding,
segmentation/clustering, and ASR run outside it. `speaker_track` describes a
session-local acoustic cluster. `person_id` is the stable enrolled UUID.
`identity_confidence` is explicitly a **cosine similarity, not a probability**.
Unknown, ambiguous, overlap, insufficient/unusable audio, and not-enrolled states
retain no resolved person. Wrong confident matches remain possible.

An `attribution` event has its own increasing `revision`, `utterance_id`,
`speaker_track`, nullable `person_id`/`score`, `state`, evidence `start`/`end`,
`backend`, and prepared `model_hash`. Evidence must be inside that utterance's
source interval. Wrong source/session, old revision, audio-gap watermark, discarded
turn, and closed session cannot apply stale attribution. Final transcript words
remain immutable. Late identity updates cannot create duplicate/retroactive replies.

`--participation all` lets known and unknown contributors request test responses.
`enrolled` requires matched identity at finalization; losing that match can cancel
unfinished output. `addressed` requires an explicit `addressed: true` transcript
event, supplied by an adapter/fixture. No wake phrase or semantic addressee detector
is implemented, so WAV/native addressed trials suppress all replies. Suppressed
turns remain in history. This policy controls test responses only: recognition
does not authorize sensitive tools, disclose personal memories, or imply that
everyone in the room has been observed.

## Model provenance and remaining work

[`speaker_catalog.json`](../src/family_harness/speaker_catalog.json) pins six
speaker model downloads, sizes, SHA-256 hashes and license attribution. The three
WeSpeaker choices record separate Apache-2.0 code /
CC-BY-4.0 VoxCeleb-weight provenance. Explicit installation sets the ONNX metadata
`feature_normalize_type=global-mean` so sherpa-onnx performs WeSpeaker's documented
feature mean subtraction. Neural weights are unchanged. Original download hashes
and prepared installed-file hashes are checked separately; profiles use the latter.
ONNX 1.19.1 is installation tooling, lazily imported during preparation.
TitaNet retains its NeMo frontend and CC-BY-4.0 weights; the two English 3D-Speaker
comparison models retain their original exports and Apache-2.0 weights. None is
installed as a startup side effect. The [follow-up](m15-speaker-follow-up.md)
records comparisons, integrity/provenance and the remaining quality failures.
The [home tuning study](m15-home-recognition.md) records the current matching and
enrollment choices. Changing thresholds alone does not require reenrollment.

[`segmentation_catalog.json`](../src/family_harness/segmentation_catalog.json)
pins sherpa-onnx's public ONNX conversion of MIT-licensed pyannote segmentation-3.0.
No cloud account or inference service is used. Segmentation/clustering is offline;
its observed CPU factor can exceed real time, before ASR. The retained 300-second
replay audio and per-job models are released afterward. Native jobs retain at most
18/30 seconds, close capture before heavy inference, and have a 180-second deadline.

Before M1.5 can pass, deliberately validate the first household's two consenting
enrolled speakers and a guest offline, at intended distances, including fast
handovers, brief acknowledgments, uncertainty and failure recovery. Measure wrong
person assignments separately from rejected known voices and rejected/accepted
guests. Current DiPCo evidence does not establish dependable autonomous attribution.
The [M1.6 bounded trial](interruptions.md) now adds playback cancellation and post-capture continuation analysis. Physical interruption and integrated milestone validation remain separate pending gates.

## Household quality trial

This trial requires deliberate action by the people in the room. Dataset replay
has not exercised their microphone, placement or voices.

1. Enroll two consenting people, alone, using three different sentences each.
   Include the intended speaking position. Review/save each profile explicitly.
   Keep a third consenting participant unenrolled.
2. Choose **Everyone** participation and run the bounded 30-second group trial.
   Take turns between all three people. Include handovers without a silent gap,
   brief acknowledgments and ordinary phrases; keep the primary sequence free
   of overlap. Repeat at nearby and intended farthest positions.
3. Collect at least 20 turns from each participant at each position over repeated
   trials. Keep a local ground-truth tally of who actually spoke, including every
   short, rejected, missed or unusable turn. Score automatic results, without
   supplying annotation boundaries or a speaker count. Extra spurious turns and
   mixed-speaker regions are failures, not additional correct observations.
4. For known speakers count correct, wrong person and unknown/missed turns;
   for the guest count rejected and falsely accepted turns. Known recall is
   correct/known turns; guest rejection is rejected/guest turns; assigned
   precision is correct/(correct + wrong known + accepted guest). Report all
   three and the number of actual turns, rather than accuracy on accepted turns.
5. Review processing time and model loading separately. A complete processing
   RTF below 1, alongside proposed 85% known recall, 95% guest rejection and
   assigned precision, and 90% balanced accuracy, is the working target. These
   are local engineering targets, not guarantees or official DiPCo standards.
6. Separately try a brief overlap, stop during capture/analysis, reopen setup,
   and exercise **Enrolled only** participation. Unknown speech should request
   repetition or suppress a test response as appropriate. Capture must stop;
   no audio should be saved. These responses remain simulated and silent.

If most contributions remain unknown, the trial fails recognition quality even
when wrong names are rare. Revisit microphone placement, enrollment and model
choice with the recorded failures. Store any personal tally/profile only in a
private local path outside source control. A completed preview job does not
automatically sign off the milestone.
