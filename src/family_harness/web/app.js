"use strict";
const $ = (id) => document.getElementById(id);
let token = "", saved = null, jobId = null, results = [], busy = false;
const labels = {microphone: "Microphone", speaker: "Speaker", noise: "Background noise", duplex: "Duplex audio"};

function showError(error) {
  const detail = error?.error || error;
  $("error").textContent = typeof detail === "string" ? detail :
    `${detail.message || "Setup could not connect."}\n${detail.recovery || "Reopen the local setup address. Audio tests stop when this page disconnects."}`;
  $("error").hidden = false;
}
async function api(path, data) {
  const options = {headers: {"X-Setup-Token": token}};
  if (data !== undefined) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(data);
  }
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok) throw value;
  return value;
}
function selection() {
  return {space_name: $("space-name").value, room_name: $("room-name").value,
    input_id: $("input-device").value, output_id: $("output-device").value,
    echo_owner: $("echo-owner").value, device_use: $("device-use").value,
    speaker_confirmed: $("speaker-confirmed").checked,
    echo_confirmed: $("echo-confirmed").checked, position: $("position").value};
}
function setBusy(value) {
  busy = value;
  document.querySelectorAll(".test, .voice-action, .people-action, .policy-action, .interruption-action, #refresh, #save, #people-save, input, select").forEach((item) => item.disabled = value);
  $("people-save").disabled = value || !candidateJobId;
  $("listening").textContent = value ? "Audio test active · use Stop / mute anytime" : "Microphone off · no test running";
  if (!value) {
    $("input-level").value = 0; $("level-text").textContent = "Microphone off";
    $("voice-level").value = 0; $("voice-level-text").textContent = "Microphone off";
    $("people-level").value = 0;
  }
}
function deviceOptions(id, devices, selected) {
  const select = $(id);
  select.replaceChildren(new Option(id === "input-device" ? "Choose a microphone" : "Choose a speaker", ""));
  devices.forEach((device) => select.add(new Option(device.name, device.id)));
  select.value = devices.some((device) => device.id === selected) ? selected : "";
  return Boolean(selected && !select.value);
}
async function refresh(initial = false) {
  $("refresh").disabled = true;
  try {
    const input = initial ? saved?.input.id : $("input-device").value;
    const output = initial ? saved?.output.id : $("output-device").value;
    const value = await api("/api/devices");
    const missingInput = deviceOptions("input-device", value.devices.filter((d) => d.direction === "input"), input);
    const missingOutput = deviceOptions("output-device", value.devices.filter((d) => d.direction === "output"), output);
    $("device-warning").textContent = value.warnings.join(" ");
    if (!value.devices.length) $("device-warning").textContent += " No compatible devices found. Connect a microphone and speaker, check Windows Sound settings, then refresh.";
    if (missingInput || missingOutput) {
      showError({message: "A selected device is missing. Choose it again when reconnected, or select another device.",
        recovery: "No substitute has been selected. Reconnecting requires another explicit test."});
      $("speaker-confirmed").checked = false;
    }
  } finally { $("refresh").disabled = busy; }
}
function instructions(job) {
  const phase = job.progress.phase;
  if (phase === "starting") return "Opening the selected device. Audio access starts now.";
  if (phase === "quiet" || phase === "noise") return "Stay quiet. Measuring room background noise.";
  if (phase === "echo_only") return "Stay quiet while the notes play. Measuring speaker echo.";
  if (phase === "speak_during_playback") return "Speak now while the notes play. Try a normal sentence.";
  if (phase === "tail") return "Stay quiet. Finishing the room test.";
  if (phase === "speaker") return "Listen for the notes. Check your volume before confirming below.";
  return job.request.position === "far" ? "Speak from your farthest intended position." : "Speak normally from your usual position.";
}
function renderResults() {
  const target = $("results"); target.replaceChildren();
  const selected = selection();
  const visible = results.filter((r) => ["input_id", "output_id", "echo_owner"].every((key) => r.selection?.[key] === selected[key]));
  visible.forEach((result) => {
    const card = document.createElement("div");
    card.className = `result ${result.status === "needs_attention" ? "attention" : ""}`;
    const title = document.createElement("strong");
    title.textContent = `${labels[result.kind]} · ${result.selection?.position === "far" ? "far position" : "near position"} · ${result.status === "needs_attention" ? "needs attention" : "measurement complete"}`;
    card.append(title);
    const details = result.messages.length ? [...result.messages] : [result.kind === "speaker" ?
      "Playback completed. Confirm below whether you heard it comfortably." : "No energy warning in this test. Repeat at the other speaking position."];
    if (result.echo_reduction_db !== null && result.echo_reduction_db !== undefined)
      details.push(`Measured echo energy reduction: ${result.echo_reduction_db} dB. This does not verify recognition quality.`);
    for (const text of details) { const p = document.createElement("p"); p.textContent = text; card.append(p); }
    target.append(card);
  });
  $("diagnostics").textContent = JSON.stringify({config_path: configPath, tests: visible}, null, 2);
}
async function poll(id) {
  try {
    const job = await api(`/api/job?id=${encodeURIComponent(id)}`);
    if (jobId !== id) return;
    const instruction = instructions(job);
    if ($("test-instruction").textContent !== instruction) $("test-instruction").textContent = instruction;
    $("test-progress").value = Math.min(1, job.progress.seconds / job.progress.duration);
    $("input-level").value = job.progress.level || 0;
    $("level-text").textContent = job.request.kind === "speaker" ? "Microphone off · speaker test only" :
      `Input: ${job.progress.level_dbfs ?? "—"} dBFS · ${Math.max(0, job.progress.duration - job.progress.seconds).toFixed(1)} seconds remaining`;
    if (job.status === "running") { setTimeout(() => poll(id), 250); return; }
    jobId = null; setBusy(false);
    if (job.status === "completed") {
      $("test-progress").value = 1;
      const result = {...job.result, selection: job.request};
      results.push(result); results = results.slice(-20); renderResults();
      $("test-instruction").textContent = "Test ended. Microphone and speaker are released. Review the results below.";
    } else if (job.status === "error") { showError(job.error); $("test-instruction").textContent = "Test failed. Audio is off."; }
    else $("test-instruction").textContent = job.reason;
  } catch (error) {
    if (jobId !== id) return;
    showError(error);
    $("test-instruction").textContent = "Connection lost. The test will stop within three seconds. Reopen setup to continue.";
    jobId = null; setBusy(false);
  }
}
async function start(kind) {
  $("error").hidden = true;
  if (kind === "duplex" && !$("echo-confirmed").checked) {
    showError({message: "Check who removes echo before starting the duplex test.",
      recovery: "Read the echo guidance and confirm that only your chosen echo remover is enabled."}); return;
  }
  setBusy(true);
  try {
    const job = await api("/api/tests", {...selection(), kind});
    document.querySelector(".test-display").scrollIntoView({behavior: "smooth", block: "center"});
    jobId = job.id; poll(jobId);
  } catch (error) { setBusy(false); showError(error); }
}
$("stop").addEventListener("click", async () => {
  try {
    await api("/api/stop", {}); jobId = null; candidateJobId = null; setBusy(false);
    $("people-instruction").textContent = "Stopped. Audio is off; any unsaved enrollment was discarded.";
    $("voice-instruction").textContent = "Stopped. Audio is off; voice models are released.";
    $("voice-progress").value = 0;
    $("test-progress").value = 0;
    $("test-instruction").textContent = "Stopped. Microphone and speaker are released.";
    $("interruption-instruction").textContent = "Stopped. Microphone and speaker are released. Start a new trial to continue.";
  } catch (error) { showError(error); }
});
document.querySelectorAll(".test").forEach((button) => button.addEventListener("click", () => start(button.dataset.kind)));
$("refresh").addEventListener("click", () => refresh().catch(showError));
$("echo-owner").addEventListener("change", () => {
  $("echo-confirmed").checked = false;
  $("echo-help").textContent = $("echo-owner").value === "software" ?
    "Use one echo remover. In Windows Sound settings and your device's app, disable microphone echo cancellation / audio enhancements before using Family Harness." :
    "Use this only when your device documentation confirms its echo cancellation is enabled. Family Harness will bypass its own echo remover. Browser processing cannot remove echo for native capture.";
  renderResults();
});
$("device-use").addEventListener("change", () => {
  $("placement-help").textContent = {room: "Place the microphone away from the speaker and fans. Test nearby and far positions.",
    headset: "Keep the headset microphone near your mouth. A headset test does not prove other people in the room can be heard.",
    conference: "Follow the device's placement guidance. Check its echo cancellation setting before duplex testing."}[$("device-use").value];
});
$("output-device").addEventListener("change", () => { $("speaker-confirmed").checked = false; $("echo-confirmed").checked = false; renderResults(); });
$("input-device").addEventListener("change", () => { $("echo-confirmed").checked = false; renderResults(); });
$("room-name").addEventListener("input", () => { $("active-room").textContent = $("room-name").value || "Choose your room below."; });
function summary() {
  $("summary").textContent = `Saved: ${saved.space_name} / ${saved.room_name}\nMicrophone: ${saved.input.name}\nSpeaker: ${saved.output.name}\n${saved.speaker_confirmed ? "Speaker heard at a comfortable volume." : "Speaker still needs your hearing/volume confirmation."}\nAudio stays off. Use the test buttons above to test again.`;
}
$("setup-form").addEventListener("submit", async (event) => {
  event.preventDefault(); $("error").hidden = true; $("save").disabled = true;
  try { const data = await api("/api/config", selection()); saved = data.config; summary(); }
  catch (error) { showError(error); }
  finally { $("save").disabled = busy; }
});
window.addEventListener("pagehide", () => {
  if (jobId) fetch("/api/stop", {method: "POST", headers: {"X-Setup-Token": token, "Content-Type": "application/json"}, body: "{}", keepalive: true}).catch(() => {});
});
let configPath = "";
(async () => {
  try {
    const state = await api("/api/state"); token = state.token; saved = state.config; configPath = state.config_path;
    renderVoiceState(state.voice);
    renderPeople(state.people);
    if (saved) {
      $("space-name").value = saved.space_name; $("room-name").value = saved.room_name;
      $("device-use").value = saved.device_use || "room"; $("echo-owner").value = saved.echo_owner;
      $("device-use").dispatchEvent(new Event("change")); $("echo-owner").dispatchEvent(new Event("change"));
      $("speaker-confirmed").checked = saved.speaker_confirmed;
      $("active-room").textContent = saved.room_name; results = saved.diagnostics || []; summary();
    }
    await refresh(true); renderResults();
  } catch (error) { showError(error); }
})();

function renderVoiceState(voice) {
  $("voice-status").textContent = voice.installed ?
    "English profile installed. Integrity is checked before loading; audio is off." :
    voice.upgrade_available ?
    "An English profile update is available to improve missing opening words. Download or import it before a voice trial. Your previous profile is retained; audio is off." :
    "English profile is not installed. Download or import it to run a voice trial.";
  if (voice.final_recognizer && voice.final_recognizer !== "zipformer") {
    $("voice-status").textContent += voice.final_recognizer_state?.installed ?
      ` Final recognizer: ${voice.final_recognizer}.` :
      ` Final recognizer ${voice.final_recognizer} is not installed. Run voice install-recognizer ${voice.final_recognizer} before a trial.`;
  }
  if (voice.speech_preset && voice.speech_preset !== "room")
    $("voice-status").textContent += ` Microphone preset: ${voice.speech_preset}.`;
  $("voice-catalog").textContent = JSON.stringify(voice, null, 2);
}
const voiceInstructions = {
  starting: "Starting the operation. Audio is off.",
  installing: "Installing and checking local model files. Audio is off.",
  loading: "Checking integrity and loading local models. Audio is off.",
  warming: "Warming local models before use. Audio is off.",
  listening: "Speak now: say one English sentence, then pause. Microphone is on, speaker is off.",
  finalizing: "Microphone is off. Finalizing the local transcript.",
  synthesizing: "Microphone is off. Preparing the fixed local test response.",
  playback: "Microphone is off. Listen for the test voice. Stop / mute ends playback.",
};
function voiceRecovery(report) {
  if (report.playback_completed)
    return "Playback completed. Check the transcript and confirm you heard the voice; no quality gate is automatically passed.";
  const levels = report.input_levels?.raw;
  if (levels?.clipping_fraction > 0.01)
    return "Microphone input clipped. Lower the Windows microphone volume or boost, and retry.";
  if (levels?.rms_dbfs <= -65)
    return "Microphone input was very quiet. Check mute, Windows input volume / microphone boost, and point the microphone toward you. Compare a nearby and distant trial.";
  if (report.recognition_status === "speech_without_text")
    return "Speech activity was detected, but no English words were recognized. Check the microphone level, use an English sentence, and reduce background noise. A headset boom may need to face you or be closer.";
  if (report.recognition_status === "no_speech_detected")
    return "No speech activity detected. Check microphone selection, mute and input volume, then compare nearby and distant speech. Noise suppression in your device or Windows may remove distant speech.";
  return "The trial reached its limit without a completed sentence. Retry one English sentence, then pause.";
}
async function pollVoice(id) {
  try {
    const job = await api(`/api/job?id=${encodeURIComponent(id)}`);
    if (jobId !== id) return;
    const progress = job.progress;
    $("voice-instruction").textContent = voiceInstructions[progress.phase] || "Finishing the operation.";
    $("listening").textContent = progress.phase === "listening" ? "Voice trial · microphone on" :
      progress.phase === "playback" ? "Voice trial · speaker on · microphone off" : "Voice operation · audio off";
    $("voice-progress").value = progress.total_bytes ? progress.bytes / progress.total_bytes :
      Math.min(1, (progress.seconds || 0) / (progress.duration || 1));
    if (progress.phase === "listening" && Number.isFinite(progress.level_dbfs)) {
      const level = progress.level_dbfs;
      $("voice-level").value = Math.max(0, Math.min(1, (level + 80) / 80));
      $("voice-level-text").textContent =
        `${level < -65 ? "Very quiet input" : level < -45 ? "Quiet input" : "Input present"}: ${level} dBFS · adjusted: ${progress.processed_level_dbfs ?? "—"} dBFS · ${progress.speech_active ? "speech activity detected" : "waiting for speech"}`;
    } else { $("voice-level").value = 0; $("voice-level-text").textContent = "Microphone off"; }
    if (job.transcript) $("voice-transcript").textContent =
      `${job.transcript.final ? "Transcript" : "Draft transcript"}: ${job.transcript.text || "No speech recognized."}`;
    if (job.status === "running") { setTimeout(() => pollVoice(id), 250); return; }
    jobId = null; setBusy(false);
    $("voice-progress").value = job.status === "completed" ? 1 : 0;
    if (job.status === "error") showError(job.error);
    $("voice-instruction").textContent = job.status === "completed" ?
      "Operation complete. Audio is off; voice models are released." : job.reason || "Operation failed. Audio is off.";
    if (job.result) {
      const {transcript, utterance_id, ...report} = job.result;
      $("voice-diagnostics").textContent = JSON.stringify(report, null, 2);
      const metrics = report.measurements;
      $("voice-result").textContent = metrics ?
        `Load: ${report.load_seconds}s · warm-up: ${report.warm_seconds}s · peak sampled RAM: ${metrics.peak_sampled_rss_mb} MB · mean CPU: ${metrics.mean_cpu_core_percent}% of one core. ` +
        (job.request.kind === "voice_trial" ? voiceRecovery(report) :
          "This speed check does not verify speech accuracy or room hardware.") : "Model operation complete.";
    }
    const state = await api("/api/state"); renderVoiceState(state.voice);
  } catch (error) {
    if (jobId !== id) return;
    showError(error); jobId = null; setBusy(false);
    $("voice-instruction").textContent = "Connection lost. The operation will stop within three seconds.";
  }
}
document.querySelectorAll(".voice-action").forEach((button) => button.addEventListener("click", async () => {
  $("error").hidden = true;
  $("voice-transcript").textContent = "";
  setBusy(true);
  try {
    const job = await api("/api/voice", {...selection(), kind: button.dataset.action, source: $("model-source").value});
    jobId = job.id; pollVoice(jobId);
  } catch (error) { setBusy(false); showError(error); }
}));

const interruptionInstructions = {
  starting: "Starting the trial. Audio is off.",
  loading: "Checking and loading local models. Audio is off.",
  warming: "Preparing the test voice. Audio is off.",
  quiet: "Stay quiet for two seconds. The selected microphone and speaker are on.",
  interruption_playback: "Speak a sentence now to interrupt the test voice.",
  interruption_continuation: "Output is stopping. Let the next person continue, one person at a time.",
  group_decoding: "Audio is off. Analyzing the continuation locally.",
};
async function pollInterruption(id) {
  try {
    const job = await api(`/api/job?id=${encodeURIComponent(id)}`);
    if (jobId !== id) return;
    const p = job.progress;
    $("interruption-instruction").textContent = interruptionInstructions[p.phase] || "Finishing the trial.";
    $("interruption-progress").value = Math.min(1, (p.seconds || 0) / (p.duration || 1));
    $("listening").textContent = ["quiet", "interruption_playback", "interruption_continuation"].includes(p.phase) ?
      "Interruption trial · microphone on · Stop / mute ends the trial" : "Interruption trial · audio off";
    if (job.status === "running") { setTimeout(() => pollInterruption(id), 250); return; }
    jobId = null; setBusy(false);
    $("interruption-instruction").textContent = "Trial ended. Microphone and speaker are released.";
    if (job.status === "error") showError(job.error);
    if (job.result) {
      $("interruption-progress").value = 1;
      const r = job.result;
      $("interruption-result").textContent = `${r.interrupted ? "Speech triggered an output stop." : "No interruption detected."} ${r.recovery}`;
      const target = $("interruption-turns"); target.replaceChildren();
      const cue = r.group.responses?.[0];
      if (cue) {
        const heard = document.createElement("p");
        heard.textContent = `Confirmed complete voice chunks: ${cue.heard_text || "None."} Played: ${cue.played_seconds.toFixed(2)} seconds. The remainder was not confirmed.`;
        target.append(heard);
      }
      for (const turn of r.group.utterances || []) {
        if (turn.utterance_id === "trial-control") continue;
        const row = document.createElement("p");
        const person = enrolledPeople.find((person) => person.person_id === turn.person_id);
        row.textContent = `${person?.name || turn.speaker_track} · ${turn.identity_state}: ${turn.text || turn.recovery || "No text recognized; repeat alone."}`;
        row.dir = "auto"; target.append(row);
      }
      const report = JSON.parse(JSON.stringify(r));
      for (const turn of report.group.utterances || []) delete turn.text;
      for (const response of report.group.responses || []) {
        delete response.text; delete response.heard_text;
        for (const chunk of response.alignment || []) delete chunk.text;
      }
      $("interruption-diagnostics").textContent = JSON.stringify(report, null, 2);
    } else $("interruption-result").textContent = job.reason || "Trial failed. Review the recovery instructions.";
  } catch (error) {
    if (jobId !== id) return;
    showError(error); jobId = null; setBusy(false);
    $("interruption-instruction").textContent = "Connection lost. The trial stops within three seconds. Start a new trial after reconnecting.";
  }
}
$("interruption-start").addEventListener("click", async () => {
  $("error").hidden = true;
  setBusy(true);
  try {
    const job = await api("/api/interruptions", selection());
    jobId = job.id; pollInterruption(jobId);
  } catch (error) { setBusy(false); showError(error); }
});

let candidateJobId = null, enrolledPeople = [];
let recognitionPolicies = null;
const policyDescriptions = {
  free: "Free favors recognizing enrolled voices. Guests and similar voices are more likely to get a wrong name.",
  balanced: "Balanced uses the current home preview settings. Recognition still needs improvement and household testing.",
  strict: "Strict requires stronger voice similarity. Enrolled people will more often remain unknown."
};
function fillPolicy(name) {
  const settings = recognitionPolicies.policies[name];
  $("policy-threshold").value = settings.threshold;
  $("policy-margin").value = settings.margin;
  $("policy-minimum").value = settings.minimum_seconds;
  const customized = Object.keys(settings).some((key) => settings[key] !== recognitionPolicies.defaults[name][key]);
  $("policy-description").textContent = policyDescriptions[name] +
    (customized ? " This preset has custom settings; its behavior may differ from these defaults." : "");
}
function renderPolicies(state, displayed = state.selected) {
  recognitionPolicies = state;
  $("recognition-policy").value = displayed;
  fillPolicy(displayed);
  $("policy-status").textContent = `Active policy: ${state.selected}. Save to apply any changes to the next trial.`;
}
$("recognition-policy").addEventListener("change", () => fillPolicy($("recognition-policy").value));
document.querySelectorAll(".policy-action").forEach((button) => button.addEventListener("click", async () => {
  $("error").hidden = true;
  const name = $("recognition-policy").value, action = button.id === "policy-reset" ? "reset" : "save";
  if (action === "save" && !["policy-threshold", "policy-margin", "policy-minimum"].every((id) => $(id).reportValidity())) return;
  const settings = {threshold: Number($("policy-threshold").value), margin: Number($("policy-margin").value),
                    minimum_seconds: Number($("policy-minimum").value)};
  setBusy(true);
  try {
    const state = await api("/api/recognition-policies", {action, name, settings});
    renderPolicies(state, name);
    $("policy-status").textContent = action === "save" ? `Saved and active: ${name}. Applies to the next trial.` :
      `Restored ${name}. Active policy: ${state.selected}.`;
  } catch (error) { showError(error); }
  finally { setBusy(false); }
}));
function renderPeople(state) {
  renderPolicies(state.recognition_policies);
  enrolledPeople = state.people;
  const size = (state.speaker_model.download_bytes / 2**20).toFixed(1);
  $("speaker-install").textContent = `Download speaker model · ${size} MiB`;
  $("people-status").textContent = `${enrolledPeople.length} enrolled people. Speaker model ${state.speaker_model.installed ? "installed" : "missing"}; segmentation ${state.segmentation_model.installed ? "installed" : "missing"}. Audio is off.`;
  $("people-models").textContent = JSON.stringify(state, null, 2);
  $("people-list").replaceChildren();
  enrolledPeople.forEach((person) => {
    const row = document.createElement("p"), label = document.createElement("span"), button = document.createElement("button");
    label.textContent = `${person.name} · enrolled locally `; label.dir = "auto";
    button.textContent = `Remove ${person.name}`; button.type = "button"; button.className = "people-action";
    button.addEventListener("click", async () => {
      setBusy(true);
      try { await api("/api/people", {kind: "people_remove", person_id: person.person_id});
        renderPeople((await api("/api/state")).people); }
      catch (error) { showError(error); }
      finally { setBusy(false); }
    });
    row.append(label, button); $("people-list").append(row);
  });
}
async function pollPeople(id) {
  try {
    const job = await api(`/api/job?id=${encodeURIComponent(id)}`);
    if (jobId !== id) return;
    const p = job.progress, listening = ["enrollment_listening", "group_listening"].includes(p.phase);
    $("listening").textContent = listening ? "People preview · microphone on" : "People preview · audio off";
    $("people-instruction").textContent = p.phase === "enrollment_listening" ?
      `Phrase ${p.phrase} of 3: ${["describe your room", "describe an activity you enjoy", "describe a plan for tomorrow"][p.phrase - 1]}. Microphone is on.` :
      p.phase === "group_listening" ? "Speak in turn. Microphone is on; speaker is off." :
      p.phase === "enrollment_analyzing" ? "Microphone is off. Checking the three phrases; nothing is saved yet." :
      p.phase === "group_decoding" ? "Microphone is off. Finding speakers and transcribing group turns." :
      "Preparing local models. Audio is off.";
    $("people-progress").value = p.total_bytes ? p.bytes / p.total_bytes :
      Math.min(1, (p.seconds || 0) / (p.duration || 1));
    $("people-level").value = listening ? Math.max(0, Math.min(1, ((p.level_dbfs ?? -80) + 80) / 80)) : 0;
    if (job.status === "running") { setTimeout(() => pollPeople(id), 250); return; }
    jobId = null;
    if (job.status === "error") showError(job.error);
    if (job.status === "completed" && job.request.kind === "people_enroll") candidateJobId = id;
    setBusy(false);
    $("people-instruction").textContent = job.status === "completed" ? "Preview complete. Audio is off." : job.reason || "Preview failed. Audio is off.";
    if (job.result) {
      const report = {...job.result, utterances: job.result.utterances?.map(({text, ...turn}) => turn)};
      $("people-diagnostics").textContent = JSON.stringify(report, null, 2);
      $("people-result").textContent = job.request.kind === "people_enroll" ?
        `Three phrases checked for ${job.request.name}. Review who spoke, then save the voice profile or record again. Nothing is saved yet.` :
        job.result.recovery || "Review the attributed turns. Unknown or uncertain voices stay unknown. Hardware quality is still unvalidated.";
      $("group-turns").replaceChildren();
      for (const turn of job.result.utterances || []) {
        const row = document.createElement("p"), person = enrolledPeople.find((p) => p.person_id === turn.person_id);
        row.dir = "auto";
        row.textContent = `${person?.name || "Unknown voice"} (${turn.speaker_track}, ${turn.identity_state}): ${turn.text || "Speech could not be transcribed; please repeat one person at a time."}`;
        $("group-turns").append(row);
      }
    }
    renderPeople((await api("/api/state")).people);
  } catch (error) {
    if (jobId !== id) return;
    showError(error); jobId = null; setBusy(false);
    $("people-instruction").textContent = "Connection lost. The operation stops within three seconds.";
  }
}
document.querySelectorAll(".people-action[data-action]").forEach((button) => button.addEventListener("click", async () => {
  $("error").hidden = true; candidateJobId = null; setBusy(true);
  try {
    const job = await api("/api/people", {...selection(), kind: button.dataset.action,
      name: $("person-name").value, consent: $("person-consent").checked,
      source: $("people-source").value, participation: $("participation").value});
    jobId = job.id; pollPeople(jobId);
  } catch (error) { setBusy(false); showError(error); }
}));
$("people-save").addEventListener("click", async () => {
  setBusy(true);
  try {
    await api("/api/people", {kind: "people_save", job_id: candidateJobId}); candidateJobId = null;
    $("people-result").textContent = "Voice profile saved locally. The original recording was discarded.";
    renderPeople((await api("/api/state")).people);
  } catch (error) { showError(error); }
  finally { setBusy(false); }
});
