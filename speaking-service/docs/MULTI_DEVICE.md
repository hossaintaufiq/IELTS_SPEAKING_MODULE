# Testing with several devices at once

Several devices (laptops, phones, tablets) can take a speaking test at the same time on one GPU box. Each browser connection gets its own examiner session; the Whisper and Kokoro models and the LLM are shared.

## 1. Share the page on your router (LAN)

On the PC that holds the SSH key to the GPU box (the PC's address on the router is shown by `ipconfig`, for example `192.168.10.79`):

```
# 1. Forward the box's web port to ALL network interfaces of the PC (not only localhost)
ssh -N -p <SSH_PORT> -i ~/.ssh/vast_ed25519 -L 0.0.0.0:8080:localhost:8080 root@<SSH_HOST>

# 2. Let the router's devices (and only them) reach the port. Run once, in an administrator PowerShell:
New-NetFirewallRule -DisplayName "IELTS speaking test bench 8080 (LAN only)" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow -RemoteAddress LocalSubnet -Profile Any
```

Every device then opens the same link: `http://<PC address>:8080`. Add `?device=Laptop` (any label) to tell the devices apart in the logs:

- `http://192.168.10.79:8080/?device=Laptop`
- `http://192.168.10.79:8080/?device=Phone`

Remove the firewall rule when you are done: `Remove-NetFirewallRule -DisplayName "IELTS speaking test bench 8080 (LAN only)"`.

### The microphone needs a secure page
Browsers allow the microphone only on `localhost` or HTTPS. A plain `http://192.168...` link loads but the mic is blocked, so on every device other than the PC itself:

| Browser | What to do |
|---|---|
| Chrome / Edge (Windows, Mac, Linux, Android) | open `chrome://flags/#unsafely-treat-insecure-origin-as-secure`, add `http://<PC address>:8080`, set Enabled, relaunch |
| Brave (Windows, Mac, Linux, Android) | same, at `brave://flags/#unsafely-treat-insecure-origin-as-secure` |
| Firefox | `about:config`, set `media.devices.insecure.enabled` and `media.getusermedia.insecure.enabled` to true |
| Safari / any browser on iPhone | no such switch: use a public HTTPS link instead (a Cloudflare Tunnel on the GPU box) |

Use headphones: the examiner cannot hear itself and does not talk over you, but speakers can still echo into a nearby device's mic.

## 2. How many at once

`MAX_SESSIONS` (default 6) is the number of tests the server accepts at the same time. The next device is refused at once with "Server is full (6 tests running). Please try again in a minute." and can retry. Raise or lower it with the environment variable in `start_web.sh`. `GET /health` shows `tests_running` and `max_tests`.

What one RTX 3090 really carries is not measured yet: three silent devices all received the examiner's greeting in about 3.1 s, but real speech from many devices at once also loads Whisper and the LLM. Start with 3 to 4 devices and watch the reply delay in the logs.

## 3. Watching every device (the logs page)

Open `http://<PC address>:8080/logs` (on the PC: `http://localhost:8080/logs`).

- **Run log, Live: newest test** follows the latest test to start.
- **Live: <device> (phase)** follows one device. The list refreshes every few seconds.
- **Live: ALL devices together** (shown when two or more are connected) merges every device into one timeline, oldest first, each line tagged with its device.
- **Saved runs** appear below, with the device label.
- **Server log (web)** has one tagged line per event, for example `[Phone] part1 examiner: ...`. Type the device label in the filter box to follow one device.
- Every finished test is saved as `runs/run_<date>_<time>_<id>.json` (with the mic recording as `.wav`). The `device` field names the device. The id in the name keeps two tests that end in the same second apart.

## 4. Known limits

- Concurrency on one GPU is untested with real speech from many devices (see section 2).
- The model objects are shared between sessions; Whisper and Kokoro calls from several tests at once have not shown a problem, but long runs have not been checked.
- The link is open to anyone on the router (the firewall rule is limited to the local subnet). There is no login. A public link would need an access code first.
- If the PC's address changes (DHCP), the link and the browser flag must be updated. Reserve the address in the router.
