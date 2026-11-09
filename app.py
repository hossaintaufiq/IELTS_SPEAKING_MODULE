"""
Local-IELTS Web Application Server
FastAPI backend for interactive, browser-based mock testing and scoring.
"""

import os
import sys
import json
import base64
import time
from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from session.test_manager import IELTSTestManager

app = FastAPI(title="Local-IELTS AI Examiner", version="1.0.0")

class TurnPayload(BaseModel):
    session_id: str
    part: int
    question: str
    audio_base64: Optional[str] = None
    raw_text: Optional[str] = None
    duration: float = 10.0

class EvaluatePayload(BaseModel):
    session_id: str

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = IELTSTestManager(BASE_DIR)

# In-memory session tracking
active_sessions: Dict[str, Dict] = {}

@app.get("/api/health")
def health_check():
    return {
        "status": "online",
        "models": {
            "asr": "faster-whisper (local)",
            "tts": "kokoro-82m (local)",
            "examiner_llm": "llama-3.1-8b (local)",
            "scoring": "active (FC, LR, GRA, PR)"
        }
    }

@app.post("/api/start-session")
def start_session():
    session_id = datetime.now().strftime("test_%Y%m%d_%H%M%S")
    active_sessions[session_id] = {
        "session_id": session_id,
        "created_at": datetime.now().isoformat(),
        "current_part": 1,
        "turns": [],
        "cue_card": manager.question_bank["part_2_cue_cards"][0]
    }
    return {
        "session_id": session_id,
        "initial_message": "Good afternoon. My name is Emma. Could you tell me your full name, please?",
        "part": 1
    }

@app.get("/api/cue-card/{session_id}")
def get_cue_card(session_id: str):
    sess = active_sessions.get(session_id)
    if not sess:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return sess["cue_card"]

@app.post("/api/submit-turn")
async def submit_turn(payload: TurnPayload):
    session_id = payload.session_id
    sess = active_sessions.get(session_id)
    if not sess:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    transcript = ""
    words_data = []

    if payload.audio_base64:
        # Decode WAV
        audio_bytes = base64.b64decode(payload.audio_base64)
        wav_path = os.path.join(BASE_DIR, "storage", "audio", f"{session_id}_p{payload.part}_{int(time.time())}.wav")
        os.makedirs(os.path.dirname(wav_path), exist_ok=True)
        with open(wav_path, "wb") as f:
            f.write(audio_bytes)
        transcript, words_data = manager.asr.transcribe(wav_path)
    elif payload.raw_text:
        transcript = payload.raw_text.strip()
        # Create synthetic word timestamps
        words = transcript.split()
        curr_t = 0.5
        for w in words:
            words_data.append({"word": w, "start": round(curr_t, 2), "end": round(curr_t + 0.35, 2), "prob": 0.95})
            curr_t += 0.45

    turn_data = {
        "part": payload.part,
        "question": payload.question,
        "transcript": transcript,
        "duration": payload.duration,
        "words_data": words_data
    }
    sess["turns"].append(turn_data)

    # Dynamic Human-like Examiner Turn Generation
    next_question = None
    if payload.part == 1:
        answered_count = len([t for t in sess["turns"] if t["part"] == 1])
        if answered_count < 3:
            next_question = manager.examiner.generate_turn(transcript, part=1)
        else:
            sess["current_part"] = 2
    elif payload.part == 2:
        sess["current_part"] = 3
        # Introduce Part 3 with an inquiry linked to their Part 2 monologue
        next_question = manager.examiner.generate_turn(transcript, part=3)
    elif payload.part == 3:
        answered_count = len([t for t in sess["turns"] if t["part"] == 3])
        if answered_count < 3:
            next_question = manager.examiner.generate_turn(transcript, part=3)
        else:
            sess["current_part"] = 4 # Completed

    return {
        "received_transcript": transcript,
        "next_part": sess["current_part"],
        "next_question": next_question
    }

@app.post("/api/evaluate-session")
def evaluate_session(payload: EvaluatePayload):
    session_id = payload.session_id
    sess = active_sessions.get(session_id)
    if not sess or not sess["turns"]:
        # Run diagnostic report if no turns
        sample_transcript = (
            "Well, I grew up in a vibrant coastal town which was renowned for its scenic beaches "
            "and rich cultural heritage. However, in recent years, rapid urbanization has noticeably "
            "exacerbated the local traffic congestion. Although the local council has implemented several "
            "sustainable initiatives, much remains to be done."
        )
        sample_words = []
        t = 0.5
        for w in sample_transcript.split():
            sample_words.append({"word": w, "start": round(t, 2), "end": round(t + 0.35, 2), "prob": 0.94})
            t += 0.42
        turns = [{"transcript": sample_transcript, "duration": 18.0, "words_data": sample_words}]
    else:
        turns = sess["turns"]

    report = manager.evaluate_full_session(turns)

    # Persist report to storage
    out_file = os.path.join(BASE_DIR, "storage", "reports", f"{session_id}.json")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({"session_id": session_id, "turns": turns, "report": report}, f, indent=2)

    return report

@app.get("/", response_class=HTMLResponse)
def index():
    html_path = os.path.join(BASE_DIR, "ui", "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Local-IELTS Web UI is initializing...</h1>"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)

