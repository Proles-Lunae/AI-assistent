"""German: what she says, how she sounds, and how she listens."""
import queue
from types import SimpleNamespace

import numpy as np
import pytest

from assistant.config import Config
from assistant.phrases import LANGUAGES, phrases_for
from assistant.weather import WeatherReport

DE = LANGUAGES["de"]


def report(temp, rain=0, unit="°C"):
    return WeatherReport("Berlin", "Nebel", temp, 0, 0, 0, rain, 0, unit, "km/h")


def test_german_is_the_default():
    config = Config()
    assert config.user.language == "de"
    assert config.listen.model == "small"


def test_german_greetings_say_sir():
    assert DE.greeting("morning", "sir") == "Guten Morgen, Sir."
    assert DE.greeting("afternoon", "sir") == "Guten Tag, Sir."
    assert DE.greeting("evening", "Luca") == "Guten Abend, Luca."
    assert DE.greeting("evening", "") == "Guten Abend."


@pytest.mark.parametrize("temp, said", [
    (8.4, "Es sind 8 Grad draußen."),
    (1.2, "Es ist ein Grad draußen."),
    (-1, "Es ist minus ein Grad draußen."),
    (-3.4, "Es sind minus 3 Grad draußen."),
    (0, "Es sind 0 Grad draußen."),
])
def test_german_temperature(temp, said):
    assert report(temp).spoken("evening", "de").startswith(said)


@pytest.mark.parametrize("temp, tip", [
    (-2, "Es friert, also ziehen Sie sich warm an und passen Sie auf Glätte auf."),
    (5, "Ein warmer Mantel wäre eine gute Idee."),
    (12, "Eine Jacke sollte reichen."),
    (18, "Ein leichter Pullover sollte genügen."),
    (25, "Es ist warm, also kleiden Sie sich leicht."),
    (33, "Es ist heiß, also trinken Sie viel Wasser und bleiben Sie im Schatten."),
])
def test_german_tips(temp, tip):
    assert report(temp).suggestion("evening", "de") == tip


def test_german_rain():
    assert report(10, rain=70).suggestion("evening", "de") == (
        "Die Regenwahrscheinlichkeit liegt heute Abend bei 70 Prozent, "
        "also nehmen Sie einen Regenschirm und eine Jacke mit.")
    assert report(3, rain=40).suggestion("morning", "de").endswith(
        "einen Regenschirm und einen warmen Mantel mit.")
    assert report(20, rain=25).suggestion("afternoon", "de").endswith(
        "heute Nachmittag bei 25 Prozent, also nehmen Sie einen Regenschirm mit.")
    assert "Prozent" not in report(10, rain=20).spoken("evening", "de")  # 20 % or less: no rain


def test_whole_german_message():
    msg = DE.greeting("evening", "sir") + " " + report(8.4).spoken("evening", "de")
    assert msg == "Guten Abend, Sir. Es sind 8 Grad draußen. Eine Jacke sollte reichen."


@pytest.mark.parametrize("text", ["Danke.", "Danke schön!", "Tschüss", "Stopp.", "Das war's.",
                                  "Das ist alles, danke.", "Gute Nacht", "Hör auf."])
def test_german_ways_to_stop(text):
    from assistant.main import is_goodbye

    assert is_goodbye(text)


@pytest.mark.parametrize("text", ["Wie spät ist es?", "Danke, und wie wird das Wetter morgen in Hamburg?",
                                  "Erzähl mir einen Witz."])
def test_german_questions_are_not_goodbyes(text):
    from assistant.main import is_goodbye

    assert not is_goodbye(text)


def test_voice_follows_the_language():
    from assistant.config import VoiceSettings
    from assistant.voice import Speaker

    assert Speaker(VoiceSettings(), "de", DE.voice).voice == "de-DE-KatjaNeural"
    # the old British voice from an older config.toml doesn't fit German: Katja instead
    assert Speaker(VoiceSettings(voice="en-GB-SoniaNeural"), "de", DE.voice).voice == DE.voice
    assert Speaker(VoiceSettings(voice="de-DE-AmalaNeural"), "de", DE.voice).voice == "de-DE-AmalaNeural"
    assert Speaker(VoiceSettings(), "en", "en-GB-SoniaNeural").voice == "en-GB-SoniaNeural"


def test_offline_voice_prefers_german_female_for_german():
    from assistant.voice import pick_british_female

    voices = [
        SimpleNamespace(id="gb-hazel", name="Hazel", languages=["en_GB"], gender="female"),
        SimpleNamespace(id="de-stefan", name="Stefan", languages=["de_DE"], gender="male"),
        SimpleNamespace(id="de-hedda", name="Hedda", languages=["de_DE"], gender="female"),
    ]
    assert pick_british_female(voices, "de").id == "de-hedda"
    assert pick_british_female(voices, "en").id == "gb-hazel"


def test_unknown_language_falls_back_to_english(capsys):
    assert phrases_for("fr").code == "en"
    assert "No phrases for language 'fr'" in capsys.readouterr().out
    assert phrases_for("DE").code == "de" and phrases_for("de-AT").code == "de"


def test_claude_is_asked_to_answer_in_german(monkeypatch):
    from assistant.brain import ClaudeBrain
    from assistant.config import BrainSettings

    brain = ClaudeBrain(BrainSettings())
    prompts = []
    monkeypatch.setattr(brain, "ask", lambda prompt: prompts.append(prompt) or "Ja.")
    brain.answer("Wie spät ist es?", [], "It is Friday.", "Sir", DE.claude_instruction)
    assert "Answer in German" in prompts[0] and "'Sie'" in prompts[0]


def test_german_conversation_uses_german_texts(monkeypatch):
    from assistant import main
    from assistant.listening import MicrophoneStopped

    a = main.Assistant(Config())  # default: German
    spoken, instructions = [], []
    a.speaker.play = lambda speech, wait=True: spoken.append(speech.text)
    a.speaker.prepare = lambda text: SimpleNamespace(text=text, samples=None)
    a.speaker.say = spoken.append
    a.speaker.beep = lambda: None
    said = iter(["Wie spät ist es?", "Danke."])

    def fake_record(blocks, rate, settings, **options):
        try:
            return np.array([next(said)], dtype=object)
        except StopIteration:
            raise MicrophoneStopped("end") from None

    monkeypatch.setattr(main, "record_question", fake_record)
    a.transcriber.transcribe = lambda audio, rate: audio[0]
    monkeypatch.setattr(a, "context", lambda: "It is Friday.")
    a.brain.answer = lambda q, h, c, address, instruction: (instructions.append(instruction)
                                                            or "Es ist acht Uhr, Sir.")
    a.converse(queue.Queue())
    assert spoken == ["Es ist acht Uhr, Sir.", DE.goodbye]
    assert instructions == [DE.claude_instruction]
    assert a.transcriber.language() == "de" and a.transcriber.prompt == DE.whisper_prompt


def test_resampling_removes_high_pitches_instead_of_distorting():
    from assistant.listening import to_whisper_rate

    rate = 44100
    t = np.arange(rate) / rate
    whistle = np.sin(2 * np.pi * 12000 * t).astype(np.float32)  # too high for 16 kHz audio
    voice = np.sin(2 * np.pi * 300 * t).astype(np.float32)  # a voice-like pitch
    assert np.max(np.abs(to_whisper_rate(whistle, rate)[200:-200])) < 0.05  # filtered away
    assert np.max(np.abs(to_whisper_rate(voice, rate)[200:-200])) > 0.9  # kept as it was


def test_quiet_speech_is_made_louder_but_not_endlessly():
    from assistant.listening import louder

    quiet = np.array([0.0, 0.1, -0.1], np.float32)
    assert np.isclose(np.max(np.abs(louder(quiet))), 0.9)
    whisper = np.array([0.0, 0.001], np.float32)
    assert np.isclose(np.max(louder(whisper)), 0.02)  # at most 20 times louder
    assert louder(np.zeros(3, np.float32)).tolist() == [0, 0, 0]


def test_lead_in_keeps_the_first_syllable():
    from assistant.config import ListenSettings
    from assistant.listening import record_question

    rate, block = 44100, 1024
    q = queue.Queue()
    rng = np.random.default_rng(0)
    for i in range(60):
        q.put(rng.normal(0, 0.002, block).astype(np.float32))
    for i in range(40):  # speech
        q.put(rng.normal(0, 0.05, block).astype(np.float32))
    for i in range(80):
        q.put(rng.normal(0, 0.002, block).astype(np.float32))
    audio = record_question(q, rate, ListenSettings())
    before_speech = np.argmax(np.abs(audio) > 0.03) / rate
    assert 0.25 < before_speech < 0.35  # about 0.3 s from just before you started
