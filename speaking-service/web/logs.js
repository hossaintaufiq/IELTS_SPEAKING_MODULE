// Logs window: the run log (live or a saved run) and the server logs, side by side. Reads only; it never touches the test.
const $ = (id) => document.getElementById(id);
const PHASES = {
  intro: "Introduction", name: "Introduction", part1: "Part 1: Interview", part2_intro: "Part 2: Introduction", part2_prep: "Part 2: Preparation",
  part2_speak: "Part 2: Your talk", part2_followup: "Part 2: Follow-up", part3: "Part 3: Discussion", done: "Finished",
};
const ORIGIN = {   // where an examiner line came from -> [label, badge colour]
  "bank": ["bank", "bank"], "ai:bank": ["LLM picked bank", "bank"], "ai:reworded": ["LLM reworded", "ai"], "ai:new": ["LLM wrote", "ai"],
  "ai:repeat": ["repeat", "sc"], "ai:redirect": ["off-test reminder", "sc"], "script:fallback": ["fallback (bank)", "fb"],
  "ai:probe": ["follow-up", "ai"], "script:probe": ["follow-up (safe)", "fb"],
  "script": ["script", "sc"], "repeat": ["repeat", "sc"], "rephrase": ["rephrased", "ai"],
};
const fmt = (s) => String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(Math.floor(s % 60)).padStart(2, "0");
const esc = (x) => String(x).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const run = { source: "live", events: [], live: { active: false, started: false } };

// ---- run log ---------------------------------------------------------------------------------
function row(e) {
  const t = `<span class="t">${fmt(e.t || 0)}</span>`;
  if (e.type === "transcript" && e.role === "examiner") {
    const [label, cls] = ORIGIN[e.origin || "script"] || [e.origin, "sc"];
    return `<div class="rl">${t}<span class="badge ${cls}">${esc(label)}</span><span>${esc(e.text)}` +
           `${e.why ? `<span class="why">why: ${esc(e.why)}</span>` : ""}</span></div>`;
  }
  if (e.type === "transcript") return `<div class="rl">${t}<span class="badge you">candidate</span><span>${esc(e.text)}</span></div>`;
  if (e.type === "ignored") return $("rl-noise").checked
    ? `<div class="rl noise">${t}<span class="badge sc">ignored ${esc(e.why || "")}</span><span>${esc(e.text)}</span></div>` : "";
  if (e.type === "latency") return $("rl-lat").checked ? `<div class="rl lat">${t}<span>reply delay</span><span>${e.seconds.toFixed(2)} s</span></div>` : "";
  if (e.type === "note") return `<div class="rl phase">${t}<span class="badge fb">control</span><span>${esc(e.text)}</span></div>`;
  if (e.type === "phase") return `<div class="rl phase">${t}<span>phase</span><span>${esc(PHASES[e.phase] || e.phase)}</span></div>`;
  if (e.type === "done") return `<div class="rl phase">${t}<span>done</span><span>test finished</span></div>`;
  return "";
}

function summary(events) {
  const c = {}; let noise = 0, notes = 0; const lat = [];
  events.forEach((e) => {
    if (e.type === "transcript" && e.role === "examiner") { const k = (ORIGIN[e.origin || "script"] || [e.origin])[0]; c[k] = (c[k] || 0) + 1; }
    else if (e.type === "ignored") noise++;
    else if (e.type === "latency") lat.push(e.seconds);
    else if (e.type === "note") notes++;
  });
  const parts = Object.entries(c).map(([k, n]) => `${esc(k)} <b>${n}</b>`).join(" &middot; ");
  const avg = lat.length ? (lat.reduce((a, b) => a + b, 0) / lat.length).toFixed(2) : "-";
  const ai = (c["LLM wrote"] || 0) + (c["LLM reworded"] || 0) + (c["LLM picked bank"] || 0);
  $("runlog-sum").innerHTML = `Examiner lines: ${parts || "none yet"}<br>` +
    `LLM involved in <b>${ai}</b> questions &middot; ignored noise <b>${noise}</b> &middot; control events <b>${notes}</b> &middot; ` +
    `reply delay avg <b>${avg}</b> s over ${lat.length} turns`;
}

function render() {
  const events = run.source === "live" ? run.live.events || [] : run.events;
  summary(events);
  const box = $("runlog");
  const atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
  box.innerHTML = events.map(row).join("");
  $("rl-count").textContent = events.length + " events";
  if (run.source === "live" ? $("rl-follow").checked && atEnd || box.scrollTop === 0 : false) box.scrollTop = box.scrollHeight;
}

async function pollLive() {
  if (run.source !== "live") return;
  try {
    const d = await (await fetch("/api/live")).json();
    const grew = (d.events || []).length !== (run.live.events || []).length;
    run.live = d;
    const pill = $("live-pill");
    pill.textContent = d.active ? "test running: " + (PHASES[d.phase] || d.phase) : d.started ? "last test finished" : "no test yet";
    pill.className = "pill " + (d.active ? "on" : "off");
    if (grew) render();
  } catch (_) { $("live-pill").textContent = "server not reachable"; }
}

async function loadList() {
  try {
    const list = await (await fetch("/api/runs")).json();
    const sel = $("runs"), keep = sel.value;
    sel.innerHTML = '<option value="live">Live: this test</option>' + list.map((r) => {
      const n = r.name;
      const label = n.slice(4, 8) + "-" + n.slice(8, 10) + "-" + n.slice(10, 12) + " " + n.slice(13, 15) + ":" + n.slice(15, 17) + ":" + n.slice(17, 19);
      return `<option value="${n}">${label} (${r.kb} KB)</option>`;
    }).join("");
    if ([...sel.options].some((o) => o.value === keep)) sel.value = keep;
  } catch (_) { /* the list is a convenience */ }
}

async function pick() {
  run.source = $("runs").value;
  if (run.source !== "live") {
    try { run.events = (await (await fetch("/api/runs/" + run.source)).json()).events || []; }
    catch (err) { run.events = []; $("runlog-sum").textContent = "Could not load that run: " + err; return; }
  }
  render();
  if (run.source !== "live") $("runlog").scrollTop = 0;
}

$("runs").onchange = pick;
$("runs-refresh").onclick = loadList;
$("rl-noise").onchange = $("rl-lat").onchange = render;

// ---- server log ------------------------------------------------------------------------------
async function loadServerLog() {
  const params = new URLSearchParams({ lines: "500", q: $("sl-filter").value, hide_debug: $("sl-nodebug").checked });
  try {
    const r = await (await fetch("/api/serverlog/" + $("sl-name").value + "?" + params)).json();
    const view = $("sl-view");
    const atEnd = view.scrollTop + view.clientHeight >= view.scrollHeight - 40;
    $("sl-info").textContent = r.exists ? r.path + " - last " + r.lines.length + " lines" : r.path + " does not exist on this machine";
    view.textContent = r.lines.join("\n");
    if ($("sl-follow").checked && atEnd) view.scrollTop = view.scrollHeight;
  } catch (err) { $("sl-info").textContent = "Could not read the log: " + err; }
}
$("sl-refresh").onclick = loadServerLog;
$("sl-name").onchange = $("sl-nodebug").onchange = loadServerLog;
$("sl-filter").oninput = () => { clearTimeout(loadServerLog.t); loadServerLog.t = setTimeout(loadServerLog, 300); };

loadList().then(pollLive);
loadServerLog();
setInterval(pollLive, 1200);
setInterval(loadServerLog, 2500);
