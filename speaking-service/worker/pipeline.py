"""Live voice pipeline for one student session (Pipecat 0.0.x API).

    browser WebSocket -> VAD/turn detection -> faster-whisper STT -> LLM (local, OpenAI-compatible)
        -> Kokoro TTS -> browser WebSocket

Everything runs on the local GPU server; the LLM URL points at our own vLLM, never a hosted API.

STATUS: written against the installed Pipecat 0.0.108 API and import-checked only. It has NOT been
run end to end (no GPU here). Heavy imports are inside build_task() so the rest of the package
imports without them.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from worker.examiner.prompts import system_prompt
from worker.protocol import SPEAKER_RATE, BrowserSerializer


@dataclass
class WorkerConfig:
    llm_base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", "http://localhost:8000/v1"))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct-AWQ"))
    whisper_model: str = field(default_factory=lambda: os.getenv("WHISPER_MODEL", "small.en"))
    whisper_device: str = field(default_factory=lambda: os.getenv("WHISPER_DEVICE", "cuda"))
    whisper_compute_type: str = field(default_factory=lambda: os.getenv("WHISPER_COMPUTE", "float16"))
    kokoro_model_path: str = field(default_factory=lambda: os.getenv("KOKORO_MODEL", "models/cache/kokoro-v1.0.onnx"))
    kokoro_voices_path: str = field(default_factory=lambda: os.getenv("KOKORO_VOICES", "models/cache/voices-v1.0.bin"))
    kokoro_voice: str = field(default_factory=lambda: os.getenv("KOKORO_VOICE", "bf_emma"))


def build_task(websocket, cfg: WorkerConfig, session):
    """Create the PipelineTask for one student. `websocket` is an accepted FastAPI WebSocket."""
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContextAggregatorPair,
        LLMUserAggregatorParams,
    )
    from pipecat.services.kokoro.tts import KokoroTTSService
    from pipecat.services.openai.llm import OpenAILLMService
    from pipecat.services.whisper.stt import WhisperSTTService
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

    from worker.taps import OutputTap, UserTextTap

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=BrowserSerializer(session),
        ),
    )
    stt = WhisperSTTService(
        device=cfg.whisper_device,
        compute_type=cfg.whisper_compute_type,
        settings=WhisperSTTService.Settings(model=cfg.whisper_model),
    )
    llm = OpenAILLMService(
        base_url=cfg.llm_base_url,
        api_key="local",
        settings=OpenAILLMService.Settings(model=cfg.llm_model),
    )
    tts = KokoroTTSService(
        model_path=cfg.kokoro_model_path,
        voices_path=cfg.kokoro_voices_path,
        settings=KokoroTTSService.Settings(voice=cfg.kokoro_voice),
    )

    context = LLMContext([{"role": "system", "content": system_prompt()}])
    user_agg, assistant_agg = LLMContextAggregatorPair(
        context, user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer())
    )

    async def send_json(event: dict):
        await websocket.send_json(event)

    pipeline = Pipeline([
        transport.input(),
        stt,
        UserTextTap(session),
        user_agg,
        llm,
        tts,
        OutputTap(session, send_json),
        transport.output(),
        assistant_agg,
    ])
    task = PipelineTask(
        pipeline,
        params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=SPEAKER_RATE),
    )
    session.task, session.context = task, context
    return task
