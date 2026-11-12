"""The overlay: an invisible window on top of everything, where Oyan lives.

How it works
------------
* For every monitor we create one see-through window that covers the whole
  screen. Mouse clicks pass straight through it, so it never gets in the way.
* A timer ticks about 60 times a second. On every tick we work out where the
  buddy should be now and repaint the small areas that changed.

What the buddy is doing (its "mode")
------------------------------------
* "follow" - gliding after the mouse cursor. This is the normal mode.
* "glide"  - flying along a curved path to a spot (to point, or to start writing).
* "pause"  - sitting still on the spot for a moment, so you notice it.
* "write"  - riding along the answer as it is written (see handwriting.py).

Coordinates
-----------
Qt gives positions in "points", not real pixels. On a Retina screen one point
is 2x2 pixels. Everything in this file is in points, in one shared "global"
coordinate space that spans all monitors.
"""

import math
import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from oyan.handwriting import Note

# --- Things you can tweak -------------------------------------------------

BUDDY_RADIUS = 7            # size of the buddy dot, in points
OFFSET_FROM_CURSOR = (20, 22)  # sit below-right of the arrow, not under it
FOLLOW_SPEED = 0.18         # 0..1, how much of the gap is closed per tick
BOB_HEIGHT = 2.0            # how far it floats up and down, in points
BOB_SPEED = 3.0             # how fast it floats
TICK_MS = 16                # 16 ms per tick is about 60 frames per second

GLIDE_SPEED = 900           # points per second when flying to a spot
GLIDE_MIN_SECONDS = 0.45    # ...but never quicker than this
GLIDE_MAX_SECONDS = 1.2     # ...or slower than this
GLIDE_CURVE = 0.25          # how much the path bends (0 = straight line)
POINT_PAUSE_SECONDS = 0.35  # how long it rests on the spot before writing
WRITE_SPEED = 38            # letters per second

BUDDY_COLOR = QColor(255, 153, 51)     # warm orange
BUDDY_OUTLINE = QColor(60, 40, 20)     # dark brown, like pencil


class ScreenOverlay(QWidget):
    """One transparent, click-through window covering one monitor."""

    def __init__(self, screen, controller):
        super().__init__()
        self.controller = controller

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint          # no title bar or border
            | Qt.WindowType.WindowStaysOnTopHint       # above other windows
            | Qt.WindowType.Tool                       # no Dock icon / app switcher entry
            | Qt.WindowType.WindowTransparentForInput  # clicks pass through
            | Qt.WindowType.WindowDoesNotAcceptFocus   # never steal typing
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        # macOS normally hides "Tool" windows when you switch to another app.
        # Oyan must stay visible all the time.
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)

        # Cover the whole monitor.
        self.setGeometry(screen.geometry())

    def paintEvent(self, event):
        """Qt calls this whenever part of the window needs redrawing."""
        controller = self.controller
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Everything is stored in global coordinates (all monitors). Shift
        # the painter so that global positions land in the right place in
        # this window.
        painter.translate(-QPointF(self.geometry().topLeft()))

        if controller.note is not None:
            controller.note.paint(painter)

        if not controller.buddy_visible:
            return   # hidden while a screenshot is being taken

        pos = controller.buddy_pos
        radius = BUDDY_RADIUS * controller.pulse()
        painter.setPen(QPen(BUDDY_OUTLINE, 1.5))
        painter.setBrush(BUDDY_COLOR)
        painter.drawEllipse(pos, radius, radius)

        # A tiny highlight so the dot looks a bit like a marble.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 170))
        painter.drawEllipse(pos + QPointF(-2.5, -2.5), 2, 2)


class OverlayController:
    """Owns the overlay windows and moves the buddy on every timer tick."""

    def __init__(self, app):
        self.app = app
        self.overlays = []
        self.buddy_pos = QPointF(QCursor.pos())  # start at the cursor
        self.buddy_visible = True
        self.thinking = False   # True while waiting for the AI: the buddy pulses
        self.start_time = time.monotonic()
        self.last_tick = self.start_time

        self.mode = "follow"
        self.note = None          # the answer on screen, if any
        self.glide = None         # details of the current flight (see _start_glide)
        self.pause_until = 0.0

        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)

        # If a monitor is plugged in or removed, rebuild the windows.
        app.screenAdded.connect(self.rebuild_overlays)
        app.screenRemoved.connect(self.rebuild_overlays)

    def start(self):
        self.rebuild_overlays()
        self.timer.start(TICK_MS)

    def rebuild_overlays(self, *_):
        """Create one overlay window per monitor (throwing away old ones)."""
        for overlay in self.overlays:
            overlay.close()
        self.overlays = []
        for screen in self.app.screens():
            overlay = ScreenOverlay(screen, self)
            overlay.show()
            self.overlays.append(overlay)

    def set_buddy_visible(self, visible):
        """Hide or show the buddy (hidden so it is not in the screenshot)."""
        self.buddy_visible = visible
        for overlay in self.overlays:
            overlay.repaint()   # redraw right now, do not wait for the next tick

    def pulse(self):
        """Size multiplier for the buddy: 1.0 normally, breathing while thinking."""
        if not self.thinking:
            return 1.0
        seconds = time.monotonic() - self.start_time
        return 1.0 + 0.3 * math.sin(seconds * 8)

    # --- Showing and removing an answer -------------------------------------

    def show_answer(self, text, spot):
        """Fly to `spot` and write `text` beside it.

        `spot` is a global screen position (QPointF), or None if the AI did
        not point at anything; then the note is written near the buddy.
        """
        self.dismiss()
        anchor = spot if spot is not None else self.buddy_pos
        screen = QGuiApplication.screenAt(anchor.toPoint()) or QGuiApplication.primaryScreen()
        self.note = Note(text, anchor, screen.geometry(), has_point=spot is not None)

        if spot is not None:
            self._start_glide(spot, then=self._arrived_at_spot)
        else:
            self._arrived_at_spot()

    def dismiss(self):
        """Remove the answer and go back to following the cursor."""
        if self.note is not None:
            self._repaint(self.note.bounds())
        self.note = None
        self.mode = "follow"

    def _arrived_at_spot(self):
        """The buddy is on the spot: show the paper, rest a moment."""
        self.note.visible = True
        self._repaint(self.note.bounds())
        self.mode = "pause"
        self.pause_until = time.monotonic() + POINT_PAUSE_SECONDS

    def _start_writing(self):
        self.mode = "write"

    # --- Flying along a curve -----------------------------------------------

    def _start_glide(self, destination, then):
        """Begin a curved flight to `destination`; call `then()` on arrival.

        The path is a "quadratic Bezier curve": it starts at `start`, ends at
        `end`, and is pulled sideways toward a third point, `bend`. We put
        `bend` beside the middle of the straight line, which gives a gentle arc.
        """
        start = QPointF(self.buddy_pos)
        end = QPointF(destination)
        dx, dy = end.x() - start.x(), end.y() - start.y()
        distance = math.hypot(dx, dy)
        middle = (start + end) / 2
        # (-dy, dx) is the direction at a right angle to the straight line.
        bend = middle + QPointF(-dy, dx) * GLIDE_CURVE
        seconds = min(max(distance / GLIDE_SPEED, GLIDE_MIN_SECONDS), GLIDE_MAX_SECONDS)
        self.glide = {
            "start": start, "bend": bend, "end": end,
            "began": time.monotonic(), "seconds": seconds, "then": then,
        }
        self.mode = "glide"

    def _glide_position(self, now):
        """Where on the curve the buddy is at time `now`, and whether it arrived."""
        g = self.glide
        t = min((now - g["began"]) / g["seconds"], 1.0)   # 0 at start, 1 at end
        t = t * t * (3 - 2 * t)   # "ease in and out": slow, fast, slow
        pos = g["start"] * (1 - t) ** 2 + g["bend"] * 2 * (1 - t) * t + g["end"] * t ** 2
        return pos, t >= 1.0

    # --- The heartbeat -------------------------------------------------------

    def tick(self):
        """Move the buddy one step, depending on its mode, and repaint."""
        now = time.monotonic()
        seconds_passed = now - self.last_tick
        self.last_tick = now
        old_pos = QPointF(self.buddy_pos)

        if self.mode == "follow":
            # Where the buddy wants to be: next to the cursor, floating gently.
            bob = math.sin((now - self.start_time) * BOB_SPEED) * BOB_HEIGHT
            cursor = QPointF(QCursor.pos())
            target = cursor + QPointF(OFFSET_FROM_CURSOR[0], OFFSET_FROM_CURSOR[1] + bob)
            # Close a fraction of the gap. Far away = big step, close = tiny step.
            self.buddy_pos += (target - self.buddy_pos) * FOLLOW_SPEED

        elif self.mode == "glide":
            self.buddy_pos, arrived = self._glide_position(now)
            if arrived:
                self.glide["then"]()

        elif self.mode == "pause":
            if now >= self.pause_until:
                # Hop from the spot to where the first letter goes, then write.
                self._start_glide(self.note.pen_position(), then=self._start_writing)

        elif self.mode == "write":
            self.note.progress += WRITE_SPEED * seconds_passed
            self.buddy_pos = self.note.pen_position()
            self._repaint(self.note.bounds())
            if self.note.finished():
                self.mode = "follow"   # done: the note stays, the buddy goes home

        # Repaint the small squares where the buddy was and now is.
        self._repaint(self._buddy_rect(old_pos))
        self._repaint(self._buddy_rect(self.buddy_pos))

    def _repaint(self, global_rect):
        """Ask every window to redraw the part of it that shows this rectangle."""
        for overlay in self.overlays:
            corner = QPointF(overlay.geometry().topLeft())
            overlay.update(global_rect.translated(-corner).toAlignedRect())

    @staticmethod
    def _buddy_rect(center):
        """A square around the buddy, slightly bigger than the buddy itself."""
        pad = BUDDY_RADIUS + 8   # room for the outline and the pulse
        return QRectF(center.x() - pad, center.y() - pad, pad * 2, pad * 2)
