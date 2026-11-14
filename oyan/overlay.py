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
* "draw"   - drawing a circle, underline or arrow (see marks.py).
* "write"  - riding along the answer as it is written (see handwriting.py).
* "wipe"   - scrubbing across an answer like a board eraser, removing it.
* "doodle" - drawing a small idle sketch in a corner (see doodles.py).
* "admire" - sitting next to the finished doodle for a few seconds.

The board
---------
Answers stay on screen like writing on a school board (`self.notes`) until
they are wiped. While a screenshot is taken they are hidden for a moment, so
old answers are never in the picture that is sent.

Coordinates
-----------
Qt gives positions in "points", not real pixels. On a Retina screen one point
is 2x2 pixels. Everything in this file is in points, in one shared "global"
coordinate space that spans all monitors.
"""

import math
import time

import objc
from AppKit import (
    NSScreenSaverWindowLevel,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskNonactivatingPanel,
)
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from oyan.doodles import make_doodle
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
WIPE_SECONDS = 0.55         # how long the eraser takes to wipe one answer
DRAW_SPEED = 520            # points of marker line drawn per second

IDLE_SECONDS = 30           # mouse still for this long -> draw a doodle
DOODLE_PAUSE_SECONDS = 45   # wait at least this long between doodles
DOODLE_SIZE = 84            # how big a doodle is, in points
DOODLE_MARGIN = 36          # distance from the corner of the screen
DOODLE_SPEED = 260          # points of line drawn per second (unhurried)
ADMIRE_SECONDS = 8          # how long a finished doodle stays
DOODLE_FADE_SECONDS = 0.8   # how long it takes to fade away

BUDDY_COLOR = QColor(255, 153, 51)     # warm orange
BUDDY_OUTLINE = QColor(60, 40, 20)     # dark brown, like pencil


def show_on_every_desktop(widget, takes_keyboard=False):
    """Make a window visible on all desktops ("Spaces") and over full-screen apps.

    By default a window belongs to the one desktop it was opened on, so Oyan
    would vanish when you swipe to another desktop or make an app full screen.
    Qt has no setting for this, so we ask macOS directly: we get the real
    macOS window behind the Qt widget and change two of its properties.
    """
    view = objc.objc_object(c_void_p=int(widget.winId()))   # the macOS view
    window = view.window()                                   # ...and its window
    # "Non-activating panel": a helper window that belongs to no particular
    # app's desktop. macOS needs this to keep it steady over full-screen apps.
    # A window you type into (the ask box) must NOT have it, or a click in
    # the window would not give it the keyboard.
    if not takes_keyboard:
        window.setStyleMask_(window.styleMask() | NSWindowStyleMaskNonactivatingPanel)
    window.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces         # on every desktop
        | NSWindowCollectionBehaviorFullScreenAuxiliary    # over full-screen apps
        | NSWindowCollectionBehaviorStationary             # does not slide away with a desktop
        | NSWindowCollectionBehaviorIgnoresCycle           # skipped by Cmd+` window switching
    )
    window.setLevel_(NSScreenSaverWindowLevel)               # above everything, like a screen saver
    window.setHidesOnDeactivate_(False)                      # stay when another app comes forward
    window.setCanHide_(False)                                # stay when apps are hidden


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

    def showEvent(self, event):
        """Qt calls this when the window appears."""
        super().showEvent(event)
        show_on_every_desktop(self)

    def paintEvent(self, event):
        """Qt calls this whenever part of the window needs redrawing."""
        controller = self.controller
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Everything is stored in global coordinates (all monitors). Shift
        # the painter so that global positions land in the right place in
        # this window.
        painter.translate(-QPointF(self.geometry().topLeft()))

        if controller.notes_visible and controller.doodle is not None:
            controller.doodle.paint(painter)

        if controller.notes_visible:
            for note in controller.notes:
                for mark in note.marks:
                    mark.paint(painter)
                note.paint(painter)

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
        self.notes = []           # every answer on the board, oldest first
        self.notes_visible = True # False for a moment while a screenshot is taken
        self.writing = None       # the note being written right now, if any
        self.to_draw = []         # marks still waiting to be drawn
        self.drawing = None       # the mark being drawn right now, if any
        self.on_note_finished = None   # a function to call when writing ends
        self.glide = None         # details of the current flight (see _start_glide)
        self.pause_until = 0.0

        # Idle doodles.
        self.doodle = None                 # the sketch on screen, if any
        self.doodle_name = None            # which one it was, to avoid repeats
        self.doodle_fading_since = None    # when it started to fade away
        self.last_cursor = QCursor.pos()
        self.still_since = self.start_time # when the mouse last stopped moving
        self.next_doodle_at = self.start_time
        self.may_doodle = lambda: True     # the app can say "not now" (see app.py)

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

    def set_board_visible(self, visible):
        """Hide or show the buddy AND the answers (hidden during a screenshot)."""
        if not visible:
            self.remove_doodle()
        self.notes_visible = visible
        self.set_buddy_visible(visible)

    @property
    def note(self):
        """The newest answer on the board, or None if the board is empty."""
        return self.notes[-1] if self.notes else None

    def pulse(self):
        """Size multiplier for the buddy: 1.0 normally, breathing while thinking."""
        if not self.thinking:
            return 1.0
        seconds = time.monotonic() - self.start_time
        return 1.0 + 0.3 * math.sin(seconds * 8)

    # --- Showing and removing an answer -------------------------------------

    def show_answer(self, text, spot, marks=(), hint=None):
        """Draw the `marks`, then fly to `spot` and write `text` beside it.

        `spot` is a global screen position (QPointF), or None if the AI did
        not point at anything; then the note is written near the buddy.
        `marks` is a list of Mark objects (see marks.py); it may be empty.
        `hint` replaces the small reminder shown under the note, if given.
        Returns the new note.
        """
        self.remove_doodle()
        # An unfinished wipe or older reminders should not linger.
        for old in self.notes:
            old.wipe = 0.0
            old.show_hint = False
            self._repaint(old.bounds())
            for mark in old.marks:
                mark.progress = 1.0   # finish any half-drawn mark at once
                mark.fade = 1.0
                self._repaint(mark.bounds())

        anchor = spot if spot is not None else self.buddy_pos
        screen = QGuiApplication.screenAt(anchor.toPoint()) or QGuiApplication.primaryScreen()
        # One rectangle around all the marks, so the note can keep out of it.
        marks_area = None
        for mark in marks:
            marks_area = mark.bounds() if marks_area is None else marks_area.united(mark.bounds())

        new_note = Note(
            text, anchor, screen.geometry(),
            has_point=spot is not None,
            avoid=[old.bounds() for old in self.notes],
            clear_of=marks_area,
        )
        self.notes.append(new_note)
        new_note.marks = list(marks)   # they belong to this answer and are wiped with it
        if hint is not None:
            new_note.hint_text = hint
        self.writing = new_note
        self.spot = spot

        self.to_draw = list(marks)
        self.drawing = None
        self._draw_next()
        return new_note

    def remove_note(self, note):
        """Take one answer (and its marks) off the board at once."""
        if note in self.notes:
            self._repaint(note.bounds())
            for mark in note.marks:
                self._repaint(mark.bounds())
            self.notes.remove(note)

    def _draw_next(self):
        """Draw the next waiting mark; when none are left, go and write."""
        if self.to_draw:
            self.drawing = self.to_draw.pop(0)
            self._start_glide(self.drawing.start_position(), then=self._start_drawing)
        elif self.spot is not None:
            self._start_glide(self.spot, then=self._arrived_at_spot)
        else:
            self._arrived_at_spot()

    def _start_drawing(self):
        self.mode = "draw"

    def dismiss(self):
        """Remove every answer at once, with no animation."""
        for old in self.notes:
            self._repaint(old.bounds())
            for mark in old.marks:
                self._repaint(mark.bounds())
        self.notes = []
        self.writing = None
        self.to_draw = []
        self.mode = "follow"

    def wipe_board(self):
        """Wipe the answers away one by one, like cleaning a school board."""
        self.remove_doodle()
        self.writing = None
        self.to_draw = []
        for note in self.notes:
            note.visible = True       # in case it was wiped before it appeared
            for mark in note.marks:
                mark.progress = max(mark.progress, 0.0)
        self._wipe_next()

    def _wipe_next(self):
        if not self.notes:
            self.mode = "follow"   # the board is clean
            return
        # Fly to the left edge of the oldest note, then start scrubbing.
        self._start_glide(self.notes[0].eraser_position(), then=self._start_wiping)

    def _start_wiping(self):
        self.mode = "wipe"

    def _arrived_at_spot(self):
        """The buddy is on the spot: show the paper, rest a moment."""
        self.writing.visible = True
        self._repaint(self.writing.bounds())
        self.mode = "pause"
        self.pause_until = time.monotonic() + POINT_PAUSE_SECONDS

    def _start_writing(self):
        self.mode = "write"

    # --- Idle doodles --------------------------------------------------------

    def _start_doodle(self):
        """Pick a doodle, place it in the bottom-right corner, fly there."""
        screen = QGuiApplication.screenAt(self.last_cursor) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()   # the screen minus menu bar and Dock
        corner = QPointF(
            area.right() - DOODLE_MARGIN - DOODLE_SIZE,
            area.bottom() - DOODLE_MARGIN - DOODLE_SIZE,
        )
        self.doodle, self.doodle_name = make_doodle(corner, DOODLE_SIZE, previous=self.doodle_name)
        self.doodle_fading_since = None
        self._start_glide(self.doodle.start_position(), then=self._start_doodling)

    def _start_doodling(self):
        self.mode = "doodle"

    def _stop_doodling(self, now):
        """Go back to the cursor and let the doodle fade away."""
        self.mode = "follow"
        self.doodle_fading_since = now
        self.next_doodle_at = now + DOODLE_PAUSE_SECONDS

    def remove_doodle(self):
        """Take the doodle off the screen at once (something real is happening)."""
        if self.doodle is not None:
            self._repaint(self.doodle.bounds())
            if self.mode in ("doodle", "admire"):
                self.mode = "follow"
        self.doodle = None
        self.doodle_fading_since = None
        self.next_doodle_at = time.monotonic() + DOODLE_PAUSE_SECONDS

    def _idle_step(self, now):
        """Called on every tick: watch the mouse and run the doodle's life."""
        cursor = QCursor.pos()
        moved = (cursor - self.last_cursor).manhattanLength() > 3
        if moved:
            self.last_cursor = cursor
            self.still_since = now

        busy_doodling = self.doodle is not None and self.doodle_fading_since is None
        if busy_doodling and moved:
            self._stop_doodling(now)          # you are back: return to the cursor

        elif (
            self.mode == "follow"
            and self.doodle is None
            and not self.notes
            and not self.thinking
            and self.buddy_visible
            and now - self.still_since >= IDLE_SECONDS
            and now >= self.next_doodle_at
            and self.may_doodle()
        ):
            self._start_doodle()

        # Fade the doodle out, then forget it.
        if self.doodle is not None and self.doodle_fading_since is not None:
            self.doodle.fade = 1 - (now - self.doodle_fading_since) / DOODLE_FADE_SECONDS
            self._repaint(self.doodle.bounds())
            if self.doodle.fade <= 0:
                self.doodle = None
                self.doodle_fading_since = None

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

        self._idle_step(now)

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
                self._start_glide(self.writing.pen_position(), then=self._start_writing)

        elif self.mode == "draw":
            mark = self.drawing
            mark.progress += DRAW_SPEED * seconds_passed / mark.total_length
            self.buddy_pos = mark.pen_position()
            self._repaint(mark.bounds())
            if mark.progress >= 1:
                self._draw_next()

        elif self.mode == "write":
            note = self.writing
            note.progress += WRITE_SPEED * seconds_passed
            self.buddy_pos = note.pen_position()
            self._repaint(note.bounds())
            if note.finished():
                self.mode = "follow"   # done: the note stays, the buddy goes home
                self.writing = None
                if self.on_note_finished is not None:
                    self.on_note_finished(note)

        elif self.mode == "doodle":
            doodle = self.doodle
            doodle.progress += DOODLE_SPEED * seconds_passed / doodle.total_length
            self.buddy_pos = doodle.pen_position()
            self._repaint(doodle.bounds())
            if doodle.progress >= 1:
                self.mode = "admire"
                self.pause_until = now + ADMIRE_SECONDS

        elif self.mode == "admire":
            if now >= self.pause_until:
                self._stop_doodling(now)

        elif self.mode == "wipe":
            note = self.notes[0]
            note.wipe += seconds_passed / WIPE_SECONDS
            for mark in note.marks:
                mark.fade = max(1 - note.wipe, 0.0)   # its marks fade out with it
                self._repaint(mark.bounds())
            self.buddy_pos = note.eraser_position()
            self._repaint(note.bounds())
            if note.wipe >= 1:
                self.notes.pop(0)    # this one is gone
                self._wipe_next()    # on to the next, if any

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
