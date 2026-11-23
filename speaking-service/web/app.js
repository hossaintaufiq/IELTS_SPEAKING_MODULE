const $ = (id) => document.getElementById(id);
const PHASES = {
  intro: "Introduction", name: "Introduction", part1: "Part 1: Interview", part2_intro: "Part 2: Introduction", part2_prep: "Part 2: Preparation",
  part2_speak: "Part 2: Your talk", part2_followup: "Part 2: Follow-up", part3: "Part 3: Discussion", done: "Finished",
};
let LEAD = 0.35;                       // seconds of audio buffered before playback; raise if you still hear clicks
window.setLead = (x) => { LEAD = x; };
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
  // Jitter buffer. Chunks arrive over a ~200 ms, bursty network path; scheduling them with only a few
  // ms of lead leaves gaps (clicks). Keep LEAD seconds of audio queued, and rebuild that cushion whenever
  // playback has run dry (a new sentence, or a late chunk = an "underrun").
  const now = state.ctx.currentTime;
  let t = state.playhead;
  if (t < now + 0.02) {
    if (state.playhead > 0 && state.sources.length) state.underruns = (state.underruns || 0) + 1;   // ran dry mid-speech
    t = now + LEAD;
  }
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
function showInterim(text) {
  let d = $("interim");
  if (!d) {
    d = document.createElement("div");
    d.id = "interim"; d.className = "msg user interim";
    d.innerHTML = "<small>You (live...)</small><span></span>";
    $("log").appendChild(d);
  }
  d.lastChild.textContent = text;
  $("log").scrollTop = $("log").scrollHeight;
}
function clearInterim() { $("interim")?.remove(); }

function onEvent(e) {
  if (e.type !== "interim") state.log.push(e);
  if (e.type === "interim") {
    showInterim(e.text);
  } else if (e.type === "transcript") {
    if (e.role === "user") clearInterim();
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
    state.srvChunks = e.mic_chunks; state.srvRms = e.mic_rms;
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
  c.bullets.concat(c.closing ? [c.closing] : []).forEach((b) => { const li = document.createElement("li"); li.textContent = b; ul.appendChild(li); });
  $("card-note").textContent = phase === "part2_prep"
    ? "Preparation time: make notes. The mic is paused."
    : "Speak for one to two minutes. The examiner will not reply until you finish. Press Next part when done.";
}

// ---- mic level meter (client side: proves the browser is capturing sound) ---------------------
function updateMeter(buf) {
  const a = new Int16Array(buf); let sum = 0;
  for (let i = 0; i < a.length; i++) sum += a[i] * a[i];
  const rms = Math.sqrt(sum / a.length) / 32768;
  state.level = Math.max(rms, (state.level || 0) * 0.85);
  $("meter-fill").style.width = Math.min(100, Math.sqrt(state.level) * 160) + "%";
}
setInterval(() => {
  if (!state.ws) return;
  $("mic-status").textContent = state.muted ? "Mic paused" :
    `Browser sent ${state.sent || 0} chunks - server heard ${state.srvChunks ?? 0} (level ${(state.srvRms ?? 0).toFixed(3)}) | audio gaps: ${state.underruns || 0}`;
}, 500);

// ---- connect / mic --------------------------------------------------------------------------
async function start() {
  $("start").disabled = true;
  stopMicTest();
  try {
    state.ctx = new AudioContext();
    await state.ctx.resume();
    // Echo cancellation + noise suppression on: the examiner's voice must not feed back into the mic.
    const deviceId = $("mic-select").value;
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true,
               ...(deviceId ? { deviceId: { exact: deviceId } } : {}) },
    });
    const track = stream.getAudioTracks()[0];
    addMsg("sys", "Microphone: " + (track.label || "default") + (track.muted ? " (MUTED by the system)" : ""));
    await state.ctx.audioWorklet.addModule("/static/worklet.js");
    const src = state.ctx.createMediaStreamSource(stream);
    state.mic = new AudioWorkletNode(state.ctx, "mic-processor");
    src.connect(state.mic);
    // Chrome may not run a worklet that has no path to the destination. Route it through a silent gain.
    const mute = state.ctx.createGain(); mute.gain.value = 0;
    state.mic.connect(mute); mute.connect(state.ctx.destination);
    state.stream = stream;

    const proto = location.protocol === "https:" ? "wss" : "ws";
    const device = new URLSearchParams(location.search).get("device");      // open the page with ?device=Laptop to label this device in the logs
    state.ws = new WebSocket(`${proto}://${location.host}/ws` + (device ? "?device=" + encodeURIComponent(device) : ""));
    state.ws.binaryType = "arraybuffer";
    state.ws.onopen = () => {
      $("conn").textContent = "Connected"; $("conn").className = "pill on";
      state.mic.port.onmessage = (m) => {
        updateMeter(m.data);
        if (state.ws.readyState === 1 && !state.muted) { state.ws.send(m.data); state.sent = (state.sent || 0) + 1; }
      };
      state.ws.send(JSON.stringify({ action: "start" }));
      $("next").disabled = false; $("end").disabled = false;
      setOrb("listening", "Your turn - speak");
    };
    state.ws.onmessage = (m) => (typeof m.data === "string" ? onEvent(JSON.parse(m.data)) : playPcm(m.data));
    state.ws.onclose = (e) => {
      $("conn").textContent = "Disconnected"; $("conn").className = "pill off";
      if (state.phase !== "done") addMsg("sys", "Connection lost (code " + e.code + (e.reason ? ", " + e.reason : "") + "). " +
        "If this repeats, the network path to the GPU server is dropping. Reload the page to start again.");
      finishUi();
    };
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


// ---- microphone check (runs before the test) -------------------------------------------------
const mic = { stream: null, ctx: null, analyser: null, raf: 0, okSince: 0, passed: false, wasSilentSince: 0 };

async function listMics() {
  try {
    const tmp = await navigator.mediaDevices.getUserMedia({ audio: true });   // permission, so names are visible
    tmp.getTracks().forEach((t) => t.stop());
    const devs = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "audioinput");
    const sel = $("mic-select"); sel.innerHTML = "";
    devs.forEach((d, i) => {
      const o = document.createElement("option");
      o.value = d.deviceId; o.textContent = d.label || ("Microphone " + (i + 1));
      sel.appendChild(o);
    });
    await startMicTest();
  } catch (err) {
    verdict("bad", "Microphone blocked or missing: " + (err.message || err) + ". Click the lock icon in the address bar and allow the microphone.");
  }
}
function verdict(kind, text) { const v = $("mic-verdict"); v.className = "mic-verdict " + kind; v.textContent = text; }

async function startMicTest() {
  stopMicTest();
  mic.passed = false; mic.okSince = 0; mic.wasSilentSince = 0; $("start").disabled = true;
  const deviceId = $("mic-select").value;
  mic.stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true,
             ...(deviceId ? { deviceId: { exact: deviceId } } : {}) },
  });
  const track = mic.stream.getAudioTracks()[0];
  const st = track.getSettings ? track.getSettings() : {};
  $("mic-track").textContent = `Opened: ${track.label || "default"} | ${st.sampleRate || "?"} Hz | ` +
    `state ${track.readyState}${track.muted ? " | MUTED by the system" : ""}${track.enabled ? "" : " | disabled"}`;
  mic.ctx = new AudioContext();
  await mic.ctx.resume();
  const src = mic.ctx.createMediaStreamSource(mic.stream);
  mic.analyser = mic.ctx.createAnalyser();
  mic.analyser.fftSize = 2048; mic.analyser.smoothingTimeConstant = 0.6;
  src.connect(mic.analyser);
  verdict("", 'Say "testing, one two three". The bars should move.');
  drawSpectrum();
}
function stopMicTest() {
  cancelAnimationFrame(mic.raf);
  mic.stream?.getTracks().forEach((t) => t.stop());
  mic.ctx?.close().catch(() => {});
  mic.stream = mic.ctx = mic.analyser = null;
}
function drawSpectrum() {
  const an = mic.analyser; if (!an) return;
  const cv = $("spectrum"), g = cv.getContext("2d");
  const bins = new Uint8Array(an.frequencyBinCount), wave = new Float32Array(an.fftSize);
  an.getByteFrequencyData(bins); an.getFloatTimeDomainData(wave);
  let sum = 0, peak = 0;
  for (const v of wave) { sum += v * v; peak = Math.max(peak, Math.abs(v)); }
  const rms = Math.sqrt(sum / wave.length);
  const hzPerBin = mic.ctx.sampleRate / an.fftSize, maxBin = Math.min(bins.length, Math.floor(8000 / hzPerBin));
  g.clearRect(0, 0, cv.width, cv.height);
  let best = 0, bestV = 0, weighted = 0, total = 0;
  const w = cv.width / maxBin;
  for (let i = 1; i < maxBin; i++) {
    const h = (bins[i] / 255) * cv.height;
    g.fillStyle = "#4cc2a6"; g.fillRect(i * w, cv.height - h, Math.max(1, w - 0.5), h);
    if (bins[i] > bestV) { bestV = bins[i]; best = i; }
    weighted += bins[i] * i * hzPerBin; total += bins[i];
  }
  g.fillStyle = "#8a97a6"; g.font = "10px sans-serif";
  [1000, 2000, 4000, 6000, 8000].forEach((hz) => g.fillText(hz / 1000 + "k", (hz / hzPerBin) * w - 8, 10));
  $("mic-level").textContent = "level " + rms.toFixed(3) + " (peak " + peak.toFixed(2) + ")";
  $("mic-freq").textContent = total > 0 ? "centre " + Math.round(weighted / total) + " Hz" : "- Hz";
  $("mic-peakfreq").textContent = bestV > 30 ? "peak " + Math.round(best * hzPerBin) + " Hz" : "peak - Hz";
  $("meter-fill").style.width = Math.min(100, Math.sqrt(rms) * 160) + "%";

  const now = performance.now();
  if (rms > 0.01 && bestV > 60) {                         // real sound with a spectrum, not electrical hiss
    mic.okSince ||= now;
    mic.wasSilentSince = 0;
    if (!mic.passed && now - mic.okSince > 400) {
      mic.passed = true; $("start").disabled = false;
      verdict("ok", "Microphone works. Voice detected around " + Math.round(weighted / total) + " Hz. You can start the test.");
    }
  } else {
    mic.okSince = 0;
    mic.wasSilentSince ||= now;
    if (!mic.passed && now - mic.wasSilentSince > 4000)
      verdict("bad", peak === 0
        ? "Total silence (all zeros). The browser opened this device but gets no signal: pick another microphone, check it is not muted, and that no other app (Zoom, Teams) is using it."
        : "Very quiet signal. Speak closer to the mic, raise the input volume in Windows Sound settings, or pick another microphone.");
  }
  mic.raf = requestAnimationFrame(drawSpectrum);
}
$("mic-select").onchange = () => startMicTest().catch((e) => verdict("bad", "Could not open that microphone: " + (e.message || e)));
$("skip-check").onclick = (e) => { e.preventDefault(); $("start").disabled = false; };
listMics();

let quietFor = 0;
setInterval(() => {
  if (!state.ws || state.muted) { quietFor = 0; return; }
  quietFor = (state.level || 0) < 0.002 ? quietFor + 1 : 0;
  $("mic-warn").classList.toggle("hidden", quietFor < 6);   // about 3 seconds of near-silence
}, 500);
