"""Her window: drawn without a screen ("offscreen"), so it can be tested anywhere."""
import os
import queue
import sys
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")  # skipped if the window toolkit is missing

from assistant.config import Config  # noqa: E402
from assistant.phrases import LANGUAGES  # noqa: E402

DE = LANGUAGES["de"]


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def window(app):
    from assistant.window import Window

    w = Window(DE)
    w.tray = None
    yield w
    w.quitting = True
    w.deleteLater()


def bubbles(w):
    return [(b.objectName(), b.text()) for b in w.chat.widget().findChildren(QtWidgets.QLabel)]


def test_states_change_the_orb_and_caption(window):
    assert window.status.text() == "Wird gestartet…"
    for state in ("waiting", "listening", "thinking", "speaking"):
        window.on_event("state", {"state": state})
        assert window.orb.state == state and window.status.text() == DE.status[state]


def test_conversation_appears_as_bubbles(window):
    window.on_event("said", {"text": "Guten Abend, Sir."})
    window.on_event("heard", {"text": "Wie spät ist es?"})
    assert bubbles(window) == [("her", "Guten Abend, Sir."), ("you", "Wie spät ist es?")]


def test_old_bubbles_are_removed(window):
    from assistant.window import MAX_MESSAGES

    for i in range(MAX_MESSAGES + 15):
        window.on_event("said", {"text": f"Nachricht {i}"})
    QtWidgets.QApplication.processEvents()
    texts = [t for _, t in bubbles(window) if t.startswith("Nachricht")]
    assert len([w for w in window.chat.widget().findChildren(QtWidgets.QWidget)
                if isinstance(w, QtWidgets.QLabel) and not w.isHidden()]) <= MAX_MESSAGES + 15
    assert window.chat.column.count() - 1 == MAX_MESSAGES
    assert texts[-1] == f"Nachricht {MAX_MESSAGES + 14}"


def test_bubbles_fit_their_text(window):
    window.resize(420, 680)
    window.on_event("said", {"text": "Ja."})
    window.on_event("said", {"text": "Ein sehr langer Satz " * 10})
    short, long = window.chat.widget().findChildren(QtWidgets.QLabel)[-2:]
    assert short.width() < 120  # a short answer gets a small bubble
    assert long.maximumWidth() <= int(max(window.chat.viewport().width(), 360) * 0.8)


def test_weather_and_notes_are_shown(window):
    window.on_event("weather", {"temperature": 8, "unit": "°C", "city": "Berlin"})
    assert window.weather.text() == "8°C  ·  Berlin"
    window.on_event("note", {"text": "Couldn't get the weather"})
    assert window.note.text() == "Couldn't get the weather"


def test_ready_after_starting_means_waiting(window):
    window.on_event("ready", {})
    assert window.orb.state == "waiting"
    window.on_event("state", {"state": "listening"})
    window.on_event("ready", {})  # a late "ready" doesn't interrupt a conversation
    assert window.orb.state == "listening"


def test_orb_reacts_to_your_voice_and_claps(window):
    orb = window.orb
    orb.set_level(0.0)
    assert orb.level == 0
    orb.set_level(0.05)
    loud = orb.level
    assert 0.5 < loud <= 1.0
    orb.set_level(10.0)
    assert orb.level == 1.0
    orb.pulse()
    assert orb.flash == 1.0
    orb._tick()
    assert orb.flash < 1.0 and orb.level < 1.0  # both fade away
    orb.grab()  # drawing in every state doesn't fail
    for state in ("waiting", "listening", "thinking", "speaking", "starting"):
        orb.set_state(state)
        assert not orb.grab().isNull()


def test_closing_hides_her_in_the_tray_and_explains_once(window):
    messages = []
    window.tray = SimpleNamespace(showMessage=lambda *a: messages.append(a[1]), hide=lambda: None)
    window.show()
    window.close()
    assert not window.isVisible() and not window.quitting  # hidden, still running
    window.show()
    window.close()
    assert messages == [DE.tray_hint]  # the hint only the first time


def test_icon_can_be_drawn(app):
    from assistant.window import orb_icon

    icon = orb_icon(64)
    assert icon.width() == 64 and not icon.isNull()


def test_log_file_works_without_a_console(tmp_path):
    from assistant.window import LogFile

    log = LogFile(tmp_path / "assistant.log", also=None)  # pythonw: no console
    print("Hallo", file=log)
    log.flush()
    assert (tmp_path / "assistant.log").read_text(encoding="utf-8") == "Hallo\n"


def test_shortcut_script_quotes_paths_safely():
    from pathlib import Path

    from assistant.shortcut import shortcut_script

    script = shortcut_script("Assistentin", Path(r"C:\Users\O'Neil\.venv\Scripts\pythonw.exe"),
                             "-m assistant", Path(r"C:\Users\O'Neil\AI-assistent"),
                             Path(r"C:\Users\O'Neil\AI-assistent\assistant.ico"))
    assert "GetFolderPath('Desktop')" in script  # also finds a OneDrive desktop
    assert r"'C:\Users\O''Neil\.venv\Scripts\pythonw.exe'" in script
    assert "$s.Arguments = '-m assistant'" in script and "'Assistentin.lnk'" in script


def test_shortcut_needs_windows(monkeypatch):
    from assistant import shortcut

    monkeypatch.setattr(shortcut.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="Windows"):
        shortcut.create_desktop_shortcut("Assistentin")


def test_shortcut_uses_pythonw(monkeypatch, tmp_path):
    from assistant import shortcut

    (tmp_path / "python.exe").touch()
    (tmp_path / "pythonw.exe").touch()
    monkeypatch.setattr(shortcut.sys, "executable", str(tmp_path / "python.exe"))
    assert shortcut.windowless_python().name == "pythonw.exe"


def test_icon_file_is_saved(app, tmp_path):
    from assistant.shortcut import make_icon

    path = make_icon(tmp_path / "assistant.ico")
    assert path.stat().st_size > 1000


def test_window_opens_by_default_and_console_on_request(monkeypatch, tmp_path):
    from assistant import main

    opened, ran = [], []
    monkeypatch.setattr(main, "open_window", lambda config: opened.append(1) or True)
    monkeypatch.setattr(main.Assistant, "run", lambda self: ran.append(1))
    monkeypatch.setattr(main.Assistant, "__init__", lambda self, config, events=None: None)
    config = tmp_path / "config.toml"
    config.write_text("")
    monkeypatch.setattr(sys, "argv", ["assistant", "--config", str(config)])
    main.main()
    assert opened == [1] and ran == []
    monkeypatch.setattr(sys, "argv", ["assistant", "--config", str(config), "--console"])
    main.main()
    assert opened == [1] and ran == [1]


def test_without_the_window_toolkit_she_runs_in_the_console(monkeypatch, tmp_path):
    from assistant import main

    ran = []
    monkeypatch.setitem(sys.modules, "assistant.window", None)  # as if PySide6 were missing
    monkeypatch.setattr(main.Assistant, "run", lambda self: ran.append(1))
    monkeypatch.setattr(main.Assistant, "__init__", lambda self, config, events=None: None)
    config = tmp_path / "config.toml"
    config.write_text("")
    monkeypatch.setattr(sys, "argv", ["assistant", "--config", str(config)])
    main.main()
    assert ran == [1]


def test_assistant_reports_what_happens(monkeypatch):
    """The events the window is told about during a clap and a conversation."""
    from assistant import main
    from assistant.listening import MicrophoneStopped
    from assistant.weather import WeatherReport

    events = []
    a = main.Assistant(Config(), events=lambda kind, **data: events.append((kind, data)))
    a.speaker.prepare = lambda text: SimpleNamespace(text=text, samples=None)
    a.speaker._say_offline = lambda text: None
    a.speaker.finish = lambda: None
    a.speaker.beep = lambda: None
    report = WeatherReport("Berlin", "Nebel", 8.4, 0, 0, 0, 0, 0, "°C", "km/h")
    monkeypatch.setattr(main, "get_weather", lambda *args: report)
    a.wake_up()
    assert ("weather", {"temperature": 8, "unit": "°C", "city": "Berlin"}) in events
    said = [d["text"] for k, d in events if k == "said"]
    assert said[0].startswith("Guten ") and said[1].startswith("Es sind 8 Grad")

    events.clear()
    turns = iter(["Wie spät ist es?", "Danke."])

    def fake_record(blocks, rate, settings, **options):
        options["on_level"](0.02)
        try:
            return np.array([next(turns)], dtype=object)
        except StopIteration:
            raise MicrophoneStopped("end") from None

    monkeypatch.setattr(main, "record_question", fake_record)
    a.transcriber.transcribe = lambda audio, rate: audio[0]
    monkeypatch.setattr(a, "context", lambda: "It is Friday.")
    a.brain.answer_in_sentences = lambda *args: iter(["Es ist acht Uhr, Sir."])
    a.converse(queue.Queue())
    kinds = [(k, d.get("state") or d.get("text") or d.get("level")) for k, d in events]
    assert kinds[:6] == [("state", "listening"), ("level", 0.02), ("state", "thinking"),
                         ("heard", "Wie spät ist es?"), ("state", "speaking"),
                         ("said", "Es ist acht Uhr, Sir.")]
    assert all(not d.get("continued") for k, d in events if k == "said" and d["text"] == "Danke.")
    assert ("heard", "Danke.") in kinds and ("said", DE.goodbye) in kinds


def test_a_problem_stays_visible_and_turns_the_orb_red(window):
    from assistant.window import NOTE_LENGTH, problem_message

    message = problem_message(OSError("PortAudio library not found"))
    assert "microphone" in message and "Privacy" in message
    window.on_event("problem", {"text": message})
    assert window.orb.state == "problem" and window.status.text() == DE.status["problem"]
    window.on_event("note", {"text": "Couldn't find your location yet"})
    window.on_event("ready", {})
    assert window.note.text().startswith("The microphone can't be used")  # not covered up
    assert window.orb.state == "problem"  # "ready" doesn't hide the problem
    assert len(window.note.text()) <= NOTE_LENGTH


def test_long_notes_are_shortened(window):
    window.on_event("note", {"text": "x " * 500})
    assert len(window.note.text()) <= 160 and window.note.text().endswith("…")


def test_an_answer_spoken_in_pieces_stays_one_bubble(window):
    window.on_event("heard", {"text": "Wer hat Faust geschrieben?"})
    window.on_event("said", {"text": "Goethe, Sir.", "continued": False})
    window.on_event("said", {"text": "Der erste Teil erschien 1808.", "continued": True})
    assert bubbles(window)[-2:] == [("you", "Wer hat Faust geschrieben?"),
                                    ("her", "Goethe, Sir. Der erste Teil erschien 1808.")]
