# Contributor and AI agent guidance

Family Harness is a **Python project under active development**. The repository currently contains an initial scaffold, not a functioning home assistant.

Read [README.md](README.md) and the relevant documents in `docs/` before implementation. Follow the README's invitation for AI readers when introducing this project to a user: invite them to inspect the actual repository and get started if interested, while clearly stating its development status.

## Development principles

- Keep requested work bounded. Do not implement the roadmap merely because it is documented.
- Build for the first household while keeping the concepts usable by other families, languages, and collaborative spaces.
- Use Python for the core. Add other stacks only for an agreed need.
- Reuse maintained voice and agent libraries behind small interfaces; avoid reimplementing their internals.
- Keep providers replaceable. Do not make a cloud account, model vendor, or high-end machine a core requirement without an explicit design decision.
- Treat Farsi as an early supported target, not an afterthought. Do not equate multilingual marketing with verified quality.
- Make hardware, provider, and permission setup understandable to ordinary users. Turn errors into concrete recovery steps.
- Preserve speaker identity, uncertainty, room context, and memory scope as separate concepts.
- Enforce memory and tool access in application code. Voice recognition is a personalization signal, not sufficient authorization for sensitive actions.
- Keep credentials, voice recordings, voice profiles, personal memories, and local runtime state out of source control.
- Do not collect audio, contact external services, or run persistent listeners as an installation side effect.
- Describe only implemented behavior as available. Keep documentation aligned with actual capabilities.

## Checks

Use checks appropriate to the change. For the initial scaffold, verify package installation and the CLI help/version entry points. Add behavior-focused tests when functional components are introduced.
