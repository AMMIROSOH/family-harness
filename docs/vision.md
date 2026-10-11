# Product direction

**Status: under development.** This document describes intended behavior, not delivered functionality.

## Purpose

Make a shared voice agent approachable and useful for ordinary families. Prove it in one household first, then improve it through real use in households with different languages, abilities, hardware, budgets, and internet connections.

Support other collaborative settings through the same basic concepts: spaces, rooms, people, conversations, memories, tools, and policies. An office deployment should not require treating coworkers as family members in the data model.

## A representative conversation

Omid activates the assistant in a room. The system recognizes his enrolled voice when confidence is sufficient and applies his preferences and allowed context. His father joins the conversation, corrects a detail, and interrupts a spoken reply. The assistant yields, attributes the new turn, and continues the room discussion without exposing Omid's private information or turning a disagreement into an established fact.

Unrecognized visitors can participate according to the space's policy. The system can say that it is unsure who is speaking instead of forcing every voice to match a known person.

## Global design requirements

- English as the first validated CPU speech profile; language-independent interfaces and localized setup, with Farsi as an early extension target.
- Right-to-left text, regional formats, local names, and mixed-language utterances.
- Explicit configuration for household and workplace roles; avoid assuming one family structure.
- Audio and hardware choices appropriate to modest PCs and different room conditions.
- Local CPU inference as the default; replaceable providers for future hardware, language, and connectivity choices.
- Accessible feedback through visible status, sounds, and spoken guidance where appropriate.
- Clear controls for enrollment, listening, retention, memory sharing, and disconnection.

## Early boundaries

The first milestone is the [Room Conversation Manager](room-conversation-roadmap.md): one room, guided localhost audio setup, an English CPU voice profile, explicit activation, attributed participants, and interruptions. A deterministic responder can validate this milestone before a conversational agent is integrated. Persistent memory and useful tools follow afterward.

Larger local/GPU models, cloud adapters, and additional language profiles including Farsi remain TODO. Keep those extension boundaries available without making them part of the first installation. Phone/browser and network audio have separate delivery tracks so native room-audio setup can be proved first.

Reliable conversational behavior and easy setup take precedence over a large integration catalog. Keep all future capabilities clearly distinguished from the initial scaffold.

Public promotion should describe the actual supported installation paths, tested languages, hardware expectations, and known limitations. Global readiness must be demonstrated through use beyond the original household.
