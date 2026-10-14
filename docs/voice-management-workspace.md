# Quick Setup: Voice Management workspace

**D1 build specification, 2026-10-12.** The software preview is implemented;
see the [delivered dashboard guide](dashboard.md) for behavior and quality limits. See the
[application plan](dashboard-plan.md) and [delivery roadmap](dashboard-roadmap.md).

## One workspace, two views

**Guided Setup** puts every step in order with a useful explanation, explicit
test/start action, results, and repair. **Voice Lab** uses the same configuration
with freely selectable scenarios, live observation, parameter drafts, and run
comparisons. Switching views leaves the configuration intact and never starts audio.

Quick Setup begins with the space/room and enters Voice Management. Later modules
for agent, tools/access and memory sit beside it; they do not become prerequisites
for voice testing. Enrollment is optional for basic speech tests. Identity/group
quality tests explain that two enrolled people and an unenrolled guest are needed.

## Guided setup steps

| Step | What the user does | Result and recovery |
| --- | --- | --- |
| **1. Room & listening** | Name the space/room, choose intended use/position, learn the microphone/output states and Stop all. | Stable context; audio off. Explain that a diagnostic test is not a persistent assistant. |
| **2. Microphone & speaker** | Refresh native devices, select by friendly names, run the bounded microphone and speaker checks, confirm hearing. | Live input level with text, silence/clipping advice, explicit output hearing confirmation. Missing devices require reselection. |
| **3. Room sound & echo** | Quiet noise test, nearby/far speech, select/confirm one echo owner, run duplex playback/speech. | Raw/clean measurements, clipping/gaps, placement and echo recovery. Unmeasurable device DSP stays unknown. |
| **4. Speech & models** | Choose installed supported English profile/final recognizer; explicitly install/import missing assets; verify and benchmark. | Download purpose/size, integrity and progress; load/warm/CPU/RAM timings with audio off; actionable failures. |
| **5. People & recognition** | Obtain consent, capture/review/save three enrollment phrases; add another person or skip; select/customize recognition preset. | Stable person IDs, quality/incompatibility guidance, remove/re-enroll. The guest remains unenrolled; recognition does not grant access. |
| **6. Participation & turn timing** | Choose Everyone/Enrolled; try pauses and handovers; inspect speech/timing choices. | Participation is separate from identity and authorization. Addressed-only works only with explicit addressed events; no wake/addressee detection is claimed. |
| **7. Live test & tune** | Start a chosen scenario, watch words/attribution/playback, interrupt, let another speaker continue, adjust a draft and take again. | Genuine live diagnostics plus labeled pending analysis, heard chunks, unknown/overlap recovery and comparisons. |
| **8. Review & save** | Review settings/evidence/limitations; save configuration or a named profile; optionally export numeric results. | Setup summary and targeted retest actions. Save/reopen leave audio off. Session start belongs to D2. |

Preserve current short-test limits: microphone 8 s, noise 5 s, speaker 3 s, duplex
12 s, voice utterance at most 20 s, enrollment three 6 s windows, group capture
30 s, and interruption capture at most 20 s. These existing modes remain useful
even when the new integrated lab is added.

## Voice Lab layout

- **Context and controls:** room, selected devices/profile, explicit scenario/start,
  remaining time, actual microphone/output state and always-available Stop all.
- **Live conversation:** replaceable drafts, immutable final words, temporary
  speaker labels, separate identity state, and response text with confirmed heard
  chunks versus uncertain/unplayed portions.
- **Live signal and event lanes:** raw/processed input, VAD activity, utterance
  boundaries, attribution updates, response/playback, interruption/stop, and gaps.
  Source audio time and processing/arrival time are distinct.
- **Tune drawer:** plain-language controls; Advanced opens supported numeric
  parameters and exact effective values. Draft changes can be prepared during a
  take but apply to the next take.
- **Results and comparison:** numeric timing/resource/error counts, manual
  observations, settings diff, limitations, rerun/repair, and explicit save/export.

Default to a compact useful monitor. Expand event payloads, queue statistics,
model hashes and provider internals on request. No fabricated activity, random
waveform, or guessed identity should look like measured runtime data.

## Test catalog: M1.1 through M1.6

| Scenario | Capabilities exercised | Live display and outcome |
| --- | --- | --- |
| **Audio check (M1.1)** | Discovery/selection, capture/playback, cancellation, save/reopen, permission/missing-device repair | Friendly IDs, raw levels, silence/clipping, output state, manual “I heard it.” Device discovery itself opens no microphone. |
| **Room sound (M1.2)** | Noise, placement, one echo owner, exact playback reference, duplex, clocks/gaps | Raw/clean levels and available echo metrics; nearby/far test labels, gaps/drops. Show a measure's limits instead of a universal acoustic pass. |
| **Speech check (M1.3)** | Install/import/status/warm-up, VAD, streaming STT, stronger finals, local TTS, completion timing | Model operations with audio off; then drafts/final, raw/adjusted level, silence candidate and fixed response. Split load, warm-up, decode, synthesis and playback times. |
| **Turn assembly (M1.4)** | Session lifecycle, transcript revisions, response IDs, playback, late/duplicate events, closure/cancellation | Live multi-turn timeline plus device-free event fixtures for reorder/duplicate/post-close cases. Fixture labels remain visible and fixtures do not run against live hardware. |
| **People & group (M1.5)** | Enrollment quality, speaker changes, known/unknown/ambiguous/overlap, attribution revisions, participation | Live pending/provisional/final attribution; similarity and runner-up gap as scores. Two people/guest scenarios, short turns, fast handover, repeat-one-at-a-time recovery. |
| **Interrupt & continue (M1.6)** | Onset-driven output stop, generation cancellation boundary, heard-chunk evidence, overlap/recovery, contention and restart | Quiet fixed-cue playback, a speaker interrupts, another continues; stop request/ack/DAC timing, complete heard chunks and uncertain fragment. Fixed responder cancellation is not an LLM cancellation test. |
| **Integrated room check** | Audio → speech → group turns → deterministic replies → interruption → continuation | New bounded live test session; combine current components without implying an agent or permanent listener. Explicit sequence and manual tally cover all attempts. |
| **Local replay/compare** | Repeatable speech/manager/identity/interruption evaluation using existing adapters | Explicit bounded local WAV/event input, protocol/settings/model identity, metrics and reports. Recorded replay does not prove physical echo or stop latency. |

Use a guided scenario runner to explain prerequisites and request each deliberate
hardware action. Do not automatically unplug hardware, change OS permissions,
start capture, or run a subsequent recording test when the previous test finishes.
Failure drills provide user instructions and simulated fixtures for automation.

## What “live” must mean

Today's voice trial streams single-utterance drafts; group and interruption trials
perform heavy transcription/attribution after capture closes. Displaying those
final results in a refreshed dashboard would not fulfill the live-lab requirement.

Add a **bounded native diagnostic session**: proposed default 60 s, hard maximum
180 s, explicit start, countdown, Stop, and no automatic extension/restart. These
are new planned limits, not changes to the existing tests. Keep per-utterance
audio bounded to the current 30 s ceiling and show forced boundaries. Enrollment
continues to use its separate explicit capture/review/save flow.

During that new session:

1. Models verify/load/warm with devices closed; failure returns recovery.
2. Native audio opens only after the explicit start and readiness checks. Callback
   work remains bounded, with exact output reference, clocks and gap handling.
3. Streaming ASR publishes replacement drafts and finalized turns as capture
   continues. Whole-utterance final recognition runs asynchronously; lag is visible.
4. Incremental, bounded speech segmentation/identity work publishes versioned
   evidence while the session remains active. Pending identity is shown as pending;
   unknown is a legitimate result. Never attach a name merely to fill the UI.
5. RoomManager receives timestamped events; a deterministic local responder and
   TTS execute eligible reply commands. No LLM or useful tool is needed in D1.
6. Speech onset stops output without waiting for final text or identity. Heard
   history includes only confirmed complete chunks; interrupted fragments remain
   uncertain. A late result cannot revive output or rewrite finalized words.
7. On Stop/end/gap/deadline, cancel outstanding work, close devices, settle evidence,
   discard incomplete input, and release models/buffers. Never bridge missing audio.

Offline diarization needs an incremental adapter, bounded evidence windows and
reconciliation of session speaker tracks. Reuse maintained inference components;
do not reimplement their internals. One background attribution worker with bounded
pending work is the initial design. Coalesce superseded work and show lag; on
overload stop the test with recovery instead of growing an unbounded queue.

Distinguish provisional attribution from final identity, and displayed identity
from eligibility for a test reply. Enrolled-only participation cannot speak on an
unresolved candidate. Later attribution must respect the manager's cancellation
and no-retroactive-reply rules. Overlap stays unresolved unless supported evidence
exists; D1 does not promise source separation or accurate no-gap diarization.

## Tunable parameters and exact semantics

All controls show units, default/current/draft values, valid range, likely
consequence, and when they take effect. The initial values follow the current
implementation, not the best score on a different recording.

| Group / parameter | Current value or supported choices | D1 treatment |
| --- | --- | --- |
| Input/output and intended use | Native host devices; room/headset context; explicit hearing confirmation | Select/retest in UI; device changes require idle audio and invalidate related evidence. |
| Echo owner | Family Harness software / confirmed device processing | Idle-only change; one owner; rerun duplex. Keep echo processing distinct from speech input conditioning. |
| Speech preset | `room` initially; current `VOICE_PRESETS` alternatives | Browser-selectable; show resolved fields and condition-specific limitations of high-gain presets. |
| Fixed input gain | 0 dB default; 0–36 dB | Next take; watch clipping/noise. No change to Windows hardware settings. |
| Speech input processing | Current WebRTC processing on/off | Next take; expose actual conditioning. Separate NS/AGC controls require adapter support; current adaptive gain cap 30 dB is initially read-only. |
| VAD threshold | 0.5 default; 0.1–0.9 | Next take; explain sensitivity versus false activity. VAD threshold is separate from identity similarity. |
| Completion silence | 0.6 s default; 0.3–2 s | Next take; longer pauses can prevent premature endings but delay finalization. |
| Streaming decoder | `greedy_search` / `modified_beam_search` | Next take with a reload/benchmark as required; report compute impact. |
| Final recognizer | Zipformer / installed Parakeet v2 / installed Whisper small.en | Select, explicitly install/import/remove as supported; next job reload. Stronger finals do not become streaming backends. |
| Recognition preset | Free / Balanced initially / Strict; independently editable | Keep current persistence compatible; do not replace identity data or permissions. |
| Minimum voice similarity | Balanced 0.30; 0–1 | Next take; cosine score, never a correctness percentage. Free 0.20; Strict 0.575. |
| Runner-up gap | Balanced 0.08; 0–1 | Next take; require separation from another candidate. Free 0.04; Strict 0.08. |
| Minimum matching speech | 0.7 s; 0.5–5 s | Next take; provider usable-speech checks also apply; short turns can remain unknown. |
| Speaker backend | TitaNet default; current catalog alternatives | Idle-only/model reload; verify profile fingerprint compatibility or require deliberate separate reenrollment. Never silently migrate profiles. |
| Participation | Everyone / matched enrolled / explicitly addressed fixture events | Next take; does not change recognition or access. Addressed-only native tests suppress replies until a real addressed-event adapter exists. |
| Interruption onset hold | 0.08 s default; 0–0.5 s | Add typed native-worker binding; current evaluation already permits overrides. Next take; shorter holds may react to noise. |
| Interruption release | 0.3 s default; 0.1–1 s | Add typed worker binding to existing `InterruptionSettings`; next take. |
| Test duration | Existing fixed short modes; new live-session 60 s default / 180 s hard cap | Explicit selection before start. No removal of safety limits through Advanced. |

Model thread counts, decoder beam details, TTS speed/voice, clustering thresholds,
frame sizes, queue capacities, VAD release internals and alignment granularity are
initially read-only unless the current adapter exposes a validated setter. Add a
specific control only after wiring it through the backend and testing its effect.
Do not advertise “tune everything” as an arbitrary configuration editor. Sensitive
access rules, callback stopping, identity ambiguity and bounded buffers are invariants.

Prepare drafts while observing a test; **Apply to next take** snapshots them for a
new job. **Save profile** persists a named configuration explicitly. Saved changes
never alter an active run. Model/device/backend/echo changes require Stop first.
**Restore defaults** updates the draft and still requires explicit apply/save.
Keep a settings revision with each run and reject conflicting saves from stale tabs.

## Metrics, comparisons and readiness

Show input levels/clipping/gaps, detected speech, partial/final latency, completion
latency, identity delay, capture queue delay, load/warm/decode/TTS time, sampled RSS,
and process CPU with its definition. Aggregate p50/p95 only over a stated sample
count. Instrument UI receipt lag separately from processing and physical audio delay.

For identity, tally correct known, wrong known, unknown/missed known, guest rejected
and guest falsely accepted. For interruptions, tally all attempts, detections,
misses, quiet-playback false stops and continuation outcomes. Manual observations
are explicitly user-provided ground truth, not model confidence. Optional known
test phrases allow labeled transcript evaluation; no automatic WER without reference.

Compare A/B effective settings side by side with units, sample counts and settings
diff. Same-input replay is repeatable; separate live retakes are different samples.
If devices, placement, model/profile, protocol or reference changed, mark the
comparison as different conditions. Enrollment samples are not recognition test data.
Repeated tuning success is not independent validation; reserve fresh phrases/trials.

Readiness records: configuration completeness, model compatibility, software test
results, human hearing confirmation, measured household quality and unknown/stale
evidence. Avoid a single “passed” flag. Bind evidence to device/echo/model/settings
fingerprints; invalidate affected results after changes. Physical output stop
measurement remains separate from `stop_to_first_zero_dac_ms`.

## Backend integration, storage and recovery

Reuse `/api/state`, `/api/devices`, `/api/tests`, `/api/voice`, `/api/people`,
`/api/interruptions`, `/api/recognition-policies`, `/api/config`, `/api/job`, and
`/api/stop`. Extend their internal service boundaries rather than invoking CLI
commands from browser handlers. Proposed additions: capability/settings schema,
versioned settings save, live diagnostic session commands and ordered event polling.
Exact endpoint names are implementation details to settle in D1.3.

Begin with the existing 250 ms polling transport and add sequence/cursor plus
bounded event retention; do not require a new streaming dependency just for meters.
Publish at most about 10 meter updates per second and coalesce them. Deliver
transcript revisions and lifecycle events separately; on cursor loss return a
versioned snapshot/reset notice, never silently omit a stop or gap.

Events carry job/session/source IDs, monotonic sequence, source audio time,
processing time, event kind, utterance/response IDs where applicable, revision,
settings revision and explicit evidence state. No raw waveform, embedding, secret,
or transcript enters persistent telemetry by default. Render personal text as text,
not HTML. The client ignores stale session/revision updates.

Use one exclusive operation/controller at a time. Retain the three-second lease
and hard worker deadlines; authenticated heartbeats from the owning tab renew it
independently of UI rendering. Observer polling cannot renew it. Tab throttling,
disconnect and missed heartbeats fail closed; reconnect offers an explicit new take.
UI unload Stop is best-effort; backend watchdog/worker limits provide the guarantee.

Persist only explicit configuration/profile saves and consenting enrollment.
Numeric diagnostic export is opt-in, versioned, and excludes text, audio, embeddings,
names/identifiers and unnecessary host paths by default. Warn before a user elects
to include identifying device details. WAV replay is explicit bounded local import,
with no upload or automatic recording archive. Preserve the existing import limits
and add a purpose-specific upload path rather than raising JSON request limits.

For each failure, offer a concrete action: missing device → reconnect/refresh/select;
quiet speech → placement/volume and retest; echo → one owner/volume/duplex;
bad identity → enrollment review/preset comparison; corrupt model → deliberate
repair/import; overload → lighter installed final/shorter test/close busy apps;
gap → discarded incomplete turn and new take. Navigation, restart and recovery
never start listening automatically.

Verification belongs to [D1's delivery gates](dashboard-roadmap.md#d1-completion-gates):
simulate audio and races in automation, test real hardware only by deliberate
household actions, and report software success separately from measured quality.
