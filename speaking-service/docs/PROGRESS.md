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
| 2026-11-21 | First live GPU session (vast.ai RTX 4090) | done | Real pipeline runs end to end: Whisper large-v3-turbo + Kokoro on GPU + vLLM Qwen2.5-7B-AWQ. Fixes found live: image had no sshd; destroy prompt; CPU ONNX Kokoro unusable (255-core host) -> onnxruntime-gpu 1.22 (0.2 s/sentence); VAD min_volume 0.6 heard nothing -> 0.3; mic worklet not connected to destination; vLLM killed with its tmux window. **Spend: about $1.04, of which $0.74 was download bandwidth ($53/TB)**; budget was $0.55 |
| 2026-11-21 | Company examiner rules ported (`worker/examiner/rules.py`, `llm.py`, `session.py`, `question_bank/ielts_bank.json`) | done (first turns verified live) | From ieltsup examCoreAPI/experimental: SCRIPT lines, timings, question engine (bank/personal/discussion modes, validation, fallbacks), 46 Part 1 topics + 50 cue cards. LLM pipeline stage removed; rule engine speaks via TTS on each finished turn. 27 tests pass; full Part 1-3 run not yet verified live |
| 2026-11-21 | Live captions (`LiveCaptionTap`) + mic meter in UI | done (captions verified live; browser mic path unverified) | User reported the browser mic still not being heard; meter added to diagnose |
| 2026-11-21 | Tester feedback fixes: hallucinated words, answering before the candidate finished, unasked repeats | done (unit-tested; NOT yet verified live) | `worker/stt.py` (decode off the event loop, company keyterm hints, confidence floor), `worker/examiner/speech.py` (noise phrases, unfinished sentences, real repeat requests), answer only after the candidate's pause (`ANSWER_PAUSE_S` 1.2 s, +`INCOMPLETE_EXTRA_S` 1.5 s after a trailing 'and/because'; waits while VAD says they are talking; merges turns that arrive in pieces), a question is never asked twice (bank used up -> next topic/part), LLM may only 'repeat' when asked. 40 tests pass. To verify on the next GPU session: pause length feels right; `STT_VAD_FILTER=0` if quiet speech is clipped |
| 2026-11-21 | Second GPU session (RTX 3090, about $0.19) | done | Verified live: examiner waits for the candidate's pause and merges a split answer, repeats only on request, start to greeting about 2.6 s. Found and fixed: CPU onnxruntime overwriting the GPU build in the setup script, jitter/clicks over a 198 ms path (page now buffers 0.35 s, shows an audio-gap counter and the reason for a disconnect), `rent` could only find 4090 offers |
| 2026-11-21 | Part 2 silence handling | done (verified live) | Silent candidate: after 10 s the examiner asks once ("Can you tell me about the topic you have been given?"; if they had started, the company's "anything more about that?" after 8 s), then a reminder 10 s later ("Remember, you have one to two minutes..."), then nothing more. `PART2_SILENCE_S`, `PART2_EARLY_STOP_S`, `PART2_REMIND_S` |
| 2026-11-21 | Off-test questions + name handling | done (verified live) | "Are you an AI?", "What's your name?", "How am I doing?" etc. get "This is an IELTS speaking test, so let's carry on." and the same question again (fixed rules + a new LLM instruction; the LLM can only trigger it for a real short question and its wording is never spoken). "You can call me X" in the first answer skips "what can I call you?". 74 tests pass |
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
