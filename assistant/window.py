"""Her window: a calm circle with her name in it that shows what she's doing,
and the conversation underneath.

The assistant itself (claps, listening, talking) runs in the background; the
window only shows what it reports. Closing the window hides her in the tray
(next to the clock), where she keeps listening for claps.

Everything that changes does so smoothly: the circle breathes and changes
colour, captions and bubbles fade in, the button morphs between "Talk" and
"End conversation", and the window itself fades in.
"""

from __future__ import annotations

import math
import sys
import threading
import traceback
from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QPointF, QPropertyAnimation, QRectF,
                            Qt, QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import (QAction, QColor, QFont, QFontMetrics, QIcon, QKeySequence,
                           QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient, QShortcut, QTextOption)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMenu,
                               QPushButton, QScrollArea, QSizePolicy, QSystemTrayIcon,
                               QVBoxLayout, QWidget)

from .config import Config
from .phrases import Phrases

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTANCE_NAME = "clap-voice-assistant"  # lets a second start find the first one
LOG_FILE = PROJECT_ROOT / "assistant.log"
MAX_MESSAGES = 60  # older chat bubbles are removed
NOTE_LENGTH = 160  # longer messages are shortened in the window (all of it is in the log)
NOTE_SECONDS = 8  # how long a passing note stays

# Colours: a dark, quiet palette; the circle brings the colour.
BACKGROUND = "#0b0d12"
SURFACE = "#12161e"
RAISED = "#1a1f29"
BORDER = "#222835"
TEXT = "#edf0f5"
MUTED = "#7e879a"
ACCENT = "#4cc9de"  # the Talk button
MINE = "#1c4753"  # your bubbles
WARNING = "#d9a63a"
PROBLEM = "#ff8a80"
# The circle's colour in each state: (bright, deep)
ORB_COLOURS = {
    "starting": ("#8d95a6", "#39404d"),
    "waiting": ("#3eb4c7", "#14474f"),
    "listening": ("#66e4ff", "#146f86"),
    "thinking": ("#b99dff", "#4a2f90"),
    "speaking": ("#ffc96c", "#8a5a16"),
    "problem": ("#ff7f76", "#7a231e"),
}
FONT_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue", "Arial"]

STYLE = f"""
QWidget#root {{ background: {BACKGROUND}; }}
QLabel {{ color: {TEXT}; background: transparent; }}
QLabel#status {{ color: {MUTED}; font-size: 14px; }}
QLabel#status[tone="problem"] {{ color: {PROBLEM}; }}
QLabel#weather {{ color: {MUTED}; font-size: 12px; background: {SURFACE};
    border: 1px solid {BORDER}; border-radius: 13px; padding: 4px 12px; }}
QLabel#note {{ color: {WARNING}; font-size: 12px; }}
QScrollArea#chat {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 18px; }}
QWidget#chatinner {{ background: transparent; }}
QLabel#her {{ background: {RAISED}; border-radius: 16px; border-bottom-left-radius: 5px;
    padding: 9px 13px; font-size: 14px; }}
QLabel#you {{ background: {MINE}; color: #e8fbff; border-radius: 16px;
    border-bottom-right-radius: 5px; padding: 9px 13px; font-size: 14px; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 8px 2px 8px 0; }}
QScrollBar::handle:vertical {{ background: #2a3140; border-radius: 3px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: #3a4358; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""
MENU_STYLE = f"""
QMenu {{ background: {RAISED}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 10px;
    padding: 6px; font-size: 13px; }}
QMenu::item {{ padding: 7px 22px 7px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: #273044; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}
QMenu::indicator {{ width: 14px; height: 14px; }}
"""


def blend(a: QColor, b: QColor, t: float) -> QColor:
    """The colour ``t`` of the way from ``a`` to ``b``."""
    return QColor(round(a.red() + (b.red() - a.red()) * t),
                  round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


def faded(colour: QColor | str, alpha: int) -> QColor:
    c = QColor(colour)
    c.setAlpha(max(0, min(255, int(alpha))))
    return c


def ui_font(size: int, weight=QFont.Weight.Normal, spacing: float = 0.0) -> QFont:
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setPixelSize(size)
    font.setWeight(weight)
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return font


class Bridge(QObject):
    """Carries events from the assistant's background thread to the window."""

    event = Signal(str, dict)

    def send(self, kind: str, **data) -> None:
        self.event.emit(kind, data)


class Fade(QObject):
    """Lets a widget fade in and out (an opacity effect that's animated)."""

    def __init__(self, widget: QWidget):
        super().__init__(widget)
        self.effect = QGraphicsOpacityEffect(widget)
        self.effect.setOpacity(1.0)
        widget.setGraphicsEffect(self.effect)
        self.animation = QPropertyAnimation(self.effect, b"opacity", self)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self._finished)
        self._then = None

    def to(self, opacity: float, duration: int = 240, start: float | None = None,
           then=None) -> None:
        """Fade to ``opacity``; ``then`` is called once it's there."""
        self.animation.stop()
        self._then = then
        self.animation.setDuration(duration)
        self.animation.setStartValue(self.effect.opacity() if start is None else start)
        self.animation.setEndValue(opacity)
        self.animation.start()

    def _finished(self) -> None:
        then, self._then = self._then, None
        if then is not None:
            then()


def slide(value_from: float, value_to: float, duration: int, on_value, parent: QObject,
          curve=QEasingCurve.Type.OutCubic) -> QVariantAnimation:
    """Animate a number from one value to another, calling ``on_value`` on the way."""
    animation = QVariantAnimation(parent)
    animation.setStartValue(float(value_from))
    animation.setEndValue(float(value_to))
    animation.setDuration(duration)
    animation.setEasingCurve(curve)
    animation.valueChanged.connect(on_value)
    animation.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation


class Orb(QWidget):
    """A calm, glowing circle with her name in it. Its colour and movement show her state:
    breathing while she waits, swelling with your voice while she listens, a ring
    turning while she thinks, waves while she speaks."""

    def __init__(self, name: str = ""):
        super().__init__()
        self.name = name
        self.setMinimumSize(220, 230)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.state = "starting"
        self.bright, self.deep = (QColor(c) for c in ORB_COLOURS["starting"])
        self.target_bright, self.target_deep = self.bright, self.deep
        self.level = 0.0  # microphone loudness while listening, 0-1
        self.flash = 0.0  # a short glow when a single clap is heard
        self.ripple = 0.0  # a ring that runs outwards when her state changes
        self.awake = 0.0  # 0 while starting, 1 once she's ready (the name lights up)
        self.phase = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)  # about 30 frames a second

    def set_name(self, name: str) -> None:
        self.name = name
        self.update()

    def set_state(self, state: str) -> None:
        if state != self.state:
            self.ripple = 1.0
        self.state = state
        bright, deep = ORB_COLOURS.get(state, ORB_COLOURS["waiting"])
        self.target_bright, self.target_deep = QColor(bright), QColor(deep)

    def set_level(self, rms: float) -> None:
        # Speech is roughly 0.005-0.1 RMS; map it onto 0-1 on a log scale.
        value = 0.0 if rms <= 0 else min(1.0, max(0.0, (math.log10(rms) + 2.7) / 1.7))
        self.level = max(value, self.level * 0.8)

    def pulse(self) -> None:
        self.flash = 1.0

    def _tick(self) -> None:
        self.phase += 0.033
        self.bright = blend(self.bright, self.target_bright, 0.1)
        self.deep = blend(self.deep, self.target_deep, 0.1)
        self.level *= 0.92
        self.flash *= 0.88
        self.ripple = max(0.0, self.ripple - 0.028)
        goal = 0.0 if self.state == "starting" else 1.0
        self.awake += (goal - self.awake) * 0.08
        self.update()

    def _radius(self, base: float) -> float:
        if self.state == "waiting":
            grow = 0.035 * math.sin(self.phase * 1.3)  # slow breathing
        elif self.state == "listening":
            grow = 0.03 * math.sin(self.phase * 3) + 0.2 * self.level
        elif self.state == "speaking":
            grow = 0.05 * math.sin(self.phase * 7) * (0.6 + 0.4 * math.sin(self.phase * 2.3))
        elif self.state == "thinking":
            grow = 0.025 * math.sin(self.phase * 2)
        else:
            grow = 0.015 * math.sin(self.phase)
        return base * (1 + grow + 0.12 * self.flash)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        centre = QPointF(self.width() / 2, self.height() / 2)
        base = min(self.width(), self.height()) * 0.33
        radius = self._radius(base)
        background = QColor(BACKGROUND)

        # A soft glow around the circle, stronger while she listens to you.
        strength = 95 + 70 * self.level + 90 * self.flash
        glow = QRadialGradient(centre, radius * 2.0)
        glow.setColorAt(0.0, faded(self.deep, strength))
        glow.setColorAt(0.55, faded(self.deep, strength * 0.35))
        glow.setColorAt(1.0, faded(self.deep, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(centre, radius * 2.0, radius * 2.0)

        self._paint_rings(p, centre, radius)

        # The disc: deep in the middle, coloured towards the rim, so her name reads well.
        disc = QRadialGradient(centre - QPointF(radius * 0.25, radius * 0.3), radius * 1.45)
        disc.setColorAt(0.0, blend(background, self.deep, 0.55))
        disc.setColorAt(0.7, blend(background, self.deep, 0.8))
        disc.setColorAt(1.0, blend(self.deep, self.bright, 0.35))
        p.setBrush(disc)
        p.drawEllipse(centre, radius, radius)

        # A sheen on the top half, like glass.
        sheen = QLinearGradient(centre.x(), centre.y() - radius, centre.x(), centre.y())
        sheen.setColorAt(0.0, faded("white", 34))
        sheen.setColorAt(1.0, faded("white", 0))
        clip = QPainterPath()
        clip.addEllipse(centre, radius, radius)
        p.save()
        p.setClipPath(clip)
        p.setBrush(sheen)
        p.drawEllipse(centre - QPointF(0, radius * 0.45), radius * 0.95, radius * 0.6)
        p.restore()

        # The rim.
        rim = QPen(faded(self.bright, 170 + 70 * self.awake), 2.2)
        p.setPen(rim)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(centre, radius, radius)

        self._paint_name(p, centre, radius)
        p.end()

    def _paint_rings(self, p: QPainter, centre: QPointF, radius: float) -> None:
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self.ripple > 0:  # her state just changed: one ring runs outwards
            t = 1 - self.ripple
            pen = QPen(faded(self.bright, 150 * self.ripple), 1.6)
            p.setPen(pen)
            r = radius * (1.05 + 0.9 * (1 - (1 - t) ** 2))
            p.drawEllipse(centre, r, r)
        if self.state == "thinking":  # two arcs turning round the circle
            pen = QPen(blend(self.bright, QColor("white"), 0.25), 2.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            r = radius * 1.22
            box = QRectF(centre.x() - r, centre.y() - r, 2 * r, 2 * r)
            start = int(-self.phase * 200 * 16) % (360 * 16)
            sweep = int((70 + 30 * math.sin(self.phase * 2.5)) * 16)
            p.drawArc(box, start, sweep)
            p.drawArc(box, start + 180 * 16, sweep)
            p.setPen(QPen(faded(self.bright, 50), 1))
            p.drawEllipse(centre, r, r)
        elif self.state in ("listening", "speaking"):  # rings moving outwards
            speed = 0.55 if self.state == "listening" else 0.8
            for i in range(3):
                t = (self.phase * speed + i / 3) % 1.0
                p.setPen(QPen(faded(self.bright, 110 * (1 - t) ** 1.5), 1.6))
                r = radius * (1.08 + 0.75 * t + 0.1 * self.level)
                p.drawEllipse(centre, r, r)
        elif self.state == "starting":  # a faint arc going round while she gets ready
            pen = QPen(faded(self.bright, 110), 1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            r = radius * 1.18
            box = QRectF(centre.x() - r, centre.y() - r, 2 * r, 2 * r)
            p.drawArc(box, int(-self.phase * 150 * 16) % (360 * 16), 60 * 16)

    def _paint_name(self, p: QPainter, centre: QPointF, radius: float) -> None:
        if not self.name:
            return
        text, font = fit_name(self.name, radius * 1.6, radius * 1.1)
        if self.state == "waiting":
            glow = 0.5 + 0.5 * math.sin(self.phase * 1.3)  # the name breathes with the circle
        else:
            glow = 0.7
        alpha = 120 + (95 + 40 * glow) * self.awake
        p.setFont(font)
        box = QRectF(centre.x() - radius * 0.8, centre.y() - radius, radius * 1.6, 2 * radius)
        option = QTextOption(Qt.AlignmentFlag.AlignCenter)
        option.setWrapMode(QTextOption.WrapMode.WordWrap)
        p.setPen(faded(self.deep, 90))  # a soft shadow keeps it readable on the bright rim
        p.drawText(box.translated(0, 1.2), text, option)
        p.setPen(faded("white", alpha))
        p.drawText(box, text, option)


def fit_name(name: str, width: float, height: float) -> tuple[str, QFont]:
    """The largest font (and, if need be, a shortened name) that fits in the circle.

    Long names go onto two lines before they're made smaller, and are only cut
    short ("Mein persönlicher…") when even that doesn't help.
    """
    flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap
    box = QRectF(0, 0, width, height).toRect()
    for size in range(21, 11, -1):
        font = ui_font(size, QFont.Weight.DemiBold, 1.4 if size > 16 else 0.6)
        metrics = QFontMetrics(font)
        if metrics.horizontalAdvance(name) <= width:
            return name, font  # one line
        needed = metrics.boundingRect(box, flags, name)
        if needed.width() <= width and needed.height() <= height:
            return name, font  # two lines
    return metrics.elidedText(name, Qt.TextElideMode.ElideRight, int(width)), font


class ThinkingDots(QWidget):
    """Three dots rising and falling in turn: the bubble she's about to fill."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(58, 36)
        self.phase = 0.0
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(33)

    def _tick(self) -> None:
        self.phase += 0.12
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(RAISED))
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), self.height()), 16, 16)
        path.addRoundedRect(QRectF(0, self.height() - 12, 12, 12), 5, 5)
        p.drawPath(path.simplified())
        for i in range(3):
            lift = max(0.0, math.sin(self.phase - i * 0.9))
            p.setBrush(faded(TEXT, 110 + 120 * lift))
            x = 16 + i * 13
            y = self.height() / 2 - 3 * lift
            p.drawEllipse(QPointF(x, y), 3.2, 3.2)
        p.end()


class TalkButton(QPushButton):
    """A pill button that glows softly, reacts to the mouse, and changes smoothly
    from "Talk" (filled) to "End conversation" (quiet) and back."""

    def __init__(self, text: str):
        super().__init__(text)
        self.hover = 0.0
        self.press = 0.0
        self.ending = 0.0  # 0 = Talk, 1 = End conversation
        self.ready = 0.0  # 0 = disabled, 1 = enabled
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(44)
        self.setFont(ui_font(14, QFont.Weight.DemiBold, 0.3))
        self.setProperty("ending", False)
        self._animations: dict[str, QVariantAnimation] = {}

    def sizeHint(self):
        hint = super().sizeHint()
        widest = max(self.fontMetrics().horizontalAdvance(t) for t in self._texts()) + 64
        hint.setWidth(max(hint.width(), widest, 180))
        return hint

    def _texts(self) -> list[str]:
        return [t for t in (self.text(), getattr(self, "other_text", "")) if t]

    def set_ending(self, ending: bool, text: str) -> None:
        self.other_text = self.text() if self.text() != text else getattr(self, "other_text", "")
        self.setText(text)
        self.setProperty("ending", ending)
        self._animate("ending", 1.0 if ending else 0.0, 280)

    def _animate(self, field: str, target: float, duration: int) -> None:
        """Move one of the 0-1 values (hover, press, ending, ready) smoothly to ``target``."""
        animation = self._animations.get(field)
        if animation is None:
            animation = self._animations[field] = QVariantAnimation(self)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.valueChanged.connect(
                lambda value, field=field: (setattr(self, field, float(value)), self.update()))
        animation.stop()
        animation.setStartValue(float(getattr(self, field)))
        animation.setEndValue(float(target))
        animation.setDuration(duration)
        animation.start()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange:
            self._animate("ready", 1.0 if self.isEnabled() else 0.0, 260)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self._animate("hover", 1.0, 140)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._animate("hover", 0.0, 220)

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        self._animate("press", 1.0, 80)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        self._animate("press", 0.0, 220)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()
        scale = 1 - 0.03 * self.press
        p.translate(w / 2, h / 2)
        p.scale(scale, scale)
        p.translate(-w / 2, -h / 2)
        pill = QRectF(1, 1, w - 2, h - 2)

        # Colours: a filled accent pill to start talking, a quiet dark one to stop.
        talk_bg = blend(QColor(ACCENT), QColor("white"), 0.12 * self.hover)
        end_bg = blend(QColor(RAISED), QColor("#262d3b"), self.hover)
        bg = blend(talk_bg, end_bg, self.ending)
        text_colour = blend(QColor("#06181c"), QColor(TEXT), self.ending)
        off_bg, off_text = QColor(SURFACE), QColor(MUTED)
        bg = blend(off_bg, bg, self.ready)
        text_colour = blend(off_text, text_colour, self.ready)
        border = faded(blend(QColor(BORDER), QColor(ACCENT), 0.25 * (1 - self.ending)),
                       255 * max(self.ending, 1 - self.ready))

        # A soft glow under the Talk button, brighter under the mouse.
        glow_alpha = 70 * self.ready * (1 - self.ending) * (0.45 + 0.55 * self.hover)
        if glow_alpha > 1:
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(4, 0, -1):
                p.setBrush(faded(ACCENT, glow_alpha / (i * 2.2)))
                p.drawRoundedRect(pill.adjusted(-i * 2.2, -i * 1.4, i * 2.2, i * 3), h, h)

        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(pill, h / 2 - 1, h / 2 - 1)
        p.setPen(text_colour)
        p.setFont(self.font())
        p.drawText(pill, self.text(), QTextOption(Qt.AlignmentFlag.AlignCenter))
        p.end()


class Chat(QScrollArea):
    """The conversation, as speech bubbles: hers on the left, yours on the right.
    New bubbles slide in, and the list scrolls down smoothly."""

    def __init__(self):
        super().__init__()
        self.setObjectName("chat")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setAutoFillBackground(False)
        self.setViewportMargins(0, 10, 0, 10)  # bubbles scroll out of sight before the corners
        inner = QWidget()
        inner.setObjectName("chatinner")
        self.column = QVBoxLayout(inner)
        self.column.setContentsMargins(14, 4, 14, 4)
        self.column.setSpacing(8)
        self.column.addStretch()
        self.setWidget(inner)
        self.messages: list[QWidget] = []  # one holder per bubble, oldest first
        self.dots: QWidget | None = None  # the thinking indicator's holder
        self.scrolling = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self.scrolling.setDuration(260)
        self.scrolling.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.verticalScrollBar().rangeChanged.connect(self._scroll_down)

    def add(self, text: str, mine: bool) -> None:
        bubble = QLabel(text)
        bubble.setObjectName("you" if mine else "her")
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        holder = self._row(bubble, right=mine)
        self.column.insertWidget(self._next_index(), holder)
        self.messages.append(holder)
        self._fit(bubble)  # now it's in the window, its font size is known
        self._reveal(holder)
        while len(self.messages) > MAX_MESSAGES:  # keep the window light
            old = self.messages.pop(0)
            self.column.removeWidget(old)
            old.deleteLater()

    def extend_last(self, text: str) -> None:
        """Add a sentence to her last bubble (an answer arrives sentence by sentence)."""
        bubbles = [b for b in self.widget().findChildren(QLabel) if b.objectName() == "her"]
        if not bubbles:
            self.add(text, mine=False)
            return
        bubble = bubbles[-1]
        bubble.setText(f"{bubble.text()} {text}")
        self._fit(bubble)

    def show_thinking(self, on: bool) -> None:
        """Three moving dots at the bottom while she thinks about an answer."""
        if on and self.dots is None:
            self.dots = self._row(ThinkingDots(), right=False)
            self.column.insertWidget(self.column.count() - 1, self.dots)
            self._reveal(self.dots)
        elif not on and self.dots is not None:
            dots, self.dots = self.dots, None
            self.column.removeWidget(dots)
            dots.hide()
            dots.deleteLater()

    def _next_index(self) -> int:
        """Where a new bubble goes: before the stretch, and before the thinking dots."""
        return self.column.count() - 1 - (1 if self.dots is not None else 0)

    @staticmethod
    def _row(widget: QWidget, right: bool) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if right:
            row.addStretch()
        row.addWidget(widget)
        if not right:
            row.addStretch()
        holder = QWidget()
        holder.setLayout(row)
        return holder

    def _reveal(self, holder: QWidget) -> None:
        """Fade the new bubble in while it slides up into place."""
        Fade(holder).to(1.0, 300, start=0.0)
        row = holder.layout()
        slide(16, 0, 320, lambda v: row.setContentsMargins(0, int(v), 0, 0), holder)

    def _fit(self, bubble: QLabel) -> None:
        """As wide as its text, but at most 80% of the chat's width (then it wraps)."""
        bubble.ensurePolished()  # so the style sheet's font size is applied
        natural = bubble.fontMetrics().horizontalAdvance(bubble.text()) + 40  # + padding
        widest = max(160, int(max(self.viewport().width(), 360) * 0.8))
        bubble.setFixedWidth(min(natural, widest))

    def _scroll_down(self, _low: int, high: int) -> None:
        bar = self.verticalScrollBar()
        self.scrolling.stop()
        self.scrolling.setStartValue(bar.value())
        self.scrolling.setEndValue(high)
        self.scrolling.start()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        for bubble in self.widget().findChildren(QLabel):
            self._fit(bubble)


def orb_icon(size: int = 256, colours=ORB_COLOURS["listening"]) -> QPixmap:
    """The app icon: the circle on a transparent background."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    centre = QPointF(size / 2, size / 2)
    r = size * 0.4
    bright, deep = QColor(colours[0]), QColor(colours[1])
    disc = QRadialGradient(centre - QPointF(r * 0.25, r * 0.3), r * 1.45)
    disc.setColorAt(0.0, blend(QColor(BACKGROUND), deep, 0.6))
    disc.setColorAt(0.7, blend(QColor(BACKGROUND), deep, 0.85))
    disc.setColorAt(1.0, blend(deep, bright, 0.4))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(disc)
    p.drawEllipse(centre, r, r)
    p.setPen(QPen(bright, max(1.5, size * 0.03)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(centre, r, r)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(blend(bright, QColor("white"), 0.6))
    p.drawEllipse(centre, r * 0.22, r * 0.22)  # a bright heart, so it reads at tray size
    p.end()
    return pixmap


class Window(QWidget):
    def __init__(self, words: Phrases, on_talk=None, on_stop=None, name: str | None = None):
        super().__init__()
        self.words = words
        self.name = name or words.app_title  # what the circle shows
        self.on_talk = on_talk or (lambda: None)  # Talk button: start a conversation
        self.on_stop = on_stop or (lambda: None)  # ... and end it again
        self.quitting = False
        self.hint_shown = False
        self.problem = False  # something stops her working: keep that message showing
        self.setObjectName("root")
        self.setWindowTitle(self.name)
        self.setWindowIcon(QIcon(orb_icon()))
        self.resize(400, 700)
        self.setMinimumSize(340, 560)
        self.setStyleSheet(STYLE)
        self.setFont(ui_font(14))

        self.weather = QLabel("")
        self.weather.setObjectName("weather")
        self.weather.hide()  # until the temperature is known
        self.weather_fade = Fade(self.weather)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addStretch()
        header.addWidget(self.weather)

        self.orb = Orb(self.name)
        self.status = QLabel(words.status["starting"])
        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_fade = Fade(self.status)
        self.note = QLabel("")
        self.note.setObjectName("note")
        self.note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.note.setWordWrap(True)
        self.note.setMinimumHeight(34)
        self.note_fade = Fade(self.note)
        self.note_timer = QTimer(self)
        self.note_timer.setSingleShot(True)
        self.note_timer.timeout.connect(self._hide_note)

        self.talk = TalkButton(words.talk_button)
        self.talk.other_text = words.end_button  # so the button is wide enough for both
        self.talk.setObjectName("talk")
        self.talk.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # space is the shortcut instead
        self.talk.setEnabled(False)
        self.talk.clicked.connect(self._talk_clicked)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self._talk_clicked)
        talk_row = QHBoxLayout()
        talk_row.addStretch()
        talk_row.addWidget(self.talk)
        talk_row.addStretch()

        self.chat = Chat()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 16, 22, 20)
        layout.setSpacing(4)
        layout.addLayout(header)
        layout.addWidget(self.orb)
        layout.addWidget(self.status)
        layout.addWidget(self.note)
        layout.addSpacing(4)
        layout.addLayout(talk_row)
        layout.addSpacing(16)
        layout.addWidget(self.chat, 1)

        self.appear = QPropertyAnimation(self, b"windowOpacity", self)
        self.appear.setDuration(340)
        self.appear.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.tray = self._make_tray()

    def _make_tray(self) -> QSystemTrayIcon | None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        tray = QSystemTrayIcon(QIcon(orb_icon(64)), self)
        tray.setToolTip(f"{self.name}: {self.words.status['starting']}")
        menu = QMenu()
        menu.setStyleSheet(MENU_STYLE)
        show = QAction(self.words.show_window, menu)
        show.triggered.connect(self.bring_back)
        leave = QAction(self.words.quit_app, menu)
        leave.triggered.connect(self.quit)
        menu.addAction(show)
        if sys.platform == "win32":
            from .shortcut import autostart_enabled

            self.autostart = QAction(self.words.autostart, menu)
            self.autostart.setCheckable(True)
            self.autostart.setChecked(autostart_enabled(self.words.app_title))
            self.autostart.toggled.connect(self._autostart_toggled)
            menu.addAction(self.autostart)
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

    def _talk_clicked(self) -> None:
        if not self.talk.isEnabled():
            return
        if self.talk.property("ending"):
            self.on_stop()
        else:
            self.on_talk()
        self.talk.setEnabled(False)  # until she reports she's started (or stopped)

    def _show_button_for(self, state: str) -> None:
        busy = state in ("listening", "thinking", "speaking")
        self.talk.set_ending(busy, self.words.end_button if busy else self.words.talk_button)
        self.talk.setEnabled(state in ("waiting", "listening", "thinking", "speaking"))

    def _set_status(self, text: str, problem: bool = False) -> None:
        if text == self.status.text() and bool(self.status.property("tone")) == problem:
            return
        self.status.setText(text)
        self.status.setProperty("tone", "problem" if problem else "")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.status_fade.to(1.0, 320, start=0.0)

    def _show_note(self, text: str) -> None:
        self.note.setText(shorten(text))
        self.note_fade.to(1.0, 260, start=0.0)

    def _hide_note(self) -> None:
        self.note_fade.to(0.0, 400, then=lambda: self.note.setText(""))

    def _autostart_toggled(self, enabled: bool) -> None:
        from .shortcut import set_autostart

        try:
            set_autostart(self.words.app_title, enabled)
        except Exception as exc:
            print(f"({self.words.autostart_failed}: {exc})")
            self.on_event("note", {"text": f"{self.words.autostart_failed}: {exc}"})
            self.autostart.blockSignals(True)
            self.autostart.setChecked(not enabled)
            self.autostart.blockSignals(False)

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
            self.tray.showMessage(self.name, self.words.tray_hint, QIcon(orb_icon(64)), 6000)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        dark_title_bar(self)
        self.appear.stop()  # the window fades in
        self.appear.setStartValue(0.0)
        self.appear.setEndValue(1.0)
        self.appear.start()

    # -- events from the assistant -------------------------------------------
    def on_event(self, kind: str, data: dict) -> None:
        if kind == "state":
            state = data["state"]
            self.orb.set_state(state)
            self._set_status(self.words.status.get(state, ""), problem=state == "problem")
            self._show_button_for(state)
            self.chat.show_thinking(state == "thinking")
            if self.tray:
                self.tray.setToolTip(f"{self.name}: {self.words.status.get(state, '')}")
        elif kind == "said":
            self.chat.show_thinking(False)
            if data.get("continued"):
                self.chat.extend_last(data["text"])  # the next sentence of the same answer
            else:
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
            if self.weather.isHidden():
                self.weather.show()
                self.weather_fade.to(1.0, 500, start=0.0)
        elif kind == "note":
            if not self.problem:  # don't cover up a problem with a passing note
                self._show_note(data["text"])
                self.note_timer.start(NOTE_SECONDS * 1000)
        elif kind == "problem":
            self.problem = True
            self.note_timer.stop()
            self._show_note(data["text"])
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


def run_window(config: Config, minimized: bool = False) -> None:
    """Open her window and start the assistant in the background.

    With ``minimized`` (when Windows starts her), she starts hidden in the tray.
    """
    from .main import Assistant  # here, so the window module stays light to import

    app = QApplication.instance() or QApplication(sys.argv)
    if already_running():
        return  # the window that's already open has come forward
    sys.stdout = LogFile(LOG_FILE, sys.__stdout__)
    sys.stderr = sys.stdout
    bridge = Bridge()
    assistant = Assistant(config, events=bridge.send)
    app.setApplicationName(assistant.name)
    app.setQuitOnLastWindowClosed(False)  # hidden in the tray isn't "closed"
    window = Window(assistant.words, on_talk=assistant.request_talk,
                    on_stop=assistant.request_stop, name=assistant.name)
    bridge.event.connect(window.on_event)
    window.server = answer_later_starts(window)
    if minimized and window.tray is not None:
        window.hint_shown = True  # she starts in the tray on purpose: no reminder needed
    else:
        window.show()

    def work() -> None:
        try:
            assistant.run()
        except Exception as exc:  # e.g. no microphone: show it rather than vanish
            traceback.print_exc()
            bridge.send("problem", text=problem_message(exc))

    threading.Thread(target=work, name="assistant", daemon=True).start()
    app.exec()
