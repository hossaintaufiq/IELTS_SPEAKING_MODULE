const btn = document.getElementById("toggle");
const statusEl = document.getElementById("status");
const logEl = document.getElementById("log");
const audioEl = document.getElementById("remote");
let pc, stream;

const setStatus = (t) => (statusEl.textContent = t);
const log = (t) => { const li = document.createElement("li"); li.textContent = t; logEl.prepend(li); };

async function start() {
  setStatus("Connecting…");
  pc = new RTCPeerConnection();
  pc.ontrack = (e) => (audioEl.srcObject = e.streams[0]);

  stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  pc.addTrack(stream.getTracks()[0]);

  const dc = pc.createDataChannel("oai-events");
  dc.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.type === "conversation.item.input_audio_transcription.completed") log("You: " + ev.transcript.trim());
    if (ev.type === "response.output_audio_transcript.done") log("AI: " + ev.transcript.trim());
  };

  await pc.setLocalDescription(await pc.createOffer());
  const res = await fetch("/session", { method: "POST", headers: { "Content-Type": "application/sdp" }, body: pc.localDescription.sdp });
  if (!res.ok) throw new Error(await res.text());
  await pc.setRemoteDescription({ type: "answer", sdp: await res.text() });

  btn.textContent = "Stop";
  btn.classList.add("live");
  setStatus("Live — start talking");
}

function stop() {
  stream?.getTracks().forEach((t) => t.stop());
  pc?.close();
  btn.textContent = "Start";
  btn.classList.remove("live");
  setStatus("Idle");
}

btn.onclick = async () => {
  try { btn.classList.contains("live") ? stop() : await start(); }
  catch (err) { stop(); setStatus("Error"); log(String(err.message || err)); }
};
