"""Tiny backend for a GPT live voice demo (OpenAI Realtime API over WebRTC).

The browser sends its WebRTC SDP offer to /session; this server forwards it to
OpenAI with the secret API key (which never reaches the browser) and returns
the SDP answer.
"""
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

load_dotenv()

API_KEY = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("REALTIME_MODEL", "gpt-realtime")
VOICE = os.getenv("REALTIME_VOICE", "marin")
STATIC = Path(__file__).parent / "static"

INSTRUCTIONS = (
    "You are a friendly IELTS Speaking examiner. Ask one short question at a "
    "time, listen, then follow up naturally. Keep replies brief."
)

app = FastAPI(title="GPT Live Voice")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.post("/session")
async def session(request: Request):
    if not API_KEY:
        raise HTTPException(500, "OPENAI_API_KEY is not set (see .env.example)")
    offer_sdp = (await request.body()).decode()
    config = {
        "type": "realtime",
        "model": MODEL,
        "instructions": INSTRUCTIONS,
        "audio": {"output": {"voice": VOICE}},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.openai.com/v1/realtime/calls",
            headers={"Authorization": f"Bearer {API_KEY}"},
            files={"sdp": (None, offer_sdp), "session": (None, json.dumps(config))},
        )
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return Response(r.text, media_type="application/sdp")


app.mount("/static", StaticFiles(directory=STATIC), name="static")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
