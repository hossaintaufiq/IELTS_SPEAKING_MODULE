"""
Text-to-Speech (TTS) Engine
Uses Kokoro-82M to synthesize the IELTS Examiner voice with an authentic British accent.
"""

import os

class LocalTTSEngine:
    def __init__(self, voice: str = "bf_emma", lang_code: str = "b", speed: float = 1.0):
        self.voice = voice          # 'bf_emma' (British female), 'bm_george' (British male)
        self.lang_code = lang_code  # 'b' for British English, 'a' for American English
        self.speed = speed
        self.pipeline = None
        self._init_kokoro()

    def _init_kokoro(self):
        try:
            from kokoro import KPipeline
            self.pipeline = KPipeline(lang_code=self.lang_code)
        except Exception as e:
            # Fallback to lightweight offline system speech
            self.pipeline = None

    def speak(self, text: str):
        """Synthesizes and speaks the examiner response."""
        print(f"\n[Examiner]: \"{text}\"")

        if self.pipeline is not None:
            try:
                import sounddevice as sd
                generator = self.pipeline(text, voice=self.voice, speed=self.speed)
                for _, _, audio in generator:
                    sd.play(audio, 24000)
                    sd.wait()
                return
            except Exception as e:
                pass

        # Secondary fallback: pyttsx3 offline system voice
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty('rate', 160)
            engine.say(text)
            engine.runAndWait()
        except Exception:
            # Console-only fallback if no sound driver available
            pass

