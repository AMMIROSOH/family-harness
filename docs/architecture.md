# Architecture direction

**Status: partially implemented.** The Windows native audio endpoint, local room configuration, localhost setup/control boundary, local English speech-profile test, and deterministic room manager exist as previews. Speech detection, streaming recognition, synthesis, and model management are integrated for one bounded native test utterance and continuous file replay. M1.5 adds local enrollment, identity uncertainty, participation policies, and bounded attributed group previews. The room manager processes common events and provider commands without an LLM. M1.6 adds onset-driven cancellation, DAC-clock heard-chunk evidence and a bounded duplex trial with post-capture attribution. Continuous live group sessions, memory, and agent integration remain proposed. See [interruptions](interruptions.md). See the [M1.4 contracts](room-manager.md) and [M1.5 identity boundary](people-and-group-turns.md).

The first milestone is the [Room Conversation Manager](room-conversation-roadmap.md), beginning with localhost audio setup and the [English CPU profile](local-voice-profile.md). Hardware exit gates remain pending. See the [audio implementation notes](audio-setup.md#implementation-boundaries) for delivered contracts and limitations.

## Separate responsibilities

| Boundary | Responsibility |
| --- | --- |
| Audio endpoint | Capture and playback, device selection, echo handling, mute, and connection health |
| Speech pipeline | Activation, speech activity, transcription, speaker attribution, synthesis, and interruption signals |
| Identity | Enrolled voice profiles, confidence, unknown speakers, and stable person identifiers |
| Conversation manager | Room session, participants, attributed turns, response timing, and spoken output state |
| Agent runtime | Model requests, tool calls, task state, cancellation, and useful responses |
| Memory and policy | Personal/shared scope, retrieval, retention, and access enforcement |
| Setup and diagnostics | Guided configuration, validation, repair, and understandable status |

Pipecat and LiveKit Agents are candidates for the voice runtime. LangGraph is a candidate when durable agent workflows are needed. Home Assistant can be an optional device-control integration. Re-evaluate these choices against concrete requirements before adding dependencies.

## Shared conversation, scoped context

Use one active room conversation with attributed participant turns. Joining a conversation changes the participant set; it must not automatically reveal another person's private memories or grant access to their connected accounts.

Represent the speaker label, resolved person, identity confidence, timestamps, and transcript separately. Diarization labels are session-local and must not be used as persistent person identifiers.

Preserve the source and scope of remembered information. Contradictory statements remain attributed claims until resolved. Do not automatically persist every transcript as a personal fact.

## Interruptions and overlap

Stopping spoken output, cancelling model generation, and cancelling a tool operation are different actions. Track them separately and retain confirmed side effects. Conversation history should reflect what participants actually heard.

Overlapping speech can produce incomplete or uncertain attribution. The system must be able to ask for repetition and refrain from writing incorrectly attributed memories.

## Deployment

The initial profile runs capture, speech processing, identity, room coordination, and playback on the same PC. After dependencies/models are installed, inference must work offline without a provider account. A Core i5-class PC with 16 GB RAM is a benchmark target; verify the exact hardware before claiming support.

Keep providers behind small interfaces with explicit capabilities such as language, execution location, streaming, diarization, enrollment, and cancellation. Optional CPU Parakeet/Whisper whole-utterance finals now sit behind a separate recognizer interface while Zipformer provides streaming drafts. GPU profiles, home-server execution, cloud adapters, and additional language profiles including Farsi are TODO extensions. Language support must not be hard-wired to CPU/GPU deployment.

Keep room listening and activation outside long-running agent tasks. Task execution must not block audio interruption handling. Start with a small deployment and avoid adding a distributed system before it is needed.

## Setup and audio endpoints

The Python backend owns native device discovery, bounded audio tests, capture/playback, and saved room configuration. A lightweight localhost web interface guides users through these operations. The browser is initially a control surface; browser microphone capture is a separate source adapter.

Represent connection method separately from physical form and intended use. A headset is usually a host audio device; a phone may be a paired endpoint or another supported source. Preserve room/source identifiers, audio-clock timestamps, connection health, playback location, and echo-reference capabilities across adapters.

Native host audio is the first delivery path. Phone/browser pairing and supported network sources are separate extension tracks. LAN discovery lists compatible advertised endpoints; it does not grant microphone access or make arbitrary devices into audio sources.

Only explicit setup/test actions open a microphone. Default setup access stays on loopback; phone access requires a deliberate LAN pairing mode with appropriate authentication and secure browser capture. Model downloads and automatic startup are explicit choices. Missing devices produce recovery guidance instead of silently selecting a different microphone.

Milestone 1 can use a deterministic response provider to validate room state and interruptions. Keep the conversational LLM, persistent memory, and useful tool runtime as later integrations.
