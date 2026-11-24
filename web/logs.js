(() => {
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
const isLive = () => run.source === "live" || run.source.startsWith("live:");

// ---- run log ---------------------------------------------------------------------------------
function row(e) {
  const dev = e.dev ? `<span class="badge you" title="device">${esc(e.dev)}</span>` : "";    // only in the "all devices" view
  const t = `<span class="t">${fmt(e.t || 0)}</span>`;
  if (e.type === "transcript" && e.role === "examiner") {
    const [label, cls] = ORIGIN[e.origin || "script"] || [e.origin, "sc"];
    return `<div class="msg ex"><div class="meta">${t}<b>Examiner</b><span class="badge ${cls}">${esc(label)}</span>${dev}</div>` +
           `<div class="bub">${esc(e.text)}${e.why ? `<span class="why">why: ${esc(e.why)}</span>` : ""}</div></div>`;
  }
  if (e.type === "transcript") return `<div class="msg cand"><div class="meta">${t}<b>Candidate</b>${dev}</div><div class="bub">${esc(e.text)}</div></div>`;
  if (e.type === "ignored") return $("rl-noise").checked
    ? `<div class="msg note-row"><span class="t">${fmt(e.t || 0)}</span><span class="badge sc">ignored ${esc(e.why || "")}</span><span class="muted">${esc(e.text)}</span></div>` : "";
  if (e.type === "latency") return $("rl-lat").checked
    ? `<div class="msg note-row"><span class="t">${fmt(e.t || 0)}</span><span class="chip${e.seconds > 6 ? " slow" : ""}">reply delay ${e.seconds.toFixed(2)} s</span></div>` : "";
  if (e.type === "note") return `<div class="msg note-row"><span class="t">${fmt(e.t || 0)}</span><span class="badge fb">control</span><span>${esc(e.text)}</span></div>`;
  if (e.type === "phase") return `<div class="divider"><span>${esc(PHASES[e.phase] || e.phase)}</span><i>${fmt(e.t || 0)}</i></div>`;
  if (e.type === "done") return `<div class="divider end"><span>Test finished</span><i>${fmt(e.t || 0)}</i></div>`;
  return "";
}

function summaryHtml(events) {
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
  return `<span class="stat"><b>${ai}</b> LLM questions</span><span class="stat"><b>${noise}</b> ignored noise</span>` +
    `<span class="stat"><b>${notes}</b> control events</span><span class="stat"><b>${avg}</b> s avg reply (${lat.length} turns)</span>` +
    `<span class="stat src">${parts || "no examiner lines yet"}</span>`;
}

function summary(events) { $("runlog-sum").innerHTML = summaryHtml(events); }

function render() {
  if (run.source === "split") return renderSplit();
  const events = isLive() ? run.live.events || [] : run.events;
  summary(events);
  const box = $("runlog");
  const atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
  box.innerHTML = events.map(row).join("");
  $("rl-count").textContent = events.length + " events";
  if (isLive() ? $("rl-follow").checked && atEnd || box.scrollTop === 0 : false) box.scrollTop = box.scrollHeight;
}

// ---- split view: every connected device in its own panel -------------------------------------------
const cards = {};     // session id -> { device, phase, active, events, gone, el }
function cardFor(id) {
  if (cards[id]) return cards[id];
  const el = document.createElement("div");
  el.className = "card";
  el.innerHTML = '<div class="card-head"><b class="dev"></b><span class="ph muted"></span></div>' +
                 '<div class="sum"></div><div class="rows"></div>';
  $("split").appendChild(el);
  cards[id] = { el, events: [], device: "", phase: "", active: true, gone: false };
  return cards[id];
}

function renderSplit() {
  const ids = Object.keys(cards);
  $("rl-count").textContent = ids.length + (ids.length === 1 ? " device" : " devices");
  $("split-empty").hidden = ids.length > 0;
  ids.forEach((id) => {
    const c = cards[id], box = c.el.querySelector(".rows");
    const atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
    c.el.querySelector(".dev").textContent = c.device || "device " + id.slice(0, 4);
    c.el.querySelector(".ph").textContent = c.gone ? "disconnected (saved in the Tests list)" : (PHASES[c.phase] || c.phase || "");
    c.el.classList.toggle("gone", c.gone);
    c.el.querySelector(".sum").innerHTML = summaryHtml(c.events);
    box.innerHTML = c.events.map(row).join("");
    if ($("rl-follow").checked && (atEnd || box.scrollTop === 0)) box.scrollTop = box.scrollHeight;
  });
}

async function pollSplit() {
  try {
    const list = (await (await fetch("/api/live")).json()).sessions || [];
    const seen = new Set(list.map((v) => v.id));
    Object.keys(cards).forEach((id) => { if (!seen.has(id)) cards[id].gone = true; });
    await Promise.all(list.map(async (v) => {
      const d = await (await fetch("/api/live?id=" + encodeURIComponent(v.id))).json();
      const c = cardFor(v.id);
      Object.assign(c, { device: d.device || v.device, phase: d.phase, active: d.active, events: d.events || [], gone: false });
    }));
    const n = list.filter((v) => v.active).length;
    const pill = $("live-pill");
    pill.textContent = n ? n + (n === 1 ? " test running" : " tests running") + " / " + list.length + " connected" : list.length ? list.length + " connected, not started" : "no device connected";
    pill.className = "pill " + (n ? "on" : "off");
    render();
  } catch (_) { $("live-pill").textContent = "server not reachable"; }
}

async function pollLive() {
  if (run.source === "split") return pollSplit();
  if (!isLive()) return;
  try {
    const id = run.source.slice(5);                 // "live" = the newest test, "live:ID" = one device's test
    const d = await (await fetch("/api/live" + (id ? "?id=" + encodeURIComponent(id) : ""))).json();
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
    let live = [];
    try { live = (await (await fetch("/api/live")).json()).sessions || []; } catch (_) { /* optional */ }
    sel.innerHTML = '<option value="live">Live: newest test</option><option value="split">Live: each device in its own panel</option>' + (live.length > 1 ? '<option value="live:all">Live: ALL devices in one timeline</option>' : "") +
      live.map((v) => `<option value="live:${v.id}">Live: ${v.device || "device " + v.id.slice(0, 4)} (${PHASES[v.phase] || v.phase})</option>`).join("") +
      list.map((r) => {
      const n = r.name;
      const label = n.slice(4, 8) + "-" + n.slice(8, 10) + "-" + n.slice(10, 12) + " " + n.slice(13, 15) + ":" + n.slice(15, 17) + ":" + n.slice(17, 19);
      return `<option value="${n}">${label}${r.device ? " " + esc(r.device) : ""} (${r.kb} KB)</option>`;
    }).join("");
    if ([...sel.options].some((o) => o.value === keep)) sel.value = keep;
    if (!run.userPicked && live.length >= 1 && sel.value !== "split") { sel.value = "split"; pick(); }   // as soon as a device is connected: show every device in its own panel
  } catch (_) { /* the list is a convenience */ }
}

async function pick() {
  run.source = $("runs").value;
  const split = run.source === "split";
  $("split").hidden = !split;
  $("runlog").hidden = $("runlog-sum").hidden = split;
  if (split) { render(); return pollSplit(); }
  if (!isLive()) {
    try { run.events = (await (await fetch("/api/runs/" + run.source)).json()).events || []; }
    catch (err) { run.events = []; $("runlog-sum").textContent = "Could not load that run: " + err; return; }
  }
  render();
  if (!isLive()) $("runlog").scrollTop = 0;
}

$("runs").onchange = () => { run.userPicked = true; pick(); };
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
setInterval(loadList, 6000);
setInterval(loadServerLog, 2500);

// the Tests view opens a saved run here
window.openRun = (name) => { run.userPicked = true; loadList().then(() => { $("runs").value = name; pick(); }); };
})();
