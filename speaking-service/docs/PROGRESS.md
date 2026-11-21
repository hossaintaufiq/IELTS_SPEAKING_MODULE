# Progress Tracker

Single place to see what is done, what is next, and what is blocked. Update it in the same commit as the work.
Status: `todo` / `doing` / `done` / `blocked`. Dates are the day the status changed.

## Milestones

| # | Milestone | Status | Exit criteria |
|---|---|---|---|
| M0 | Project scaffold, docs, first tests | done (2026-11-21) | Folder, branch, tests pass |
| M1 | Eval harness + model benchmark on the real GPU | todo | STT WER measured on non-native speech; first-audio latency measured; 10-12 stream load test |
| M2 | Voice pipeline (Pipecat: VAD, faster-whisper, LLM via vLLM, Kokoro) | todo | CLI/WebSocket conversation works; first audio under 2 s p95 at 10-12 streams |
| M3 | Examiner (Part 1/2/3 flow, prompts, pre-rendered audio) | doing | Full mock test runs end to end |
| M4 | Control plane (leases, sessions, tokens, webhooks) | todo | Node team can run a lease + session against a fake GPU, then a real one |
| M5 | Assessment (fluency, LR/GRA, pronunciation) | todo | Scores correlate with human scores on the eval set |
| M6 | Deploy + pilot (one class of 10-12) | todo | Pilot completed, cost and latency recorded |
| M7 | Owned GPUs (phase 2) | todo | Provisioner swapped, API unchanged |

## Task log

| Date | Task | Status | Notes |
|---|---|---|---|
| 2026-11-21 | Create branch `feat/speaking-service`, folder `speaking-service/` | done | Branched from `feat/gpt-live-voice-api`; unrelated uncommitted changes in the tree are left alone |
| 2026-11-21 | WER + latency metrics (`eval/metrics.py`) | done | 4 tests |
| 2026-11-21 | GPU provisioner interface + fake (`control_plane/gpu_provisioner`) | done | 3 tests; real DC provisioner not written |
| 2026-11-21 | Test flow state machine (`worker/examiner/flow.py`) | done | 1 test; prompts and LLM hook-up not written |
| 2026-11-21 | vast.ai prep: SSH key, guarded `vast.py` wrapper, `setup_instance.sh`, `RUNBOOK.md` | done | Nothing rented. Search verified live (4090 from about $0.40/h); setup script untested on a GPU |
| 2026-11-21 | Benchmarks: `eval/bench_llm.py`, `bench_stt.py`, `bench_tts.py` | done (untested on GPU) | Compile only; run during the vast.ai session |
| 2026-11-21 | vast.ai API key | blocked | Key authenticates, but its account shows $0.00; company credit is not reachable from it (probably a team-account issue) |
| 2026-11-21 | Pipecat pipeline (`worker/pipeline.py`) | doing | Written against installed Pipecat 0.0.108; all imports verified. NOT run end to end; serializer/browser client and constructor args need checking on the GPU box |
| 2026-11-21 | Live test bench: web UI (`web/`), `worker/server.py`, `worker/session.py`, `worker/protocol.py`, `worker/taps.py` | done (untested live) | Browser speaking test: Part 1/2/3, cue card, timers, Next/End, transcript, reply-delay stats, run log. 19 tests pass incl. a mock-mode server. Real pipeline cannot be built on the dev PC (Application Control blocks `av` DLL); first real run is on the GPU box |
| 2026-11-21 | Examiner prompts + draft question bank | done (draft) | `worker/examiner/prompts.py`, `question_bank/questions.json`; placeholders, not evaluated or academically approved |
| 2026-11-21 | Control-plane API skeleton (`control_plane/app.py`) | done (draft) | Leases, sessions, signed tokens, seat limits; 5 tests. In-memory + fake GPU only: no DB, no webhooks, no audio WebSocket |
| 2026-11-21 | Real eval data (non-native speech clips + transcripts) | blocked | Needs recordings; nobody has supplied them yet |

## Blocked / waiting on

- **GPU access**: this dev machine has no NVIDIA GPU (`nvidia-smi` not found). M1 and M2 latency numbers need the real server. Need the GPU model and VRAM from the infra team.
- **Human-scored IELTS data** for the assessment eval set (M5).
- **Node team's existing LLM-service API shape**, to copy for leases and webhooks (M4).

## Not verified yet

Everything below is a plan or an assumption, not a measurement:
- One 24 GB+ card can host the LLM, STT and TTS for 10-12 streams.
- Turn latency on GPU is under 2 s.
- Pipecat's current API matches what we plan to write (check the installed version's docs first).
