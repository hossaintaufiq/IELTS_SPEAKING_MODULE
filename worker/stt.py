"""Speech recognition tuned for the exam. Replaces Pipecat's stock Whisper service.

What changes compared with the stock service:
- Decoding runs in a worker thread. The stock service iterates Whisper's lazy generator on the event
  loop, which stalls audio handling and the whole pipeline while it decodes (the lag).
- A keyterm hint (ported from ieltsup keyterms.ts): Bangladeshi places, foods and exam words, plus the
  content words of the question just asked, so "Chattogram" or "fuchka" are not misheard.
- `condition_on_previous_text=False`, a log-probability floor and a compression-ratio limit, to stop
  Whisper looping or inventing text, and segments it is not confident about are dropped.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import AsyncGenerator

import numpy as np
from pipecat.frames.frames import ErrorFrame, Frame, TranscriptionFrame
from pipecat.services.whisper.stt import WhisperSTTService
from pipecat.utils.time import time_now_iso8601

from worker.examiner.speech import has_foreign_script

# ieltsup/services/examCoreAPI/experimental/deepgram/lib/speaking/transcript/keyterms.ts
FIXED = [
    "cue card", "IELTS", "Bangladesh", "Bangladeshi", "Dhaka", "Puran Dhaka", "Chattogram", "Sylhet", "Rajshahi",
    "Khulna", "Barishal", "Cox's Bazar", "Sundarbans", "rickshaw", "Eid", "Pohela Boishakh", "Bangla",
    "BRAC University", "BUET", "North South University", "Dhaka University", "Mirpur", "Dhanmondi", "Gulshan",
    "Uttara", "Mohammadpur", "Narayanganj", "Gazipur", "Mymensingh", "Comilla", "biryani", "fuchka", "pitha",
    "bhorta", "khichuri", "hilsa", "Durga Puja", "Ramadan", "metro rail", "CNG", "bKash",
    "Bashundhara", "Banani", "Motijheel", "Farmgate", "Savar", "Cumilla", "Shaheed Minar", "Victory Day",
    "Ekushey February", "kacchi", "tehari", "lungi", "panjabi", "adda",
]
# The prompt is deliberately SHORT. Measured on a real Bangladeshi test recording: the full company list above made Whisper
# swallow minutes of speech, repeat the prompt itself ("IELTS speaking test.") and invent words ("I don't sign on my topic");
# ten core names plus the question's own words transcribed the same audio correctly.
CORE = ["Bangladesh", "Dhaka", "Chattogram", "Sylhet", "Eid", "Pohela Boishakh", "rickshaw", "biryani", "fuchka", "Bangla"]
STOP = set("""about above after again also always another anything around because been before being
  between both could describe does doing during each either enjoy ever every explain feel
  from have having into just like many more most much often other people person should
  some something sometimes than that their them then there these they thing things think
  this those through usually very want what when where which while whom whose with would
  your yours you'd you're today usually really""".split())
MAX_QUESTION_TERMS = 4


def keyterms_for(question: str | None) -> list[str]:
    words = [w for w in re.sub(r"[^a-z\s'-]", " ", (question or "").lower()).split() if len(w) >= 4 and w not in STOP]
    unique = list(dict.fromkeys(words))[:MAX_QUESTION_TERMS]
    core_lower = {f.lower() for f in CORE}
    return CORE + [w for w in unique if w not in core_lower]


def initial_prompt(question: str | None) -> str:
    return ", ".join(keyterms_for(question)) + "."


def language_code(language) -> str:
    """The plain code faster-whisper needs ("en"). Pipecat's Language is an enum: formatted into Whisper's language token it can
    become "<|Language.EN|>" on some Python versions, the token is then not found and the decoder runs without a language."""
    code = getattr(language, "value", language) or "en"
    return str(code).split("-")[0].lower()


def level_up(audio: np.ndarray, target: float = 0.08, max_gain: float = 6.0) -> np.ndarray:
    """Quiet microphones (speech rms 0.02-0.03) make Whisper guess; bring the speech up to a normal level.
    The gain comes from the speaking frames only (not the silence between words) and never lowers the volume."""
    n = len(audio) // 4000 * 4000                      # 0.25 s frames
    if n == 0:
        return audio
    rms = np.sqrt((audio[:n].reshape(-1, 4000) ** 2).mean(axis=1))
    speech = rms[rms > 0.012]
    if len(speech) == 0:
        return audio
    gain = min(max_gain, target / float(np.median(speech)))
    return np.clip(audio * gain, -1.0, 1.0) if gain > 1.05 else audio


def echoes_prompt(text: str, prompt: str) -> bool:
    """Whisper sometimes outputs its own prompt words when the audio is unclear: those are not the candidate's words."""
    words = re.findall(r"[a-z']+", text.lower())
    known = set(re.findall(r"[a-z']+", prompt.lower()))
    return len(words) >= 3 and all(w in known for w in words)


class ExamWhisperSTTService(WhisperSTTService):
    MIN_AVG_LOGPROB = -1.0

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.question_hint: str | None = None     # the examiner's latest line; the session keeps this current

    def _decode(self, audio_float: np.ndarray) -> list[tuple[str, float, float]]:
        segments, _ = self._model.transcribe(
            level_up(audio_float),
            language=language_code(self._settings.language),
            initial_prompt=initial_prompt(self.question_hint),
            condition_on_previous_text=False,
            beam_size=5,
            temperature=[0.0, 0.2],
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
            vad_filter=os.getenv("STT_VAD_FILTER", "1") == "1",   # set 0 if quiet speech is being clipped
            vad_parameters={"threshold": 0.35, "min_silence_duration_ms": 600, "speech_pad_ms": 300},
        )
        # Materialise here, inside the worker thread: the generator does the real decoding as it is read.
        return [(s.text.strip(), s.no_speech_prob, s.avg_logprob) for s in segments]

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        if not self._model:
            yield ErrorFrame("Whisper model not available")
            return
        await self.start_processing_metrics()
        audio_float = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        parts = await asyncio.to_thread(self._decode, audio_float)
        prompt = initial_prompt(self.question_hint)
        text = " ".join(t for t, no_speech, logprob in parts
                        if t and no_speech < self._settings.no_speech_prob and logprob > self.MIN_AVG_LOGPROB
                        and not echoes_prompt(t, prompt) and not has_foreign_script(t))
        await self.stop_processing_metrics()
        if text:
            await self._handle_transcription(text, True, self._settings.language)
            yield TranscriptionFrame(text, self._user_id, time_now_iso8601(), self._settings.language)
