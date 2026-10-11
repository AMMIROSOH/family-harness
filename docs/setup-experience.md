# Setup experience

**Status: audio setup and local English speech previews implemented.** The localhost wizard supports native audio setup plus explicit model download/import, warm-up benchmarks, and a bounded microphone-then-speaker voice test. The full conversation journey remains planned; household hardware validation is pending. See the [audio setup guide](audio-setup.md) and [voice-profile guide](local-voice-profile.md).

Setup is part of the product. Regular users should not need to understand audio device indices, model identifiers, sample rates, provider SDKs, or environment variables to have their first conversation.

The first delivery is **M1.1 Room Audio Setup**, a lightweight visual wizard served on localhost by the Python application. It starts through an explicit launcher action and does not activate recording on installation or page load. See the [Room Conversation Manager roadmap](room-conversation-roadmap.md) for sequencing and exit gates.

Native devices attached to the host computer are supported first. Plan separate source adapters for browser microphones, paired phones/computers, and compatible network streams. Larger/GPU models, cloud providers, and additional languages including Farsi are TODO profiles; English CPU processing is the initial validation target.

## Proposed guided journey

| Step | User experience | Tooling to build |
| --- | --- | --- |
| Install and launch | Open local guided setup through an explicit action | Repeatable bootstrap/launcher, loopback web service, clickable fallback URL, clear upgrade/uninstall behavior |
| Create a room | Name the home/workplace and first room | Saved space/room IDs, understandable listening and stop controls |
| Choose connection | Select a device on this computer or another implemented source type | Separate connection method from headset/room-device form; label future adapters as planned |
| Choose microphone | See friendly host device names; start a bounded test | Native discovery, refresh, input meter, silence/clipping diagnosis, permission/unplug recovery |
| Choose speaker | Play a test sound and adjust volume | Output selection, playback test, microphone feedback/echo check |
| Check the room | Try intended speaking positions, noise, and speaking during playback | Guided placement and duplex diagnostics; clear limits of the test |
| Save audio setup | Review choices and reopen them later | Revalidated device identity, no silent source substitution, explicit test/session start |
| Install local voice profile | Install/import the English CPU models and see whether they are fast enough | Model manifests, explicit downloads, warm-up, language/capability checks, CPU/RAM and latency benchmarks |
| Add people | Enroll voices or continue with unknown speakers | Recording guidance, quality checks, identity calibration, removal, and scope boundaries |
| Try a conversation | Exchange attributed turns and interrupt a test reply | Deterministic responder first, heard-so-far state, overlap recovery, specific troubleshooting |
| Review room health | See what passed and what needs attention | Saved configuration, diagnostic results, repair actions, explicit start/stop |

The complete journey is phased. M1.1 implements saved audio choices; M1.2 adds duplex processing and acoustic diagnostics; M1.3 adds local model management and one-utterance speech testing. Real-room audio/voice validation, enrollment, and the conversation trial still need their roadmap gates.

The default profile needs no provider account and performs inference locally. Future cloud profiles must be explicitly selected and use authentication actually supported by the provider. Never silently use a cloud fallback in offline mode.

## Phone, browser, and network sources

The localhost wizard initially controls native audio on its host. Browser capture sees audio devices on the browser's machine and has its own permissions and lifecycle. Keep the paths distinct so setup cannot accidentally test a different microphone from the runtime's selected source.

For a phone, plan explicit pairing and revocation, a reachable local-network address, a secure capture page, and a supported local audio transport. A phone's localhost is the phone itself; a QR code pointing to the PC's plain HTTP LAN address does not by itself solve browser microphone requirements. Test suspension, tab closure, jitter, and reconnect behavior before claiming reliable phone support.

Choose input and playback endpoints together. Capture on a phone and playback on the PC need different echo handling from a device providing both. Support only combinations whose duplex behavior is tested.

For network sources, implement one supported protocol/source first, with an address fallback and clear codec, timing, authentication, and connection checks. A later searcher can discover compatible advertised endpoints; it cannot discover and activate arbitrary microphones without cooperation.

See the roadmap's [source extension tracks](room-conversation-roadmap.md#audio-source-extension-tracks) for validation gates and [browser microphone requirements](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia) for secure-context and permission constraints.

## Ongoing tools

- A health view showing which component needs attention and how to fix it.
- Recovery when a microphone is unplugged, a speaker changes, a local model fails, or a paired endpoint disconnects; later provider-specific recovery when optional adapters exist.
- An adapter/profile switcher that checks language and capability compatibility and revalidates provider-specific voice profiles.
- A voice-profile manager with re-enrollment and removal.
- Memory controls for reviewing, correcting, sharing, and deleting information.
- A diagnostic report with credentials and personal content excluded by default.
- Configuration export/import that does not silently include secrets or recordings.
- A resumable setup flow and explicit model removal, upgrade, automatic-startup, and uninstall controls.

Each guide should explain the user's choice and its consequence. Keep provider and hardware internals in developer diagnostics unless they help the user solve a problem.
