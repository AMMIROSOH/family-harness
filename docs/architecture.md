# Architecture direction

**Status: proposed.** No voice or agent backend has been integrated or selected as a permanent dependency.

The first milestone is the [Room Conversation Manager](room-conversation-roadmap.md), beginning with guided localhost room-audio setup. Its first supported profile will be English with local CPU processing. These are planned boundaries, not available features.

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

Keep providers behind small interfaces with explicit capabilities such as language, execution location, streaming, diarization, enrollment, and cancellation. Larger local/GPU models, home-server execution, cloud adapters, and additional language profiles including Farsi are TODO extensions. Language support must not be hard-wired to CPU/GPU deployment.

Keep room listening and activation outside long-running agent tasks. Task execution must not block audio interruption handling. Start with a small deployment and avoid adding a distributed system before it is needed.

## Setup and audio endpoints

The Python backend owns native device discovery, bounded audio tests, capture/playback, and saved room configuration. A lightweight localhost web interface guides users through these operations. The browser is initially a control surface; browser microphone capture is a separate source adapter.

Represent connection method separately from physical form and intended use. A headset is usually a host audio device; a phone may be a paired endpoint or another supported source. Preserve room/source identifiers, audio-clock timestamps, connection health, playback location, and echo-reference capabilities across adapters.

Native host audio is the first delivery path. Phone/browser pairing and supported network sources are separate extension tracks. LAN discovery lists compatible advertised endpoints; it does not grant microphone access or make arbitrary devices into audio sources.

Only explicit setup/test actions open a microphone. Default setup access stays on loopback; phone access requires a deliberate LAN pairing mode with appropriate authentication and secure browser capture. Model downloads and automatic startup are explicit choices. Missing devices produce recovery guidance instead of silently selecting a different microphone.

Milestone 1 can use a deterministic response provider to validate room state and interruptions. Keep the conversational LLM, persistent memory, and useful tool runtime as later integrations.
