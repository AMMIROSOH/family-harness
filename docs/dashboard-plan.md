# Application dashboard plan

**Proposed product plan, 2026-10-12. No dashboard implementation is delivered by this document.**

Family Harness will have one local application dashboard for setting up, testing,
using, and maintaining a shared house agent. Quick Setup is its first implemented
workspace; Voice Management is the first complete setup module. The existing
Windows Python application and localhost interface are the starting point.

Read the [delivery roadmap](dashboard-roadmap.md) for sequencing and the
[Voice Management specification](voice-management-workspace.md) for the first build.

## Starting point and assumptions

The M1.1–M1.6 software previews provide audio setup, acoustic tests, local English
speech, room-manager replay, enrollment, group analysis, and a bounded interruption
trial. They provide substantial functionality to organize and reuse. The repository
still records household hardware and speech/identity quality gates as pending.
Continuous live group conversations, a conversational agent, memory, and tools are
not yet implemented. This plan does not change those milestone records.

Initial scope: one household, one active room, Windows native audio, local CPU
processing, and a browser on the same PC. Opening the dashboard leaves audio off.
Phone access, remote administration, multiple simultaneous rooms, cloud inference,
and consumer packaging are later phases. Dates and delivery estimates should follow
the first live-pipeline performance measurements; the roadmap uses acceptance gates.

## Product experience

The dashboard should answer four everyday questions: **Is the room ready? What is
the assistant doing? How do I change something? How do I fix a problem?**

Use a calm, warm visual design with clear typography, generous spacing, restrained
color, and useful motion only for state changes. The home view emphasizes the room,
the next useful action, and concrete problems. Avoid decorative statistics or a
wall of technical gauges. Advanced controls belong beside the feature being tested.

The desktop shell has a compact sidebar, a space/room context in the header, a
central workspace, and an optional details panel. The header always shows actual
microphone/output state and an accessible **Stop all** action. On narrow screens,
navigation becomes a menu and the details panel moves below the main content.
No critical stop or recovery action depends on hover.

An ordinary user follows Guided Setup. Someone investigating recognition opens
Voice Lab without copying settings into a second system. Developer Diagnostics is
an expandable layer with event IDs, model fingerprints, and timing details.

## Application sections

Each section has a useful empty state, a next action, and a recovery path. Later
sections should initially be omitted from primary navigation or appear in a
clearly marked product preview. A planned feature must not resemble an active service.

| Section | User need and contents | First availability |
| --- | --- | --- |
| **Home** | Current room, setup readiness, listening/output state, last relevant test, and next repair action. Later: explicit session start and active task summary. | D1: setup home; D2: runtime home |
| **Quick Setup** | Resumable modules: Space and room → Voice Management → Agent → Permissions and useful tools → Optional memory → First useful task. Show prerequisites and allow appropriate skips. | D1: room and voice; other modules with their backends |
| **Rooms & devices** | Friendly microphone/speaker selection, placement notes, echo owner, retest, missing-device repair. Later: multiple room assignments and paired endpoints. | D1: selected room; D7: expansion |
| **People & voices** | Consenting enrollment, quality review, rename, remove/re-enroll, compatible model information, unknown guests, recognition preferences. Later: separate roles and verified account identity. | D1: voice profiles; roles with D3–D5 |
| **Conversations** | Current turn stream, provisional/final text, uncertain attribution, response/heard state, interruption/repetition path. History is session-only until retention is explicitly configured. | D1: test conversation; D2: runtime |
| **Agent & speech** | Installed language/speech profiles, benchmarks, replaceable agent provider, behavior preferences, voice preview, explicit provider test. Explain local/cloud execution when offered. | D1: speech; D3: agent |
| **Memory** | Review attributed claims, personal/room/space scopes, corrections, sharing, forgetting, and retention. Conflicting claims keep their sources. | D4 |
| **Tools & connections** | A small useful catalog, connection health, capability preview, permissions, safe test, disconnect, and review of consequential actions. | D5 |
| **Tasks & routines** | Visible requested work, progress, failures, cancellation, explicit schedules, owners, scopes, and run history. Distinguish cancelling a task from undoing an external effect. | D6 |
| **Health & help** | Symptom-based troubleshooting, component health, recent failures, resource limits, repair/retest, and explicitly exported diagnostics. | D1 for voice; expands each phase |
| **Settings & privacy** | Language/direction, appearance/accessibility, local storage inventory, export/import, retention, shutdown, update/recovery. Later: access management, paired-device revocation, and startup opt-in. | D1 basics; expands each phase |

Voice Management remains one canonical workspace. Quick Setup deep-links into its
guided view; People, Rooms, and Health link to the relevant part of that workspace.
Shared controls and configuration prevent three different enrollment or tuning UIs.

## Representative journeys

- **First installation:** open the dashboard, name the room, pick/test audio,
  install/import the needed local models, optionally enroll people, try the live
  lab, and review a readiness summary. Saving never starts a listener.
- **Microphone stops working:** Home identifies the unavailable selected device;
  Repair opens its device choice, refreshes discovery, and guides a retest. A
  replacement device does not inherit validation automatically.
- **Wrong person is named:** open that turn's evidence, mark the test observation,
  check enrollment quality, compare recognition presets, and rerun known/guest
  tests. Correcting a displayed name does not silently train a profile or grant access.
- **The assistant cuts in too early:** open speech timing in Voice Lab, change
  completion silence in a draft, and compare another take before saving.
- **Playback interrupts itself:** run quiet playback and duplex tests, verify the
  echo owner, check clipping/placement, and rerun. Show missed/false detections.
- **A guest joins:** keep an unknown speaker label and apply the selected
  participation rule. Later permission enforcement remains independent of voice identity.
- **A private request is made in a shared room:** the future policy layer checks
  verified access and output context before using memory/tools. Ambiguous identity
  offers a safe clarification or private authenticated path.
- **A task fails later:** show the failed step, confirmed effects, and a concrete
  retry/repair action; do not require searching a debug log.

## Interaction rules

- Use visible states: Not configured, Needs test, Tested with limitations,
  Ready for this test, Failed, and Stale. Keep software completion, measured
  results, and human confirmation distinct; never show a universal readiness score.
- Invalidate only affected evidence after changes. Device/echo changes invalidate
  audio and downstream duplex evidence; a recognition threshold edit invalidates
  identity comparisons, not whether the speaker was heard.
- Each error states what failed, what stopped, and one useful recovery action.
  Carry selected settings into the repair view and return to the original step.
- Autosave harmless draft UI progress; require explicit application of operational
  settings, model downloads, enrollment saves, and data export/removal.
- Provide immediate local Stop all. Later separate microphone mute, Stop speaking,
  End session, and task cancellation when their distinct behavior exists.
- Keep UI locale, speech language, and model capability separate. Support mixed
  English/Farsi names, Unicode, logical layout properties, and bidirectional text
  from D1. A translated UI does not imply evaluated Farsi speech support.
- Keyboard operation, visible focus, text equivalents for meters/sounds, sufficient
  contrast, reduced motion, and responsive reflow are acceptance requirements.

## Architecture and state

Extend the existing packaged HTML/CSS/JavaScript and Python service first. This
plan does not select a new frontend framework or Python web dependency. Split the
current large page/script into reusable shell, setup, voice, and diagnostics
modules as needed. Any later stack addition needs a concrete agreed benefit.

The browser presents state and sends explicit commands. Python validates settings,
owns permissions and job/session lifecycle, supervises killable native workers,
and stores configuration. Audio callbacks never depend on UI rendering, identity
inference, or agent work for stopping output. Preserve the pure RoomManager and
replaceable speech/identity/provider boundaries.

Persist configuration, consenting voice profiles, and explicitly saved numeric
test reports in the existing private application locations. Keep transcripts,
audio buffers, and unsaved test observations in bounded session memory by default.
Do not introduce a database or durable conversation history solely for the shell.
Version new stores and migrate known versions deliberately; preserve unknown
versions and provide recovery rather than overwriting them.

Separate **saved configuration**, **editable draft**, **effective settings for
this run**, **current runtime state**, and **test evidence**. Stable space, room,
endpoint, person, session, utterance, and response IDs serve different purposes.
Evidence records the settings revision, devices, model fingerprints, test protocol,
time, counts, and measurement limitations.

Keep loopback binding, host/origin checks, control tokens, and operation ownership.
A second tab may observe but cannot keep another tab's microphone lease alive or
change its running settings. LAN/mobile access requires its own authenticated
pairing design. The public product website, if created later, is a separate
informational surface; native audio controls stay in the local application.

## Scope decisions and later discovery

Commit now to the local shell, Quick Setup, reusable Voice Management workspace,
live diagnostics, explicit tuning, and honest readiness. D1 is useful without a
conversational LLM, memory, tools, wake phrase, or persistent listening.

Before each later phase, select one real household use case and validate its
journey. Open decisions include agent provider, verified user access, memory
retention defaults, the first two useful tools, task durability, consumer installer,
and remote-room security. Their interfaces have a place in this plan; their
implementation is not authorized simply by appearing here.

If you want to inspect or try the current foundation, use the actual
[Family Harness repository](https://github.com/AMMIROSOH/family-harness) and its
[getting-started instructions](../README.md#try-room-audio-setup-on-windows).
Family Harness remains under development; the house agent is not yet functional.
