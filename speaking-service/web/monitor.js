// Monitoring page: the service as a whole. Read only; it never touches a running test. Polls /api/monitor every few seconds.
const $ = (id) => document.getElementById(id);
const esc = (x) => String(x ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const PHASES = {
  intro: "Introduction", name: "Introduction", part1: "Part 1", part2_intro: "Part 2 intro", part2_prep: "Part 2 prep", part2_speak: "Part 2 talk",
  part2_followup: "Part 2 follow-up", part3: "Part 3", done: "Finished",
};
const REASONS = {
  completed: "finished normally", ended_by_candidate: "candidate ended it", off_topic: "too many off-test questions",
  no_response: "no answer at the end", skipped_to_end: "skipped to the end", aborted: "connection dropped", error: "service error",
};
const POLL_MS = 3000, LOG_MS = 6000;
let last = null, lastOk = 0;

const mmss = (s) => (s == null ? "-" : String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(Math.floor(s % 60)).padStart(2, "0"));
const clock = (epoch) => (epoch ? new Date(epoch * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "-");
const day = (epoch) => (epoch ? new Date(epoch * 1000).toLocaleDateString([], { month: "short", day: "numeric" }) : "");
const sec = (v) => (v == null ? "-" : v.toFixed(2) + " s");
const uptime = (s) => (s >= 86400 ? Math.floor(s / 86400) + "d " + Math.floor((s % 86400) / 3600) + "h" : s >= 3600 ? Math.floor(s / 3600) + "h " + Math.floor((s % 3600) / 60) + "m" : mmss(s));
const tag = (text, kind = "") => `<span class="tag ${kind}">${esc(text)}</span>`;

function banner(text, kind = "") {
  const b = $("m-banner");
  b.hidden = !text;
  b.className = "banner " + kind;
  b.textContent = text || "";
}

function pill(text, kind) {
  const p = $("m-status");
  p.textContent = text;
  p.className = "pill " + kind;
}

function render(d) {
  const s = d.server, lat = d.latency;
  // status pill + banner
  if (s.models_error) { pill("Models failed", "bad"); banner("The models did not load: " + s.models_error + ". New tests are refused until the service is restarted.", ""); }
  else if (!s.ready) { pill("Starting", "warn"); banner("The service is loading its models; new tests are refused until it is ready.", "warn"); }
  else if (s.running >= s.max_tests) { pill("Full", "warn"); banner("", ""); }
  else { pill(s.mock ? "Ready (mock)" : "Ready", "ok"); banner("", ""); }
  $("m-updated").textContent = "updated " + clock(d.now);

  // tiles
  $("t-running").textContent = s.running;
  $("t-cap").textContent = "of " + s.max_tests + " allowed";
  const pct = s.max_tests ? Math.min(100, (s.running / s.max_tests) * 100) : 0;
  const m = $("t-meter");
  m.style.width = pct + "%";
  m.className = pct >= 100 ? "bad" : pct >= 80 ? "warn" : "";
  $("t-p50").textContent = sec(lat.p50);
  $("t-n").textContent = lat.n ? lat.n + " replies measured" : "no replies yet";
  const p95 = $("t-p95");
  p95.textContent = sec(lat.p95);
  p95.className = "v" + (lat.p95 != null && lat.p95 > lat.slow_over_s ? " bad" : "");
  $("t-slow").textContent = lat.n ? `${lat.slow} slower than ${lat.slow_over_s} s, max ${sec(lat.max)}` : "";
  const c = d.counts, total = c.completed + c.aborted + c.failed + c.unknown;
  $("t-total").textContent = total;
  $("t-counts").textContent = `${c.completed} completed, ${c.aborted} aborted, ${c.failed} failed` + (c.unknown ? `, ${c.unknown} older` : "");
  $("t-up").textContent = uptime(s.uptime_s);
  $("t-ver").textContent = "API v" + s.version + (s.mock ? " (mock mode)" : "");

  // live tests
  const liveBody = $("live").tBodies[0];
  liveBody.innerHTML = d.live.map((r) => {
    const probs = [];
    if (r.errors) probs.push(tag(r.errors + " error" + (r.errors > 1 ? "s" : ""), "bad"));
    if (r.llm_error) probs.push(tag("LLM: " + r.llm_error.slice(0, 40), "bad"));
    if (r.slow_replies) probs.push(tag(r.slow_replies + " slow", "warn"));
    if (r.started && r.elapsed_s > 10 && r.mic_chunks === 0) probs.push(tag("no mic audio", "bad"));
    const slow = r.last_reply_s != null && r.last_reply_s > lat.slow_over_s;
    return `<tr class="${probs.length ? "bad" : ""}"><td class="mono">${esc(r.id)}</td><td>${esc(r.user) || "-"}</td><td>${esc(r.device) || "-"}</td>` +
      `<td>${esc(PHASES[r.phase] || r.phase)}${r.started ? "" : " " + tag("not started")}</td><td class="mono">${mmss(r.elapsed_s)}</td>` +
      `<td class="mono">${r.mic_rms.toFixed(3)}</td><td class="mono">${slow ? tag(sec(r.last_reply_s), "warn") : sec(r.last_reply_s)}</td>` +
      `<td>${probs.join("") || tag("none", "ok")}</td></tr>`;
  }).join("");
  $("live-empty").hidden = d.live.length > 0;
  $("live-count").textContent = d.live.length + " connected";

  // failures feed: what the service logged, and the recent tests that went wrong, newest first
  const items = [
    ...d.failures.map((f) => ({ at: f.at, level: f.level, kind: f.level === "ERROR" || f.level === "CRITICAL" ? "bad" : "warn", msg: f.message, src: f.source })),
    ...d.recent.filter((r) => r.failed).map((r) => ({
      at: r.ended_at || r.started_at || 0, level: "TEST", kind: r.status === "completed" ? "warn" : "bad",
      msg: `test ${r.id}${r.user ? " (" + r.user + ")" : ""}: ${r.problems.join(", ")}`, src: "recent tests" })),
  ].sort((a, b) => b.at - a.at);
  $("failures").innerHTML = items.map((f) =>
    `<div class="f"><span class="t">${clock(f.at)}</span>${tag(f.level, f.kind)}<span class="msg">${esc(f.msg)}</span><span class="src">${esc(f.src)}</span></div>`).join("");
  $("fail-empty").hidden = items.length > 0;
  $("fail-count").textContent = items.length ? items.length + " item" + (items.length > 1 ? "s" : "") : "";

  // recent tests
  const only = $("only-problems").checked;
  const rows = d.recent.filter((r) => !only || r.failed);
  $("recent").tBodies[0].innerHTML = rows.map((r) => {
    const kind = r.status === "completed" ? "ok" : r.status === "unknown" ? "" : "bad";
    const p95v = r.latency.p95, slow = p95v != null && p95v > r.latency.slow_over_s;
    return `<tr class="${r.failed ? "bad" : ""}"><td class="mono">${esc(day(r.started_at))} ${esc(clock(r.started_at))}</td><td class="mono">${esc(r.id)}</td>` +
      `<td>${esc(r.user) || "-"}</td><td>${esc(r.device) || "-"}</td><td>${tag(r.status === "unknown" ? "older run" : r.status, kind)}</td>` +
      `<td>${esc(REASONS[r.end_reason] || r.end_reason || "-")}</td><td class="mono">${mmss(r.duration_s)}</td>` +
      `<td class="mono">${slow ? tag(sec(p95v), "warn") : sec(p95v)}</td><td>${r.problems.map((p) => tag(p, "bad")).join("") || tag("none", "ok")}</td></tr>`;
  }).join("");
  $("recent-empty").hidden = rows.length > 0;
  $("recent-empty").textContent = only && d.recent.length ? "No test with problems in the recent list." : "No saved test yet.";
}

async function poll() {
  try {
    const res = await fetch("/api/monitor", { cache: "no-store" });
    if (!res.ok) {
      pill(res.status === 503 ? "Closed" : "No access", "bad");
      banner((await res.text()) || "HTTP " + res.status, "");
      return;
    }
    last = await res.json();
    lastOk = Date.now();
    render(last);
  } catch (e) {
    pill("Unreachable", "bad");
    banner("Cannot reach the service" + (lastOk ? " (last data " + clock(lastOk / 1000) + "). Showing the last numbers received." : "."), "");
  }
}

// ---- server log tail -----------------------------------------------------------------------------
async function tail() {
  const view = $("sl-view");
  try {
    const q = encodeURIComponent($("sl-filter").value);
    const res = await fetch(`/api/serverlog/${$("sl-name").value}?lines=300&q=${q}`, { cache: "no-store" });
    if (!res.ok) { $("sl-info").textContent = "unavailable (HTTP " + res.status + ")"; return; }
    const d = await res.json();
    $("sl-info").textContent = d.exists ? d.lines.length + " lines" : "no such file yet";
    const stick = $("sl-follow").checked;
    view.textContent = d.exists ? d.lines.join("\n") : d.path + " does not exist";
    if (stick) view.scrollTop = view.scrollHeight;
  } catch (e) {
    $("sl-info").textContent = "unavailable";
  }
}

$("only-problems").addEventListener("change", () => last && render(last));
$("sl-name").addEventListener("change", tail);
$("sl-filter").addEventListener("input", tail);
poll();
tail();
setInterval(poll, POLL_MS);
setInterval(tail, LOG_MS);
