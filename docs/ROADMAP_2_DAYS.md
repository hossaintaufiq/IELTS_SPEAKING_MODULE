# Two-day roadmap: hand the speaking service to ieltsup

> **Status, 2026-11-25:** Day 1 is done and merged (steps 1.1 to 1.6; 1.6 is tooling only until a domain exists). Day 2 has not started: **one day behind**. See `docs/UPDATE_2026-11-25.md`.

Goal: by the end of day 2, ieltsup can run a real test from their own page against **one service** that contains speech recognition (STT), the examiner brain (LLM) and the voice (TTS), with nothing else for them to install or call.

"One service" means: one address, one API, one start command on one GPU box. The three models already run on the same machine (Whisper + vLLM Qwen2.5-7B + Kokoro); the work is to make it safe, packaged and reachable.

Plan dated 2026-11-25. Tick boxes as done and mirror the result into `docs/PROGRESS.md`.

## Definition of done (end of day 2)

1. One command (or one service unit) starts STT, LLM and TTS together and reports `ready` on `/health`.
2. ieltsup's browser connects directly to `wss://<our domain>/v1/...` with a short-lived signed token. No API key reaches a browser.
3. When a test ends we send a signed webhook with retries; `GET /v1/tests/{id}` works as their fallback.
4. Only `/v1`, `/health` and the webhook are public. The monitor, run log, server log and test bench are closed or behind keys.
5. Overload is safe: past the limit new tests are refused with a clear code, nothing goes silent, GPU memory is freed.
6. One real test run from an ieltsup page against staging, with a real voice, passes.
7. A handover doc ieltsup can follow without us.

## Day 1: make it safe and reachable

| # | Task | Output | Time |
|---|---|---|---|
| 1.1 | **Close the open routes.** `/api/runs`, `/api/runs/{name}`, `/api/live`, `/api/serverlog/*` require `MONITOR_KEY`. Refuse to start in non-mock mode without `SERVICE_API_KEYS` and `MONITOR_KEY`. Tests for each route. | No student transcript readable without a key | 1 h |
| 1.2 | **Split public from internal.** Public app: `/v1`, `/health`. Internal app (monitor, bench, logs): separate port/host bound to localhost, reached by SSH tunnel. | Public surface = contract only | 1.5 h |
| 1.3 | **Signed browser token.** `POST /v1/tokens` (API key, server to server) returns a short-lived token bound to test id and user; the WebSocket accepts the token only. Expiry, single use, tests. | Browser-direct works without exposing the key | 2.5 h |
| 1.4 | **Allowed origins (CORS and WebSocket Origin check).** `ALLOWED_ORIGINS` env, rejects others. | ieltsup domains only | 0.5 h |
| 1.5 | **Overload safety.** Hard `MAX_SESSIONS` (ship about 9 for one 3090, never above 20), refuse with close code 1013 and a retry hint; free GPU memory when sessions end or fail; ask the waiting student to wait rather than going silent. | Reproduce the 32-session ramp: refusals, no silence, memory returns | 2 h |
| 1.6 | **Domain and TLS.** Cloudflare Tunnel or Caddy on a real hostname (staging first). Decide with ieltsup if they already own the domain. | `https://speaking-staging.<domain>/health` | 1 h |
| 1.7 | **Ask ieltsup to answer the 16 questions today** (token shape, origins, webhook URL and signing, retries, rejoin, one test per booking, privacy, contact). Anything unanswered gets our default, written in the contract. | Contract section 7 closed | async |

End of day 1 check: token flow and route lock-down covered by unit tests; staging address reachable with TLS; overload behaviour verified on a rented GPU (about 1 h, about $0.30).

## Day 2: webhook, packaging, real test, handover

| # | Task | Output | Time |
|---|---|---|---|
| 2.1 | **Webhook sender.** Signed (HMAC with a shared secret, timestamp header), sent when a test ends, retries with back-off (for example 1 min, 5 min, 30 min), result stays fetchable via `GET /v1/tests/{id}`. Tests with a fake receiver. | Contract section 4 complete | 3 h |
| 2.2 | **Single-service packaging.** One start script (`deploy/run_service.sh`) that starts vLLM, waits for it, loads Whisper and Kokoro, then starts the public app; restarts on crash (systemd or supervisor); `/health` says `ready` only when all three models answer. Warm-up before accepting tests. | `bash deploy/run_service.sh` and nothing else | 2 h |
| 2.3 | **Retention and privacy.** Run files and audio kept for the period ieltsup chose; delete job; no student speech in the server log. | Documented and tested | 1 h |
| 2.4 | **Real-voice test on the GPU box.** Staff or non-native speakers, 3 full tests by hand through the browser, then the capacity ramp with real recordings. Confirm `MAX_SESSIONS`. | Report added to `docs/GPU_TEST_*.md` | 2.5 h |
| 2.5 | **Staging run from ieltsup's page.** They request a token, open the test, finish it, receive the webhook. Fix what breaks. | One green end-to-end test | 1.5 h |
| 2.6 | **Handover doc.** `docs/INTEGRATION_GUIDE.md`: base URL, auth, token request, WebSocket messages and close codes, webhook payload and signature check, errors, limits, contact, runbook for us (start, stop, rent, destroy). Update `API_CONTRACT_V1.md`, `DECISIONS.md`, `PROGRESS.md`. | Doc sent to ieltsup | 1.5 h |

## Risks and fallbacks

| Risk | Effect | Fallback |
|---|---|---|
| ieltsup answers late | Token or webhook design may change | Build to our written defaults; changes are small (header names, TTL) |
| Marketplace GPU host (vast.ai) disappears or leaks speech | Tests lost, privacy concern | Keep staging on vast.ai only; name the production host as an open decision for ieltsup (D-list) |
| One 3090 is the ceiling (about 9 comfortable) | Not enough for a full class | Ship `MAX_SESSIONS` honestly; second card or 4090 is a config change, not new code |
| Real voices behave worse than synthetic | Recognition errors, awkward pauses | Day 2.4 finds it; examiner tuning continues after handover, API unchanged |
| Pipecat or driver surprise on a fresh box | Lost hours | Use the existing `setup_instance.sh`; fold the upload fixes noted on 2026-11-24 into it first |

## Out of scope for these two days

- Scoring and feedback (`assessment/`, milestone M5): needs human-scored recordings that do not exist yet. The API returns transcript, timings and run data only.
- Multi-GPU routing, waiting room, autoscaling (the 3000-student plan). Not needed for a pilot class.
- Owned GPUs (phase 2).
- Academic review of the question bank.

## Needed from you

- Today: nudge ieltsup for the 16 answers, and confirm who owns the domain.
- GPU budget: about $3-5 for the two days (remaining vast credit about $4.45; may need a top-up).
- Two or three people with non-native accents for 30 minutes on day 2.
