"""The overlay: an invisible window on top of everything, where Oyan lives.

How it works
------------
* For every monitor we create one see-through window that covers the whole
  screen. Mouse clicks pass straight through it, so it never gets in the way.
* A timer ticks about 60 times a second. On every tick we look at where the
  mouse cursor is and move the buddy a little bit toward it. Moving only a
  fraction of the remaining distance each tick is what makes it glide
  instead of jumping.
* Each window then repaints only the small area around the buddy.

Coordinates
-----------
Qt gives positions in "points", not real pixels. On a Retina screen one point
is 2x2 pixels. Everything in this file is in points, in one shared "global"
coordinate space that spans all monitors. This will matter later when we map
screenshot pixels back to screen positions.
"""

import math
import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QCursor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

# --- Things you can tweak -------------------------------------------------

BUDDY_RADIUS = 7            # size of the buddy dot, in points
OFFSET_FROM_CURSOR = (20, 22)  # sit below-right of the arrow, not under it
FOLLOW_SPEED = 0.18         # 0..1, how much of the gap is closed per tick
BOB_HEIGHT = 2.0            # how far it floats up and down, in points
BOB_SPEED = 3.0             # how fast it floats
TICK_MS = 16                # 16 ms per tick is about 60 frames per second

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
        if not self.controller.buddy_visible:
            return   # hidden while a screenshot is being taken

        # The buddy position is global (all monitors). Convert it to a
        # position inside this window by subtracting the window's corner.
        local = self.controller.buddy_pos - QPointF(self.geometry().topLeft())

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(BUDDY_OUTLINE, 1.5))
        painter.setBrush(BUDDY_COLOR)
        radius = BUDDY_RADIUS * self.controller.pulse()
        painter.drawEllipse(local, radius, radius)

        # A tiny highlight so the dot looks a bit like a marble.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 170))
        painter.drawEllipse(local + QPointF(-2.5, -2.5), 2, 2)


class OverlayController:
    """Owns the overlay windows and moves the buddy on every timer tick."""

    def __init__(self, app):
        self.app = app
        self.overlays = []
        self.buddy_pos = QPointF(QCursor.pos())  # start at the cursor
        self.buddy_visible = True
        self.thinking = False   # True while waiting for the AI: the buddy pulses
        self.start_time = time.monotonic()

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

    def tick(self):
        """Move the buddy a step toward the cursor and repaint."""
        old_pos = QPointF(self.buddy_pos)

        # Where the buddy wants to be: next to the cursor, floating gently.
        seconds = time.monotonic() - self.start_time
        bob = math.sin(seconds * BOB_SPEED) * BOB_HEIGHT
        cursor = QPointF(QCursor.pos())
        target = cursor + QPointF(OFFSET_FROM_CURSOR[0], OFFSET_FROM_CURSOR[1] + bob)

        # Close a fraction of the gap. Far away = big step, close = tiny step.
        self.buddy_pos += (target - self.buddy_pos) * FOLLOW_SPEED

        # Repaint only the small squares where the buddy was and now is.
        for overlay in self.overlays:
            corner = QPointF(overlay.geometry().topLeft())
            for pos in (old_pos, self.buddy_pos):
                overlay.update(self._dirty_rect(pos - corner))

    @staticmethod
    def _dirty_rect(center):
        """A square around the buddy, slightly bigger than the buddy itself."""
        pad = BUDDY_RADIUS + 8   # room for the outline and the pulse
        return QRectF(center.x() - pad, center.y() - pad, pad * 2, pad * 2).toAlignedRect()
