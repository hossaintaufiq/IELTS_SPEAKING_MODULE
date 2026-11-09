# Project Structure & Resource Acquisition Guide

## Project: Local-IELTS AI Examiner & Scoring System
**Folder:** `D:\Office\IELTS-Speaking_Module`  
**Document:** System Architecture & Resource Catalog  
**Version:** 1.1.0  

---

## 1. Project Directory Structure

The repository is organized following clean architectural principles: separating the real-time audio loop, analytical scoring engines, test content data, automated test suites, and the browser interface.

```
IELTS-Speaking_Module/
│
├── PRD.md                           # Comprehensive Product Requirements Document (v1.1)
├── STRUCTURE.md                     # This document: Architecture & Resources catalog
├── PROJECT_UPDATES.md               # Engineering progress and milestone status
├── README.md                        # Quickstart and usage manual
├── requirements.txt                 # Python dependencies
├── setup_resources.py               # Automated one-click resource & dictionary setup
│
├── run_web_ui.bat                   # Double-click launcher for FastAPI Web App
├── run_cli.bat                      # Double-click launcher for Interactive CLI Mock Test
├── app.py                           # FastAPI Web Application & REST API
├── main.py                          # Interactive CLI Runner for tests and diagnostics
│
├── core/                            # Real-time Voice & Dialogue Subsystem
│   ├── __init__.py
│   ├── audio_capture.py             # Microphone input, audio buffering & Silero VAD
│   ├── transcriber.py               # Faster-Whisper ASR with word-level timestamps
│   ├── examiner_agent.py            # Local LLM persona (Ollama / GGUF auto-discovery)
│   └── tts_engine.py                # Kokoro-82M Text-to-Speech (British accent)
│
├── scoring/                         # Post-Test Analytical Scoring Pipeline
│   ├── __init__.py
│   ├── fluency_scorer.py            # WPM, pause duration, hesitation & filler metrics
│   ├── lexical_scorer.py            # TTR diversity & CEFR A1-C2 vocabulary profiler
│   ├── grammar_scorer.py            # Syntactic tree complexity & structural consistency
│   ├── pronunciation_scorer.py      # Rhythm variance, acoustic confidence & GoP
│   └── score_synthesizer.py         # Official IELTS Band (0-9) rounding & report generator
│
├── session/                         # Test Flow Controller
│   ├── __init__.py
│   └── test_manager.py              # State machine for Part 1, Part 2 (prep timer), Part 3
│
├── data/                            # Question Banks, Lexicons, and Prompts
│   ├── question_bank.json           # Authentic IELTS Part 1, 2, and 3 topics
│   ├── cefr_vocab_list.json         # Oxford 3000/5000 & CEFR A1-C2 lemma mapping
│   ├── discourse_markers.json       # Coherence transition phrases dictionary
│   └── fillers.json                 # Hesitation & filled pause dictionary
│
├── ui/                              # Web Interface
│   └── index.html                   # Single-Page App (Offline CSS, Web Audio Visualizer, PDF Print)
│
├── tests/                           # Automated Verification Suite
│   ├── test_scoring.py              # Unit tests for rounding math & scoring algorithms
│   └── test_api.py                  # End-to-end HTTP simulation test across all 3 parts
│
├── models/                          # Local Weight Storage (Git-ignored)
│   ├── llm/                         # Llama-3.1-8B GGUF weights (auto-discovered)
│   ├── asr/                         # Faster-Whisper cached checkpoints
│   ├── tts/                         # Kokoro-82M model and voice vectors
│   ├── grammar/                     # T5 grammar correction checkpoint
│   └── pronunciation/               # Wav2Vec2 SpeechOcean762 acoustic model
│
└── storage/                         # Local User Session Database (Git-ignored)
    ├── audio/                       # Candidate recorded .wav files per turn
    ├── sessions/                    # JSON session logs & transcripts
    └── reports/                     # Generated diagnostic scorecards
```

---

## 2. Resource Inventory & Where to Get Them

All models and datasets are **open-source, freely available, and run 100% on-device** without external cloud API subscriptions.

### Summary Resource Matrix

| Resource Category | Asset Name | Source / Repository ID | Disk Size | RAM/VRAM Required | Download Method |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Examiner LLM** | Llama-3.1-8B-Instruct (`Q4_K_M`) | `bartowski/Meta-Llama-3.1-8B-Instruct-GGUF` | 4.92 GB | ~6.0 GB VRAM | `huggingface-cli` or `ollama` |
| **Speech-to-Text (ASR)** | Faster-Whisper `medium.en` | `Systran/faster-whisper-medium.en` | 1.53 GB | ~2.0 GB VRAM | Auto-download via `faster-whisper` |
| **Voice Activity (VAD)** | Silero VAD v5 | `snakers4/silero-vad` (ONNX / Torch) | 1.8 MB | < 50 MB RAM | PyTorch Hub or direct ONNX download |
| **Text-to-Speech (TTS)** | Kokoro-82M + British Voices | `hexgrad/Kokoro-82M` | 330 MB | ~500 MB RAM | Hugging Face Hub / `kokoro` package |
| **Pronunciation / GoP** | Wav2Vec2 SpeechOcean762 | `facebook/wav2vec2-base-960h` / `mispeech` | 380 MB | ~1.0 GB RAM | Hugging Face `transformers` |
| **Grammar Correction** | T5-base Grammar Correction | `vennify/t5-base-grammar-correction` | 892 MB | ~1.5 GB RAM | Hugging Face `transformers` |
| **CEFR Vocabulary Data** | CEFR English Vocabulary Profile | Cambridge / Oxford 5000 Open Lexicon | ~15 MB | < 50 MB RAM | Generated via `setup_resources.py` |
| **NLP Syntax Engine** | NLTK + spaCy dual support | Pure Python / Explosion AI | ~30 MB | < 100 MB RAM | Built-in fallback in `setup_resources.py` |

---

## 3. Step-by-Step Acquisition Commands

### 3.1 Examiner LLM (Llama-3.1 8B Instruct)
* **Option A (Ollama):**
  ```bash
  ollama pull llama3.1:8b-instruct-q4_K_M
  ```
* **Option B (Direct GGUF download into `models/llm/`):**
  ```bash
  pip install huggingface_hub
  huggingface-cli download bartowski/Meta-Llama-3.1-8B-Instruct-GGUF Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf --local-dir models/llm
  ```

### 3.2 Speech-to-Text (Faster-Whisper)
* **Auto-managed by Python:**
  When `transcriber.py` runs, it automatically fetches and caches `Systran/faster-whisper-medium.en` into your local Hugging Face cache.
* **Manual Pre-download:**
  ```bash
  huggingface-cli download Systran/faster-whisper-medium.en --local-dir models/asr/medium.en
  ```

### 3.3 Text-to-Speech (Kokoro-82M)
* **Direct Download:**
  ```bash
  huggingface-cli download hexgrad/Kokoro-82M --local-dir models/tts
  ```

### 3.4 Linguistic Dictionaries & NLP
* **Automated Setup:**
  ```bash
  python setup_resources.py
  ```
  This creates `data/fillers.json`, `data/discourse_markers.json`, `data/cefr_vocab_list.json`, and downloads NLTK tokenizers (`punkt`, `wordnet`, `averaged_perceptron_tagger_eng`).

---

## 4. UI Offline Architecture (Zero-CDN)

The Web interface in `ui/index.html` is constructed with **zero external CDN dependencies**:
1. All styling is self-contained using modern CSS custom properties (`:root`).
2. Live audio frequency visualization is powered by the browser's native **HTML5 Web Audio API** (`AudioContext` and `AnalyserNode`).
3. Clean `@media print` styling is embedded so candidates can click **"Print / Save Official PDF Scorecard"** to export an official score report without requiring external PDF rendering services.
