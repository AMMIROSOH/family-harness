# People and group turns preview (M1.5)

**Implemented bounded preview, 2026-10-12.** Local enrollment, stable person IDs,
voice similarity with explicit unknown states, attributed group WAV replay,
participation policy, and attribution revisions are available. The localhost page
also offers an explicit bounded enrollment and group microphone trial. Family
Harness is still under development. Live conversations, physical interruptions,
memory, and tools remain planned. The M1.5 household/quality exit gate is pending;
see the [DiPCo results](m15-dipco-evaluation.md).

## Try enrollment and a group trial

1. Install/update the Python package with `uv sync` or the Windows installer.
   Installation opens no devices and acquires no voice weights.
2. Run `family-harness setup`. Choose/test the room microphone. In **People and
   group turns**, explicitly download the speaker model (109.0 MiB) and speech
   segmentation (6.6 MiB). A local folder can supply the original catalog files
   offline. Allow about 400 MiB of free staging space. Missing/corrupt models fail
   before capture, with recovery instructions; inference never downloads models.
3. With the person's agreement, enter their name and confirm consent. Start
   **Record three phrases**. During each of three six-second windows, speak a
   different sentence for at least two seconds. Other people should stay quiet.
4. Capture closes before segmentation/embedding inference. The speech in each
   window must be long enough; silence, gaps, excessive clipping, detected overlap,
   and weak consistency fail the take. Review who spoke and the result, then press
   **Save this voice profile**. Repeating or stopping discards an unsaved candidate.
5. Enroll a second person. Choose participation, then deliberately start **Try
   group turns**. Speak in turn, including an unenrolled guest. Capture closes
   after 30 seconds; attribution/transcription then run locally. Review the names,
   session speaker tracks, uncertain states, and transcripts. Test responses are
   simulated and silent. This is an offline analysis of bounded captured audio,
   not a live conversational assistant.

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
Unlike guided capture, the generic file enrollment adapter checks signal/embedding
quality but does not prove that every sample contains only one voice. Inspect your
files first. The native guide additionally uses automatic speech segmentation.
Choose `--from-directory PATH` on either install command for offline import.
`people --backend wespeaker-resnet34` selects a smaller comparison model; all
profiles in one matching operation must use the selected backend and identical
prepared model fingerprint. There is no silent profile/model migration.

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

[`speaker_catalog.json`](../src/family_harness/speaker_catalog.json) pins three
WeSpeaker model downloads, sizes, SHA-256 hashes, and separate Apache-2.0 code /
CC-BY-4.0 VoxCeleb-weight provenance. Explicit installation sets the ONNX metadata
`feature_normalize_type=global-mean` so sherpa-onnx performs WeSpeaker's documented
feature mean subtraction. Neural weights are unchanged. Original download hashes
and prepared installed-file hashes are checked separately; profiles use the latter.
ONNX 1.19.1 is installation tooling, lazily imported during preparation.

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
M1.6 playback interruption and integrated milestone validation are separate work.
