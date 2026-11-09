"""
Audio Capture Module
Handles microphone recording, audio buffering, and voice activity detection (VAD).
"""

import os
import time
import numpy as np

class AudioCapture:
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate

    def record_to_file(self, output_path: str, max_duration_sec: int = 60, silence_threshold_sec: float = 2.5) -> float:
        """
        Records candidate voice from the default microphone.
        Saves output as a 16kHz mono WAV file suitable for Whisper and Wav2Vec2.
        Returns the duration of the recording in seconds.
        """
        try:
            import sounddevice as sd
            import soundfile as sf
        except ImportError:
            print("[AudioCapture] sounddevice or soundfile not installed.")
            print("[AudioCapture] Simulating recording for demonstration...")
            self._create_dummy_wav(output_path, duration_sec=5)
            return 5.0

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        print(f"\n[Microphone Active]: Listening... (Speak now. Max duration: {max_duration_sec}s)")
        print("[Tip: Press Ctrl+C at any time when you finish speaking to proceed]")

        try:
            recording = sd.rec(
                int(max_duration_sec * self.sample_rate),
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32"
            )
            start_time = time.time()
            sd.wait()
            duration = round(time.time() - start_time, 2)
        except KeyboardInterrupt:
            sd.stop()
            duration = round(time.time() - start_time, 2)
            # Slice only the recorded segment
            recorded_samples = int(duration * self.sample_rate)
            recording = recording[:recorded_samples]
            print(f"\n[Recording Stopped] Captured {duration}s of audio.")

        sf.write(output_path, recording, self.sample_rate)
        return duration

    def _create_dummy_wav(self, output_path: str, duration_sec: int = 5):
        """Creates an empty/dummy WAV file when audio hardware or libraries are missing."""
        import wave
        import struct

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with wave.open(output_path, "w") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(self.sample_rate)
            data = struct.pack("<h", 0) * (self.sample_rate * duration_sec)
            f.writeframes(data)

