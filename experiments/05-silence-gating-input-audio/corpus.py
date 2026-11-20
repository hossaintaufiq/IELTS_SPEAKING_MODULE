import subprocess
from pathlib import Path

PASSAGES = {
    "hometown": (
        "I grew up in a small coastal town in the south of the country. "
        "It is a quiet place with narrow streets, a busy fish market and a long beach "
        "where people walk in the evening. What I like most about it is the sense of community, "
        "because everybody knows each other and neighbours always help when someone has a problem. "
        "However, there are not many job opportunities there, so many young people move to the capital."
    ),
    "technology": (
        "Technology has changed the way people study in a very significant way. "
        "Nowadays students can attend lectures online, search for information in seconds "
        "and collaborate with classmates who live in different countries. "
        "On the other hand, I believe that it can also be distracting, since notifications "
        "and social media constantly compete for our attention, which makes it harder to concentrate."
    ),
    "memorable_trip": (
        "The most memorable journey I have ever taken was a week in the mountains with my cousins. "
        "We hired a small cabin near a frozen lake and spent our days hiking through the forest. "
        "Although the weather was extremely cold, we cooked together every night and talked for hours. "
        "Looking back, I think it was special because we were completely disconnected from our busy lives."
    ),
}

VOICES = ("Microsoft David Desktop", "Microsoft Zira Desktop")


def synthesize(text: str, out: Path, voice: str, rate: int = 0) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.SelectVoice('{voice}');$s.Rate={rate};"
        f"$f=New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,'Sixteen','Mono');"
        f"$s.SetOutputToWaveFile('{out}',$f);$s.Speak($env:TEXT);$s.Dispose()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        check=True,
        env={**__import__("os").environ, "TEXT": text},
    )


def build_corpus(directory: Path) -> list[tuple[Path, str]]:
    clips = []
    for voice in VOICES:
        tag = voice.split()[1].lower()
        for name, text in PASSAGES.items():
            path = directory / f"{name}_{tag}.wav"
            if not path.exists():
                synthesize(text, path, voice)
            clips.append((path, text))
    return clips


def load_audio(path: Path):
    import soundfile as sf

    data, rate = sf.read(str(path), dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    assert rate == 16000
    return data
