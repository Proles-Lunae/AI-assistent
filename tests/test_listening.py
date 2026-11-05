import queue
from types import SimpleNamespace

import numpy as np
import pytest

from assistant.config import Config, ListenSettings
from assistant.listening import Transcriber, record_question, to_whisper_rate

RATE = 44100
BLOCK = 1024
BLOCK_SECONDS = BLOCK / RATE


def audio_queue(*parts):
    """A queue of microphone blocks: parts are (seconds, loudness) pairs."""
    rng = np.random.default_rng(0)
    q = queue.Queue()
    for seconds, loudness in parts:
        for _ in range(round(seconds / BLOCK_SECONDS)):
            q.put((rng.normal(0, loudness, BLOCK)).astype(np.float32))
    return q


ROOM = 0.002  # quiet room noise
VOICE = 0.05  # someone talking


def test_records_until_you_stop_talking():
    q = audio_queue((0.5, ROOM), (1.5, VOICE), (2.0, ROOM), (3.0, ROOM))
    audio = record_question(q, RATE, ListenSettings())
    seconds = len(audio) / RATE
    # 0.3 s from before, the 1.5 s of speech, then the 1.2 s of quiet that ends it
    assert 2.85 < seconds < 3.15
    assert not q.empty()  # the rest wasn't needed


def test_nothing_said_gives_none():
    q = audio_queue((7.0, ROOM))
    assert record_question(q, RATE, ListenSettings(wait_seconds=6)) is None


def test_steady_room_noise_is_not_mistaken_for_speech():
    q = audio_queue((7.0, 0.004))  # a fan or a computer: louder, but constant
    assert record_question(q, RATE, ListenSettings()) is None


def test_long_speech_is_cut_off_at_max_seconds():
    q = audio_queue((0.3, ROOM), (20.0, VOICE))
    audio = record_question(q, RATE, ListenSettings(max_seconds=5))
    assert len(audio) / RATE <= 5.2


def test_microphone_going_quiet_entirely_is_reported(monkeypatch):
    from assistant.listening import MicrophoneStopped

    q = queue.Queue()  # no audio at all arrives
    monkeypatch.setattr(q, "get", lambda timeout=None: (_ for _ in ()).throw(queue.Empty()))
    with pytest.raises(MicrophoneStopped):
        record_question(q, RATE, ListenSettings())


def test_resampled_for_whisper():
    one_second = np.zeros(RATE, np.float32)
    assert len(to_whisper_rate(one_second, RATE)) == 16000
    assert to_whisper_rate(np.zeros(16000), 16000).dtype == np.float32


def test_transcriber_uses_the_language_and_16_khz(monkeypatch):
    calls = []

    class FakeModel:
        def transcribe(self, audio, **options):
            calls.append((len(audio), options))
            return [SimpleNamespace(text=" What time is it? "), SimpleNamespace(text="Thanks.")], None

    t = Transcriber(ListenSettings(language="en"), prompt="Hello.")
    t._model = FakeModel()
    assert t.transcribe(np.zeros(RATE, np.float32), RATE) == "What time is it? Thanks."
    length, options = calls[0]
    assert length == 16000 and options["language"] == "en"
    assert options["beam_size"] == 5 and options["initial_prompt"] == "Hello."
    t.s.language = "auto"
    t.transcribe(np.zeros(RATE, np.float32), RATE)
    assert calls[1][1]["language"] is None  # "auto" = let Whisper detect it


def test_speech_language_follows_her_language_unless_set():
    assert Transcriber(ListenSettings(), language="de").language() == "de"
    assert Transcriber(ListenSettings(language="en"), language="de").language() == "en"
    assert Transcriber(ListenSettings(language="AUTO"), language="de").language() is None


@pytest.mark.parametrize("text", ["Thanks!", "Thank you.", "No, that's all.", "Goodbye", "bye bye",
                                  "OK, thanks", "Never mind."])
def test_goodbye_phrases_end_the_conversation(text):
    from assistant.main import is_goodbye

    assert is_goodbye(text)


@pytest.mark.parametrize("text", ["What's the capital of France?",
                                  "Thanks, and what time is the football on tonight?",
                                  "How do I stop my cat scratching the sofa?", "Tell me a joke."])
def test_real_questions_are_not_goodbyes(text):
    from assistant.main import is_goodbye

    assert not is_goodbye(text)


def make_talker(monkeypatch, said, answers=None, brain_fails=False, **listen):
    """An Assistant whose microphone 'hears' ``said`` (None = silence) in turn.

    When ``said`` runs out, the microphone 'stops', which ends the conversation."""
    from assistant import main
    from assistant.brain import BrainError

    config = Config()
    config.user.language = "en"  # these tests check the English texts
    for key, value in listen.items():
        setattr(config.listen, key, value)
    a = main.Assistant(config)
    spoken, asked = [], []
    a.speaker.prepare = lambda text: SimpleNamespace(text=text, samples=None)
    a.speaker.play = lambda speech, wait=True: spoken.append(speech.text)
    a.speaker.say = lambda text: spoken.append(text)
    a.speaker.beep = lambda: spoken.append("<beep>")
    turns = iter(said)
    heard = []

    def fake_record(blocks, rate, settings):
        from assistant.listening import MicrophoneStopped

        text = next(turns, "<end>")
        if text == "<end>":
            raise MicrophoneStopped("end of test")
        heard.append(text)
        return None if text is None else np.array([0.1], np.float32)

    monkeypatch.setattr(main, "record_question", fake_record)
    a.transcriber.transcribe = lambda audio, rate: heard[-1]
    monkeypatch.setattr(a, "context", lambda: "It is Friday.")

    def fake_answer(question, history, context, address, instruction="Answer in English."):
        asked.append((question, list(history), context, address))
        if brain_fails:
            raise BrainError("not logged in")
        return (answers or {}).get(question, f"Answer to: {question}")

    a.brain.answer = fake_answer
    return a, spoken, asked


def test_question_is_answered_then_she_listens_again(monkeypatch):
    a, spoken, asked = make_talker(monkeypatch, ["What's two plus two?", None])
    a.converse(queue.Queue())
    assert spoken == ["<beep>", "Answer to: What's two plus two?", "<beep>"]
    assert asked[0][0] == "What's two plus two?" and asked[0][3] == "sir"


def test_follow_up_questions_remember_the_conversation(monkeypatch):
    a, _, asked = make_talker(monkeypatch, ["Who wrote Hamlet?", "When was he born?", None],
                              {"Who wrote Hamlet?": "Shakespeare."})
    a.converse(queue.Queue())
    assert asked[1][1] == [("Who wrote Hamlet?", "Shakespeare.")]


def test_thanks_ends_the_conversation_politely(monkeypatch):
    from assistant.phrases import LANGUAGES

    GOODBYE = LANGUAGES["en"].goodbye

    a, spoken, asked = make_talker(monkeypatch, ["Thank you."])
    a.converse(queue.Queue())
    assert spoken == ["<beep>", GOODBYE] and asked == []


def test_mumbling_gets_a_polite_retry(monkeypatch):
    from assistant.phrases import LANGUAGES

    DIDNT_CATCH = LANGUAGES["en"].didnt_catch

    a, spoken, _ = make_talker(monkeypatch, ["", "Hello?", None])
    a.converse(queue.Queue())
    assert spoken[:3] == ["<beep>", DIDNT_CATCH, "<beep>"]
    assert "Answer to: Hello?" in spoken


def test_claude_unavailable_is_explained(monkeypatch):
    from assistant.phrases import LANGUAGES

    NO_BRAIN = LANGUAGES["en"].no_brain

    a, spoken, _ = make_talker(monkeypatch, ["What's the time?"], brain_fails=True)
    a.converse(queue.Queue())
    assert spoken == ["<beep>", NO_BRAIN, "<beep>"]  # she apologises and keeps listening


def test_silence_does_not_end_the_conversation(monkeypatch):
    from assistant.phrases import LANGUAGES

    GOODBYE = LANGUAGES["en"].goodbye

    # a whole minute of quiet, then a question, then "stop"
    a, spoken, asked = make_talker(monkeypatch, [None] * 10 + ["What's the time?", "Stop."])
    a.converse(queue.Queue())
    assert spoken == ["<beep>", "Answer to: What's the time?", "<beep>", GOODBYE]
    assert [q for q, *_ in asked] == ["What's the time?"]


def test_she_can_still_be_set_to_stop_after_quiet(monkeypatch):
    a, spoken, asked = make_talker(monkeypatch, [None, None, "Hello?"],
                                   end_after_quiet=12, wait_seconds=6)
    a.converse(queue.Queue())
    assert spoken == ["<beep>"] and asked == []  # stopped after 12 s, before "Hello?"


@pytest.mark.parametrize("text", ["Stop.", "Go to sleep.", "That's enough, thanks.",
                                  "That will be all.", "You can go now."])
def test_ways_of_telling_her_to_stop(text):
    from assistant.main import is_goodbye

    assert is_goodbye(text)


def test_claude_prompt_has_context_history_and_question(monkeypatch):
    from assistant.brain import ClaudeBrain
    from assistant.config import BrainSettings

    brain = ClaudeBrain(BrainSettings())
    prompts = []
    monkeypatch.setattr(brain, "ask", lambda prompt: prompts.append(prompt) or "Yes.")
    history = [(f"q{i}", f"a{i}") for i in range(10)]
    brain.answer("Is it raining?", history, "It is Friday 18:00, in Berlin.", "sir")
    prompt = prompts[0]
    assert "It is Friday 18:00, in Berlin." in prompt and '"Is it raining?"' in prompt
    assert "User: q9" in prompt and "You: a9" in prompt
    assert "q3" not in prompt  # only the last 6 exchanges are kept
    assert "'sir'" in prompt and "three short spoken sentences" in prompt


def test_listening_can_be_switched_off(tmp_path):
    from assistant.config import load_config

    path = tmp_path / "config.toml"
    path.write_text("[listen]\nenabled = false\nlanguage = \"de\"\n")
    config = load_config(path)
    assert config.listen.enabled is False and config.listen.language == "de"


def test_model_download_warnings_are_hidden(monkeypatch):
    import logging
    import os
    import warnings

    from assistant.listening import quiet_model_download

    monkeypatch.delenv("HF_HUB_DISABLE_SYMLINKS_WARNING", raising=False)
    monkeypatch.delenv("HF_HUB_VERBOSITY", raising=False)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        quiet_model_download()
        warnings.warn_explicit("symlinks not supported", UserWarning,
                               "file_download.py", 149, module="huggingface_hub.file_download")
    assert caught == []
    assert os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] == "1"
    assert os.environ["HF_HUB_VERBOSITY"] == "error"
    assert logging.getLogger("huggingface_hub").level == logging.ERROR
