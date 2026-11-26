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
| `deploy/` | Renting and setting up the GPU box, and putting the public port on the internet (`deploy/public/`, `docs/DEPLOY_PUBLIC.md`) |
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
| `MAX_SESSIONS` | Tests allowed at once (default 6). Over that, a new test is refused with close code 1013. Kept at or below `SAFE_MAX_SESSIONS` (default 20; the 24 GB card broke at 29). `ALLOW_UNSAFE_MAX_SESSIONS=1` lifts the ceiling, for the load test that looks for the breaking point. |
| `GPU_MIN_FREE_MB` | A new test is refused ("Server is busy", close 1013) while less than this much GPU memory is free (default 1500). Read with `nvidia-smi` every `GPU_POLL_S` seconds (default 5); with no NVIDIA GPU this guard is off. |
| `SLOW_P95_S`, `SLOW_CLEAR_P95_S`, `REPLY_WINDOW_S`, `REPLY_MIN_SAMPLES` | A new test is refused while the 95th percentile of the last 60 s of reply delays (at least 10 replies) is above 12 s; it opens again below 8 s. Tests already running are never touched. |
| `RECYCLE_ON_LEAK` | `1`: with no test running, if GPU memory is still more than `RECYCLE_EXTRA_MB` (3000) above its start-up level after a cleanup, the service exits with code 75 and `start_web.sh` starts it again. Off by default; `setup_instance.sh` turns it on. |
| `RETENTION_DAYS` | Saved tests (transcript and recording) are deleted this many days after they were saved: at start, then every hour (default 30). `0` keeps them for ever; a value that is not a number also deletes nothing. Server logs are not covered. |
| `MAX_RECORDING_S` | How much of a candidate's microphone is recorded per test, in seconds (default 1800). It is held in memory until the test ends: about 58 MB per test at the limit. A record whose recording was cut says `recording_truncated: true`. |
| `ACCESS_CODE` | Optional code for the browser test bench pages (`/`, `/logs`). Does not apply to `/v1` or the monitor. |
| `MONITOR_SLOW_S` | A reply slower than this many seconds counts as slow on the monitor (default 3). |
| `CAPTIONS` | `off` switches live captions off completely (the small caption model is not even loaded). Default on. |
| `CAPTION_WINDOW_S` | Live captions re-decode only the last N seconds of speech (default 8; it was 15). |
| `CAPTION_INTERVAL_S` | Seconds between caption updates (default 1.2; it was 0.9). |
| `CAPTION_MAX_CONCURRENT` | Most caption decodes at one moment in the whole server (default 2). A caption that finds them busy is skipped, so captions can never delay a real answer. The monitor shows how many were skipped. |

The overload numbers (`GPU_MIN_FREE_MB`, `SLOW_P95_S` ...) come from one measurement series on one RTX 3090 (`docs/GPU_TEST_2026-11-24.md`). They are first guesses until the next GPU session; `/api/monitor` shows the live values under `load` (reply delay, GPU memory, refusals by reason).

The caption defaults are a first guess to be tuned by the load test below, not measured values.

## Load test (run on the GPU box)

`eval/load_test.py` runs N scripted candidates at once and reports reply delay (p50, p95), refusals, errors and, with `--gpu`, the busiest the GPU got.
Run one session first as the baseline, then more, and keep `/monitor` open while it runs:

```
python -m eval.load_test --sessions 1 --report base.json    # bench /ws on the internal port 8081; with --api-key it uses /v1/session on 8080
python -m eval.load_test --sessions 3 --baseline base.json
python -m eval.load_test --sessions 9 --baseline base.json --gpu --report nine.json     # add --part2 for the long talk
```

To find the breaking point (as on 2026-11-24) start the service with the guards off, otherwise it refuses the extra tests, which is what it should do:
`MAX_SESSIONS=200 ALLOW_UNSAFE_MAX_SESSIONS=1 GPU_MIN_FREE_MB=0 SLOW_P95_S=100000`. To check the guards, run the same ramp with the normal settings and expect refusals instead of silent tests.

It passes when the p95 reply delay is no more than 1 s (`--allow-extra-s`) above the baseline and nobody is refused or left without a reply.
The examiner deliberately waits about 2 s for the candidate's pause, so the delay of a single session is never near zero: compare, do not expect 2 s.
To compare caption settings run the same test with `CAPTIONS=off` and with the defaults. Use `--audio wav --wav a.wav b.wav` for your own 16 kHz mono
recordings; `--audio fake` (noise) only checks that sessions connect. Use `--api-key` to test the service API (`/v1/session`) instead of the bench.

## Checking the public address

`python -m eval.check_public --base https://<public address> --origin https://<ieltsup site> --api-key <key>` looks at the service from the outside
(certificate, nothing internal reachable, key and CORS rules, headers, token round trip) and exits non-zero if the address is not fit to hand over.
See `docs/DEPLOY_PUBLIC.md`.

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
