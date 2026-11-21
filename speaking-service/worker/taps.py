"""Pipeline taps: observe frames to feed transcripts, interruptions and latency to the session."""
from __future__ import annotations

import time

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InputAudioRawFrame,
    InterruptionFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TTSTextFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
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
        if isinstance(frame, (BotStartedSpeakingFrame, TTSStartedFrame)):
            self.session.bot_started()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self.session.bot_stopped()
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._t_stop = time.perf_counter()
        elif isinstance(frame, (UserStartedSpeakingFrame, InterruptionFrame)):
            await self._send({"type": "interrupt"})
        elif isinstance(frame, TTSAudioRawFrame) and self._t_stop is not None:
            await self.session.on_latency(time.perf_counter() - self._t_stop)
            self._t_stop = None
        await self.push_frame(frame, direction)


class LiveCaptionTap(FrameProcessor):
    """Streams a rolling partial transcript while the candidate speaks (live captions).

    Sits right after the transport input. It listens for the VAD speaking frames (broadcast from the
    user aggregator) and every `interval` seconds transcribes the audio so far with a small, fast
    Whisper, sending {"type": "interim", "text": ...}. The accurate final transcript still comes from
    the main STT; the page replaces the caption with it.
    """

    PRE_ROLL = 16000 * 2 * 4 // 10     # 0.4 s of 16 kHz PCM16, so the first word is not cut off
    MAX_BYTES = 16000 * 2 * 15         # never transcribe more than the last 15 s

    def __init__(self, send, model_name: str = "small.en", device: str = "cuda",
                 compute_type: str = "float16", interval: float = 0.9, on_start=None, on_stop=None):
        super().__init__()
        self._send, self._interval = send, interval
        self._on_start, self._on_stop = on_start, on_stop     # tell the session when the candidate talks
        self._cfg = (model_name, device, compute_type)
        self._model = None
        self._pre = bytearray()
        self._buf = bytearray()
        self._active = False
        self._task = None

    def _load(self):
        from faster_whisper import WhisperModel

        if self._model is None:
            name, device, compute = self._cfg
            self._model = WhisperModel(name, device=device, compute_type=compute)
        return self._model

    def _transcribe(self, pcm: bytes) -> str:
        import numpy as np

        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segs, _ = self._load().transcribe(audio, language="en", beam_size=1, vad_filter=False,
                                          condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segs).strip()

    async def _loop(self):
        import asyncio

        loop = asyncio.get_running_loop()
        last = ""
        while self._active:
            await asyncio.sleep(self._interval)
            if not self._active or len(self._buf) < 16000 * 2 // 2:    # need at least 0.5 s
                continue
            pcm = bytes(self._buf[-self.MAX_BYTES:])
            try:
                text = await loop.run_in_executor(None, self._transcribe, pcm)
            except Exception:   # a failed caption must never break the exam
                continue
            if self._active and text and text != last:
                last = text
                await self._send({"type": "interim", "text": text})

    def _begin(self):
        import asyncio

        if self._active:
            return
        self._active = True
        self._buf = bytearray(self._pre)
        self._task = asyncio.create_task(self._loop())

    def _end(self):
        self._active = False

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, (VADUserStartedSpeakingFrame, UserStartedSpeakingFrame)):
            self._begin()
            if self._on_start:
                self._on_start()
        elif isinstance(frame, (VADUserStoppedSpeakingFrame, UserStoppedSpeakingFrame)):
            self._end()
            if self._on_stop:
                self._on_stop()
        elif isinstance(frame, InputAudioRawFrame):
            if self._active:
                self._buf.extend(frame.audio)
            else:
                self._pre.extend(frame.audio)
                del self._pre[:-self.PRE_ROLL]
        await self.push_frame(frame, direction)
