# Speaking Service API, contract v1 (DRAFT for review)

One complete IELTS Speaking examiner, delivered as a service. The ieltsup server connects to it the way it connects to a speech
provider today: one WebSocket per test, one API key. The service runs the whole exam (rules, questions, timing, voice).
ieltsup keeps booking, auth, proctoring and its own test records.

Replaces the lease-based `API_CONTRACT.md` (v0). Leases are dropped for now: the service runs on an always-on GPU machine with a fixed
capacity. They can return later without changing anything below.

Marked **[exists]** = already implemented in `worker/`, **[new]** = to be built in step 2.

## 1. Conventions
- Base URL: `https://speaking.<our-domain>` (HTTP) and `wss://speaking.<our-domain>` (WebSocket).
- Every public HTTP response is `Cache-Control: no-store` and carries `X-Content-Type-Options`, `Referrer-Policy` and `Strict-Transport-Security`. `/health` shows readiness and capacity only. **[new]**
- Public surface: only `/v1/...` and `/health` exist on the public address. Everything else (our test bench, monitor and logs) is on an internal port that is not reachable from outside and answers 404 here. **[new]**
- Auth: `Authorization: Bearer <api key>` on every HTTP call and on the WebSocket upgrade. **[new]** Keys are issued per caller and can be revoked.
- Versioning: the version is in the path (`/v1`). Within v1 only additive changes (new optional fields, new event types).
  Clients must ignore event types and fields they do not know.
- Audio: PCM16 little-endian, mono. **Up** (candidate) 16 000 Hz. **Down** (examiner) 24 000 Hz. Sent as binary WebSocket frames. **[exists]**
- Times in events: `t` = seconds since the test started, `at` = wall-clock Unix seconds. **[exists]**

## 2. Health and capacity
`GET /health` (no auth) **[exists, to be extended]**
```json
{ "ok": true, "version": "1", "tests_running": 3, "max_tests": 9, "ready": true }
```
`ready` is false while models are still loading (the first minutes after a start). Callers should not send tests until it is true. **[new]**
`accepting` is true when a new test would be taken right now; when false, `busy_reason` says why: `full` (all test places used), `gpu_memory` (the GPU is nearly full), `slow` (replies are slow at the moment), `restarting` (the service is restarting to free GPU memory; models reload, `ready` is false for a few minutes). Callers should wait and retry, not send tests while `accepting` is false. **[new]**

## 2a. Browser tokens (a student's browser connects directly) **[new]**
The browser never holds an API key. ieltsup's **server** asks for a token for one candidate and hands it to that candidate's browser.

`POST /v1/tokens` (Bearer API key, JSON body):
```json
{ "external_user_id": "student-7", "hour": 9 }
```
`hour` is optional (0-23). Reply `200` (with `Cache-Control: no-store`):
```json
{ "token": "eyJ2IjoxLC...", "expires_at": 1795597919, "expires_in": 120 }
```
Errors: `400 invalid_request` (missing or too long `external_user_id`, bad `hour`), `401`, `503 no_token_secret`.

The browser then opens `wss://<host>/v1/session?token=<token>` (optionally `&device=<label>`). Rules:
- The candidate and hour come from the token. `external_user_id` or `hour` in the URL are ignored when a token is present.
- A token opens **one** test and is valid for `expires_in` seconds (default 120) to **start** it; the test may then run as long as it needs.
  If the service was full or still loading (close `1013`), the token is not spent and may be tried again before it expires.
- A token is not an API key: it cannot call `/v1/tests/...` or mint other tokens.
- A bad token does not open a test. The socket is accepted, sent `{"type":"error","code":"token_invalid"|"token_expired"|"token_used","message":...}`
  and closed with `1008`. The browser should then ask its server for a new token.
- Tokens are kept out of the service's logs. Ask for a token right before the student presses start, not in advance.
- **Allowed websites.** A browser sends the page's `Origin` with the socket. If it is not in the service's `ALLOWED_ORIGINS` list, the socket is accepted,
  sent `{"type":"error","code":"origin_not_allowed",...}` and closed with `1008`; the token is not spent. We need the exact list from ieltsup
  (for example `https://ieltsup.org` and `https://www.ieltsup.org`, and a staging site). Server-to-server calls send no `Origin` and are not checked.
- **CORS.** Only `GET /health` can be read by a browser page (from a listed website), so the page can wait for `ready`. `POST /v1/tokens` and
  `/v1/tests/...` carry the API key and are for ieltsup's server only: they send no CORS headers, so a browser page cannot read them.
- To void every token at once, change `TOKEN_SECRET` (restarts the service).

## 3. Live test (WebSocket)
`GET /v1/session` upgraded to WebSocket. Authenticate with an API key (`Authorization: Bearer`, server to server) **or** with a browser token (`?token=`, section 2a). Query parameters (with a token, only `device` is read):

| Param | Required | Meaning |
|---|---|---|
| `external_user_id` | yes | The caller's own id for the candidate. Opaque to us, stored with the test. **[new]** |
| `hour` | no | Local hour 0-23 for the greeting ("Good morning"). Defaults to the server's hour. **[exists]** |
| `device` | no | Free label for logs. **[exists]** |

Refusals at upgrade (the socket never opens, the caller sees an HTTP `403` on the upgrade request): a bad, missing or unconfigured API key,
a missing `external_user_id`, or an `hour` outside 0-23. If the service is full, or its models are still loading (`ready: false` in `/health`),
the socket is accepted and closed at once with close code **1013**, reason `"Server is full (N tests running)"`, `"Service is starting"`, `"Server is busy, try again in a minute"` (GPU nearly full, or replies slow) or `"Service is restarting, try again in a minute"`. Tests already running are never cut off to make room.
The caller retries later or routes elsewhere. **[implemented in step 2]**

### 3.1 Client to server
- Binary frame: candidate microphone audio (16 kHz PCM16). **[exists]**
- Text frame, JSON `{"action": ...}`: **[exists]**

| action | Effect |
|---|---|
| `start` | Begins the test; the examiner greets. Send once, after the socket opens and the microphone works. |
| `end` | Ends the test politely (the examiner closes the test) |
| `skip_prep` | The candidate is ready before the Part 2 preparation time is up: the long turn starts now. Ignored in every other phase. |
| `next_part` | Skips to the next part. Testing and admin use only; ieltsup should not expose it to students. |

### 3.2 Server to client
Binary frame: examiner speech (24 kHz PCM16), streamed as it is produced. **[exists]**

Text frames, JSON with a `type`:

| type | Fields | When |
|---|---|---|
| `test` | `id` | First message: the test id. Use it to fetch the result. **[new, name taken from ieltsup's own message]** |
| `phase` | `phase`, `limit` (seconds or null), `cue_card` (only in part 2 phases) | The test moves to a new phase **[exists]** |
| `timer` | `phase`, `elapsed`, `limit`, `mic_chunks`, `mic_rms` | About every 0.5 s. `mic_rms` near 0 means the microphone is silent. **[exists]** |
| `transcript` | `role` (`examiner` or `user`), `text`, `origin` (examiner only) | A finished line **[exists]** |
| `interim` | `text` | Live caption while the candidate speaks. Replaced by the final `transcript`. Optional, may be turned off. **[exists]** |
| `interrupt` | none | The candidate started speaking: stop playing examiner audio **[exists]** |
| `latency` | `seconds` | Candidate stopped to first examiner audio **[exists]** |
| `ignored` | `text`, `why` | Speech discarded as noise. Diagnostic. **[exists]** |
| `note` | `text` | Why the examiner did something. Diagnostic, safe to hide from students. **[exists]** |
| `done` | `reason` | The test is over **[exists; `reason` is new]** |
| `error` | `code`, `message` | Something failed in the service **[new]** |

`phase` values, in order: `intro`, `name`, `part1`, `part2_intro`, `part2_prep`, `part2_speak`, `part2_followup`, `part3`, `done`.
`cue_card` is `{ "prompt": str, "bullets": [str], "closing": str }`.

`done.reason` **[new]**:
`completed` (normal finish), `ended_by_candidate` (`end` action or the candidate asked to finish), `off_topic` (limit of irrelevant questions reached),
`no_response` (silence at the end of Part 3), `skipped_to_end` (`next_part` past Part 3), `error`.

### 3.3 Close codes
`1000` normal end after `done`. `1013` service full, busy, starting or restarting (try again later; `/health` `accepting` says when). `1011` internal error. If the caller drops the connection mid-test the test is saved as
`status: "aborted"` with whatever happened so far. There is no resume in v1. **[exists as abort+save; status is new]**

## 4. Results (HTTP, Bearer auth) **[new]**
| Call | Returns |
|---|---|
| `GET /v1/tests/{id}` | `{ id, external_user_id, status, started_at, ended_at, end_reason, phase }`. `status`: `running`, `completed`, `aborted`, `failed`. |
| `GET /v1/tests/{id}/result` | Full record: examiner and candidate turns with `t`/`at`, phase boundaries, topics and cue card used, latencies, flags. `404` while the test is still running. |
| `GET /v1/tests/{id}/audio` | The candidate's microphone recording as WAV (16 kHz mono) |

**Retention:** results and recordings are kept for **30 days** and then deleted; after that these calls answer `404`. Fetch and store
what you need within that time. The recording covers the whole test (up to 30 minutes; the record says `recording_truncated` if longer).

Scoring (the four IELTS criteria) is **not part of v1**. When added it will be a separate `GET /v1/tests/{id}/assessment` returning
estimated bands with an `estimated: true` flag. No official-score claim (decision D6).

## 5. Errors and limits
- HTTP errors (results calls): `401` bad or missing key (with `WWW-Authenticate: Bearer`), `503` no API key configured on the service, `404` unknown test or a test still running (`code: not_finished`). `429` (rate limit) is not implemented yet. Body: `{ "error": { "code": "...", "message": "..." } }`.
- Capacity is fixed by configuration (`MAX_SESSIONS`) and measured by load test. The service never degrades running tests to take a new one.

## 6. Out of scope for v1 (decided later)
Pricing and usage billing. Webhooks (the caller already holds the socket and can poll `/v1/tests/{id}`). Resume after a dropped connection.
Leases and GPU rental control. Scoring.

## 7. Open points for the ieltsup team
1. Is a server-to-server socket (ieltsup relays audio to the browser, as it does today) acceptable, or does it want the browser to connect directly?
Ans: Ieltsup will connect to this service directly from browser, but with a gate of basic encryption.

2. Do they want the results fetched, or pushed by webhook?
Ans: Webhook first. but if webhook missed or we didnt get any hit, we will POST request after a basic timeout to fetch the result. If we got by webhook, we wont hit that POST. 
   
3. How long must audio and transcripts be kept? (retention is an open decision in `DECISIONS.md`)
Ans: You dont have to keep that, thats your choice, but IELTSUP will store with his own policy out of your service.
   
4. Are the `phase`, `cue_card` and `done.reason` values enough to drive their screen, or do they need extra events (for example `begin_part`, `end_test`)?
Ans: No need
