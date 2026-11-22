"""Kokoro with a controllable speaking rate.

Pipecat's Kokoro service hard-codes speed=1.0. Learners from Bangladesh follow a slightly slower,
clearly articulated examiner more easily (the TTS decision doc settles on 0.95), and a tiny
per-line variation stops every sentence sounding stamped from the same mould.
"""
from __future__ import annotations

import os
import random
from typing import AsyncGenerator

import numpy as np
from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.kokoro.tts import KokoroTTSService

SPEED = float(os.getenv("EXAMINER_SPEED", "0.95"))
SPEED_JITTER = float(os.getenv("EXAMINER_SPEED_JITTER", "0.02"))


class ExamKokoroTTSService(KokoroTTSService):
    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        try:
            await self.start_tts_usage_metrics(text)
            speed = round(SPEED + random.uniform(-SPEED_JITTER, SPEED_JITTER), 3)
            stream = self._kokoro.create_stream(text, voice=self._settings.voice, lang=self._settings.language, speed=speed)
            async for samples, sample_rate in stream:
                await self.stop_ttfb_metrics()
                audio = await self._resampler.resample((samples * 32767).astype(np.int16).tobytes(), sample_rate, self.sample_rate)
                yield TTSAudioRawFrame(audio=audio, sample_rate=self.sample_rate, num_channels=1, context_id=context_id)
        except Exception as e:
            yield ErrorFrame(error=f"Unknown error occurred: {e}")
        finally:
            await self.stop_ttfb_metrics()
