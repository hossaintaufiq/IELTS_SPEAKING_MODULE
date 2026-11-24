# API Contract for the Node app (DRAFT v0) -- SUPERSEDED by API_CONTRACT_V1.md (2026-11-24)

Draft for review with the Node team. Nothing here is implemented yet. Align with their existing LLM-service API shape once we have it.

Auth: service-to-service API key in `Authorization: Bearer <key>`. The service never stores user accounts, only an opaque `external_user_id`.

## Leases (GPU capacity for a class)

| Call | Purpose |
|---|---|
| `POST /leases` `{start_at, duration_s, seats}` | Reserve capacity and start the GPU. Ask ahead of class; returns `lease_id`, state `pending`. `409` if seats exceed capacity. |
| `GET /leases/{id}` | State: `pending`, `ready`, `draining`, `ended`. |
| `POST /leases/{id}/extend` `{extra_s}` | Add time. |
| `DELETE /leases/{id}` | Release early. |

Webhook to the Node app: `lease.ready`, `lease.expiring` (about 10 min before end), `lease.ended`.

## Sessions (one student's test)

| Call | Purpose |
|---|---|
| `POST /sessions` `{lease_id, external_user_id}` | Returns `session_id`, a signed short-lived `ws_token`, and the WebSocket URL. |
| WebSocket `/ws/{session_id}?token=...` | Browser streams mic audio up; receives examiner audio and events. |
| `GET /sessions/{id}` | State and progress. |
| `GET /sessions/{id}/result` | Transcript and estimated scores once assessment finished. |

Webhook: `session.completed`, `session.result_ready`.

## Errors
`429`/`503` with `Retry-After` when the lease is full ("busy"). Never silently degrade other students.

## Result shape (draft)
Four criteria (fluency and coherence, lexical resource, grammatical range and accuracy, pronunciation), each with an estimated band and evidence, plus an `estimated: true` flag. No official-score claim.
