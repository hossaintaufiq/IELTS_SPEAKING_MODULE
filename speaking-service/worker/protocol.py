"""Browser <-> server WebSocket protocol, as a Pipecat frame serializer.

Browser to server:  binary = mic audio, PCM16 mono 16 kHz.   text = JSON control {"action": ...}
Server to browser:  binary = examiner audio, PCM16 mono 24 kHz.   text = JSON events (see session.py)

Plain PCM instead of Pipecat's protobuf format, so the browser needs no extra libraries.
"""
from __future__ import annotations

import json

from pipecat.frames.frames import Frame, InputAudioRawFrame, OutputAudioRawFrame, OutputTransportMessageFrame
from pipecat.serializers.base_serializer import FrameSerializer

MIC_RATE = 16000
SPEAKER_RATE = 24000


class BrowserSerializer(FrameSerializer):
    def __init__(self, session):
        super().__init__()
        self.session = session

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, OutputAudioRawFrame):
            return frame.audio
        if isinstance(frame, OutputTransportMessageFrame):
            return json.dumps(frame.message)
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        if isinstance(data, (bytes, bytearray)):
            self.session.note_audio(bytes(data))
            if self.session.muted or self.session.listening_blocked():
                return None
            return InputAudioRawFrame(audio=bytes(data), sample_rate=MIC_RATE, num_channels=1)
        try:
            msg = json.loads(data)
        except (TypeError, ValueError):
            return None
        if isinstance(msg, dict):
            await self.session.handle_control(msg)
        return None
