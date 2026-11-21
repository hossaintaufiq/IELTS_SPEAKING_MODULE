# Architecture

Diagrams (system, lease/session lifecycle, one live turn, rollout, open decisions):
Whimsical board "IELTS Speaking Service - Architecture & Plan" in the Edumax Labs workspace (Shared section):
https://whimsical.com/DH9KKjvdcwEWYpGkVubkjh

## Shape

Two parts, one codebase:

- **Control plane** (always on, small CPU box): FastAPI gateway and WebSocket, lease/capacity manager, session orchestrator, question bank, Postgres, Redis, Celery assessment jobs.
- **GPU worker** (inference only): VAD + faster-whisper (STT), LLM via vLLM, Kokoro (TTS), wired with Pipecat.

The Node app talks to the control plane only. Students connect their audio WebSocket to the control plane with a short-lived signed token.

## Repository layout

```
speaking-service/
  control_plane/          FastAPI app, leases, sessions
    gpu_provisioner/      GpuProvisioner interface + implementations
  worker/                 Pipecat pipeline per session
    examiner/             test flow state machine, prompts
  assessment/             post-test scoring jobs
  question_bank/          questions, cue cards, pre-rendered audio
  models/                 model serving config and download scripts
  eval/                   metrics, datasets, benchmark and load-test scripts
  db/                     schema and migrations
  deploy/                 Docker Compose, GPU image
  docs/                   this folder
  tests/
```

## Live turn (target)

Student audio -> VAD end-of-turn -> faster-whisper transcript with word timestamps -> orchestrator.
Scripted phases play pre-rendered audio. LLM phases stream the first sentence to Kokoro as soon as it exists. Target: first audio under 2 s (unmeasured on GPU).
