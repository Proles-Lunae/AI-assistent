"""Answers spoken sentence by sentence, while Claude is still writing them."""
import time
from types import SimpleNamespace

import pytest

from assistant.brain import BrainError, ClaudeBrain, split_sentences, text_delta
from assistant.config import BrainSettings, VoiceSettings
from tests.test_assistant import stand_in_claude


@pytest.mark.parametrize("text, done, rest", [
    ("Faust wurde von Goethe geschrieben. Der erste", ["Faust wurde von Goethe geschrieben."],
     " Der erste"),
    ("Er wurde am 28. August 1749 geboren. Ja", ["Er wurde am 28. August 1749 geboren."], " Ja"),
    ("Zum Beispiel z.B. so. Und Dr. Faust? Gut! ", ["Zum Beispiel z.B. so.", "Und Dr. Faust?",
                                                    "Gut!"], " "),
    ("Es sind 8,5 Grad. Nimm", ["Es sind 8,5 Grad."], " Nimm"),
    ("Hello, sir.\nIt's late", ["Hello, sir."], "\nIt's late"),
    ("No full stop yet", [], "No full stop yet"),
    ("Version 3.5 is out. ", ["Version 3.5 is out."], " "),
])
def test_split_sentences(text, done, rest):
    assert split_sentences(text) == (done, rest)


def test_text_delta_reads_only_answer_text():
    event = {"type": "stream_event",
             "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}}}
    assert text_delta(event) == "Hi"
    assert text_delta({"type": "stream_event", "event": {"type": "message_start"}}) == ""
    assert text_delta({"type": "result", "result": "Hi"}) == ""


def test_sentences_arrive_while_claude_is_still_writing(tmp_path, monkeypatch):
    stand_in_claude(tmp_path, monkeypatch)
    monkeypatch.setenv("STAND_IN_PIECES", "Erster Satz. |Zweiter |Satz. |Dritter.")
    monkeypatch.setenv("STAND_IN_PAUSE", "0.4")
    start = time.monotonic()
    times, sentences = [], []
    for sentence in ClaudeBrain(BrainSettings()).ask_in_sentences("Hallo"):
        times.append(time.monotonic() - start)
        sentences.append(sentence)
    assert sentences == ["Erster Satz.", "Zweiter Satz.", "Dritter."]
    assert times[0] < times[-1] - 0.6  # the first came well before the end


def test_streaming_asks_claude_for_stream_json(tmp_path, monkeypatch):
    _, call = stand_in_claude(tmp_path, monkeypatch)
    list(ClaudeBrain(BrainSettings()).ask_in_sentences("Sag hallo.\nKurz."))
    argv = call()["argv"]
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--include-partial-messages" in argv and "--verbose" in argv
    assert call()["stdin"] == "Sag hallo.\nKurz."  # still through stdin, for Windows


def test_streaming_failure_is_reported(tmp_path, monkeypatch):
    stand_in_claude(tmp_path, monkeypatch)
    monkeypatch.setenv("STAND_IN_FAIL", "1")
    with pytest.raises(BrainError, match="exit 1.*Not logged in"):
        list(ClaudeBrain(BrainSettings()).ask_in_sentences("Hallo"))


def test_streaming_gives_up_after_the_timeout(tmp_path, monkeypatch):
    stand_in_claude(tmp_path, monkeypatch)
    monkeypatch.setenv("STAND_IN_PIECES", "a|b|c|d|e|f")
    monkeypatch.setenv("STAND_IN_PAUSE", "1")
    start = time.monotonic()
    with pytest.raises(BrainError, match="too long"):
        list(ClaudeBrain(BrainSettings(timeout=1.5)).ask_in_sentences("Hallo"))
    assert time.monotonic() - start < 4  # stopped, not waited out


def make_speaker():
    from assistant.voice import Speaker

    speaker = Speaker(VoiceSettings())
    played = []
    speaker.prepare = lambda text: SimpleNamespace(text=text, samples=None)
    speaker.play = lambda speech, wait=True, continued=False: played.append(
        (speech.text, continued, time.monotonic()))
    return speaker, played


def test_she_starts_speaking_before_the_answer_is_complete():
    speaker, played = make_speaker()

    def slow_answer():
        yield "Erster Satz."
        time.sleep(0.5)
        yield "Zweiter Satz."

    start = time.monotonic()
    said = speaker.say_sentences(slow_answer())
    assert said == "Erster Satz. Zweiter Satz."
    assert [(t, c) for t, c, _ in played] == [("Erster Satz.", False), ("Zweiter Satz.", True)]
    assert played[0][2] - start < 0.3  # the first sentence didn't wait for the second


def test_error_before_anything_is_said_is_passed_on():
    speaker, played = make_speaker()

    def failing():
        raise BrainError("not logged in")
        yield  # pragma: no cover

    with pytest.raises(BrainError):
        speaker.say_sentences(failing())
    assert played == []


def test_error_halfway_keeps_what_was_said(capsys):
    speaker, played = make_speaker()

    def half():
        yield "Erster Satz."
        raise BrainError("connection lost")

    assert speaker.say_sentences(half()) == "Erster Satz."
    assert "stopped early" in capsys.readouterr().out
