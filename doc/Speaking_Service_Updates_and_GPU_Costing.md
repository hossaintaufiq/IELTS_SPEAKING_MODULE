# Speaking Service: Updates Log and GPU Costing

**Date:** 21 November 2026 · **Branch / repo:** `speaking-service/` in `rbrclabs/local_first_speaking_module`
**Status:** a fully local IELTS speaking-test service (STT + LLM + TTS on GPU). It has run end to end on a rented GPU, but only in short single-user tests. Quality, accuracy and multi-student capacity are **not yet measured**.

> **Honesty note.** Numbers are labelled by how we got them: **measured** (we ran it), **live-quoted** (read from vast.ai today), **sourced** (a web page, linked at the end) or **assumption** (my estimate; replace with real quotes before deciding anything).

---

## 1. What was built (`speaking-service/`)

| Area | What exists | State |
|---|---|---|
| **Voice pipeline** (`worker/pipeline.py`) | Browser WebSocket → VAD + end-of-turn detection → Whisper STT → rule engine → Kokoro TTS → browser. Built on Pipecat 0.0.108. | Runs on GPU (measured) |
| **Examiner rules** (`worker/examiner/rules.py`) | Port of the company's `ieltsup/.../experimental` rule set: fixed script lines, exam timings (Part 1 4–5 min, Part 2 1 min prep + 2 min talk, Part 3 4–5 min), question engine (bank / personal / discussion modes, validation, fallbacks, no praise, banned topics). | First turns verified live; full run by tests only |
| **Question bank** (`question_bank/ielts_bank.json`) | The company bank converted unchanged: 46 Part 1 topics, 50 cue cards. | Done |
| **Test flow** (`worker/session.py`) | Intro → name → Part 1 → Part 2 (card, prep, long turn, follow-up) → Part 3 → close. Skip/end buttons. Run log per test. | Unit-tested |
| **Listening quality** (`worker/stt.py`, `examiner/speech.py`) | Decode off the event loop; Whisper hints from the company keyterm list; noise-phrase filter; examiner answers only after the candidate's pause (1.2 s + 1.5 s after "and/because"); merges answers that arrive in pieces; a question is never asked twice; repeats only when asked. | Unit-tested, **not yet live** |
| **Echo protection** | Browser echo cancellation on; server ignores the mic while the examiner speaks (+0.7 s tail). | Unit-tested, not tested with speakers |
| **Live captions** (`worker/taps.py`) | Rolling partial transcript while the candidate speaks, replaced by the final text. | Verified live (32 updates in a run) |
| **Speed** (`worker/warm.py`) | Whisper and Kokoro load once at server start. Start → greeting: about 3 s (was about 10 s). | Measured |
| **Web UI** (`web/`) | Test page: orb, timers, cue card, transcript, reply-delay stats, **pre-test microphone check** (device picker, live spectrum, level, frequency, verdict), silence warning. | Used live |
| **Control plane** (`control_plane/`) | Lease and session API skeleton with signed tokens, 12-seat cap, `GpuProvisioner` interface (fake only). | Tests only; no database, webhooks or real GPU provisioner |
| **Eval tools** (`eval/`) | WER and latency metrics; STT/TTS/LLM benchmark scripts; `ws_probe.py` and `ws_flow.py` (an automated "candidate" that speaks to the live server). | Probes used live; benchmarks not run |
| **GPU rental tooling** (`deploy/vast/`) | `vast.py` (search, guarded rent with price cap, stop, start, destroy), setup script for the vast image, safe upload script (no secrets), runbook. | Used live |
| **Docs / tests** | `docs/` progress log, decisions, architecture, draft API; **40 tests pass**. | Done |

### Repository history
| Event | Reference |
|---|---|
| First push, merged as PR #23 | `b3624c8` → merge `e07845e` on company `main` |
| Examiner rules, captions, half-duplex mic, mic check, speed | `2fbed25` pushed straight to company `main` |
| Listening fixes (pauses, hallucinations, repeats) | `0d9d057`, merged as **PR #24** (`d70d500`) on company `main` |
| This document | PR `docs/speaking-service-updates-and-gpu-costing` |

---

## 2. Problems found while testing live (and fixes)

| Problem | Cause | Fix |
|---|---|---|
| Instance never became reachable | Plain PyTorch image has no SSH server | Use vast's own image |
| `destroy` did nothing | CLI waits at an "Are you sure?" prompt; the safety timer would have failed too | Wrapper answers the prompt |
| Setup paths wrong | Image has no `/workspace`, Python is in `/venv/main` | Rewrote setup script |
| vLLM disappeared | Killed when its parent tmux window closed | Own tmux session |
| Voice reply took 10+ s | Kokoro ran on a CPU with 255 cores shown (thread flood) | `onnxruntime-gpu` 1.22: **0.2 s per sentence** (CPU: over 100 s for six) |
| Speech never detected | VAD volume gate 0.6 too strict | Gate removed, confidence 0.5 |
| Browser mic silent | Worklet not connected; later, wrong/muted device (peak level 0.0003 saved in the run log) | Mic check page, device picker, silence warning |
| Examiner answered itself | I had disabled echo cancellation | Echo cancellation back on; mic ignored while the examiner speaks |
| Slow to start | Models reloaded per session | Load once at server start |
| Answered before the candidate finished; hallucinated words; repeated questions | See section 1 (listening quality) | Fixed in `0d9d057`, unverified live |
| Run logs about to be committed | Broken `.gitignore` line | Fixed before pushing |

**Measured results (single-user probes on one RTX 4090):** examiner reply 0.3–0.6 s from end of speech to first audio (inside the server); Kokoro 0.2 s per sentence (real-time factor 0.06); start to greeting about 3 s; GPU memory about 14 GB used with the LLM loaded.

---

## 3. What the GPU testing actually cost

**First session, measured: $1.39 of the $8.99 credit** (credit $8.99 → $7.60). The budget I was given for the first test was **$0.55**, so **I overspent it**: I under-estimated one cost.

| Item | Amount | Basis |
|---|---|---|
| Failed first instance (image without SSH), about 10 min | ≈ $0.02 | Credit change |
| Main instance: RTX 4090, Vietnam host, about 99 min at $0.398/h (includes 60 GB disk) | ≈ $0.66 | Instance billing fields |
| **Download bandwidth, about 13.9 GB at $53.33 per TB** | **≈ $0.71–0.74** | Instance billing fields |
| **Total** | **$1.39** | Measured from credit |

**Lessons that change the cost model**
1. **Bandwidth was over half the bill.** Installing vLLM and downloading the models cost more than the GPU time. This host charges $0.0533/GB.
2. **Hosts differ 10–20× on download price.** In today's offers, L40S and A100 hosts quote $0.0027–0.0053/GB; the cheapest 4090 hosts $0.0533/GB. Choose the host by download price too, or avoid downloads altogether (custom image or persistent volume with the models baked in).
3. **A stopped instance still bills for disk** (about $0.028/h for 60 GB). Destroy it unless you will resume soon.
4. A **cold start** (boot + model load) is billed time. Budget about 15 extra minutes per lease.

---

### Second session (applying the lessons): about $0.19

| Item | Amount |
|---|---|
| Host | RTX 3090 (24 GB), Bulgaria, **$0.214/h**, download price about $0.0014/GB |
| Session length | about 50 minutes (setup, automated checks, live testing) |
| Bandwidth billed | about 13.4 GB, which cost almost nothing at that rate |
| **Cost** | **about $0.19** (credit $7.60 → $7.41), against $1.39 for the first session |

**Total spent on GPU testing across both sessions: about $1.58** (credit $8.99 → $7.41).

What the cheaper host cost us: a slower GPU than the 4090, and **about 198 ms of network round trip** to Bulgaria (stable, no loss). That delay is physical distance and made audio playback click until the page was given a larger audio buffer. For a nearer host, search Asia (Singapore, India, Japan) and accept a somewhat higher hourly price.

Setup lesson: `kokoro-onnx` pulls in the CPU `onnxruntime`, which overwrites `onnxruntime-gpu` if installed afterwards. Install the GPU build **last** or Kokoro takes about 48 s per sentence instead of 0.2 s. The setup script now does this and stops if the GPU provider is missing.

## 4. Renting GPUs: cost per test

### Live-quoted prices today (vast.ai, verified hosts, 1 GPU, reliability > 98%, per GPU-hour including a 60 GB disk)

| GPU | VRAM | Cheapest | Median | Download $/GB |
|---|---|---|---|---|
| RTX 3090 | 24 GB | $0.21 | $0.26 | 0.016 |
| **RTX 4090** (what we used) | 24 GB | **$0.40** | $0.52 | 0.053 |
| RTX A6000 | 48 GB | $0.42 | $0.53 | 0.000 |
| A100 (PCIe / SXM4) | 40 GB | $0.42 | $0.69 / $0.98 | 0.005 / 0.003 |
| RTX 5090 | 32 GB | $0.50 | $0.67 | 0.005 |
| L40S | 45 GB | $0.54 | $0.81 | 0.003 |
| H100 SXM | 80 GB | $2.35 | $2.48 | 0.003 |

Marketplace prices move hour to hour. Your company's two data centres may quote differently: ask them for a per-GPU-hour price and compare.

### Model (assumptions: replace with measurements)
- **Capacity: 10–12 concurrent students per GPU is an assumption.** We only ran single sessions. The 4090's 24 GB showed about 14 GB used with one session, so memory may allow it, but throughput under load is **not measured**.
- Each class lease = 1 h of use + 0.25 h boot and model load = **1.25 billed hours**. Models are pre-cached (no re-download).

| Students per lease | Cost per test at $0.40/h | at $0.52/h |
|---|---|---|
| 12 (full class) | **$0.042** | $0.054 |
| 6 (half-full) | $0.083 | $0.108 |

### Monthly cost by volume (compute only; 4090 at $0.40 and $0.52 per hour)

| Tests per month | 12 per lease | 6 per lease |
|---|---|---|
| 100 | $4 – $5 | $8 – $11 |
| 1,000 | $42 – $54 | $83 – $108 |
| 5,000 | $208 – $271 | $417 – $542 |
| 10,000 | $417 – $542 | $833 – $1,083 |

**If the models are re-downloaded every lease on a high-bandwidth-price host, add about $0.71 per lease**, which would dominate the table. That is the mistake in section 3.

For comparison, earlier repo notes calculated (not measured) about $0.65–1.00 per 14-minute test on the OpenAI Realtime API, and about $0.06 for a hybrid design. Self-hosted rental looks cheaper than the full API **only if** classes are mostly full.

---

## 5. If the company owns the GPUs

The company plans to buy two or three GPUs for its data centre. Costs below are **my estimates from sourced prices and stated assumptions**; get vendor and data-centre quotes before deciding.

### Purchase prices found
| Item | Price found | Source quality |
|---|---|---|
| RTX 4090 (24 GB) | No current new price found; one used listing at about **$1,500** | Weak (one secondhand figure) |
| RTX 5090 (32 GB) | List $1,999, but street prices about **$3,300–$9,400** this month (AI-driven shortage) | Sourced, sources disagree |
| RTX 6000 Ada (48 GB) | About **$5,000–7,000** (launch $6,800) | Older / undated |
| L40S (48 GB, data-centre card) | From about **€7,700** in one German listing | Undated snapshot |
| Server chassis (CPU, 128 GB RAM, NVMe, PSU) | about $1,500–3,000 | **Assumption** |

### Important licence caveat (verify first)
NVIDIA's GeForce driver terms have historically **restricted data-centre deployment of GeForce cards** (RTX 4090 / 5090). I could not confirm the current wording from the pages I found. If it applies, the company would need data-centre or professional cards (L40S, RTX 6000 Ada class), which cost about 3–5× more than a 4090. **Check the current NVIDIA driver licence and ask NVIDIA or a distributor before buying GeForce cards for a data centre.**

### Monthly cost of owning (36-month straight-line depreciation; power at $0.12/kWh; hosting assumed $100 per server per month; staff, spares and downtime not included)

| Scenario | Capex | Depreciation | Power (24/7) | Hosting | **Per month** |
|---|---|---|---|---|---|
| 1 server, 1× RTX 4090 (used) | $3,500 | $97 | $53 | $100 | **≈ $250** |
| 1 server, 1× L40S | $10,500 | $292 | $48 | $100 | **≈ $440** |
| 3 servers, 3× L40S | $31,500 | $875 | $144 | $300 | **≈ $1,320** |

### Own or rent? Break-even
Owning is a fixed monthly cost; renting is pay per hour. They cost the same at:

| Scenario | vs rent at | Break-even hours/month | Share of the month |
|---|---|---|---|
| 4090 owned ($250) | $0.40/h – $0.52/h | 625 – 480 h | 86% – 66% |
| L40S owned ($440) | $0.54/h – $0.81/h | 809 – 543 h | 111% – 74% |

**Reading it:**
- **Class-based use** (for example 40 hours a week, about 170 h/month) costs about **$70/month to rent one GPU**, against $250–440/month to own it. **Rent.**
- **Owning pays off only with near-constant use** (roughly two-thirds of all hours or more), or when you value guaranteed capacity and keeping student audio on your own hardware.
- A **hybrid** is sensible: own one GPU for the baseline load and rent for peaks.
- At current street prices, GeForce 5090s make owning even less attractive.

### What to ask the company
1. The data centres' price per GPU-hour and any bandwidth or storage fees.
2. The GPU models and VRAM they offer or plan to buy.
3. Expected hours per month and concurrent students per class. This number decides rent versus own.

---

## 6. Still open
- **Live verification** of the listening fixes (pause length, hallucinations, repeats), full Part 1 → 3 with a real voice, and the echo guard with speakers.
- **Capacity:** concurrent 10–12 students on one GPU (throughput, VRAM, shared-model thread-safety).
- **STT accuracy** on real non-native speech (no labelled clips yet).
- **Scoring** (fluency, vocabulary, grammar, pronunciation) and the **Node integration** (database, webhooks, real GPU provisioner).
- **Next GPU session plan:** set a budget of about $2, pick a host with low download price (or pre-bake the models), and keep the first run short.

---

## Sources
- [vast.ai live offers](https://vast.ai): queried 21 Nov 2026 with `deploy/vast/vast.py` (prices in section 4).
- [RTX 5090 pricing, November 2026 (GPU Poet)](https://gpupoet.com/gpu/learn/price/november-2026/nvidia-geforce-rtx-5090) and [Tech Insider](https://tech-insider.org/nvidia-rtx-50-prices-rise-november-2026-rtx-5090-3340/)
- [RTX 6000 Ada listed at $6,800 (TweakTown)](https://www.tweaktown.com/news/90105/nvidia-rtx-6000-ada-workstation-gpu-listed-at-6800-with-48gb-of-memory/index.html)
- [L40S vs RTX 6000 Ada, inference and pricing (Spheron)](https://www.spheron.network/blog/nvidia-l40s-vs-rtx-6000-ada-cheapest-gpu-inference-2026/)
- [Used GPU server buying guide 2026](https://pcserverandparts.com/news/used-gpu-server-buying-guide-2026-l40s-vs-a100-vs-rtx-4090/)
- [NVIDIA forum thread on 4090s in a data centre](https://forums.developer.nvidia.com/t/nvidia-geforce-rtx-4090s/262442) (informal; not an authoritative licence statement)
