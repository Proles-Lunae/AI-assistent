"""Her window: a glowing orb that shows what she's doing, and the conversation.

The assistant itself (claps, listening, talking) runs in the background; the
window only shows what it reports. Closing the window hides her in the tray
(next to the clock), where she keeps listening for claps.
"""

from __future__ import annotations

import math
import sys
import threading
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import (QAction, QColor, QFont, QIcon, QPainter, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QMenu,
                               QScrollArea, QSizePolicy, QSystemTrayIcon, QVBoxLayout,
                               QWidget)

from .config import Config
from .phrases import Phrases

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTANCE_NAME = "clap-voice-assistant"  # lets a second start find the first one
LOG_FILE = PROJECT_ROOT / "assistant.log"
MAX_MESSAGES = 60  # older chat bubbles are removed

# Colours
BACKGROUND = "#0e1117"
SURFACE = "#171b24"
TEXT = "#e6e9ef"
MUTED = "#8a93a6"
ACCENT = "#3fb6c9"
# The orb's colour in each state: (inner, outer glow)
ORB_COLOURS = {
    "starting": ("#6b7280", "#374151"),
    "waiting": ("#2c8c9c", "#12424a"),
    "listening": ("#5ee7ff", "#137a92"),
    "thinking": ("#b18cff", "#4b2d8f"),
    "speaking": ("#ffc66d", "#8f5a14"),
    "problem": ("#ff7b72", "#7a1f1a"),
}
NOTE_LENGTH = 160  # longer messages are shortened in the window (all of it is in the log)

STYLE = f"""
QWidget#root {{ background: {BACKGROUND}; }}
QLabel {{ color: {TEXT}; }}
QLabel#title {{ font-size: 15px; font-weight: 600; letter-spacing: 0.5px; }}
QLabel#weather {{ color: {MUTED}; font-size: 13px; }}
QLabel#status {{ color: {MUTED}; font-size: 14px; }}
QLabel#note {{ color: #c9a227; font-size: 12px; }}
QScrollArea {{ background: transparent; border: none; }}
QWidget#chat {{ background: transparent; }}
QLabel#her {{ background: {SURFACE}; border-radius: 14px; padding: 9px 13px; font-size: 14px; }}
QLabel#you {{ background: #1f5f6b; border-radius: 14px; padding: 9px 13px; font-size: 14px; }}
QScrollBar:vertical {{ background: transparent; width: 6px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2a3040; border-radius: 3px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


class Bridge(QObject):
    """Carries events from the assistant's background thread to the window."""

    event = Signal(str, dict)

    def send(self, kind: str, **data) -> None:
        self.event.emit(kind, data)


class Orb(QWidget):
    """A softly glowing ball whose colour and movement show her state."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(220, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.state = "starting"
        self.inner, self.outer = (QColor(c) for c in ORB_COLOURS["starting"])
        self.target_inner, self.target_outer = self.inner, self.outer
        self.level = 0.0  # microphone loudness while listening, 0-1
        self.flash = 0.0  # a short glow when a single clap is heard
        self.phase = 0.0
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(33)  # about 30 frames a second

    def set_state(self, state: str) -> None:
        self.state = state
        inner, outer = ORB_COLOURS.get(state, ORB_COLOURS["waiting"])
        self.target_inner, self.target_outer = QColor(inner), QColor(outer)

    def set_level(self, rms: float) -> None:
        # Speech is roughly 0.005-0.1 RMS; map it onto 0-1 on a log scale.
        value = 0.0 if rms <= 0 else min(1.0, max(0.0, (math.log10(rms) + 2.7) / 1.7))
        self.level = max(value, self.level * 0.8)

    def pulse(self) -> None:
        self.flash = 1.0

    @staticmethod
    def _blend(a: QColor, b: QColor, t: float) -> QColor:
        return QColor(round(a.red() + (b.red() - a.red()) * t),
                      round(a.green() + (b.green() - a.green()) * t),
                      round(a.blue() + (b.blue() - a.blue()) * t))

    def _tick(self) -> None:
        self.phase += 0.033
        self.inner = self._blend(self.inner, self.target_inner, 0.12)
        self.outer = self._blend(self.outer, self.target_outer, 0.12)
        self.level *= 0.92
        self.flash *= 0.88
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        centre = QPointF(self.width() / 2, self.height() / 2)
        base = min(self.width(), self.height()) * 0.25
        if self.state == "waiting":
            grow = 0.04 * math.sin(self.phase * 1.3)  # slow breathing
        elif self.state == "listening":
            grow = 0.05 * math.sin(self.phase * 3) + 0.25 * self.level
        elif self.state == "speaking":
            grow = 0.06 * math.sin(self.phase * 7) * (0.6 + 0.4 * math.sin(self.phase * 2.3))
        elif self.state == "thinking":
            grow = 0.03 * math.sin(self.phase * 2)
        else:
            grow = 0.02 * math.sin(self.phase)
        radius = base * (1 + grow + 0.15 * self.flash)

        # Outer glow
        glow = QRadialGradient(centre, radius * 2.1)
        outer = QColor(self.outer)
        outer.setAlpha(150)
        glow.setColorAt(0.0, outer)
        outer.setAlpha(0)
        glow.setColorAt(1.0, outer)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(centre, radius * 2.1, radius * 2.1)

        # The ball: bright centre, darker edge
        ball = QRadialGradient(centre - QPointF(radius * 0.3, radius * 0.35), radius * 1.3)
        ball.setColorAt(0.0, self._blend(self.inner, QColor("white"), 0.45))
        ball.setColorAt(0.55, self.inner)
        ball.setColorAt(1.0, self.outer)
        p.setBrush(ball)
        p.drawEllipse(centre, radius, radius)

        if self.state == "thinking":  # a ring turning round the ball
            pen = QPen(self._blend(self.inner, QColor("white"), 0.3), 3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            r = radius * 1.35
            start = int(-self.phase * 220 * 16) % (360 * 16)
            p.drawArc(QRectF(centre.x() - r, centre.y() - r, 2 * r, 2 * r), start, 100 * 16)
            p.drawArc(QRectF(centre.x() - r, centre.y() - r, 2 * r, 2 * r),
                      start + 180 * 16, 100 * 16)
        elif self.state in ("listening", "speaking"):  # rings moving outwards
            for i in range(2):
                t = (self.phase * 0.7 + i * 0.5) % 1.0
                ring = QColor(self.inner)
                ring.setAlpha(int(120 * (1 - t)))
                p.setPen(QPen(ring, 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                r = radius * (1.1 + 0.8 * t)
                p.drawEllipse(centre, r, r)
        p.end()


class Chat(QScrollArea):
    """The conversation, as speech bubbles: hers on the left, yours on the right."""

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("chat")
        self.column = QVBoxLayout(inner)
        self.column.setContentsMargins(4, 4, 8, 4)
        self.column.setSpacing(8)
        self.column.addStretch()
        self.setWidget(inner)
        self.verticalScrollBar().rangeChanged.connect(
            lambda _min, high: self.verticalScrollBar().setValue(high))

    def add(self, text: str, mine: bool) -> None:
        bubble = QLabel(text)
        bubble.setObjectName("you" if mine else "her")
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if mine:
            row.addStretch()
        row.addWidget(bubble)
        if not mine:
            row.addStretch()
        holder = QWidget()
        holder.setLayout(row)
        self.column.addWidget(holder)
        self._fit(bubble)  # now it's in the window, its font size is known
        while self.column.count() - 1 > MAX_MESSAGES:  # keep the window light
            old = self.column.takeAt(1).widget()
            old.deleteLater()

    def _fit(self, bubble: QLabel) -> None:
        """As wide as its text, but at most 80% of the chat's width (then it wraps)."""
        bubble.ensurePolished()  # so the style sheet's font size is applied
        natural = bubble.fontMetrics().horizontalAdvance(bubble.text()) + 36  # + padding
        widest = max(160, int(max(self.viewport().width(), 360) * 0.8))
        bubble.setFixedWidth(min(natural, widest))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        for bubble in self.widget().findChildren(QLabel):
            self._fit(bubble)


def orb_icon(size: int = 256, colours=ORB_COLOURS["listening"]) -> QPixmap:
    """The app icon: the orb on a transparent background."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    centre = QPointF(size / 2, size / 2)
    r = size * 0.42
    inner, outer = QColor(colours[0]), QColor(colours[1])
    ball = QRadialGradient(centre - QPointF(r * 0.3, r * 0.35), r * 1.3)
    ball.setColorAt(0.0, QColor("#e9fbff"))
    ball.setColorAt(0.55, inner)
    ball.setColorAt(1.0, outer)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(ball)
    p.drawEllipse(centre, r, r)
    p.end()
    return pixmap


class Window(QWidget):
    def __init__(self, words: Phrases):
        super().__init__()
        self.words = words
        self.quitting = False
        self.hint_shown = False
        self.problem = False  # something stops her working: keep that message showing
        self.setObjectName("root")
        self.setWindowTitle(words.app_title)
        self.setWindowIcon(QIcon(orb_icon()))
        self.resize(420, 680)
        self.setMinimumSize(340, 520)
        self.setStyleSheet(STYLE)
        font = QFont("Segoe UI", 10)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        self.setFont(font)

        title = QLabel(words.app_title)
        title.setObjectName("title")
        self.weather = QLabel("")
        self.weather.setObjectName("weather")
        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.weather)

        self.orb = Orb()
        self.status = QLabel(words.status["starting"])
        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.note = QLabel("")
        self.note.setObjectName("note")
        self.note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.note.setWordWrap(True)
        self.note_timer = QTimer(self)
        self.note_timer.setSingleShot(True)
        self.note_timer.timeout.connect(lambda: self.note.setText(""))

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {SURFACE};")
        self.chat = Chat()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 14, 14)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self.orb)
        layout.addWidget(self.status)
        layout.addWidget(self.note)
        layout.addSpacing(6)
        layout.addWidget(line)
        layout.addWidget(self.chat, 1)

        self.tray = self._make_tray()

    def _make_tray(self) -> QSystemTrayIcon | None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        tray = QSystemTrayIcon(QIcon(orb_icon(64)), self)
        tray.setToolTip(f"{self.words.app_title}: {self.words.status['starting']}")
        menu = QMenu()
        show = QAction(self.words.show_window, menu)
        show.triggered.connect(self.bring_back)
        leave = QAction(self.words.quit_app, menu)
        leave.triggered.connect(self.quit)
        menu.addAction(show)
        menu.addSeparator()
        menu.addAction(leave)
        tray.setContextMenu(menu)
        tray.activated.connect(self._tray_clicked)
        tray.show()
        self._menu = menu  # keep it alive
        return tray

    def _tray_clicked(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.bring_back()

    def bring_back(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit(self) -> None:
        self.quitting = True
        if self.tray:
            self.tray.hide()
        QApplication.quit()

    def closeEvent(self, event) -> None:
        if self.quitting or self.tray is None:
            event.accept()
            QApplication.quit()
            return
        event.ignore()  # closing only hides her: she keeps listening for claps
        self.hide()
        if not self.hint_shown:
            self.hint_shown = True
            self.tray.showMessage(self.words.app_title, self.words.tray_hint,
                                  QIcon(orb_icon(64)), 6000)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        dark_title_bar(self)

    # -- events from the assistant -------------------------------------------
    def on_event(self, kind: str, data: dict) -> None:
        if kind == "state":
            state = data["state"]
            self.orb.set_state(state)
            self.status.setText(self.words.status.get(state, ""))
            if self.tray:
                self.tray.setToolTip(f"{self.words.app_title}: {self.words.status.get(state, '')}")
        elif kind == "said":
            self.chat.add(data["text"], mine=False)
        elif kind == "heard":
            self.chat.add(data["text"], mine=True)
        elif kind == "level":
            self.orb.set_level(data["level"])
        elif kind == "clap":
            self.orb.pulse()
        elif kind == "weather":
            city = data.get("city") or ""
            self.weather.setText(f"{data['temperature']}{data.get('unit', '°')}"
                                 + (f"  ·  {city}" if city else ""))
        elif kind == "note":
            if not self.problem:  # don't cover up a problem with a passing note
                self.note.setText(shorten(data["text"]))
                self.note_timer.start(8000)
        elif kind == "problem":
            self.problem = True
            self.note_timer.stop()
            self.note.setText(shorten(data["text"]))
            self.on_event("state", {"state": "problem"})
        elif kind == "ready" and self.orb.state == "starting":
            self.on_event("state", {"state": "waiting"})


def shorten(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= NOTE_LENGTH else text[:NOTE_LENGTH - 1].rstrip() + "…"


def problem_message(exc: Exception) -> str:
    """A short explanation of why she can't work, for the window."""
    text = str(exc)
    if "PortAudio" in text or "Invalid device" in text or "Error opening InputStream" in text:
        return ("The microphone can't be used: " + text + ". Check that it's plugged in "
                "and that Windows allows apps to use it (Settings > Privacy > Microphone).")
    return f"{type(exc).__name__}: {text}"


def dark_title_bar(window: QWidget) -> None:
    """Ask Windows 10/11 for a dark title bar, to match the window."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        value = ctypes.c_int(1)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new, then old number)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    int(window.winId()), attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


class LogFile:
    """Where messages go when there's no Command Prompt: assistant.log."""

    def __init__(self, path: Path, also=None):
        self.file = open(path, "a", encoding="utf-8", buffering=1)
        self.also = also  # the console, if there is one

    def write(self, text: str) -> int:
        self.file.write(text)
        if self.also is not None:
            try:
                self.also.write(text)
            except Exception:
                pass
        return len(text)

    def flush(self) -> None:
        self.file.flush()


def already_running() -> bool:
    """If she's already running, ask that window to come forward and say so."""
    socket = QLocalSocket()
    socket.connectToServer(INSTANCE_NAME)
    if not socket.waitForConnected(300):
        return False
    socket.write(b"show")
    socket.waitForBytesWritten(300)
    socket.disconnectFromServer()
    return True


def answer_later_starts(window: Window) -> QLocalServer:
    """Bring this window forward whenever she's started a second time."""
    server = QLocalServer(window)
    QLocalServer.removeServer(INSTANCE_NAME)  # left over if she wasn't closed properly
    server.listen(INSTANCE_NAME)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), window.bring_back()))
    return server


def run_window(config: Config) -> None:
    """Open her window and start the assistant in the background."""
    from .main import Assistant  # here, so the window module stays light to import

    app = QApplication.instance() or QApplication(sys.argv)
    if already_running():
        return  # the window that's already open has come forward
    sys.stdout = LogFile(LOG_FILE, sys.__stdout__)
    sys.stderr = sys.stdout
    app.setApplicationName("Assistentin")
    app.setQuitOnLastWindowClosed(False)  # hidden in the tray isn't "closed"
    bridge = Bridge()
    assistant = Assistant(config, events=bridge.send)
    window = Window(assistant.words)
    bridge.event.connect(window.on_event)
    window.server = answer_later_starts(window)
    window.show()

    def work() -> None:
        try:
            assistant.run()
        except Exception as exc:  # e.g. no microphone: show it rather than vanish
            traceback.print_exc()
            bridge.send("problem", text=problem_message(exc))

    threading.Thread(target=work, name="assistant", daemon=True).start()
    app.exec()
