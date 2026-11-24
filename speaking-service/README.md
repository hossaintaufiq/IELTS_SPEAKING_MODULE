# Speaking Service

Fully local IELTS Speaking test service: an AI examiner that speaks, listens and produces estimated practice feedback. Runs on GPU servers, called by the company's Node app over an API. See `docs/`.

- `docs/PROGRESS.md`: what is done, next and blocked (update with every change)
- `docs/DECISIONS.md`: why we chose what we chose, plus open questions
- `docs/ARCHITECTURE.md`: shape and diagram link
- `docs/API_CONTRACT_V1.md`: the service API for the ieltsup server (`API_CONTRACT.md` is the superseded v0 draft)

## Server settings (environment variables)

| Variable | What it does |
|---|---|
| `SERVICE_API_KEYS` | API keys for `/v1`, comma separated, one per caller. **With none set, every `/v1` call is refused.** |
| `MONITOR_KEY` | Key for the monitoring page. **With none set, the page is closed** (except in `MOCK=1`). |
| `MAX_SESSIONS` | Tests allowed at once (default 6). Over that, a new test is refused with close code 1013. |
| `ACCESS_CODE` | Optional code for the browser test bench pages (`/`, `/logs`). Does not apply to `/v1` or the monitor. |
| `MONITOR_SLOW_S` | A reply slower than this many seconds counts as slow on the monitor (default 3). |

## Monitoring page

Open `https://<service>/monitor?key=<MONITOR_KEY>` once; the browser keeps a cookie after that. It shows whether the service is ready,
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
