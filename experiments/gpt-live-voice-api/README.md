# GPT Live Voice (starter)

Minimal demo: talk to OpenAI's Realtime API from the browser over WebRTC.
FastAPI serves the page and relays the SDP handshake so the API key stays server-side.

## Run
```
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env     # then put your OPENAI_API_KEY in it
python server.py
```
Open http://127.0.0.1:8000 and press Start.

## Files
- `server.py` – FastAPI app, `/session` endpoint, examiner instructions
- `static/` – `index.html`, `style.css`, `app.js`

## Cost breakdown (OpenAI Realtime API)

Prices checked 19 Nov 2026 against the [official pricing page](https://developers.openai.com/api/docs/pricing), cross-checked with third-party summaries. **Re-check before budgeting; prices change.** Billing is per token, not per minute.

### Audio token rates (per 1M tokens)

| Model | Audio input | Cached input | Audio output |
|---|---|---|---|
| `gpt-realtime-2.1` | $32.00 | $0.40 | $64.00 |
| `gpt-realtime-2.1-mini` | $10.00 | $0.30 | $20.00 |

Text tokens (instructions, transcripts) are billed at separate, much lower text rates; they are small next to audio and are left out here.

### Converting to per-minute cost

OpenAI's documented approximation: the candidate's audio is about 1 token per 100 ms (**~600 tokens/min**), and the model's audio is about 1 token per 50 ms (**~1,200 tokens/min**).

| Model | Candidate speaking (per min) | AI speaking (per min) |
|---|---|---|
| `gpt-realtime-2.1` | 600 × $32/1M = **$0.019** | 1,200 × $64/1M = **$0.077** |
| `gpt-realtime-2.1-mini` | 600 × $10/1M = **$0.006** | 1,200 × $20/1M = **$0.024** |

The AI's voice costs about 4× the candidate's per minute, so cost depends mostly on how much the examiner talks.

### Example: one 14-minute IELTS speaking test

Assumption: candidate speaks 9 min, examiner 5 min (a placeholder split, not measured).

| | `gpt-realtime-2.1` | `gpt-realtime-2.1-mini` |
|---|---|---|
| Candidate audio (9 min) | $0.17 | $0.05 |
| Examiner audio (5 min) | $0.38 | $0.12 |
| **Floor (audio only)** | **≈ $0.56** | **≈ $0.17** |
| Context re-reads (see below), estimate | + $0.10 to $0.40 | + $0.03 to $0.10 |
| **Realistic range** | **≈ $0.65 – $1.00** | **≈ $0.20 – $0.30** |

| Volume | `gpt-realtime-2.1` | `gpt-realtime-2.1-mini` |
|---|---|---|
| 100 tests | $65 – $100 | $20 – $30 |
| 1,000 tests | $650 – $1,000 | $200 – $300 |
| 10,000 tests | $6,500 – $10,000 | $2,000 – $3,000 |

### Why the real bill is above the floor

- **The whole conversation is re-sent as context on every turn.** Earlier audio is billed again as input, at the cheap cached rate when the cache hits and at the full input rate when it doesn't. Long tests (Part 2 monologue, Part 3 discussion) grow this term. The "re-reads" row above is an estimate, not a measurement.
- **Silence and background noise** can still produce input tokens while the line is open. Close the session when a test ends.
- **Interruptions and retries** that generate discarded audio are still billed.
- **Input transcription** (for the on-screen transcript or scoring) is billed separately at the transcription model's rate.

### Ways to lower cost

1. Use the `-mini` model if quality is acceptable for the examiner role (about 70% cheaper).
2. Keep examiner turns short; output audio is the most expensive part.
3. Keep the system prompt stable so it stays in the cache.
4. Disconnect promptly after the test and cap session length server-side.
5. Run a real test and read the per-response token usage from the API's `response.done` events to replace the estimates above.

### Compared with the self-hosted plan

The repo's architecture proposal uses local Kokoro TTS + Whisper STT + a self-hosted LLM. That swaps per-minute API fees for fixed server cost, which only wins above some volume. Compute that break-even from measured RTF and your real server price, not from this table alone.
