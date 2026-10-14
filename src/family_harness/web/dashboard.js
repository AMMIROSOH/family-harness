"use strict";

const stages = [
  ["room", "Room", "Name your space and room. Audio stays off until you start a test."],
  ["devices", "Devices", "Choose friendly device names, test the microphone and confirm you heard the speaker."],
  ["acoustics", "Acoustics", "Compare nearby and far positions. Confirm one echo owner before duplex tests."],
  ["models", "Models", "Install or import explicitly, benchmark with audio off, then try one sentence."],
  ["people", "People", "Enroll consenting people or continue without names. Include an unknown guest when testing."],
  ["timing", "Timing & recognition", "Prepare supported settings, apply to the next take, and save only when ready."],
  ["live", "Live test", "Open Voice Lab for streaming diagnostics, or run the short interruption check here."],
  ["review", "Review", "Save room choices and review evidence. Saving and reopening leave audio off."]
];
let dashboardState = null, appliedSettings = null, latestState = null, observedId = null;
let eventCursor = new Map(), takes = [], route = "home", lastSetup = "room", activeHeartbeat = null;
const tallyNames = {known_correct: "Correct known turns", known_wrong: "Wrong known person", known_unknown: "Unknown / missed known",
  guest_rejected: "Guest turns rejected", guest_accepted: "Guest assigned a name", interruption_attempts: "Interruption attempts",
  interruption_detected: "Attempts detected", quiet_trials: "Quiet playback trials", quiet_false_stops: "False stops in quiet trials",
  continuation_attempts:"Continuation attempts", continuation_correct:"Continuations captured correctly",spurious_turns:"Spurious / mixed turns"};
const copy = value => JSON.parse(JSON.stringify(value));
const node = (tag, text, cls) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (cls) el.className = cls; return el; };
const oldApi = api, oldSetBusy = setBusy;

api = async function(path, data) {
  const starting = ["/api/tests", "/api/voice", "/api/people", "/api/interruptions", "/api/lab"].includes(path);
  if (data && starting && appliedSettings) data = {...data, settings: copy(appliedSettings), settings_revision: dashboardState?.revision ?? 0};
  if (path.startsWith("/api/job?")) {
    const id = new URL(path, location.origin).searchParams.get("id");
    path += `&cursor=${eventCursor.get(id) || 0}`;
  }
  const value = await oldApi(path, data);
  if (starting && value.status === "running") { activeHeartbeat = value.id; observeJob(value); }
  if (path.startsWith("/api/job?") && (!jobId || value.id === jobId || value.id === observedId)) observeJob(value);
  if (path==="/api/stop"&&value.id)observeJob(value);
  if (path === "/api/state") { latestState = value; renderReadiness(); }
  if (path === "/api/recognition-policies" && appliedSettings) {
    appliedSettings.recognition_name = value.selected;
    appliedSettings.matching = copy(value.active.settings);
  }
  return value;
};
setBusy = function(value) {
  oldSetBusy(value);
  document.querySelectorAll(".lab-action, .model-action, .policy-action, #lab-start, #save-settings, #save-profile, #reload-settings").forEach(el => el.disabled = value);
  if(value)$("listening").textContent="Preparing operation · device state pending";
  if (!value) { activeHeartbeat = null; $("lab-raw").value = 0; $("lab-clean").value = 0; }
};

function navigate(target, persist = true) {
  if (!/^(home|lab|results|health|privacy|setup\/(room|devices|acoustics|models|people|timing|live|review))$/.test(target)) target = "home";
  route = target;
  if(target==="home")renderReadiness();
  document.querySelectorAll(".view, .guided-section").forEach(el => el.hidden = true);
  const guided = target.startsWith("setup/");
  $("setup-toolbar").hidden = !guided && target !== "lab";
  $("setup-steps").hidden = !guided; $("step-hint").hidden = !guided;
  $("guided-navigation").hidden = !guided;
  if (guided) {
    const stage = target.split("/")[1], index = stages.findIndex(s => s[0] === stage);
    lastSetup = stage;
    try { localStorage.setItem("fh-setup-step", stage); } catch (_) { /* UI progress only. */ }
    if (stage === "timing") $("timing-stage").append($("runtime-settings"));
    document.querySelectorAll(`[data-step="${stage}"]`).forEach(el => el.hidden = false);
    $("step-hint").textContent = stages[index][2];
    $("page-title").textContent = "Voice Management";
    $("breadcrumb").textContent = `Quick Setup / ${stages[index][1]}`;
    $("previous-step").disabled = index === 0;
    $("next-step").textContent = index === stages.length-1 ? "Return home" : "Next step";
  } else {
    $(`${target}-view`).hidden = false;
    $("page-title").textContent = {home:"Make this room work for you.", lab:"Live test & tune", results:"What works better?", health:"Get the room working again", privacy:"Settings & privacy"}[target];
    $("breadcrumb").textContent = {home:"Home / Overview", lab:"Quick Setup / Voice Lab", results:"Voice Management / Results", health:"Room / Health & help", privacy:"Local application / Your controls"}[target];
    if (target === "lab") $("lab-tuning").append($("runtime-settings"));
    if (target === "results") renderComparison();
  }
  document.querySelectorAll("[data-route]").forEach(el => {
    const current = el.dataset.route === target;
    if (current) el.setAttribute("aria-current", "page"); else el.removeAttribute("aria-current");
  });
  document.querySelectorAll("[data-guide-step]").forEach(el => el.setAttribute("aria-pressed", String(target === `setup/${el.dataset.guideStep}`)));
  $("app-nav").classList.remove("is-open"); $("nav-toggle").setAttribute("aria-expanded", "false");
  if (persist) history.replaceState(null, "", `#${target}`);
}
document.querySelectorAll("[data-route]").forEach(el => el.addEventListener("click", () => navigate(el.dataset.route)));
stages.forEach(([id,label], index) => {
  const button = node("button", `${index+1} ${label}`); button.type = "button"; button.dataset.guideStep = id;
  button.addEventListener("click", () => navigate(`setup/${id}`)); $("setup-steps").append(button);
});
$("previous-step").onclick = () => navigate(`setup/${stages[Math.max(0,stages.findIndex(s=>s[0]===lastSetup)-1)][0]}`);
$("next-step").onclick = () => { const i=stages.findIndex(s=>s[0]===lastSetup); navigate(i===7?"home":`setup/${stages[i+1][0]}`); };
$("resume-setup").onclick = () => navigate(`setup/${lastSetup}`);
$("nav-toggle").onclick = () => { const open=$("app-nav").classList.toggle("is-open"); $("nav-toggle").setAttribute("aria-expanded",String(open)); };
window.addEventListener("hashchange",()=>navigate(location.hash.slice(1),false));
document.addEventListener("audio-test-start", event => { navigate("setup/acoustics"); $("test-instruction").textContent = `Starting ${labels[event.detail] || "audio"} test.`; });

function fillSettings(settings) {
  $("speech-preset").value=settings.preset; $("final-recognizer").value=settings.recognizer;
  $("speaker-backend").value=settings.backend; $("live-seconds").value=settings.seconds;
  $("speech-gain").value=settings.speech.gain_db; $("speech-vad").value=settings.speech.vad_threshold;
  $("speech-silence").value=settings.speech.silence; $("speech-decoder").value=settings.speech.decoding;
  $("speech-processing").checked=settings.speech.processing;
  $("onset-hold").value=settings.interruption.hold_seconds; $("onset-release").value=settings.interruption.release_seconds;
  $("recognition-policy").value=settings.recognition_name; $("participation").value=settings.participation;
  $("policy-threshold").value=settings.matching.threshold; $("policy-margin").value=settings.matching.margin;
  $("policy-minimum").value=settings.matching.minimum_seconds;
  $("policy-description").textContent=policyDescriptions[settings.recognition_name];
  $("policy-status").textContent=`Recognition in next-take settings: ${settings.recognition_name}. Apply drafts explicitly.`;
}
function readDraft() {
  const invalid = [...$("runtime-settings").querySelectorAll("input[type=number]")].find(el=>!el.checkValidity());
  if (invalid) { invalid.closest("details")?.setAttribute("open", ""); invalid.reportValidity(); throw {message:"Correct the invalid tuning value.",recovery:"Use the stated range and units. The running take is unchanged."}; }
  return {preset:$("speech-preset").value, recognizer:$("final-recognizer").value, backend:$("speaker-backend").value,
    seconds:Number($("live-seconds").value), participation:$("participation").value,
    speech:{processing:$("speech-processing").checked, decoding:$("speech-decoder").value, silence:Number($("speech-silence").value), vad_threshold:Number($("speech-vad").value), gain_db:Number($("speech-gain").value)},
    interruption:{hold_seconds:Number($("onset-hold").value),release_seconds:Number($("onset-release").value)},
    recognition_name:$("recognition-policy").value, matching:{threshold:Number($("policy-threshold").value),margin:Number($("policy-margin").value),minimum_seconds:Number($("policy-minimum").value)}};
}
function draftNotice() { $("draft-status").textContent="Draft changed. Apply to next take; the current take keeps its settings."; }
$("runtime-settings").addEventListener("input",draftNotice);
$("speech-preset").onchange = () => { const next=readDraft(); next.speech=copy(dashboardState.presets[next.preset]); fillSettings(next); draftNotice(); };
$("apply-draft").onclick=()=>{try{appliedSettings=readDraft();$("draft-status").textContent="Applied to the next take. Nothing saved; any current take is unchanged.";}catch(error){showError(error);}};
$("restore-draft").onclick=()=>{fillSettings(dashboardState.defaults);draftNotice();};
$("saved-profiles").onchange=()=>{const value=dashboardState.profiles[$("saved-profiles").value];if(value){fillSettings(value);draftNotice();}};
function renderProfileChoices() { $("saved-profiles").replaceChildren(new Option("Choose a saved profile","")); Object.keys(dashboardState.profiles).forEach(name=>$("saved-profiles").add(new Option(name,name))); }
async function saveSettings(named) {
  try {
    const settings=readDraft(), request={revision:dashboardState.revision,settings};
    if(named)request.name=$("profile-name").value.trim();
    dashboardState=await api("/api/settings",request); appliedSettings=copy(dashboardState.settings); renderProfileChoices();
    $("draft-status").textContent=`Saved revision ${dashboardState.revision}. Audio remains off.`;
    const state=await api("/api/state"); renderVoiceState(state.voice); renderPeople(state.people); fillSettings(appliedSettings);
  }catch(error){showError(error);}
}
$("save-settings").onclick=()=>saveSettings(false);$("save-profile").onclick=()=>saveSettings(true);
$("reload-settings").onclick=async()=>{try{const state=await api("/api/state");dashboardState=state.dashboard;appliedSettings=copy(dashboardState.settings);fillSettings(appliedSettings);renderProfileChoices();$("draft-status").textContent="Reloaded saved settings into the draft and next take.";}catch(error){showError(error);}};

function renderReadiness() {
  if(!latestState)return;
  const config=saved||latestState.config, voice=latestState.voice, people=latestState.people;
  const items=[
    ["Room choices",config?"Configured · retest after changes":"Not configured","setup/room"],
    ["Microphone & speaker",config?.speaker_confirmed?"Hearing confirmed · device checks still apply":"Needs test and hearing confirmation","setup/devices"],
    ["Local speech profile",voice.installed?"Installed · speed and quality need tests":"Needs explicit install or offline import","setup/models"],
    ["People & identity",`${people.people.length} enrolled · household quality unverified`,"setup/people"],
    ["Household evidence","Audio, recognition and physical stop: unverified","health"]];
  $("readiness").replaceChildren();items.forEach(([title,value,dest])=>{const card=node("div",undefined,"readiness-item");card.append(node("h3",title),node("p",value,"muted"));const b=node("button","Review / repair");b.type="button";b.onclick=()=>navigate(dest);card.append(b);$("readiness").append(card);});
}

function updateDeviceContext() {
  const input=$("input-device"),output=$("output-device");
  $("active-devices").textContent=`${input.value?input.selectedOptions[0].textContent:"Microphone not selected"} / ${output.value?output.selectedOptions[0].textContent:"Speaker not selected"}`;
}
$("input-device").addEventListener("change",updateDeviceContext);
$("output-device").addEventListener("change",updateDeviceContext);

function observeJob(job) {
  const p=job.progress||{}, running=job.status==="running";
  if(!running && activeHeartbeat===job.id)activeHeartbeat=null;
  const phase=p.phase||"starting";
  const live=phase==="live_listening" && running;
  if(live)$("listening").textContent=`Microphone on · ${p.speaker_on?"speaker playing":"speaker quiet"}`;
  else if(!running)$("listening").textContent="Microphone off · devices released";
  else if(["loading","warming","installing","starting","finalizing","synthesizing","group_decoding","enrollment_analyzing","releasing"].includes(phase))$("listening").textContent="Preparing / analyzing · microphone off";
  else if(phase==="speaker"||phase==="playback")$("listening").textContent="Speaker playing · microphone off";
  else $("listening").textContent=`Microphone on · ${["echo_only","speak_during_playback","interruption_playback"].includes(phase)?"speaker playing":"speaker quiet"}`;
  const instruction=live?"Live take: speak, pause and watch the evidence. Stop all ends the take.":running?`Preparing: ${phase}. Audio is off until capture starts.`:job.error?`${job.error.message} ${job.error.recovery}`:job.reason||"Take complete. Audio is off; review the evidence.";
  if($("lab-instruction").textContent!==instruction)$("lab-instruction").textContent=instruction;
  $("lab-remaining").textContent=live?`${(Math.max(0,(p.duration||60)-(p.seconds||0))).toFixed(1)} seconds remaining`:"";
  $("lab-progress").value=Math.min(1,(p.seconds||0)/(p.duration||1));
  $("lab-raw").value=live?Math.max(0,Math.min(1,((p.level_dbfs??-80)+80)/80)):0;
  $("lab-clean").value=live?Math.max(0,Math.min(1,((p.processed_level_dbfs??-80)+80)/80)):0;
  $("lab-signal").textContent=live?`Raw ${p.level_dbfs??"—"} dBFS · processed ${p.processed_level_dbfs??"—"} dBFS · ${p.speech_active?"speech detected":"waiting for speech"} · queue ${Number(p.capture_queue_ms||0).toFixed(1)} ms · ${p.analysis_pending||0} analysis pending`:"No active audio measurements.";
  if(job.room)renderRoom(job.room);
  if(job.events_reset)$("event-notice").textContent="Older event rows expired. The current session snapshot is complete; the timeline begins at retained events.";
  for(const e of job.events||[]) {
    const entry=node("li",`${Number(e.at||0).toFixed(2)} s · ${e.kind} · ${e.source_id}`);
    $("live-events").append(entry);while($("live-events").children.length>40)$("live-events").firstChild.remove();
  }
  eventCursor.set(job.id,job.event_cursor||0);
  if(job.result)$("lab-diagnostics").textContent=JSON.stringify(numericReport(job),null,2);
  if(!running&&!takes.some(t=>t.id===job.id)) {
    takes.push({id:job.id,job:copy(job),observations:{}});takes=takes.slice(-12);renderTakeChoices();renderReadiness();
  }
}
function renderRoom(room) {
  $("live-room-status").textContent=room.status||"Replay";
  const fragment=document.createDocumentFragment();
  for(const turn of room.utterances||[]) {
    const person=enrolledPeople.find(p=>p.person_id===turn.person_id), row=node("div",undefined,"turn-row");
    const head=node("div",undefined,"turn-heading");
    head.append(node("strong",person?.name||turn.speaker_track||"Unknown voice"),node("span",`${turn.status} · ${turn.attribution_revision?turn.identity_state:room.status==="closed"?"identity unverified":"identity pending"}`,"muted"));
    row.append(head);const words=node("p",turn.text||turn.recovery||(turn.status==="discarded"||room.status==="closed"?"No complete transcript. Check levels and repeat one sentence.":"Speech / identity evidence pending."));words.dir="auto";row.append(words);
    if(turn.identity_confidence!==null&&turn.identity_confidence!==undefined)row.append(node("p",`Similarity ${Number(turn.identity_confidence).toFixed(3)} · score, not probability`,"muted"));
    if(turn.recovery)row.append(node("p",turn.recovery,"notice"));fragment.append(row);
  }
  for(const reply of room.responses||[]) {
    const row=node("div",undefined,"turn-row response-row");row.append(node("strong",`Fixed test voice · ${reply.status}`),node("p",reply.text||(reply.status==="requested"?"Preparing a deterministic reply.":"No response audio prepared in this check.")));
    row.append(node("p",`Confirmed heard chunks: ${reply.heard_text||"none confirmed"}`,"heard-evidence"));
    if(reply.status==="cancelled")row.append(node("p","An interrupted fragment remains uncertain; unplayed text is not counted as heard.","muted"));fragment.append(row);
  }
  if(!fragment.childNodes.length)fragment.append(node("p","No turns yet. Start a deliberate take; unknown identities are valid results.","muted"));
  $("live-turns").replaceChildren(fragment);
}
async function startLab(kind) {
  $("error").hidden=true;candidateJobId=null;setBusy(true);$("live-events").replaceChildren();$("event-notice").textContent="";
  try{const job=await api("/api/lab",{...selection(),kind,scenario:$("lab-scenario").value,source:$("replay-source").value});jobId=job.id;pollLab(jobId);}
  catch(error){setBusy(false);showError(error);}
}
async function pollLab(id) {
  try{const job=await api(`/api/job?id=${encodeURIComponent(id)}`);if(jobId!==id)return;
    if(job.status==="running"){setTimeout(()=>pollLab(id),250);return;}jobId=null;setBusy(false);if(job.error)showError(job.error);
  }catch(error){if(jobId!==id)return;jobId=null;setBusy(false);showError(error);$("lab-instruction").textContent="Connection lost. The backend lease stops the take; reconnect never restarts it.";}
}
$("lab-start").onclick=()=>startLab("lab_live");
document.querySelectorAll("[data-lab-action]").forEach(b=>b.onclick=()=>startLab(b.dataset.labAction));
$("lab-scenario").onchange=()=>{$("scenario-help").textContent={integrated:"Take turns, interrupt a fixed reply, then let another speaker continue. Use two consenting enrolled people and an unknown guest.",speech:"Say a sentence, pause, and continue. Drafts/finals update while capture remains open. Names and spoken replies are disabled.",people:"Take turns between enrolled people and a guest; try short handovers and overlap. Names may remain unknown. Replies are disabled.",interruptions:"Stay quiet for two seconds, interrupt the fixed cue, then let another person continue.","quiet-playback":"Stay quiet while the fixed cue plays. Count any false speech detections or output stops; repeat at the intended volume."}[$("lab-scenario").value];};
document.querySelectorAll("[data-model-action]").forEach(b=>b.onclick=async()=>{const action=b.dataset.modelAction;if(action==="recognizer_import"&&!$("recognizer-source").value.trim()){showError({message:"Enter the original model folder before offline import.",recovery:"Import never downloads a missing selection."});return;}setBusy(true);try{const job=await api("/api/voice",{kind:action==="recognizer_import"?"recognizer_install":action,recognizer:$("optional-recognizer").value,...(action==="recognizer_import"?{source:$("recognizer-source").value}:{})});jobId=job.id;pollVoice(jobId);}catch(error){setBusy(false);showError(error);}});
setInterval(()=>{if(activeHeartbeat)oldApi("/api/heartbeat",{id:activeHeartbeat}).catch(()=>{activeHeartbeat=null;});},900);
$("stop").addEventListener("click",()=>{activeHeartbeat=null;observedId=null;$("lab-instruction").textContent="Stop requested. Waiting for device release.";});

function numericReport(job) {
  const r=job.result||{}, m=r.measurements||{};
  const effective=job.request.effective_settings,scope=job.request.settings_scope||[];
  const scoped=effective?Object.fromEntries(scope.map(key=>[key,effective[key]])):null;
  const report={version:1,kind:job.request.kind,status:job.status,settings:scoped,
    settings_revision:job.request.settings_revision??0,hardware_gate:"unverified",mode:job.request.kind.includes("replay")?"local replay":job.request.kind==="lab_fixture"?"fixture":"native test",
    observations:takes.find(t=>t.id===job.id)?.observations||{}};
  if(["near","far"].includes(job.request.position))report.position=job.request.position;
  if(["integrated","speech","people","interruptions","quiet-playback"].includes(job.request.scenario))report.scenario=job.request.scenario;
  const allowed=["audio_seconds","load_seconds","warm_seconds","real_time_factor","max_capture_queue_ms","audio_gaps","stop_to_first_zero_dac_ms","identity_analysis_ms","first_partial_latency_ms","completion_latency_ms","stream_queue_ms","speech_processing_real_time_factor"];
  report.metrics={};for(const key of allowed){if(typeof r[key]==="number")report.metrics[key]=r[key];else if(Array.isArray(r[key])&&r[key].every(v=>typeof v==="number")){const values=[...r[key]].sort((a,b)=>a-b),percentile=p=>{const index=(values.length-1)*p,left=Math.floor(index),right=Math.ceil(index);return values[left]+(values[right]-values[left])*(index-left);};report.metrics[key]={count:values.length,p50:values.length?percentile(.5):null,p95:values.length>1?percentile(.95):null,max:values.length?values.at(-1):null};}}
  for(const key of ["wall_seconds","cpu_seconds","mean_cpu_core_percent","peak_sampled_rss_mb"])if(typeof m[key]==="number")report.metrics[key]=m[key];
  if(m.frame_processing_ms)report.frame_processing_ms=m.frame_processing_ms;
  report.counts=r.room?.counts||r.counts||{};
  report.model_hashes=(r.model_assets||[]).map(a=>a.sha256).filter(x=>/^[a-f0-9]{64}$/.test(x));
  if(/^[a-f0-9]{64}$/.test(r.source_sha256||""))report.input_sha256=r.source_sha256;
  return report;
}
function renderTakeChoices() {
  for(const id of ["take-a","take-b"]) {const prior=$(id).value;$(id).replaceChildren(new Option("Choose a take",""));takes.forEach((t,i)=>$(id).add(new Option(`${i+1} · ${t.job.request.kind} · ${t.job.status}`,t.id)));if(takes.some(t=>t.id===prior))$(id).value=prior;}
  if(!$("take-b").value&&takes.length)$("take-b").value=takes.at(-1).id;
  if(!$("take-a").value&&takes.length>1)$("take-a").value=takes.at(-2).id;
  renderComparison();
}
function conditionKey(take) { const j=take.job,r=j.result||{};return JSON.stringify({kind:j.request.kind,source:r.source_sha256||j.request.source||null,input:j.request.input_id,output:j.request.output_id,echo:j.request.echo_owner,position:j.request.position,recognizer:j.request.effective_settings?.recognizer,backend:j.request.effective_settings?.backend,model:r.speaker_model_hash,assets:r.model_assets}); }
function renderComparison() {
  const a=takes.find(t=>t.id===$("take-a").value),b=takes.find(t=>t.id===$("take-b").value);
  $("comparison").replaceChildren();$("export-results").disabled=!b;
  if(!b){$("comparison").append(node("p","Complete a take to compare actual results."));return;}
  if(a)$("comparison").append(node("p",conditionKey(a)===conditionKey(b)?(b.job.request.kind.includes("replay")?"Matching input fingerprint and recorded conditions.":"Matching recorded conditions; live retakes still contain different audio."):"Different test/device/model conditions. Treat this comparison as exploratory.","notice"));
  const reports=[a?numericReport(a.job):null,numericReport(b.job)];
  const table=node("table"),head=node("tr");["Metric / setting","Take A","Take B"].forEach(v=>head.append(node("th",v)));table.append(head);
  const flat=v=>{const out={};function visit(obj,prefix){for(const [key,value]of Object.entries(obj||{})){if(value&&typeof value==="object"&&!Array.isArray(value))visit(value,`${prefix}${key}.`);else out[`${prefix}${key}`]=value;}}visit(v?.metrics,"metric.");visit(v?.frame_processing_ms,"frame_processing_ms.");visit(v?.counts,"manager.");visit(v?.settings,"settings.");return out;};
  const af=flat(reports[0]),bf=flat(reports[1]);for(const key of new Set([...Object.keys(af),...Object.keys(bf)])){const row=node("tr");[key,af[key]??"—",bf[key]??"—"].forEach(v=>row.append(node("td",Array.isArray(v)?JSON.stringify(v):String(v))));table.append(row);}
  const wrapper=node("div",undefined,"table-wrap");wrapper.append(table);$("comparison").append(wrapper);
  for(const key of Object.keys(tallyNames))$("tally-"+key).value=b.observations[key]??0;
  validateTallyPairs();
}
$("take-a").onchange=renderComparison;$("take-b").onchange=renderComparison;
Object.entries(tallyNames).forEach(([key,label])=>{const field=node("label",label),input=node("input");input.type="number";input.min="0";input.max="10000";input.step="1";input.value="0";input.id="tally-"+key;field.append(input);$("tally-fields").append(field);});
function validateTallyPairs() {
  for(const [result,total] of [["interruption_detected","interruption_attempts"],["quiet_false_stops","quiet_trials"],["continuation_correct","continuation_attempts"]]) {
    $("tally-"+result).setCustomValidity(Number($("tally-"+result).value)>Number($("tally-"+total).value)?"A result count cannot exceed its attempts / trials.":"");
  }
}
$("tally-fields").addEventListener("input",validateTallyPairs);
$("save-tally").onclick=()=>{const b=takes.find(t=>t.id===$("take-b").value);if(!b){$("tally-result").textContent="Choose an actual take first.";return;}const values={};for(const key of Object.keys(tallyNames)){const el=$("tally-"+key);if(!el.checkValidity()){el.reportValidity();return;}values[key]=Number(el.value);}if(values.interruption_detected>values.interruption_attempts||values.quiet_false_stops>values.quiet_trials){$("tally-result").textContent="Detected / false-stop counts cannot exceed their attempts / trials.";return;}b.observations=values;const known=values.known_correct+values.known_wrong+values.known_unknown,guest=values.guest_rejected+values.guest_accepted,assigned=values.known_correct+values.known_wrong+values.guest_accepted;$("tally-result").textContent=`User observations attached. Known recall ${known?(100*values.known_correct/known).toFixed(1)+"% (n="+known+")":"unmeasured"}; guest rejection ${guest?(100*values.guest_rejected/guest).toFixed(1)+"% (n="+guest+")":"unmeasured"}; assignment precision ${assigned?(100*values.known_correct/assigned).toFixed(1)+"% (n="+assigned+")":"unmeasured"}.`;};
$("export-results").onclick=()=>{const b=takes.find(t=>t.id===$("take-b").value);if(!b)return;const url=URL.createObjectURL(new Blob([JSON.stringify(numericReport(b.job),null,2)],{type:"application/json"}));const link=node("a");link.href=url;link.download="family-harness-numeric-diagnostics.json";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};

const repairs=[
  ["Nothing is heard / device missing","Reconnect, check hardware mute and Windows desktop microphone permission, refresh devices and select again.","devices"],
  ["Quiet or clipped speech","Compare raw/processed levels nearby and far. Check placement and Windows input volume; digital gain cannot restore removed speech.","acoustics"],
  ["Echo or false interruption","Lower speaker volume, separate devices, confirm exactly one echo owner and retest duplex / quiet playback.","acoustics"],
  ["Missing words / early endings","Check the English profile, compare completion silence and installed final recognizers. Retest with fresh phrases.","timing"],
  ["Wrong name / too many unknown voices","Review enrollment and microphone placement. Compare recognition presets using all known and guest attempts.","people"],
  ["Models missing / corrupt","Explicitly repair/download or import pinned originals. A missing model never switches to cloud inference.","models"],
  ["Lag, gaps or overload","Choose a lighter installed final, close busy apps or shorten the take. Incomplete audio is discarded; start a new take explicitly.","timing"]];
repairs.forEach(([title,detail,step])=>{const item=node("div",undefined,"repair-item");item.append(node("h3",title),node("p",detail));const button=node("button","Open repair step");button.onclick=()=>navigate(`setup/${step}`);item.append(button);$("repair-list").append(item);});
function applyAppearance(){document.documentElement.dataset.appearance=$("appearance").value;document.documentElement.dir=$("layout-direction").value==="auto"?"ltr":$("layout-direction").value;try{localStorage.setItem("fh-appearance",$("appearance").value);localStorage.setItem("fh-direction",$("layout-direction").value);}catch(_){}}
$("appearance").onchange=applyAppearance;$("layout-direction").onchange=applyAppearance;
try{lastSetup=localStorage.getItem("fh-setup-step")||"room";$("appearance").value=localStorage.getItem("fh-appearance")||"system";$("layout-direction").value=localStorage.getItem("fh-direction")||"auto";}catch(_){}
applyAppearance();navigate(location.hash.slice(1)||"home",false);
$("recognition-slot").append($("recognition-controls"));
document.addEventListener("dashboard-ready", event=>{
  const state=event.detail;dashboardState=state.dashboard;latestState=state;appliedSettings=copy(dashboardState.settings);
  for(const name of Object.keys(dashboardState.presets))$("speech-preset").add(new Option(name,name));
  for(const name of dashboardState.speaker_backends)$("speaker-backend").add(new Option(name,name));
  fillSettings(appliedSettings);renderProfileChoices();renderReadiness();
  updateDeviceContext();
  $("draft-status").textContent=`Saved revision ${dashboardState.revision} loaded. Apply a draft to the next take.`;
  $("storage-location").textContent=`Room configuration: ${state.config_path}. Tuning settings are saved beside it; model and voice profile locations appear in their diagnostics.`;
  if(state.job?.status==="running") {observedId=state.job.id;setBusy(true);observeJob(state.job);const observe=async()=>{if(!observedId)return;try{const j=await api(`/api/job?id=${encodeURIComponent(observedId)}`);if(j.status==="running")setTimeout(observe,250);else{observedId=null;setBusy(false);}}catch(error){observedId=null;setBusy(false);showError(error);}};observe();}
});
