# Dashboard delivery roadmap

**Proposed, 2026-10-12. Planning only; application code has not changed.**

This roadmap creates the application dashboard described in the
[product plan](dashboard-plan.md). **The first implementation request should start
D1: Quick Setup and Voice Management, including real live tests and tuning.**
The existing M1.1–M1.6 roadmap remains the record of voice implementation and
validation. Dashboard phases use D identifiers to keep the two roadmaps separate.

## Ordered phases

| Phase | Useful delivered result | Prerequisites and acceptance gate |
| --- | --- | --- |
| **D1 — Quick Setup + Voice Management** | Application shell; guided setup; reusable voice workspace; live test conversation; tuning, comparisons, and repair. | Reuse M1 previews. Complete the D1 gates below; track household quality separately. |
| **D2 — Room operation** | Explicit start/end of sustained room sessions, actual state/mute/output controls, live conversations and reliable recovery. | D1 live pipeline and lifecycle evidence. Run an agreed household soak test with reconnect, restart, contention, and no unexpected restart of listening. |
| **D3 — Conversational agent** | Replaceable agent connection, explicit provider check, streamed useful answers, response cancellation and heard history in the dashboard. | D2. Demonstrate one useful household conversation; cancelling stale generation cannot revive playback. State execution location and offline limitations. |
| **D4 — Scoped memory** | Review/correct/forget attributed information; explicit personal/room/space scopes, sharing and retention. | D3 plus a verified access mechanism independent of voice matching. Test private/shared retrieval, contradictions, correction and deletion. |
| **D5 — Useful tools & permissions** | A small agreed tool set, connection setup, access checks, consequential-action review, audit and disconnection. | D3 plus verified access and policy enforcement. D4 is needed only for memory-dependent tools. Demonstrate authorized/denied actions and confirmed side effects after cancellation. |
| **D6 — Tasks & routines** | Progress, cancellation, recovery, explicit schedules, ownership and run history for useful household work. | D5. Test interrupted execution, duplicate prevention, restart, expiry, and schedule controls; state effects that cannot be undone. |
| **D7 — Rooms, endpoints & profiles** | Additional rooms, compatible browser/phone/network endpoints, evaluated language/hardware profiles including Farsi. | D2 lifecycle, capacity evidence, authenticated pairing for remote endpoints, and per-profile validation. Each adapter/language has its own gate. |
| **D8 — Everyday distribution** | Consumer installation/upgrade/uninstall, data-retention choices, local recovery/backup, optional startup, broader accessibility/localization validation. | A selected supported runtime profile from D2/D3 and household evidence. Upgrade preserves configuration and leaves audio off; additional households complete setup without developer intervention. |

Health, privacy, accessibility, and failure recovery ship with every phase.
D1 remains the first delivery even if later phases are reprioritized. D4 and D5
can be reordered after their access prerequisites exist. D7's adapter prototypes
and packaging improvements may proceed earlier when explicitly scoped, without
expanding the first-room implementation by default.

## D1 implementation sequence

The [Voice Management specification](voice-management-workspace.md) defines the
test catalog, parameter semantics, and live data contract. The following slices
are ordered reviewable changes within D1, not separate completed milestones.

| Slice | Work and concrete result | Verification |
| --- | --- | --- |
| **D1.1 — Shell and navigation** | Local app shell, Home readiness, Quick Setup route, persistent room context and Stop all. Break existing sections into navigable views and preserve existing launcher/CLI behavior. | Existing operations still work; page load/navigation/reopen keep devices closed; packaged assets and keyboard/narrow-screen flow work. |
| **D1.2 — Guided voice setup** | Room, native devices, acoustics, model install/import/speed check, consenting enrollment, recognition/participation, trial and summary. Resume progress and deep-link repairs. | Existing M1 actions are reachable; missing/corrupt model and unplugged-device flows are understandable; enrollment candidates save only explicitly. |
| **D1.3 — Settings and live telemetry** | Typed settings schema, server-side validation, saved/draft/run separation, browser model/preset selection, per-job event cursor, controller lease and live monitor. | Rejected/stale saves, bad numeric values, second-tab control, disconnect, duplicate/out-of-order updates, and Stop during loading/analysis are behavior-tested. |
| **D1.4 — Genuine live Voice Lab** | A new bounded multi-turn native diagnostic session with streaming drafts, final text, asynchronous speaker/identity updates, deterministic TTS replies, onset cancellation, heard chunks, and overlap recovery. | Results update while capture remains active. A second turn follows a reply without restarting the test; heavy identity/final decoding cannot block local output stop. |
| **D1.5 — Tuning and comparisons** | All supported parameter groups, immutable run settings, next-take changes, named local profiles, A/B summary, observer tallies, replay and manager fixture tests. | Actual worker settings match the UI/report; comparisons require matching protocol/hardware/model conditions; unavailable measurements remain unknown. |
| **D1.6 — Repair and delivery validation** | Symptom-guided recovery, readiness/invalidation, explicit numeric export, migration, regression tests, installation/CLI/package checks, accessibility and deliberate household trial guide. | Software gate and household evidence are reported separately; no silent listening, recording persistence, model download, or cloud fallback. |

Start with a thin end-to-end path through the existing microphone test to establish
navigation, job ownership, live display, Stop, and recovery. Then carry every
existing voice operation through that path before extending the native live worker.
Do not implement a standalone settings dashboard disconnected from real workers.

D1.3 should measure model loading, queue delay, and ASR/identity processing cost on
the target PC. D1.4 then uses bounded incremental analysis behind the existing
interfaces. If the current offline diarizer cannot keep up, retain clearly marked
pending/post-take attribution while building the incremental adapter. That is a
useful intermediate slice, **not completion of the requested live identity lab**.
Do not silently add GPU/cloud requirements to clear this gate.

## D1 completion gates

### Product and software gate

- A user can complete/resume room and voice setup, retest, repair failures, and
  access the live lab through the dashboard without editing files or restarting
  the CLI to select supported recognizers/settings.
- Every M1.1–M1.6 capability has the native/replay/fixture coverage assigned in the
  test catalog. Fixture-only capabilities are labeled as such.
- During an explicitly started live test, levels, speech state, draft/final text,
  speaker/identity updates, response/playback, interruptions and heard evidence
  are observable. Identity may remain unknown; stale results cannot become current.
- Tuning a draft during capture never changes that take invisibly. Apply to next
  take, compare, save deliberately, reopen, and restore defaults all work.
- Local Stop remains independent of expensive inference. Lease expiry, device
  loss, worker failure and deadline expiry release devices and invalidate incomplete
  input. Reconnecting never restarts capture automatically.
- Simulated behavior tests, lint, package build/install, CLI help/version, asset
  packaging, known-schema migration and browser/accessibility checks pass.

### Target-household evidence gate

Run hardware only through deliberate local test actions. Record exact host,
devices, model versions, effective settings, room placement and test denominators.
Use the existing [audio trial](audio-setup.md#household-validation-trial),
[people quality trial](people-and-group-turns.md#household-quality-trial), and
[interruption trial](interruptions.md#integrated-household-exit-trial).

Verify microphone/speaker/echo behavior, nearby and far speech, two consenting
enrolled people and an unknown guest, quiet playback, interruption and continuation,
overlap, contention, and failure recovery. Measure physical stop independently of
software DAC timing. Report current limitations and failed/untested cases.

The dashboard software can be delivered as a **live diagnostic preview** even if
recognition or acoustics miss the household targets. Household readiness and the
underlying M1 quality gates stay pending until their evidence passes. No green
check should turn poor recognition into a claim of dependable personalization.

## Risks to resolve early

| Risk | First mitigation/evidence |
| --- | --- |
| Existing group analysis is offline and may exceed real time | Measure it in D1.3; incremental bounded attribution in D1.4; expose lag and unknown states. |
| UI controls can suggest settings the worker does not accept | One Python-validated schema and an effective-settings acknowledgment for every job. |
| Telemetry can delay audio or retain private content | Separate bounded telemetry from callbacks; coalesce meters, retain lifecycle events, default to memory-only text. |
| A/B results can look better because of different audio/conditions | Same-input local replay for repeatability; label live retakes as different samples; record denominators and environment. |
| A larger app can break current stop/lease protections | Preserve backend protections, add per-controller ownership, test page closure and multiple tabs before live expansion. |
| Full application scope can swamp the first useful delivery | Ship only D1's operational sections; later sections follow backend gates. |

## Next implementation request

“Implement D1 from `docs/dashboard-roadmap.md`, starting with D1.1 and D1.2,
and continue through the live Voice Lab, tuning, and validation specified in
`docs/voice-management-workspace.md`.”

That request would authorize implementation. This planning change creates the
specification and roadmap only; it does not activate hardware or build the runtime.
