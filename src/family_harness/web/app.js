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
  document.querySelectorAll(".test, #refresh, #save, input, select").forEach((item) => item.disabled = value);
  $("listening").textContent = value ? "Audio test active · use Stop / mute anytime" : "Microphone off · no test running";
  if (!value) { $("input-level").value = 0; $("level-text").textContent = "Microphone off"; }
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
    await api("/api/stop", {}); jobId = null; setBusy(false);
    $("test-progress").value = 0;
    $("test-instruction").textContent = "Stopped. Microphone and speaker are released.";
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
