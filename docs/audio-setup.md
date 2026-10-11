# Room audio setup preview

**Implemented 2026-10-11; household hardware trial pending.** This delivers the M1.1 setup path and M1.2 native duplex processing/diagnostics. It does not deliver a talking assistant. Energy measurements cannot establish transcription accuracy or false interruptions.

## Install and launch

The first target is Windows 10/11 x64 using Windows WASAPI devices. Read-only discovery was checked on the development host; capture/playback support on actual household devices remains unverified. Other OS adapters are not implemented.

Run `Install-Windows.cmd` from the checkout. This explicit action acquires uv from its [official versioned installer](https://docs.astral.sh/uv/getting-started/installation/) if needed, Python 3.12 if needed, and dependencies from `uv.lock`. A fresh machine may download roughly 50–100 MB. uv installed by this script stays under `.local/tools/bin` without PATH changes; dependencies live in `.venv`. Installation does not open audio, acquire voice models, or activate a service. This bootstrap is not the full milestone's consumer installer.

Run `Start-Setup.cmd`, or `uv run family-harness setup`. The launcher prints the actual localhost URL before opening a browser. Copy/click that address if browser launch fails. An occupied port falls back to a free loopback port. `setup --port 0` explicitly chooses a free port; `setup --no-browser` prints the URL without opening a browser. Keep the launcher window open; Ctrl+C closes setup and stops its test.

The service binds only to `127.0.0.1`. The browser controls host devices and has no microphone permission. Opening setup, discovering devices, saving choices, and importing the package do not start capture/playback or contact an inference service.

## Tests and controls

| Test | User action and result |
| --- | --- |
| Microphone, 8 seconds | Speak normally; repeat at nearby/farthest intended positions. The live meter has a text level; silence, weak input, and clipping produce recovery advice. |
| Speaker, 3 seconds | Reduce volume first, play the notes, then confirm hearing at a comfortable volume. Opens output only. Software cannot verify that a person heard it. |
| Background noise, 5 seconds | Remain quiet. Reports the numeric noise floor and a heuristic warning for a noisy room. |
| Duplex, 12 seconds | Quiet for 2 seconds; quiet during 5 seconds of notes; speak during the next 4 seconds while playback continues; finish quietly for 1 second. Live instructions guide each phase. |

Duplex results compare echo-only energy before/after processing and speech-phase energy above residual sound. These are measurements with limits, not a universal room pass/fail. Try both speaking positions. A personal headset does not prove that other people in the room can be heard.

Stop / mute terminates the test process and releases input/output; samples already in the OS/hardware playback buffer may finish. Tests also stop on completion, device failure, shutdown, or three seconds without a browser poll (plus OS scheduling/termination time). Reconnection never restarts capture automatically. Cancelled/failed tests are not saved as completed measurements.

Samples exist only in bounded process memory and are discarded. There is no recording/export endpoint, audio upload, microphone loopback monitor, or inference call. Numeric results are saved only when the user presses Save. The interface supports keyboard controls, text status, and automatic direction for names including Farsi. It does not recognize speech in any language.

## One echo cancellation owner

Choose **Family Harness (WebRTC)** or **device-owned echo removal**, then confirm the settings before each duplex test. Software mode uses [pywebrtc-audio's WebRTC AEC3 adapter](https://github.com/strands-labs/pywebrtc-audio), with noise suppression and automatic gain disabled so the measurement reflects the chosen echo path. Disable Windows/device microphone echo effects in this mode. The app cannot inspect or disable every device's DSP; confirmation is a user assertion.

Device mode bypasses software AEC. Use it only if device documentation/settings confirm built-in echo cancellation is enabled. Already-processed input cannot reveal the device's internal before/after attenuation; an unmeasurable path is reported honestly. Browser echo cancellation cannot remove native endpoint echo.

The reference contains the exact samples submitted to this application's output stream, including the envelope and silence padding. It does not include unrelated apps, OS sounds, or other speakers. Avoid changing speaker volume during a duplex test; replay with the final placement/volume. Speech intelligibility and self-interruption validation require the later speech pipeline.

## Saved choices and repair

The default file is `%LOCALAPPDATA%/FamilyHarness/room.json`. Use `setup --config PATH` for another location, kept outside source control. Schema 1 stores stable space/room/application endpoint IDs, names, host connection/playback location, intended microphone use, Windows endpoint identities, echo owner, hearing confirmation, and numeric diagnostics. No device list indices, audio, profiles, secrets, or personal memories are stored.

Windows endpoint IDs map to uniquely named WASAPI devices. Reordering does not change selection; a different OS endpoint with the same name does not inherit it. Ambiguous mappings are not usable: give identical devices distinct names in Windows Sound settings and refresh. A disappeared device leaves its selection empty and requires a new explicit choice. Saves revalidate both endpoints and write atomically; failed replacement preserves the previous file. Unknown schema versions are not overwritten.

| Problem | Recovery |
| --- | --- |
| No devices / missing selection | Reconnect hardware, verify Windows Sound settings, Refresh, then choose again. |
| Permission denied / device cannot open | Windows Settings → Privacy & security → Microphone → allow access and desktop apps. Close apps holding the device. Some drivers report denial as a generic host error; the same guidance is supplied. |
| Silence / weak far-position input | Check hardware mute and input gain, verify selection, move the microphone nearer. |
| Clipping | Lower microphone input gain or move farther away; retest. |
| High background noise | Move away from fans/traffic; test with nobody speaking. |
| Speaker not heard | Check selection, Windows output/mute/volume; replay before confirming. |
| Echo / weak speech during playback | Lower speaker volume, separate devices, verify one echo owner, retest near/far. |
| Gaps / busy device / Bluetooth duplex failure | Close busy apps, check Windows audio formats, try a wired device, start a fresh test. |
| Hot unplug | The test stops with recovery guidance. Reconnect, refresh, explicitly start again. |
| Corrupt/newer configuration | Back up the shown file, move it aside, reopen setup. Unknown versions are never silently overwritten. |

Completed results apply to their selected device IDs and echo owner; changing these clears applicable results in the page. Saving untested choices is allowed and does not assert that the room passed a trial. Repeated saves retain stable room/space IDs.

## Implementation boundaries

- `devices.py` wraps sounddevice/PortAudio discovery and format checks, with Pycaw for stable Windows endpoint IDs. A fresh discovery process avoids PortAudio's cached initialization list after hot plug. Format checks do not start a recording. See [sounddevice hardware checks](https://python-sounddevice.readthedocs.io/en/latest/api/checking-hardware.html).
- `audio.py` owns native input/output/duplex callbacks and the echo adapter. `AudioFrame` separates endpoint ID, sequence, sample rate, capture/output timestamps, clock identity, samples, actual played reference, and discontinuity. PortAudio supplies one stream clock; the capture/output timestamp difference hints AEC delay. Output mono samples are copied to every output channel. DSP runs on one worker thread and resets after gaps. See [callback timing](https://python-sounddevice.readthedocs.io/en/latest/api/streams.html).
- Callbacks enqueue at most 20 frames (200 ms at 10 ms/frame), with no DSP, file/network I/O, or blocking queue waits. Python copies/allocates frame arrays, so hard realtime behavior is not guaranteed. Overflow drops frames and records counts; sequence/clock gaps and PortAudio flags are visible. Processing occurs outside the callback.
- `audio_worker.py` re-resolves identities before one explicit test, emits numeric progress/results, closes streams, and exits. Processing accepts fake audio dependencies for tests.
- `control.py` exposes refresh/start/poll/stop/close and supervises cancellation, deadlines, browser leases, and completed results. Reconnection requires a fresh explicit start.
- `server.py` serves packaged assets/JSON on loopback. Host/Origin/Fetch Metadata checks, a per-launch token, bounded JSON-only bodies, no CORS, restrictive CSP, and browser microphone denial prevent unrelated pages from starting capture. It is a local single-room service, not a LAN deployment surface.
- `config.py` owns validation and atomic writes. Recognition, identity, agents, memory, and sensitive tool permissions remain outside this implementation.

Libraries perform native audio and AEC; Family Harness does not implement echo cancellation internals. Future adapters should extend saved endpoint identities and frame metadata instead of replacing the configured host path.

## Upgrade, data retention, and uninstall

Close setup, update the checkout, inspect release changes, and rerun `Install-Windows.cmd` to sync locked dependencies. Schema 1 has no older runtime configuration to migrate; future versions require an explicit migration. Unknown schemas currently block overwriting.

No models, logins, service registrations, or startup tasks are installed. To uninstall, close setup and remove this checkout's `.venv` and `.local` (or the checkout). Separately choose whether to retain/delete `%LOCALAPPDATA%/FamilyHarness/room.json`; it is not deleted automatically. A pre-existing shared uv, its cache, or Python installation need not be removed.

## Household validation trial

Run this deliberately on intended hardware. Record OS build, CPU/RAM, audio product names, placement, formats, DSP owner/settings, and dependency versions from Advanced diagnostics in a private local report. Do not commit voices or personal configuration.

1. Install from a fresh checkout; verify audio stays off until a test button is pressed. Occupy the default port and verify the fallback URL.
2. Save, close/reopen, and verify identical selections with audio off. Try Farsi names, keyboard controls, and text status.
3. Test microphone near/far, silence/mute, and reduced gain. Confirm Stop releases capture. Deny desktop microphone permission, inspect recovery, restore permission, and retry explicitly.
4. Confirm speaker hearing/volume. Unplug input and output; verify refresh/redetection, reordering, and no silent substitution. A replacement with the same name must not inherit the OS endpoint assignment.
5. Check quiet noise and duplex with one echo owner. Record raw/clean energy, residual echo, clipping, gaps, and nearby/far speech. Verify Stop during playback, page closure/disconnection, and launcher shutdown.
6. Save/reopen results. Repeat offline after dependency installation; no model/account/network is needed.
7. When M1.3–M1.6 exist, measure human transcription during playback and false self-transcriptions/interruptions. These cannot be claimed from tone/energy tests.

M1.1 sign-off requires the intended household to configure/retest and recover on real devices. Full M1.2 sign-off requires useful live duplex behavior in the downstream speech pipeline. Both household sign-offs remain pending.

## Development validation evidence

Checks on 2026-10-11 cover installation, CLI help/version, native read-only discovery, browser start/stop/save/reopen with simulated devices and Farsi names, and fake-device/HTTP/synthetic-audio tests. The actual pywebrtc-audio wheel processes delayed synthetic echo with a separate near signal. Wheel build/install checks verify packaged web assets. See `tests/` for repeatable behavior checks.

Actual host capture, audible playback, Windows permission denial, hot unplug, room intelligibility, and false interruption/transcription measurements were **not performed**. No personal audio was recorded. This evidence does not sign off household milestone gates.
