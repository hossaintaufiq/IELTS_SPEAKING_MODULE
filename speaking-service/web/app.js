const $ = (id) => document.getElementById(id);
const PHASES = {
  intro: "Introduction", part1: "Part 1: Interview", part2_prep: "Part 2: Preparation",
  part2_speak: "Part 2: Your talk", part2_followup: "Part 2: Follow-up", part3: "Part 3: Discussion", done: "Finished",
};
const state = { ws: null, ctx: null, mic: null, playhead: 0, sources: [], lat: [], log: [], phase: null, speakingUntil: 0 };

function addMsg(role, text, label) {
  const d = document.createElement("div");
  d.className = "msg " + role;
  d.innerHTML = role === "sys" ? "" : `<small>${label}</small>`;
  d.appendChild(document.createTextNode(text));
  $("log").appendChild(d);
  $("log").scrollTop = $("log").scrollHeight;
}
const fmt = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function setOrb(mode, label) { $("orb").className = "orb " + mode; $("orb-label").textContent = label; }

// ---- playback: queue PCM16 24 kHz chunks gaplessly ------------------------------------------
function playPcm(buf) {
  const pcm = new Int16Array(buf);
  const f32 = Float32Array.from(pcm, (v) => v / 32768);
  const ab = state.ctx.createBuffer(1, f32.length, 24000);
  ab.copyToChannel(f32, 0);
  const src = state.ctx.createBufferSource();
  src.buffer = ab; src.connect(state.ctx.destination);
  const t = Math.max(state.ctx.currentTime + 0.03, state.playhead);
  src.start(t);
  state.playhead = t + ab.duration;
  state.sources.push(src);
  src.onended = () => { state.sources = state.sources.filter((s) => s !== src); };
  setOrb("speaking", "Examiner speaking");
  state.speakingUntil = state.playhead;
}
function stopPlayback() {
  state.sources.forEach((s) => { try { s.stop(); } catch (_) {} });
  state.sources = []; state.playhead = 0;
}
setInterval(() => {
  if (!state.ctx || !state.ws) return;
  if (state.ctx.currentTime >= state.speakingUntil && $("orb").classList.contains("speaking")) {
    setOrb(state.muted ? "muted" : "listening", state.muted ? "Mic paused" : "Your turn - speak");
  }
}, 200);

// ---- events from the server -----------------------------------------------------------------
function onEvent(e) {
  state.log.push(e);
  if (e.type === "transcript") {
    addMsg(e.role === "user" ? "user" : "examiner", e.text, e.role === "user" ? "You" : "Examiner");
  } else if (e.type === "phase") {
    state.phase = e.phase;
    $("phase").textContent = PHASES[e.phase] || e.phase;
    $("next").disabled = e.phase === "done";
    state.muted = e.phase === "part2_prep" || e.phase === "done";
    if (e.cue_card) showCard(e.cue_card, e.phase); else $("card").classList.add("hidden");
    addMsg("sys", "-- " + (PHASES[e.phase] || e.phase) + " --");
    if (e.phase === "done") finishUi();
  } else if (e.type === "timer") {
    if (e.limit) {
      $("timer").textContent = fmt(Math.max(0, e.limit - e.elapsed));
      $("timer").classList.toggle("low", e.limit - e.elapsed < 15);
      $("bar-fill").style.width = Math.min(100, (e.elapsed / e.limit) * 100) + "%";
    } else { $("timer").textContent = fmt(e.elapsed); $("bar-fill").style.width = "0"; }
  } else if (e.type === "latency") {
    state.lat.push(e.seconds);
    const avg = state.lat.reduce((a, b) => a + b, 0) / state.lat.length;
    $("lat-last").textContent = e.seconds.toFixed(2);
    $("lat-avg").textContent = avg.toFixed(2);
    $("lat-max").textContent = Math.max(...state.lat).toFixed(2);
    $("lat-n").textContent = state.lat.length;
  } else if (e.type === "interrupt") {
    stopPlayback();
  } else if (e.type === "done") {
    finishUi();
  }
}
function showCard(c, phase) {
  $("card").classList.remove("hidden");
  $("card-prompt").textContent = c.prompt;
  const ul = $("card-bullets"); ul.innerHTML = "";
  c.bullets.forEach((b) => { const li = document.createElement("li"); li.textContent = b; ul.appendChild(li); });
  $("card-note").textContent = phase === "part2_prep"
    ? "Preparation time: make notes. The mic is paused."
    : "Speak for one to two minutes. The examiner will not reply until you finish. Press Next part when done.";
}

// ---- connect / mic --------------------------------------------------------------------------
async function start() {
  $("start").disabled = true;
  try {
    state.ctx = new AudioContext();
    await state.ctx.resume();
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    await state.ctx.audioWorklet.addModule("/static/worklet.js");
    const src = state.ctx.createMediaStreamSource(stream);
    state.mic = new AudioWorkletNode(state.ctx, "mic-processor");
    src.connect(state.mic);
    state.stream = stream;

    const proto = location.protocol === "https:" ? "wss" : "ws";
    state.ws = new WebSocket(`${proto}://${location.host}/ws`);
    state.ws.binaryType = "arraybuffer";
    state.ws.onopen = () => {
      $("conn").textContent = "Connected"; $("conn").className = "pill on";
      state.mic.port.onmessage = (m) => { if (state.ws.readyState === 1 && !state.muted) state.ws.send(m.data); };
      state.ws.send(JSON.stringify({ action: "start" }));
      $("next").disabled = false; $("end").disabled = false;
      setOrb("listening", "Your turn - speak");
    };
    state.ws.onmessage = (m) => (typeof m.data === "string" ? onEvent(JSON.parse(m.data)) : playPcm(m.data));
    state.ws.onclose = () => { $("conn").textContent = "Disconnected"; $("conn").className = "pill off"; finishUi(); };
    state.ws.onerror = () => addMsg("sys", "Connection error. Is the server running?");
  } catch (err) {
    addMsg("sys", "Could not start: " + (err.message || err));
    $("start").disabled = false;
  }
}
function finishUi() {
  $("next").disabled = true; $("end").disabled = true; $("dl").disabled = false;
  setOrb("idle", "Test finished");
  state.stream?.getTracks().forEach((t) => t.stop());
}
$("start").onclick = start;
$("next").onclick = () => state.ws?.send(JSON.stringify({ action: "next_part" }));
$("end").onclick = () => { state.ws?.send(JSON.stringify({ action: "end" })); };
$("dl").onclick = () => {
  const blob = new Blob([JSON.stringify({ latencies_s: state.lat, events: state.log }, null, 2)], { type: "application/json" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "speaking-test.json"; a.click();
};
