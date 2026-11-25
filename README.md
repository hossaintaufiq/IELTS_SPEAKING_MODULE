# Speaking Service

Fully local IELTS Speaking test service: an AI examiner that speaks, listens and produces estimated practice feedback. Runs on GPU servers, called by the company's Node app over an API. See `docs/`.

- `docs/PROGRESS.md`: what is done, next and blocked (update with every change)
- `docs/DECISIONS.md`: why we chose what we chose, plus open questions
- `docs/ARCHITECTURE.md`: shape and diagram link
- `docs/API_CONTRACT_V1.md`: the service API for the ieltsup server (`API_CONTRACT.md` is the superseded v0 draft)

## Repository layout

This repository is the speaking service. Run everything from the repo root (`python -m worker.server`, `python -m eval.load_test`, `pytest`).

| Folder | What it is |
|---|---|
| `worker/` | The live test: examiner rules, speech recognition, voice, the server and the service API |
| `control_plane/`, `assessment/` | Capacity/lease skeleton and post-test scoring (not finished) |
| `web/` | The test bench page, the run-log page and the monitoring page |
| `question_bank/` | Questions and cue cards |
| `eval/` | Benchmarks and the load test |
| `deploy/` | Renting and setting up the GPU box |
| `docs/` | Contract, decisions, architecture, progress, the examiner's rules and prompts |
| `tests/` | The test suite |
| `experiments/` | Earlier experiments (numbered studies, a GPT live voice sample, the browser TTS and STT labs). Not part of the service; nothing here imports them. |

## Server settings (environment variables)

| Variable | What it does |
|---|---|
| `SERVICE_API_KEYS` | API keys for `/v1`, comma separated, one per caller. **With none set, every `/v1` call is refused.** |
| `TOKEN_SECRET` | At least 32 random characters. Signs the short-lived browser tokens (`POST /v1/tokens`); the service refuses to start without it. Changing it voids every token. |
| `TOKEN_TTL_S` | How long a token can be used to open a test (default 120, between 10 and 600). The test itself may run longer. |
| `ALLOWED_ORIGINS` | The websites whose pages may open a test from a browser: exact origins, comma separated, e.g. `https://ieltsup.org,https://www.ieltsup.org`. No wildcard, path or trailing slash; plain `http` only for localhost. **Not set: no browser is allowed** (a start-up warning says so). Callers that send no `Origin` header (ieltsup's server, our load test) are not browsers and are not affected. |
| `MONITOR_KEY` | Key for the monitoring page. **With none set, the page is closed** (except in `MOCK=1`). |
| `HOST`, `PORT` | Address of the **public** port (default `127.0.0.1:8080`): serves only `/v1/...` and `/health`. This is the one to expose. |
| `INTERNAL_HOST`, `INTERNAL_PORT` | Address of the **internal** port (default `127.0.0.1:8081`): test bench page and `/ws`, `/monitor`, run log, server log. The service refuses to start if `INTERNAL_HOST` is not a loopback address (unless `INTERNAL_ALLOW_REMOTE=1`); reach it with an SSH tunnel. |
| `SINGLE_PORT` | `1` serves everything on `PORT`, as before. For local development only: it puts the bench and monitor wherever `/v1` is. |
| `MAX_SESSIONS` | Tests allowed at once (default 6). Over that, a new test is refused with close code 1013. |
| `ACCESS_CODE` | Optional code for the browser test bench pages (`/`, `/logs`). Does not apply to `/v1` or the monitor. |
| `MONITOR_SLOW_S` | A reply slower than this many seconds counts as slow on the monitor (default 3). |
| `CAPTIONS` | `off` switches live captions off completely (the small caption model is not even loaded). Default on. |
| `CAPTION_WINDOW_S` | Live captions re-decode only the last N seconds of speech (default 8; it was 15). |
| `CAPTION_INTERVAL_S` | Seconds between caption updates (default 1.2; it was 0.9). |
| `CAPTION_MAX_CONCURRENT` | Most caption decodes at one moment in the whole server (default 2). A caption that finds them busy is skipped, so captions can never delay a real answer. The monitor shows how many were skipped. |

The caption defaults are a first guess to be tuned by the load test below, not measured values.

## Load test (run on the GPU box)

`eval/load_test.py` runs N scripted candidates at once and reports reply delay (p50, p95), refusals, errors and, with `--gpu`, the busiest the GPU got.
Run one session first as the baseline, then more, and keep `/monitor` open while it runs:

```
python -m eval.load_test --sessions 1 --report base.json    # bench /ws on the internal port 8081; with --api-key it uses /v1/session on 8080
python -m eval.load_test --sessions 3 --baseline base.json
python -m eval.load_test --sessions 9 --baseline base.json --gpu --report nine.json     # add --part2 for the long talk
```

It passes when the p95 reply delay is no more than 1 s (`--allow-extra-s`) above the baseline and nobody is refused or left without a reply.
The examiner deliberately waits about 2 s for the candidate's pause, so the delay of a single session is never near zero: compare, do not expect 2 s.
To compare caption settings run the same test with `CAPTIONS=off` and with the defaults. Use `--audio wav --wav a.wav b.wav` for your own 16 kHz mono
recordings; `--audio fake` (noise) only checks that sessions connect. Use `--api-key` to test the service API (`/v1/session`) instead of the bench.

## Monitoring page

Open `http://localhost:8081/monitor?key=<MONITOR_KEY>` (internal port, through the SSH tunnel) once; the browser keeps a cookie after that. It shows whether the service is ready,
tests running against the limit, every live test, reply-delay figures (p50, p95), recent tests with how each ended, failures
(warnings and errors the service logged, plus tests that were aborted, failed, had errors or slow replies) and the server log.
Scripts can read the same data from `GET /api/monitor` with `Authorization: Bearer <MONITOR_KEY>`. It never includes what a candidate said.

## Run the tests

```
py -3.10 -m venv .venv
.venv\Scripts\python -m pip install pytest
.venv\Scripts\python -m pytest
```

Only the pure-Python parts exist and are tested so far (eval metrics, GPU provisioner interface, test flow). The voice pipeline and control-plane API are not written yet; see PROGRESS.md.
