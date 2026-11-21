"""Pipeline taps: observe frames to feed transcripts, interruptions and latency to the session."""
from __future__ import annotations

import time

from pipecat.frames.frames import (
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class UserTextTap(FrameProcessor):
    """Sits after STT. Reports what the candidate said; in Part 2 it swallows the text (held)."""

    def __init__(self, session):
        super().__init__()
        self.session = session

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame) and frame.text.strip():
            if not await self.session.on_user_text(frame.text.strip()):
                return  # held for the Part 2 monologue; do not trigger an LLM reply
        await self.push_frame(frame, direction)


class OutputTap(FrameProcessor):
    """Sits after TTS. Reports examiner text, interruptions and user-stop -> first-audio latency."""

    def __init__(self, session, send):
        super().__init__()
        self.session, self._send = session, send
        self._text: list[str] = []
        self._t_stop: float | None = None

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, UserStoppedSpeakingFrame):
            self._t_stop = time.perf_counter()
        elif isinstance(frame, (UserStartedSpeakingFrame, InterruptionFrame)):
            await self._send({"type": "interrupt"})
        elif isinstance(frame, LLMTextFrame):
            self._text.append(frame.text)
        elif isinstance(frame, LLMFullResponseEndFrame):
            text = "".join(self._text).strip()
            self._text = []
            if text:
                await self.session.on_examiner_text(text)
        elif isinstance(frame, TTSAudioRawFrame) and self._t_stop is not None:
            await self.session.on_latency(time.perf_counter() - self._t_stop)
            self._t_stop = None
        await self.push_frame(frame, direction)
