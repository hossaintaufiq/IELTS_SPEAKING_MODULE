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

from worker.protocol import SPEAKER_RATE, BrowserSerializer


@dataclass
class WorkerConfig:
    llm_base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", "http://localhost:8000/v1"))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct-AWQ"))
    whisper_model: str = field(default_factory=lambda: os.getenv("WHISPER_MODEL", "large-v3-turbo"))
    whisper_device: str = field(default_factory=lambda: os.getenv("WHISPER_DEVICE", "cuda"))
    whisper_compute_type: str = field(default_factory=lambda: os.getenv("WHISPER_COMPUTE", "float16"))
    kokoro_model_path: str = field(default_factory=lambda: os.getenv("KOKORO_MODEL", "models/cache/kokoro-v1.0.onnx"))
    kokoro_voices_path: str = field(default_factory=lambda: os.getenv("KOKORO_VOICES", "models/cache/voices-v1.0.bin"))
    kokoro_voice: str = field(default_factory=lambda: os.getenv("KOKORO_VOICE", "bf_emma"))
    caption_model: str = field(default_factory=lambda: os.getenv("CAPTION_MODEL", "small.en"))
    # Voice-activity detection. Defaults were too strict for a normal mic (min_volume 0.6 heard nothing).
    vad_confidence: float = field(default_factory=lambda: float(os.getenv("VAD_CONFIDENCE", "0.5")))
    vad_min_volume: float = field(default_factory=lambda: float(os.getenv("VAD_MIN_VOLUME", "0.0")))
    vad_start_secs: float = field(default_factory=lambda: float(os.getenv("VAD_START_SECS", "0.2")))
    vad_stop_secs: float = field(default_factory=lambda: float(os.getenv("VAD_STOP_SECS", "0.6")))


def build_task(websocket, cfg: WorkerConfig, session):
    """Create the PipelineTask for one student. `websocket` is an accepted FastAPI WebSocket."""
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContextAggregatorPair,
        LLMUserAggregatorParams,
    )
    from pipecat.services.kokoro.tts import KokoroTTSService
    from worker.tts import ExamKokoroTTSService
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

    from worker.stt import ExamWhisperSTTService
    from worker.taps import LiveCaptionTap, OutputTap

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=BrowserSerializer(session),
        ),
    )
    stt = ExamWhisperSTTService(
        device=cfg.whisper_device,
        compute_type=cfg.whisper_compute_type,
        settings=ExamWhisperSTTService.Settings(model=cfg.whisper_model),
    )
    tts = ExamKokoroTTSService(
        model_path=cfg.kokoro_model_path,
        voices_path=cfg.kokoro_voices_path,
        settings=KokoroTTSService.Settings(voice=cfg.kokoro_voice),
    )

    # The aggregator is used only for voice-activity + end-of-turn detection; it gives us the finished
    # answer. The company's rule engine (ExamSession) decides what the examiner says, not a chat LLM.
    context = LLMContext([])
    user_agg, _unused = LLMContextAggregatorPair(
        context, user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer(params=VADParams(
            confidence=cfg.vad_confidence, min_volume=cfg.vad_min_volume,
            start_secs=cfg.vad_start_secs, stop_secs=cfg.vad_stop_secs)))
    )

    @user_agg.event_handler("on_user_turn_stopped")
    async def _turn_done(aggregator, strategy, message):
        import asyncio
        asyncio.create_task(session.on_candidate_turn(message.content))

    async def send_json(event: dict):
        await websocket.send_json(event)

    pipeline = Pipeline([
        transport.input(),
        LiveCaptionTap(send_json, model_name=cfg.caption_model, device=cfg.whisper_device,
                       compute_type=cfg.whisper_compute_type,
                       on_start=session.vad_started, on_stop=session.vad_stopped),
        stt,
        user_agg,
        tts,
        OutputTap(session, send_json),
        transport.output(),
    ])
    task = PipelineTask(
        pipeline,
        params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=SPEAKER_RATE),
    )
    session.task = task
    session.stt = stt

    @transport.event_handler("on_client_disconnected")
    async def _left(_transport, _websocket):
        # The page was closed, refreshed or lost: end this test now. Without this the pipeline waits for its idle timeout
        # (minutes) and the test keeps its place, so the next candidate is told the server is full.
        await task.cancel()

    return task
