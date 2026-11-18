# IELTS Speaking Test Engine — TTS & STT Test Labs

Early-stage work toward a self-hosted IELTS Speaking practice engine: an AI examiner that speaks (text-to-speech), listens to the candidate (speech-to-text), and gives feedback. This repository currently holds the **architecture proposal** and two **single-file browser test labs** used to evaluate the speech components before any server code is written.

> Status (18 Nov 2026): TTS standard configuration decided and a benchmark page is ready. Benchmark numbers have **not** been recorded yet. STT accuracy lab is built and untested. The server engine, LLM examiner and assessment are not started.

---

## Repository contents

```
.
├── README.md                      this file
├── doc/
│   ├── IELTS_Speaking_Engine_System_Architecture_Proposal.docx   architecture proposal v1.0
│   └── TTS_Tuning_and_Decisions.md                               every TTS setting, why, and what is still open
├── tts_lab/
│   └── tts_browser.html           Kokoro TTS test page + benchmark + server sizing/cost estimator
└── stt_lab/
    └── stt_browser.html           Whisper accuracy lab (WER/CER, word diff, filler tracking)
```

Earlier prototype code (a local CLI/web app) was removed from the working tree. It is still available in git history.

## The plan

The architecture proposal describes one permanent **modular monolith**: FastAPI (REST + WebSocket), Kokoro TTS, faster-whisper STT, a self-hosted LLM, PostgreSQL, Redis, Celery and Docker. Work proceeds in this order:

1. **TTS** — choose and tune the examiner voice, pass latency and quality benchmarks locally. *(in progress; this repo)*
2. **STT** — measure transcription accuracy on realistic candidate speech. *(lab built, not yet run)*
3. **LLM** — examiner dialogue and assessment, then any fine-tuning. *(not started; nothing decided)*
4. **Server integration** — Python/GPU service, WebSocket streaming, load tests. *(not started)*

See `doc/` for the full proposal. The proposal itself states that capacity claims must be established by benchmarks, and that results are *estimated practice feedback*, not official IELTS scores.

---

## Running the labs

Both labs are single HTML files with no build step and no backend.

**Requirements:** a current Chrome or Edge, and an internet connection on first load (the page fetches a JavaScript library from a CDN and model files from Hugging Face; the browser caches them afterwards). Open the file by double-clicking it, or serve the folder with any static file server.

### TTS lab — `tts_lab/tts_browser.html`

Runs the Kokoro-82M model in the browser through ONNX/WebAssembly (CPU).

1. Open the file and wait for "Model ready" (first load downloads about 330 MB for the fp32 model).
2. Paste text into the box (write `[pause]` for an extra break) and press **Speak**. Audio streams sentence by sentence.
3. **Test my text ×5** runs your text five times and scores it. **Full benchmark** runs three built-in feedback texts (short, medium, long) plus your text, five runs each.
4. Read the pass/fail table, the measured-on-this-machine cards, and the server sizing and cost estimate.

**Fixed standard configuration** (no switches on the page):

| Setting | Value |
|---|---|
| Model | Kokoro-82M, **fp32**, via `kokoro-js` 1.2.1 |
| Voice | **`bf_emma` 75% + `bf_alice` 25%** (blended style vectors) |
| Speed | **0.95** (± 0.02 repeatable variation per chunk) |
| Mode | **Feedback** — streamed, first chunk kept short |
| Pauses | 0.30 s after statements, 0.45 s after questions, +0.60 s for `[pause]`, then 20% tighter in streaming mode |
| Processing | edge-silence trim, 80 Hz high-pass, even loudness at −3 dBFS, 5 ms fades |
| Target first audio | 1.5 s (editable; a placeholder, not a requirement) |

The reasoning behind each value, and what was tried before it, is in [`doc/TTS_Tuning_and_Decisions.md`](doc/TTS_Tuning_and_Decisions.md).

**Benchmark metrics**

| Metric | Meaning |
|---|---|
| First audio | Time from pressing Speak until the first sentence is ready to play (p50 / p95) |
| RTF | Real-time factor: generation time ÷ speech duration. Below 1.0 means speech is generated faster than it plays |
| Stalls | Times the next sentence was not ready when the previous one finished playing (an audible gap) |
| Words/min | Speaking pace, both speech-only and including pauses |
| JS heap | Browser JavaScript memory. Does **not** include the model's WASM memory — read the real figure in Chrome Task Manager |

**Pass criteria:** first-audio p95 ≤ target, RTF p95 < 1.0, zero stalls. Benchmarks run one request at a time; concurrency is not tested.

**Server sizing and cost estimator.** Turns the measured RTF into core, RAM, server count and monthly cost estimates for a given load. Every input is editable and every default is a **placeholder** (100 concurrent tests, $150/month server, and so on). The proposal's 5,000–6,000 peak figure is still unvalidated. Treat the output as an illustration of method, not a quote.

### STT lab — `stt_lab/stt_browser.html`

Runs OpenAI Whisper models (tiny.en, base.en, small.en on CPU; large-v3-turbo on WebGPU) in the browser through `@huggingface/transformers`.

1. Choose a model and press **Load model**.
2. Record with the microphone or upload an audio file. Audio is processed locally and is not uploaded anywhere.
3. Type exactly what was said as the reference (three sample passages are provided to read aloud).
4. Press **Transcribe & score**.

You get WER and CER, substitution/deletion/insertion counts, a word-by-word colored comparison, filler-word counts (spoken → transcribed, since Whisper tends to drop "um/uh"), transcription time, RTF, a history table, per-model averages and a CSV export.

**Caveat:** the planned server engine is *faster-whisper*, which uses the same Whisper weights through a different runtime. Accuracy by model size should carry over; speed will not. Run several clips from different speakers and accents per model — one clip proves little.

---

## Known limitations

- Browser measurements are **not** server measurements. RTF, latency and memory must be re-measured with the Python engine on the real GPU server.
- The browser page runs the model on a single thread; a server will behave differently.
- Voice quality was judged by ear by the project owner. No MOS scores, listening-panel results or round-trip WER numbers exist yet.
- Concurrent-load behavior (the target is 10–15 simultaneous students) has not been tested.
- The STT lab has not been run yet, and the LLM/assessment stages are not started.
- Pronunciation scoring from a transcript alone is not valid; it needs its own method (see the proposal).

## Third-party components

| Component | Used for |
|---|---|
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) and [kokoro-js](https://www.npmjs.com/package/kokoro-js) | Text-to-speech |
| [OpenAI Whisper](https://github.com/openai/whisper) via [Transformers.js](https://huggingface.co/docs/transformers.js) | Speech-to-text lab |
| ONNX Runtime Web | In-browser inference |

Check each project's current license before any commercial deployment; this repository does not yet declare a license of its own.
