# Decision Log

One entry per decision, newest last. Add a new entry instead of rewriting an old one; mark the old one superseded.

## D1: Separate service, fully local (2026-11-21)
The speaking module is its own service, hosted on GPUs, called by the company's Node app over an API. No external AI APIs. Load target: 10-12 concurrent students.

## D2: GPU is a pluggable resource (2026-11-21)
Phase 1 rents GPUs from two data centres (a lease of about one hour per class). Phase 2 uses 2-3 company-owned GPUs. Both sit behind `GpuProvisioner` so the Node-facing API does not change. See `control_plane/gpu_provisioner/base.py`.

## D3: Build on Pipecat (2026-11-21)
Pipecat (BSD-2, Python) is the framework for the live voice pipeline. Hugging Face `speech-to-speech` is used only for a quick latency benchmark, not as the base. LiveKit Agents was rejected because it adds a media server we do not need at this scale. Re-check if Pipecat's local-model support proves weak.

## D4: Model stack (2026-11-21), provisional
- STT: faster-whisper (model size to be chosen on real non-native speech).
- TTS: Kokoro-82M (see `docs/TTS_Tuning_and_Decisions.md`).
- LLM: an open model served with vLLM behind an OpenAI-compatible endpoint. Model chosen by evaluation, not by benchmark rankings. Ollama is for development only.
- No fine-tuning until prompts and a good base model show a specific gap.

## D5: Hybrid examiner (2026-11-21)
Intro, Part 1 and the Part 2 prompt are scripted with pre-rendered audio. The LLM is used for Part 2 follow-up and Part 3 only. Fluency is computed from STT timestamps, not guessed by the LLM. Pronunciation needs an audio-based method; it is never inferred from text alone.

## D6: Results are estimates (2026-11-21)
Output is labelled as estimated practice feedback, never an official IELTS band.

## D7: One complete exam service, not three parts (2026-11-24)
This is an ieltsup product. It is packaged as one service that runs the whole exam (our rules engine, STT, LLM, TTS), used by the ieltsup
server the way it uses a speech provider today: one WebSocket per test, one API key. It is not split into separate STT, LLM and TTS
services, because the rules engine would then have to be rebuilt inside ieltsup. Internals stay modular (vLLM is already a separate process).
Contract: `API_CONTRACT_V1.md`. Leases are dropped for v1 (fixed capacity). Pricing and billing are out of scope for now. D1 (no external AI APIs) still holds.

## D8: The repo root is the service; experiments live under experiments/ (2026-11-24)
The repository used to hold the service in a `speaking-service/` subfolder next to experiments, two browser labs and a GPT sample. The service is
now the project: `worker/`, `control_plane/`, `web/`, `docs/`, `tests/` and the rest sit at the repo root. `gpt-live-voice-api/`, `stt_lab/`, `tts_lab/`
and the old root README moved under `experiments/` (they were experiments; nothing in the service imports them). `doc/` moved into `docs/`.
History is kept (files were moved with git, not re-added). Consequence for deployment: `deploy/vast/upload.sh` no longer tars the current folder,
because the root can hold a private key; it sends the files git knows about minus a deny list, and `--list` shows what would be sent.

## D9: Saved tests are kept for 30 days (2026-11-26)
The service deletes a test's record and recording 30 days after saving them (`RETENTION_DAYS`). ieltsup keeps its own copy under its own
policy (its answer in `API_CONTRACT_V1.md`, section 7). The owner of this repo chose 30 days; it can be changed without code.
Server logs also contain what candidates said and are not covered by this: limiting them belongs to how the service is run.

## D10: One GPU server, one container (2026-11-26)
At most 10 students at once, almost all day (owner of this repo). One 24 GB GPU holds that (`GPU_TEST_2026-11-26.md`), so the service runs
as one container on one server: a small supervisor starts the language model, then the service, and restarts either (`deploy/docker/`).
No Kubernetes and no second server for now; the accepted cost is that tests stop while the server is down or being updated. The same image
can go to Kubernetes later.

## Open decisions

| Question | Current assumption | Owner |
|---|---|---|
| GPU models/VRAM (rented and planned) | 24 GB+ card hosts everything | Infra |
| Lease lead time from Node app | Requested ahead of class | Node team |
| Node team's LLM-service API shape | Reuse for leases/webhooks | Node team |
| Human-scored data source | Needed for eval + any fine-tune | Academic |
| Result format | Four criteria with bands, labelled estimates | Product |
| Lease-end grace period | A few minutes | Product |
| Multi-tenant | No, company only | Product |
