# Publishing the service: a real address with https

Goal (roadmap Day 1, step 6): `https://speaking-staging.<domain>/health` answers from the internet, with a valid certificate, and nothing but `/v1` and `/health` is reachable there.

The GPU box is rented (vast.ai) and has no fixed address, no certificate, and its ports are not open to the internet. A **Cloudflare named tunnel** fixes all three: the box makes an outbound connection to Cloudflare, Cloudflare serves `https://<hostname>` with its own certificate (renewed automatically) and passes requests down the tunnel to the service. WebSockets work through it (uvicorn pings every 20 s, so the connection is never idle for Cloudflare's 100 s limit).

## What we need before this can be done (not code)

| Need | From |
|---|---|
| A domain on Cloudflare (DNS managed there), and the hostnames to use, e.g. `speaking-staging.<domain>` and later `speaking.<domain>` | ieltsup, or you if the domain is ours |
| A Cloudflare account that can create a tunnel (Zero Trust is free) | whoever owns the domain |
| The exact website origins of ieltsup's pages, for `ALLOWED_ORIGINS` | ieltsup |

Without a domain only a quick tunnel (random `trycloudflare.com` address) is possible. That is for a one-off smoke test, never for students: the address changes at every start and has no guarantee.

## Steps

1. **Install cloudflared on the GPU box** (once):
   ```
   wget -O /root/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 && chmod +x /root/cloudflared
   ```
2. **Create the tunnel** in Cloudflare: Zero Trust, Networks, Tunnels, Create a tunnel (Cloudflared), name it `speaking-staging`. Copy the **token** from the install command it shows. Treat it like a password: never paste it into chat or commit it.
3. **Add the public hostname** to that tunnel: `speaking-staging.<domain>`, service type **HTTP**, URL **`localhost:8080`**. It must be the public port (8080), never 8081: 8081 is the test bench, monitor and logs. Cloudflare creates the DNS record and the certificate.
4. **Set the allowed websites**: `/root/work/origins.env` gets `export ALLOWED_ORIGINS=https://<ieltsup site>[,...]`. Restart the `web` tmux session. Without it no browser can open a test.
5. **Start the tunnel** (tmux session `cf`):
   ```
   TUNNEL_TOKEN=<token> bash deploy/public/start_tunnel.sh named
   ```
   The script refuses to start when nothing answers on the public port, when the port also serves `/monitor` (the wrong port, or `SINGLE_PORT=1`), or when `PORT` equals `INTERNAL_PORT`.
6. **Check it from outside**, from any machine (this is the acceptance test, and ieltsup can run it too):
   ```
   python -m eval.check_public --base https://speaking-staging.<domain> --origin https://<ieltsup site> --api-key <a key from SERVICE_API_KEYS>
   ```
   Every line must be PASS (a WARN for "ready" or "taking tests" only means the models are still loading or the service is busy). It checks the certificate, that no internal page or the bench socket exists on this address, that the API refuses a missing or wrong key, CORS (only `/health`, only for listed sites), security headers, and a real token round trip with the browser's `Origin`. With `--api-key` it opens two sockets and closes them without starting a test.
7. **Give ieltsup** the base URL, their API key (never through chat), and `docs/API_CONTRACT_V1.md` section 2a.

## What the public address shows and does not show

- Only `/v1/...` and `/health`. Everything else is a 404 with the same body, so scanners learn nothing. This is enforced in code (`worker/public.py`), not by the tunnel, so a wrong tunnel setting cannot publish the monitor on 8080.
- `/health` returns readiness and capacity only (no error texts, no mode).
- Every response: `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Strict-Transport-Security` (180 days). Cloudflare must not cache results or audio.
- The URL of a socket carries a one-time token. It is removed from our logs. Cloudflare's own logs can still contain URLs: keep tokens short-lived (default 120 s) and single use, which they are.

## Looking after it

- **Monitor and logs** stay on 8081: `ssh -L 8081:localhost:8081 ...`, then `http://localhost:8081/monitor?key=<MONITOR_KEY>`.
- **Certificate**: Cloudflare renews it. `eval.check_public` warns when fewer than 14 days are left.
- **Tunnel down** (box rebooted, tmux lost): `/health` from outside fails; restart step 5. cloudflared reconnects on its own after a network drop.
- **Rotating a secret**: a leaked tunnel token is revoked in the Cloudflare dashboard (delete the tunnel's token / recreate); a leaked API key is replaced in `keys.env` and the service restarted; changing `TOKEN_SECRET` voids every token.

## Not covered by this

- **Privacy of student voices.** TLS ends at Cloudflare and again at our box: the traffic is encrypted on the internet, but the rented machine's owner could in principle read what runs on it. Whether voices may be processed on a marketplace host is an open decision (see the risk list in `docs/ROADMAP_2_DAYS.md`).
- **DDoS and rate limits.** Cloudflare's free tier absorbs ordinary floods, and `MAX_SESSIONS` plus the overload guard bound GPU use, but there is no per-caller rate limit yet (contract section 5).
