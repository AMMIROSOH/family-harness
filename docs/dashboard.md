# Local dashboard and Voice Lab (D1)

**Implemented diagnostic preview, 2026-10-12.** The Windows localhost dashboard
organizes room setup, models, enrollment, bounded live tests, tuning, replay,
comparisons and recovery. Sustained room sessions, the conversational agent,
memory and tools remain later work. Household audio/identity quality and physical
interruption validation remain pending.

## Start and set up

Run `Start-Setup.cmd`, or `uv run family-harness setup`. Opening, navigating,
saving and reopening keep audio off. The browser controls native audio on this
PC; browser microphone capture remains a separate future adapter.

Quick Setup has eight steps: Room, Devices, Acoustics, Models, People, Timing and
recognition, Live test, and Review. Resume remembers the last visited step;
explicitly saved room configuration and tuning survive restart. Unsaved drafts
and takes do not survive reload. Use nearby/far tests, confirm comfortable output
and one echo owner. Saving an untested selection does not validate it.

Install/import the English baseline explicitly. Manage optional Parakeet v2 or
Whisper small.en finals in Models and select them in Timing. Download sizes and
staging requirements are displayed; offline imports require original catalog
files on the PC. Model loading never downloads or falls back to a cloud service.
Speed checks keep devices closed. The original short voice/group/interruption
checks remain available alongside the new live session.

Enrollment requires agreement, three phrases, quality review and explicit save.
Rename keeps the stable person ID; removal deletes the selected local profile.
Speaker-backend changes require compatible fingerprints or deliberate
reenrollment. No recording is stored or profile migrated silently. See the
[people guide](people-and-group-turns.md).

## Live tests and tuning

Select a scenario and explicitly Start live take. Duration defaults to 60 seconds,
with a 10–180 second range. Models verify/load/warm before capture. The integrated
scenario streams drafts/finals, windowed identity, fixed spoken replies,
interruptions and continuation. Speech-only and people-only scenarios withhold
spoken replies. Interruption and quiet-playback scenarios start a control cue
after quiet; quiet playback does not add replies to detected human turns.

The fast duplex/VAD lane does not wait for streaming ASR or heavier final/identity
analysis. Queues and audio windows are bounded. Overload, gaps, stalled input,
Stop, callback limits and the owner-tab lease stop the take. Other tabs may
observe or stop but cannot renew that lease. Reconnecting never starts listening.

Pending, unknown, ambiguous, overlap and insufficient/unusable evidence are
visible. Windowed segmentation is not source separation. The track cosine cutoff
0.75 is an unvalidated diagnostic heuristic; no-gap speaker changes can remain
ambiguous and wrong matches remain possible. Scores are not probabilities or
permissions. Addressed-only suppresses native replies because no addressed-event
detector exists.

Late finals cannot request stale replies over newer speech. Forced 30-second
boundaries discard incomplete turns and request repetition. Only complete chunks
confirmed by the DAC clock count as heard; interrupted fragments remain uncertain.
Parent cancellation retains the last confirmed playback evidence, not a guess
about the final hardware buffer. Physical stopping needs acoustic measurement.

One shared tuning panel serves Guided Setup and Voice Lab. Apply to next take
freezes a draft; a running take never changes invisibly. Save settings/named
profile writes explicitly; Restore defaults edits the draft. Twelve profiles are
supported; stale saves require reload/review. Reports include applicable settings:
offline group replay uses matching/participation/final recognition, rather than
live VAD/completion timing. Thread counts, gain cap and safety limits are read-only.

Saved recognition policies remain shared with CLI. A browser keeps its applied
snapshot until explicit reload/apply. Explicit `setup --recognizer`, `--preset`
and `--speaker-backend` override preferences for that launch without rewriting them.

## Replay, comparisons and privacy

Device-free manager fixtures exercise duplicate events and closure. Explicit
PCM16 mono WAV paths (8–48 kHz) support speech/turn replay for the chosen prefix
up to 180 seconds and group replay up to 300 seconds. Input SHA-256 is recorded;
replay opens no devices. CLI evaluation retains its existing longer protocols.

At most twelve takes stay in page memory. Compare measured resources/latencies,
settings, model/input fingerprints, devices and near/far position. Live retakes
contain different audio. Latency summaries show counts; one sample has no p95.
Timings use VAD/source/queue evidence, not human word boundaries. Frame statistics
cover the streaming speech lane; CPU is percent of one core and RSS is sampled.

Attach user ground-truth counts including missed/wrong/unknown known turns,
guests, interruptions, quiet playback and continuations. Recall/rejection/precision
use explicit denominators. Observations never automatically pass a household gate.
Numeric export excludes audio, text, names, embeddings, secrets, IDs and host paths.

Room choices and explicitly saved tuning profiles live beside the configured
room file in `dashboard-settings.json`. Unknown versions fail visibly and remain
untouched. Dashboard speech results are memory-only until exported; CLI benchmark
reports retain their existing behavior. Health links symptoms to repair steps;
Settings supports system/light/dark appearance and RTL/LTR layout. Mixed English/
Farsi names work, while current speech models are English and Farsi is unverified.

## Validation

Behavior checks simulate audio, device release, gaps, owner/observer leases,
frozen settings, conflicts, live attribution/finals, stale results, immediate
output zeroing and heard chunks. Browser checks use labeled simulated endpoints.
Package checks cover CLI, assets and exclusion of private runtime files.

Device-free checks used local Piper-generated English speech, wall-clock paced
through installed Zipformer/Silero/TitaNet/segmentation with empty enrollment.
Both baseline and Parakeet-final runs completed two turns and four attribution
updates while the session remained active. No personal recordings, devices,
downloads or uploads were used. Baseline loading took 9.226 s; Parakeet loading
took 23.402 s, with 2.337/2.455 s completion latency across two synthetic turns.
These small checks verify integration and reveal model delay; they establish no
household, echo or identity quality. Measure again on the intended PC.

Use deliberate local actions for the [audio trial](audio-setup.md#household-validation-trial),
[people trial](people-and-group-turns.md#household-quality-trial) and
[integrated interruption trial](interruptions.md#integrated-household-exit-trial).
Record environment, near/far positions, two consenting known speakers, a guest,
all attempt counts, quiet/overlap, contention/restart and acoustic stop measurement.
