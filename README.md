# Local-IELTS: On-Device AI IELTS Speaking Examiner & Scoring System

An end-to-end, 100% offline AI system that conducts full official-grade IELTS Speaking tests (Parts 1, 2, and 3) and computes diagnostic Band 0.0–9.0 scorecards directly on your local workstation without external cloud APIs.

---

## Key Features

* **100% On-Device & Air-Gapped:** Zero telemetry, no cloud API subscriptions (no OpenAI, no ElevenLabs).
* **Self-Contained Offline Web Console:** Zero external CDN dependencies (works with or without internet access).
* **Live HTML5 Audio Waveform Visualizer:** Real-time frequency bars while the candidate speaks.
* **Human-like Conversational Flow:**
  * **Dynamic Contextual Inquiry:** The examiner listens to what the candidate actually says and produces relevant, tailored follow-up questions rather than repeating hardcoded lists.
  * **Zero Manual Voice Buttons:** The examiner speaks automatically when asking questions.
  * **Hands-Free Silence / Pause Detection (VAD):** Candidates do not need to click "Stop & Submit". A natural 2.2-second conversational pause automatically concludes the turn and prompts the examiner to respond.
* **Official 3-Part State Machine:**
  * **Part 1:** Introduction and familiar interview questions.
  * **Part 2:** Cue card long-turn with an automated 60-second preparation countdown timer and digital scratchpad.
  * **Part 3:** Thematic, abstract two-way discussion questions.
* **Multi-Metric Scoring Engine:**
  * **Fluency and Coherence (FC):** Words Per Minute (WPM), pause gap distributions (>400ms), and filler density.
  * **Lexical Resource (LR):** Type-Token Ratio (TTR), CEFR A1–C2 tier distribution, and discourse markers.
  * **Grammatical Range and Accuracy (GRA):** Subordinate clause depth, complex sentence ratios, and structural consistency.
  * **Pronunciation (PR):** Acoustic timing continuity, rhythm variance, and phonemic confidence.
* **Official Cambridge / British Council Rounding:** Strictly implements official IELTS rounding (`.25` $\to$ `.5`, `.75` $\to$ next band).
* **Printable PDF Scorecard:** One-click print styling to export an official evaluation report.

---

## Project Structure

```
IELTS-Speaking_Module/
├── PRD.md                  # Comprehensive Product Requirements Document (v1.1)
├── STRUCTURE.md            # Architecture & Resource Catalog (Hugging Face IDs)
├── PROJECT_UPDATES.md      # Detailed engineering milestone status
├── README.md               # User guide and quickstart manual
├── requirements.txt        # Python library dependencies
├── setup_resources.py      # Automated model and dictionary setup script
│
├── run_web_ui.bat          # Double-click launcher for Web Server
├── run_cli.bat             # Double-click launcher for CLI Exam
├── app.py                  # FastAPI Web Application & REST API
├── main.py                 # Interactive CLI Runner for tests and diagnostics
│
├── core/                   # Audio recording, ASR, LLM Examiner, and Kokoro TTS
├── scoring/                # Computational scorers for FC, LR, GRA, and PR
├── session/                # 3-part test state machine manager
├── data/                   # Question banks, fillers, and CEFR lexicons
├── ui/                     # Single-Page Web App (Zero-CDN offline CSS)
├── tests/                  # Unit tests and API simulation tests
├── models/                 # Local GGUF, Whisper, and TTS checkpoints
└── storage/                # Recorded candidate audio and saved score reports
```

---

## Quickstart Guide

### 1. Launch via Double-Click (Windows)
* Double-click **`run_web_ui.bat`** to start the web console on **`http://127.0.0.1:8000`**.
* Double-click **`run_cli.bat`** to start the interactive terminal exam.

---

### 2. Launch via Terminal / PowerShell

#### Start the Web Application Console:
```powershell
python .\app.py
```
Open **`http://127.0.0.1:8000`** in your browser.

#### Run Instant Diagnostic Test (No Microphone Required):
```powershell
python .\main.py
# Select Option 1
```

#### Run Full Interactive Mock Test in Terminal:
```powershell
python .\main.py
# Select Option 2
```

---

## Running the Automated Test Suites

### 1. Unit Tests for Scoring & Rounding Rules
```powershell
python .\tests\test_scoring.py
```
*Validates that Cambridge `.25` and `.75` rounding rules, WPM thresholds, and CEFR lexicons compute accurately.*

### 2. End-to-End API Simulation Test
```powershell
python .\tests\test_api.py
```
*Simulates a complete candidate session across Parts 1, 2, and 3 through the FastAPI REST server.*

---

## Hardware Requirements

* **Minimum:** 16 GB RAM + 6 GB VRAM (RTX 3060 / Apple M1)
* **Recommended:** 32 GB RAM + 12 GB VRAM (RTX 3060 12GB / RTX 4070+)
* **CPU Fallback:** Fully supported for testing, scoring, and UI execution.
