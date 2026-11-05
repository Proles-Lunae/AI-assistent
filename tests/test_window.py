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
    monkeypatch.setattr(main, "open_window", lambda config, minimized=False: opened.append(1) or True)
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


# -- Talk button ---------------------------------------------------------------

@pytest.fixture
def talk_window(app):
    from assistant.window import Window

    calls = []
    w = Window(DE, on_talk=lambda: calls.append("talk"), on_stop=lambda: calls.append("stop"))
    w.tray = None
    yield w, calls
    w.quitting = True
    w.deleteLater()


def test_talk_button_follows_her_state(talk_window):
    w, _ = talk_window
    assert not w.talk.isEnabled()  # still starting
    w.on_event("state", {"state": "waiting"})
    assert w.talk.isEnabled() and w.talk.text() == "Sprechen"
    for state in ("listening", "thinking", "speaking"):
        w.on_event("state", {"state": state})
        assert w.talk.isEnabled() and w.talk.text() == "Gespräch beenden"
    w.on_event("problem", {"text": "Mikrofon fehlt"})
    assert not w.talk.isEnabled()


def test_talk_button_starts_and_ends_a_conversation(talk_window):
    w, calls = talk_window
    w.on_event("state", {"state": "waiting"})
    w.talk.click()
    assert calls == ["talk"] and not w.talk.isEnabled()  # no double clicks meanwhile
    w.on_event("state", {"state": "listening"})
    w.talk.click()
    assert calls == ["talk", "stop"]


def test_space_bar_works_like_the_button(talk_window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    w, calls = talk_window
    w.show()
    w.activateWindow()
    w.on_event("state", {"state": "waiting"})
    w._talk_clicked()  # what the space-bar shortcut calls
    assert calls == ["talk"]
    QTest.keyClick(w, Qt.Key.Key_Space)  # disabled until she has started: ignored
    assert calls == ["talk"]


def test_talk_request_starts_a_conversation_without_clapping(monkeypatch):
    """The microphone loop notices the button and starts talking, no claps needed."""
    import threading

    from assistant import microphone
    from assistant.config import ClapSettings

    blocks = queue.Queue()
    for _ in range(20):
        blocks.put(np.zeros(1024, np.float32))
    talk = threading.Event()
    talk.set()
    started = []

    class Done(Exception):
        pass

    def on_talk(q):
        started.append(q)
        raise Done  # end the endless loop for the test

    monkeypatch.setattr(microphone, "choose_microphone", lambda s: None)
    monkeypatch.setattr(microphone, "recording", lambda s, d: __import__("contextlib").nullcontext(blocks))
    with pytest.raises(Done):
        microphone.listen(ClapSettings(), lambda q: None, talk_request=talk, on_talk=on_talk)
    assert started == [blocks] and not talk.is_set()


def test_ending_from_the_window_stops_the_conversation(monkeypatch):
    from assistant import main

    a = main.Assistant(Config())
    a.speaker.beep = lambda: None
    seen_stop = []

    def fake_record(blocks, rate, settings, stop=None, **options):
        seen_stop.append(stop)
        a.request_stop()  # you press "Gespräch beenden" while she listens
        return None

    monkeypatch.setattr(main, "record_question", fake_record)
    a.converse(queue.Queue())  # returns instead of listening forever
    assert seen_stop == [a.stop_request] and not a.stop_request.is_set()


def test_listening_stops_at_once_when_ended():
    import threading

    from assistant.config import ListenSettings
    from assistant.listening import record_question

    stop = threading.Event()
    stop.set()
    assert record_question(queue.Queue(), 44100, ListenSettings(), stop=stop) is None


def test_talk_button_skips_the_greeting(monkeypatch):
    from assistant import main

    a = main.Assistant(Config())
    did = []
    monkeypatch.setattr(a, "wake_up", lambda: did.append("greeting"))
    monkeypatch.setattr(a, "converse", lambda blocks: did.append("conversation"))
    monkeypatch.setattr(a, "warm_up", lambda: None)

    def fake_listen(settings, on_double_clap, on_clap=None, talk_request=None, on_talk=None):
        on_talk("blocks")
        on_double_clap("blocks")

    monkeypatch.setattr(main, "listen", fake_listen)
    a.run()
    assert did == ["conversation", "greeting", "conversation"]


# -- Starting with Windows -------------------------------------------------------

def test_autostart_shortcut_goes_to_the_startup_folder_and_starts_hidden(monkeypatch, tmp_path):
    from assistant import shortcut

    made = []
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(shortcut.sys, "platform", "win32")

    def fake_create(name, place="Desktop", arguments="-m assistant"):
        made.append((name, place, arguments))
        shortcut.autostart_path(name).parent.mkdir(parents=True, exist_ok=True)
        shortcut.autostart_path(name).touch()
        return str(shortcut.autostart_path(name))

    monkeypatch.setattr(shortcut, "create_shortcut", fake_create)
    assert not shortcut.autostart_enabled("Assistentin")
    shortcut.set_autostart("Assistentin", True)
    assert made == [("Assistentin", "Startup", "-m assistant --minimized")]
    assert shortcut.autostart_enabled("Assistentin")
    assert shortcut.autostart_path("Assistentin") == (
        tmp_path / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Assistentin.lnk")
    shortcut.set_autostart("Assistentin", False)
    assert not shortcut.autostart_enabled("Assistentin")
    shortcut.set_autostart("Assistentin", False)  # turning it off twice is fine


def test_startup_shortcut_script_uses_the_startup_folder():
    from pathlib import Path

    from assistant.shortcut import shortcut_script

    script = shortcut_script("Assistentin", Path("pythonw.exe"), "-m assistant --minimized",
                             Path("C:/x"), Path("C:/x/a.ico"), place="Startup")
    assert "GetFolderPath('Startup')" in script and "'-m assistant --minimized'" in script


def test_autostart_command(monkeypatch, tmp_path, capsys):
    from assistant import main, shortcut

    changes = []
    monkeypatch.setattr(shortcut, "set_autostart", lambda name, on: changes.append((name, on)))
    config = tmp_path / "config.toml"
    config.write_text("")
    for value in ("on", "off"):
        monkeypatch.setattr(sys, "argv", ["assistant", "--config", str(config), "--autostart", value])
        main.main()
    assert changes == [("Assistentin", True), ("Assistentin", False)]
    out = capsys.readouterr().out
    assert "start with Windows" in out and "won't start with Windows" in out


def test_minimized_start_stays_in_the_tray(monkeypatch, tmp_path):
    from assistant import main

    calls = []
    monkeypatch.setattr(main, "open_window", lambda config, minimized=False: calls.append(minimized) or True)
    config = tmp_path / "config.toml"
    config.write_text("")
    monkeypatch.setattr(sys, "argv", ["assistant", "--config", str(config), "--minimized"])
    main.main()
    assert calls == [True]


# -- Her name, and the new look ----------------------------------------------------

def test_the_circle_shows_her_name(app):
    from assistant.window import Window

    w = Window(DE)
    w.tray = None
    assert w.orb.name == "Assistentin" and w.windowTitle() == "Assistentin"  # the default
    w.deleteLater()
    w = Window(DE, name="Eva")
    w.tray = None
    assert w.orb.name == "Eva" and w.windowTitle() == "Eva"
    assert not w.orb.grab().isNull()
    w.deleteLater()


def test_long_names_wrap_before_they_are_cut_short(app):
    from assistant.window import fit_name

    short, font = fit_name("Eva", 120, 80)
    assert short == "Eva" and font.pixelSize() == 21
    wrapped, font = fit_name("Mein persönlicher Assistent", 120, 80)
    assert wrapped == "Mein persönlicher Assistent" and font.pixelSize() < 21  # two lines, smaller
    cut, font = fit_name("Supercalifragilisticexpialigetisch", 120, 80)
    assert cut.endswith("…") and font.pixelSize() == 12


def test_her_name_comes_from_the_settings():
    from assistant import main
    from assistant.config import AssistantSettings

    assert AssistantSettings().display_name("Assistentin") == "Assistentin"
    assert AssistantSettings(name="  Eva  ").display_name("Assistentin") == "Eva"
    config = Config()
    config.assistant.name = "Eva"
    a = main.Assistant(config)
    assert a.name == "Eva" and a.context().startswith("Your name is Eva. It is ")
    assert main.Assistant(Config()).name == "Assistentin"


def test_name_setting_is_read_from_the_file(tmp_path):
    from assistant.config import load_config

    path = tmp_path / "config.toml"
    path.write_text('[assistant]\nname = "Eva"\n', encoding="utf-8")
    assert load_config(path).assistant.name == "Eva"


def test_thinking_shows_moving_dots_until_she_answers(window):
    from assistant.window import ThinkingDots

    window.on_event("state", {"state": "thinking"})
    assert window.chat.dots is not None
    window.on_event("heard", {"text": "Wie spät ist es?"})  # your bubble goes above the dots
    assert window.chat.column.indexOf(window.chat.dots) == window.chat.column.count() - 2
    assert len(window.chat.widget().findChildren(ThinkingDots)) == 1
    window.on_event("said", {"text": "Es ist acht Uhr."})
    assert window.chat.dots is None
    assert bubbles(window) == [("you", "Wie spät ist es?"), ("her", "Es ist acht Uhr.")]
    window.on_event("state", {"state": "thinking"})
    window.on_event("state", {"state": "waiting"})  # ended without an answer
    assert window.chat.dots is None


def test_a_state_change_sends_a_ring_outwards(window):
    orb = window.orb
    orb.set_state("waiting")
    assert orb.ripple == 1.0
    orb.set_state("waiting")  # the same state again: no new ring
    orb._tick()
    assert 0 < orb.ripple < 1.0


def test_weather_pill_appears_when_the_weather_is_known(window):
    assert window.weather.isHidden()
    window.on_event("weather", {"temperature": 21, "unit": "°C", "city": ""})
    assert not window.weather.isHidden() and window.weather.text() == "21°C"


def test_talk_button_changes_its_look_with_her_state(talk_window):
    w, _ = talk_window
    w.on_event("state", {"state": "waiting"})
    assert w.talk.property("ending") is False and w.talk.sizeHint().width() >= 180
    w.on_event("state", {"state": "listening"})
    assert w.talk.property("ending") is True
    w.talk.grab()  # drawing the button in each state works
    w.on_event("state", {"state": "problem"})
    assert not w.talk.isEnabled() and not w.talk.grab().isNull()


def test_notes_fade_away_after_a_while(window):
    window.on_event("note", {"text": "Kurz mal was"})
    assert window.note.text() == "Kurz mal was" and window.note_timer.isActive()
    window._hide_note()
    window.note_fade.animation.setCurrentTime(window.note_fade.animation.duration())  # finished
    QtWidgets.QApplication.processEvents()
    assert window.note.text() == ""
