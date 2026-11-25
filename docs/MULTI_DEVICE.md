# Testing with several devices at once (Cloudflare link)

Several devices (laptops, phones, tablets, on any network) can take a speaking test at the same time on one GPU box. Each browser connection gets its own examiner session; the Whisper and Kokoro models and the LLM are shared.

A browser allows the microphone only on `localhost` or an HTTPS page, so a plain `http://192.168...` link on the router does not work (tried: the page loads, the mic is blocked, and iPhones have no workaround). A Cloudflare Tunnel gives a public **HTTPS** link instead: no certificates, no router or firewall changes, works on every browser including iPhone, and the audio goes straight to the GPU box.

## 1. Start it (on the GPU box)

```
# once: download the tunnel program
wget -O /root/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 && chmod +x /root/cloudflared

# the web server WITH an access code (anyone with the bare link must not be able to use the GPU)
ACCESS_CODE=<a long random code> /root/work/start_web.sh        # in tmux session "web"

# the tunnel (tmux session "cf"); the link is printed in the log
/root/cloudflared tunnel --no-autoupdate --url http://localhost:8081 2>&1 | tee /root/work/cloudflared.log
grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' /root/work/cloudflared.log | head -1
```

The tunnel points at the **internal** port (8081), which serves the test bench; the public port (8080) carries only `/v1` and `/health`. This tunnel is for our own testers and must not be left running: it exposes the bench behind the access code only. ieltsup gets a separate address for 8080 (roadmap Day 1, step 6).

The `trycloudflare.com` address is new every time the tunnel starts, and the tunnel lasts only as long as the process. Keep it inside tmux.

## 2. Share the link

Give each device: `https://<tunnel address>/?key=<code>&device=<label>`

- `key` is the access code. The first visit stores it in a cookie (24 hours), after which the page, the logs and the microphone connection all work. Without it the server answers "Access code needed" (HTTP 401, WebSocket closed). `/health` stays open.
- `device` is any label (Laptop, Phone, Student1). It names the device in the logs.

Treat the full link like a password. Stop the tunnel (`tmux kill-session -t cf`) when the session is over; that closes the public address.

## 3. How many at once

`MAX_SESSIONS` (default 6) is the number of tests the server accepts at the same time. The next device is refused at once with "Server is full (6 tests running). Please try again in a minute." and can retry. `GET /health` shows `tests_running` and `max_tests`.

What one RTX 3090 really carries is not measured: three silent devices all received the examiner's greeting in about 3.1 s, but real speech from many devices also loads Whisper and the LLM. Start with 3 to 4 devices and watch the reply delay in the logs.

## 4. Watching every device (the logs page)

Open `https://<tunnel address>/logs?key=<code>` (or `http://localhost:8081/logs?key=<code>` through the SSH tunnel on your PC; the code applies there too when `ACCESS_CODE` is set).

- **Run log, Live: newest test** follows the latest test to start.
- **Live: <device> (phase)** follows one device. The list refreshes every few seconds.
- **Live: ALL devices together** (shown when two or more are connected) merges every device into one timeline, oldest first, each line tagged with its device.
- **Saved runs** appear below, with the device label.
- **Server log (web)** has one tagged line per event, for example `[Phone] part1 examiner: ...`. Type the device label in the filter box to follow one device.
- Every finished test is saved as `runs/run_<date>_<time>_<id>.json` (with the mic recording as `.wav`). The `device` field names the device; the id in the name keeps two tests that end in the same second apart.

## 5. Known limits

- Concurrency on one GPU is untested with real speech from many devices (section 3).
- Whisper and Kokoro objects are shared between sessions; calls from several tests at once have not shown a problem, but long runs have not been checked.
- The access code is a shared secret in the link, not a login. Anyone who has the link can use the GPU until the tunnel is stopped or the code changed.
- The first request through a new tunnel can take a few seconds while Cloudflare connects.
