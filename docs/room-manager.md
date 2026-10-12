# Room manager core and offline evaluation (M1.4)

**Implemented replay foundation, 2026-10-12.** The Python room manager assembles
provisional/final utterances, assigns response IDs, tracks playback, and cancels
outdated work. It runs with a deterministic responder and explicit local file
replay. M1.5 now adds [local enrollment and bounded attributed group previews](people-and-group-turns.md).
Live room sessions and physical interruptions remain later phases. Family Harness
is still under development.

## Contracts and lifecycle

`RoomEvent` contains `event_id`, `session_id`, `source_id`, `at`, `kind`, and
`data`. Times are nonnegative seconds on the source audio timeline, independent
of inference arrival time. `RoomManager.apply()` processes arrival order and
returns commands; it never runs inference or opens a device.

| Event | Payload |
| --- | --- |
| `session_started`, `session_closed`, `audio_gap` | No required fields |
| `transcript` | `utterance_id`, increasing `revision`, replacement `text`, `final`, `start`, `end`; optional `speaker_track`, `language`, `reason` |
| `turn_candidate` | `utterance_id`, `authority` (`vad-silence`) |
| `utterance_cancelled` | `utterance_id` |
| `response_ready` | `response_id`, `text`, audio `duration` |
| `response_cancelled` | `response_id` |
| `playback_progress`, `playback_finished` | `response_id`, confirmed `played_seconds` |

A session starts explicitly and cannot reopen after closure. Reopening creates
a new manager/session ID. Revisions replace text; duplicates and old revisions
cannot append words. Final utterances are immutable and request one response.
An older final arriving after newer speech can complete history without
cancelling the current response or requesting an outdated reply.
An empty or cancelled/gapped final cannot request output. One selected speech
adapter owns finalization; silence candidates remain separate evidence.

New final input cancels an unfinished response. Closing the session or losing
audio discards provisional input and emits separate `cancel_generation` and
`stop_playback` commands. Late results cannot revive a cancelled response.
Gap watermarks reject speech that began before missing audio. Playback progress
must be monotonic and within the response duration. Partial playback stores only
the confirmed duration; text is marked heard only after complete playback.
There is no word alignment or physical interruption guarantee in this phase.

Speaker tracks are session-local labels. The original continuous speech replay
leaves `person_id` and `identity_confidence` unset. The separate `room group` path
uses actual speaker models and explicit attribution events; its uncertainty and
participation rules are in the [people guide](people-and-group-turns.md).
Annotation-derived labels in event evaluation remain fixture metadata, not model recognition or authorization.
Memory and tool access are not implemented.

Sessions hold at most 4,096 utterances/responses and a 4,096-ID duplicate cache.
At capacity, start a new session explicitly. Older transcript/response repeats
remain harmless through revision and terminal-state checks. No session state or
transcript is saved automatically; replay reports omit text.

## Run a replay

Install the normal Python package and the optional scoring dependencies:

```sh
uv sync --extra evaluation
uv run family-harness room --help
uv run family-harness room replay conversation.wav --report .local/room-replay.json
uv run family-harness room replay events.jsonl --events --report .local/events.json
```

WAV replay accepts PCM16 mono at 8-48 kHz, up to one hour, reads in bounded
chunks, keeps source timestamps, and resets recognizer context between
utterances. It feeds onset audio before VAD confirmation, uses a configurable
silence candidate, and caps an uninterrupted segment at 30 seconds.
Forced segment boundaries reset VAD state as well as recognizer context; the
upstream duration setting alone is a soft limit and can grow its audio buffer.
Idle recognizer streams reset every five seconds. EOF appends at least one second of synthetic
silence, extended to completion silence plus 700 ms for VAD release when necessary.
Partial/completion timings
are measured against detected VAD activity,
not human word boundaries. The processing real-time factor includes file reading,
resampling, input conditioning, speech decoding, and manager processing; it
excludes model loading and does not simulate hardware scheduling.

JSONL contains one `RoomEvent` object per line, in arrival order, and must
explicitly start and close a session. For example:

```json
{"event_id":"1","session_id":"example","source_id":"fixture","at":0,"kind":"session_started","data":{}}
{"event_id":"2","session_id":"example","source_id":"fixture","at":2,"kind":"transcript","data":{"utterance_id":"u1","revision":1,"text":"Hello room","final":true,"start":1,"end":2}}
{"event_id":"3","session_id":"example","source_id":"fixture","at":3,"kind":"session_closed","data":{}}
```

The responder uses fixed text and simulated half-second playback. It exercises
response IDs and output cancellation without an LLM, microphone, TTS generation,
or real speaker. A later provider executes the same manager commands outside
the reducer. The M1.3 voice trial remains the real local TTS/capture test.

## DiPCo validation

The [DiPCo dataset card](https://huggingface.co/datasets/huckiyang/DiPCo) describes
separate close-talk microphones and room array channels, with per-device
timestamps and public participant labels. Its development/evaluation sessions
are respected. The supplied local subset has S02 P05/U01.CH1 development audio
and S08 U01.CH1 evaluation audio. These are single channels, not beamformed arrays.
The follow-up [accuracy study](dipco-accuracy.md) adds S09 U04 development audio,
S06 U04 fresh validation audio, and S08 P25 close-talk audio. Additional downloads
total 112,697,364 bytes including annotations, below the requested 300 MB limit.

```sh
uv run family-harness room evaluate E:/Datasets/DiPCo --mode events --report .local/manager-events.json
uv run family-harness room evaluate E:/Datasets/DiPCo --mode utterances --split dev --limit 32 --report .local/dev.json
uv run family-harness room evaluate E:/Datasets/DiPCo --mode continuous --split eval --report .local/eval-continuous.json
```

Use `room --models PATH` to select existing verified models. Evaluation blocks
outbound sockets, does not download weights or contact inference services, and
never opens audio devices. Models must be explicitly installed/imported first.

- `events` builds partial/final events from the annotations and injects duplicate,
  stale-revision, and post-close events. It verifies exact turn assembly and
  closure with simulated response cancellation.
- `utterances` uses the annotated device-specific boundaries with 200 ms lead-in,
  150 ms trailing context, and a synthetic silence tail of at least one second
  (completion silence plus 700 ms for VAD release). Each
  clip runs the M1.3 one-utterance path, including premature completion behavior.
  Close-talk scores only its named participant. `--limit` samples evenly through
  each speaker's recording; omit it for all eligible annotations.
- `recognizer` decodes the **entire exact annotated interval** without neighboring
  context, VAD suppression, or early endpointing. It isolates acoustic recognition
  from pipeline misses. It uses the same reference exclusions, normalization and
  word-weighted edit counts; it is not autonomous conversation accuracy.
- `continuous` replays the waveform without reference segmentation or speaker
  labels, scoring all annotated speakers even when a close-talk file contains
  cross-talk. Its chronological single-stream WER is a diagnostic measure, not
  official DiPCo/CHiME scoring; overlapping reference words have no unique order.

WER uses [JiWER](https://github.com/jitsi/jiwer). Normalization applies NFKC and
case folding, removes bracketed tags and punctuation except apostrophes, and
collapses whitespace. Unintelligible annotations, nonlexical annotations, and
utterances longer than 28 seconds are excluded from clip WER. Scores report the
exclusions, overlap/nonoverlap groups, raw edit counts and word denominators.
Continuous scoring uses the same eligible reference subset, so speech from
excluded annotations can appear as insertions. Do not compare these scores
directly with published official results.

Reports contain file hashes/names, selected annotation indices, model asset
hashes, explicit settings, environment/resource measurements, WER, VAD misses,
premature endings, and timing distributions. They contain no reference or
recognized text. Keep local reports in `.local/`; recordings/models stay outside
source control. A public numeric result summary belongs in the evaluation notes.

Two opt-in presets were selected on S02 development data: `quiet-close-talk`
uses 12 dB fixed input gain followed by WebRTC processing; `quiet-room` uses
36 dB fixed gain without WebRTC noise suppression. Both use greedy decoding,
the original 0.5 VAD threshold, and 900 ms completion silence. The high-gain
preset is intended for quiet recordings like this subset; test clipping/noise
before choosing it for a device. Presets never change Windows microphone settings
or infer calibration from a product name. The setup wizard retains its original
600 ms, WebRTC-only baseline pending household validation.

```sh
uv run family-harness room evaluate E:/Datasets/DiPCo --file S02_P05.wav --preset quiet-close-talk --report .local/close-talk.json
uv run family-harness room evaluate E:/Datasets/DiPCo --file S08_U01.CH1.wav --preset quiet-room --report .local/heldout.json
uv run family-harness room evaluate E:/Datasets/DiPCo --file S08_U01.CH1.wav --mode continuous --preset quiet-room --report .local/heldout-continuous.json
uv run family-harness voice replay short-quiet.wav --preset quiet-room --report .local/short-quiet.json
```

Advanced comparisons can override `--gain-db` and `--silence` for room replay.
`room-beam` and `close-talk-beam` are comparison presets, not selected winners.

Install optional final models explicitly with `voice install-recognizer parakeet-v2`
or `whisper-small-en`. `--recognizer` selects the final model independently of the
microphone preset, for WAV replay, clip scoring and continuous scoring. Zipformer
remains the default and supplies drafts when a stronger final model is selected.

```sh
uv run family-harness room evaluate E:/Datasets/DiPCo --mode recognizer --recognizer parakeet-v2 --preset close-talk --gain-db 24 --split eval --report .local/eval-asr.json
uv run family-harness room replay conversation.wav --recognizer parakeet-v2 --preset close-talk --report .local/stronger-replay.json
```

Exact-boundary ASR scores and endpointed scores are different measurements; compare
backends only within the same protocol and selected annotation indices. Excluded
regions and overlapping speakers still make chronological continuous WER unsuitable
as the primary accuracy number. No official meeting scorer or speaker separation
is implemented here.

The software replay gate can pass while recognition quality is poor. Hardware
capture/playback, room echo, actual speaker identity, and interruptions remain
unvalidated by this dataset.

See the [measured subset results](dipco-evaluation.md), including the S08 clip
preset regression and the remaining speech-quality limits.
