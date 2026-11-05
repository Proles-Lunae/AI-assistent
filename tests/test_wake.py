"""Waking her by saying her name."""
import queue
import time
from types import SimpleNamespace

import numpy as np
import pytest

from assistant.config import Config, ListenSettings
from assistant.wake import SpeechCutter, WakeListener, find_wake_word

RATE, BLOCK = 44100, 1024
ROOM, VOICE = 0.002, 0.05


@pytest.mark.parametrize("text, question", [
    ("Rose.", ""),
    ("Rose!", ""),
    ("Hey Rose.", ""),
    ("Hallo, Rose?", ""),
    ("Rosé.", ""),  # Whisper sometimes adds an accent
    ("Rose, wie spät ist es?", "wie spät ist es?"),
    ("Hey Rose, wie wird das Wetter morgen?", "wie wird das Wetter morgen?"),
    ("Wie spät ist es, Rose?", "Wie spät ist es?"),
])
def test_her_name_is_found(text, question):
    assert find_wake_word(text, ["Rose"]) == question


@pytest.mark.parametrize("text", ["Wie spät ist es?", "Rosen sind rot.", "Die Rosa Jacke.",
                                  "Ich habe Rosemarie getroffen.", ""])
def test_other_speech_does_not_wake_her(text):
    assert find_wake_word(text, ["Rose"]) is None


def test_another_name_works_too():
    assert find_wake_word("Eva, mach Licht an.", ["Eva"]) == "mach Licht an."
    assert find_wake_word("Rose.", ["Eva"]) is None


def blocks(*parts):
    rng = np.random.default_rng(0)
    out = []
    for seconds, loudness in parts:
        out += [rng.normal(0, loudness, BLOCK).astype(np.float32)
                for _ in range(round(seconds * RATE / BLOCK))]
    return out


def utterances(*parts, **cutter_options):
    cutter = SpeechCutter(RATE, ListenSettings(), **cutter_options)
    return [a for a in (cutter.feed(b) for b in blocks(*parts)) if a is not None]


def test_a_short_call_is_cut_out():
    found = utterances((1, ROOM), (0.6, VOICE), (1.5, ROOM))
    assert len(found) == 1
    assert 0.8 < len(found[0]) / RATE < 2.0  # the word, a moment before and the pause after


def test_two_calls_are_two_utterances():
    assert len(utterances((1, ROOM), (0.5, VOICE), (1, ROOM), (0.5, VOICE), (1, ROOM))) == 2


def test_a_clap_is_too_short_to_be_a_word():
    assert utterances((1, ROOM), (0.05, 0.8), (1.5, ROOM)) == []


def test_long_talking_is_not_checked():
    assert utterances((1, ROOM), (12, VOICE), (1.5, ROOM)) == []  # the TV, a conversation


def test_quiet_room_gives_nothing():
    assert utterances((10, ROOM)) == []


def make_listener(said):
    calls = []

    def transcribe(audio, rate, quick=False, prompt=None):
        calls.append((quick, prompt))
        return said

    listener = WakeListener(SimpleNamespace(transcribe=transcribe), ["Rose"], RATE, ListenSettings())
    return listener, calls


def feed_call(listener):
    for b in blocks((1, ROOM), (0.6, VOICE), (1.5, ROOM)):
        listener.feed(b)
    for _ in range(100):  # the check runs in the background
        if not listener.busy.is_set():
            break
        time.sleep(0.01)


def test_saying_her_name_calls_her():
    listener, calls = make_listener("Rose.")
    feed_call(listener)
    assert listener.take() == "" and listener.take() is None
    assert calls == [(True, "Rose.")]  # quick check, with her name as a hint


def test_a_question_with_her_name_is_passed_on():
    listener, _ = make_listener("Rose, wie spät ist es?")
    feed_call(listener)
    assert listener.take() == "wie spät ist es?"


def test_other_speech_is_ignored():
    listener, calls = make_listener("Was gibt es zum Abendessen?")
    feed_call(listener)
    assert listener.take() is None and len(calls) == 1


def test_a_call_heard_before_a_reset_is_forgotten():
    listener, _ = make_listener("Rose.")
    listener.round_at_start = listener.round
    started = []
    real = listener.transcriber.transcribe

    def slow(*args, **kwargs):
        started.append(1)
        time.sleep(0.3)
        return real(*args, **kwargs)

    listener.transcriber.transcribe = slow
    for b in blocks((1, ROOM), (0.6, VOICE), (1.5, ROOM)):
        listener.feed(b)
    while not started:
        time.sleep(0.01)
    listener.reset()  # e.g. a conversation started meanwhile
    time.sleep(0.5)
    assert listener.take() is None


def test_one_check_at_a_time():
    listener, calls = make_listener("Rose.")
    listener.busy.set()  # still checking the last utterance
    for b in blocks((1, ROOM), (0.6, VOICE), (1.5, ROOM)):
        listener.feed(b)
    assert calls == []


def test_microphone_loop_wakes_her_when_called(monkeypatch):
    import contextlib

    from assistant import microphone
    from assistant.config import ClapSettings

    q = queue.Queue()
    for b in blocks((0.5, ROOM)):
        q.put(b)
    fed, woken = [], []

    class FakeWake:
        def feed(self, block):
            fed.append(block)

        def take(self):
            return "wie spät ist es?" if len(fed) == 5 else None

        def reset(self):
            woken.append("reset")
            raise KeyboardInterrupt  # end the endless loop for the test

    monkeypatch.setattr(microphone, "choose_microphone", lambda s: None)
    monkeypatch.setattr(microphone, "recording", lambda s, d: contextlib.nullcontext(q))
    with pytest.raises(KeyboardInterrupt):
        microphone.listen(ClapSettings(), lambda q: None, wake=FakeWake(),
                          on_wake=lambda q, question: woken.append(question))
    assert woken == ["wie spät ist es?", "reset"]


def make_rose(monkeypatch):
    from assistant import main

    a = main.Assistant(Config())
    did = []
    monkeypatch.setattr(a, "wake_up", lambda: did.append("greeting"))
    monkeypatch.setattr(a, "converse", lambda blocks, first_question="": did.append(
        ("conversation", first_question)))
    monkeypatch.setattr(a, "warm_up", lambda: None)
    return a, did, main


def test_just_her_name_is_like_a_double_clap(monkeypatch):
    a, did, main = make_rose(monkeypatch)
    monkeypatch.setattr(main, "listen", lambda *args, on_wake=None, **kw: on_wake("blocks", ""))
    a.run()
    assert did == ["greeting", ("conversation", "")]


def test_her_name_with_a_question_goes_straight_to_the_answer(monkeypatch):
    a, did, main = make_rose(monkeypatch)
    monkeypatch.setattr(main, "listen",
                        lambda *args, on_wake=None, **kw: on_wake("blocks", "wie spät ist es?"))
    a.run()
    assert did == [("conversation", "wie spät ist es?")]


def test_name_wake_up_can_be_switched_off(monkeypatch):
    a, _, main = make_rose(monkeypatch)
    a.config.listen.wake_word = False
    seen = []
    monkeypatch.setattr(main, "listen", lambda *args, wake=None, **kw: seen.append(wake))
    a.run()
    assert seen == [None]


def test_question_asked_with_her_name_is_answered_first(monkeypatch):
    from assistant import main
    from assistant.listening import MicrophoneStopped

    a = main.Assistant(Config())
    a.speaker.beep = lambda: None
    a.speaker.play = lambda speech, wait=True, continued=False: None
    asked = []
    a.brain.answer_in_sentences = lambda q, *rest: asked.append(q) or iter([f"Antwort: {q}"])
    a.speaker.say_sentences = lambda sentences: " ".join(sentences)
    monkeypatch.setattr(a, "context", lambda: "")
    monkeypatch.setattr(main, "record_question",
                        lambda *args, **kw: (_ for _ in ()).throw(MicrophoneStopped("end")))
    a.converse(queue.Queue(), first_question="wie spät ist es?")
    assert asked == ["wie spät ist es?"]  # answered before listening for more


def test_window_says_her_name_wakes_her(app=None):
    pytest.importorskip("PySide6.QtWidgets")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from assistant.phrases import LANGUAGES
    from assistant.window import Window

    QApplication.instance() or QApplication([])
    w = Window(LANGUAGES["de"], name="Rose", wake_word=True)
    w.tray = None
    w.on_event("state", {"state": "waiting"})
    assert w.status_text("waiting") == "Zweimal klatschen oder „Rose“ sagen"
    w.wake_word = False
    assert w.status_text("waiting") == "Zweimal klatschen, um mich zu wecken"
    w.quitting = True
