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
Oyan's windows are marked "leave me out of screenshots" (see
show_on_every_desktop), so nothing drawn here is ever in the picture that is
sent to the AI.

Answers stay on screen like writing on a school board (`self.notes`), up to
MAX_NOTES of them; a new one is placed where it covers nothing. Esc wipes the
whole board; rubbing the cursor quickly over one answer erases just that one.

Each answer is a card of frosted glass. The glass is a panel that macOS draws
underneath our own drawing (see glass.py); `_animate_cards` keeps every panel
in step with its note: it fades and springs in when the answer arrives, gets
holes where you rub, and fades out when the answer is removed.

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
    NSWindowSharingNone,
    NSWorkspace,
    NSWorkspaceActiveSpaceDidChangeNotification,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskNonactivatingPanel,
)
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen, QPolygonF, QRegion
from PyQt6.QtWidgets import QWidget

from oyan import style
from oyan.doodles import make_doodle
from oyan.glass import Glass
from oyan.handwriting import Note

# --- Things you can tweak -------------------------------------------------

BUDDY_RADIUS = 10           # roughly half the buddy's size, in points (used for repainting)
OFFSET_FROM_CURSOR = (20, 22)  # sit below-right of the arrow, not under it
FOLLOW_SPEED = 0.18         # 0..1, how much of the gap is closed per tick
BOB_HEIGHT = 2.0            # how far it floats up and down, in points
BOB_SPEED = 3.0             # how fast it floats
TICK_MS = 16                # 16 ms per tick is about 60 frames per second

GLIDE_SPEED = 2200          # points per second when flying to a spot
GLIDE_MIN_SECONDS = 0.22    # ...but never quicker than this
GLIDE_MAX_SECONDS = 0.55    # ...or slower than this
GLIDE_CURVE = 0.25          # how much the path bends (0 = straight line)
POINT_PAUSE_SECONDS = 0.10  # how long it rests on the spot before writing
WRITE_SPEED = 170           # letters per second
WIPE_SECONDS = 0.55         # how long the eraser takes to wipe one answer
DRAW_SPEED = 1300           # points of marker line drawn per second

MAX_NOTES = 3               # answers kept on the board; a 4th removes the oldest
RUB_SPEED = 1100            # the cursor must move this fast (points/second) to count as rubbing
RUB_TURNS = 3               # ...and change direction this many times, back and forth,
RUB_TURN_SECONDS = 0.9      # within this long, before anything is erased
ERASER_WIDTH = 30           # width of the strip the cursor rubs out, in points
ERASED_ENOUGH = 0.85        # once this share of an answer is rubbed out, the rest goes too

IDLE_SECONDS = 30           # mouse still for this long -> draw a doodle
DOODLE_PAUSE_SECONDS = 45   # wait at least this long between doodles
DOODLE_SIZE = 84            # how big a doodle is, in points
DOODLE_MARGIN = 36          # distance from the corner of the screen
DOODLE_SPEED = 380          # points of line drawn per second (unhurried)
DOODLE_CANCEL_DISTANCE = 45 # the mouse must move this far to interrupt a doodle
ADMIRE_SECONDS = 8          # how long a finished doodle stays
DOODLE_FADE_SECONDS = 0.8   # how long it takes to fade away

# Oyan's two colours. Switch by typing /green or /burgundy in the ask box.
BUDDY_COLORS = {
    "burgundy": QColor(128, 0, 32),
    "green": QColor(19, 128, 52),       # royal green
}
DEFAULT_COLOR = "burgundy"
# The shadow under the triangle: (how far it is shifted, how dark), outermost first.
SHADOW_LAYERS = [(4.0, 22), (3.0, 34), (2.0, 46), (1.0, 58)]


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
    # Leave this window out of screenshots. Oyan's answers and its triangle
    # are then never in the picture that is sent, without having to hide
    # them (hiding made the board flicker every time you asked something).
    window.setSharingType_(NSWindowSharingNone)
    # macOS adds a shadow round whatever a window shows. On a see-through
    # window that turns into a faint outline round every card, so we switch
    # it off and draw our own soft shadows (see style.py).
    window.setHasShadow_(False)


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

        # Your own pen strokes. These stay visible even while a screenshot is
        # taken: they are meant to be in the picture.
        if controller.user_strokes:
            from oyan.sketch import paint_strokes   # imported here: sketch.py itself imports this file
            paint_strokes(painter, controller.user_strokes)

        if controller.notes_visible and controller.doodle is not None:
            controller.doodle.paint(painter)

        if controller.notes_visible:
            # Two layers: first the circles and arrows, then the papers with
            # their text on top.
            # (`leaving` holds answers that are fading away.)
            on_board = controller.leaving + controller.notes
            for note in on_board:
                for mark in note.marks:
                    mark.paint(painter)
            for note in on_board:
                note.paint(painter)

            # Rub out the strips the cursor has erased. "Clear" is a special
            # way of painting that removes what is there instead of adding
            # colour, leaving the screen behind showing through again. It is
            # limited to the note and its drawings, so nothing else is touched.
            for note in controller.notes:
                if not note.erased:
                    continue
                painter.save()
                allowed = QRegion(note.paint_bounds().toAlignedRect())
                for mark in note.marks:
                    allowed += QRegion(mark.bounds().toAlignedRect())
                painter.setClipRegion(allowed, Qt.ClipOperation.IntersectClip)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                painter.setPen(QPen(Qt.GlobalColor.black, ERASER_WIDTH, Qt.PenStyle.SolidLine,
                                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                for start, end in note.erased:
                    painter.drawLine(start, end)
                painter.restore()

        if not controller.buddy_visible:
            return   # hidden while a screenshot is being taken

        # Oyan is a small triangle, shaped like the tip of a mouse arrow
        # (its corners are in style.py). It is red while the microphone is on.
        triangle = QPolygonF(style.triangle_points(controller.buddy_pos, controller.pulse()))
        color = style.system_colour("red") if controller.listening else BUDDY_COLORS[controller.color_name]
        painter.setPen(Qt.PenStyle.NoPen)
        # A soft shadow instead of an outline: the same triangle drawn a few
        # times, see-through, each a little further down and to the right.
        for offset, darkness in SHADOW_LAYERS:
            painter.setBrush(QColor(0, 0, 0, darkness))
            painter.drawPolygon(triangle.translated(offset, offset * 1.3))
        painter.setBrush(color)
        painter.drawPolygon(triangle)


class OverlayController:
    """Owns the overlay windows and moves the buddy on every timer tick."""

    def __init__(self, app):
        self.app = app
        self.overlays = []
        self.buddy_pos = QPointF(QCursor.pos())  # start at the cursor
        self.buddy_visible = True
        self.thinking = False   # True while waiting for the AI: the buddy pulses
        self.listening = False  # True while the microphone is on: the buddy is red
        self.color_name = DEFAULT_COLOR   # which of BUDDY_COLORS the buddy wears
        self.start_time = time.monotonic()
        self.last_tick = self.start_time

        self.mode = "follow"
        self.notes = []           # every answer on the board, oldest first
        self.leaving = []         # answers that were removed and are still fading away
        self.notes_visible = True # False for a moment while a screenshot is taken
        self.writing = None       # the note being written right now, if any
        self.to_draw = []         # marks still waiting to be drawn
        self.drawing = None       # the mark being drawn right now, if any
        self.user_strokes = []    # what YOU drew while holding Control + Option (see sketch.py)
        self.on_note_finished = None   # a function to call when writing ends
        self.on_note_removed = None    # a function to call when an answer leaves the board
        self.rub_cursor = QPointF(QCursor.pos())   # where the cursor was on the last tick
        self.rub_direction = None    # which way the cursor was last moving fast
        self.rub_turns = []          # when it recently turned round (times)
        self.glide = None         # details of the current flight (see _start_glide)
        self.pause_until = 0.0

        # Idle doodles.
        self.doodle = None                 # the sketch on screen, if any
        self.doodle_name = None            # which one it was, to avoid repeats
        self.doodle_fading_since = None    # when it started to fade away
        self.last_cursor = QCursor.pos()
        self.doodle_cursor = QCursor.pos()
        self.still_since = self.start_time # when the mouse last stopped moving
        self.next_doodle_at = self.start_time
        self.may_doodle = lambda: True     # the app can say "not now" (see app.py)

        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)

        # If a monitor is plugged in or removed, rebuild the windows.
        app.screenAdded.connect(self.rebuild_overlays)
        app.screenRemoved.connect(self.rebuild_overlays)
        # If the Mac switches between light and dark mode, redraw everything
        # in the new colours.
        app.styleHints().colorSchemeChanged.connect(self._redraw_everything)

    def start(self):
        self.rebuild_overlays()
        self.timer.start(TICK_MS)

        # While macOS slides from one desktop to another (about a second) it
        # hides every app's windows, Oyan's included; no window setting
        # changes that. What we can do is come back the instant the slide
        # ends: macOS tells us "the desktop changed", and we put our windows
        # in front and redraw them completely, straight away.
        self._space_observer = NSWorkspace.sharedWorkspace().notificationCenter().addObserverForName_object_queue_usingBlock_(
            NSWorkspaceActiveSpaceDidChangeNotification, None, None, self._on_desktop_changed
        )

    def _on_desktop_changed(self, notification):
        for overlay in self.overlays:
            window = objc.objc_object(c_void_p=int(overlay.winId())).window()
            window.orderFrontRegardless()
            overlay.repaint()

    def _redraw_everything(self, *_):
        for overlay in self.overlays:
            overlay.update()

    def rebuild_overlays(self, *_):
        """Create one overlay window per monitor (throwing away old ones)."""
        for note in self.leaving + self.notes:
            self._drop_glass(note)   # the glass lived in the old window; it is made again
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
        if not (self.thinking or self.listening):
            return 1.0
        seconds = time.monotonic() - self.start_time
        return 1.0 + 0.3 * math.sin(seconds * 8)

    # --- Showing and removing an answer -------------------------------------

    def show_answer(self, text, spot, marks=(), hint=None, clutter=None):
        """Fly to `spot`, write `text` beside it, then draw the `marks`.

        The words come first because they are what you are waiting for; the
        circles and arrows follow while you are already reading.

        `spot` is a global screen position (QPointF), or None if the AI did
        not point at anything; then the note is written near the buddy.
        `marks` is a list of Mark objects (see marks.py); it may be empty.
        `hint` replaces the small reminder shown under the note, if given.
        `clutter` knows which parts of the screen are busy (see clutter.py);
        with it, the note is put in an empty area.
        Returns the new note.
        """
        self.remove_doodle()
        # Older answers stay on the board, but only MAX_NOTES - 1 of them:
        # the oldest makes way. They also lose the reminder line, and any
        # half-finished wipe or drawing on them is completed at once.
        while len(self.notes) >= MAX_NOTES:
            self.remove_note(self.notes[0])
        for old in self.notes:
            old.wipe = 0.0
            old.show_hint = False
            self._repaint(old.paint_bounds())
            for mark in old.marks:
                mark.progress = 1.0
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
            avoid=[old.bounds() for old in self.notes]
            + [mark.bounds() for old in self.notes for mark in old.marks],
            clear_of=marks_area,
            clutter=clutter,
        )
        self.notes.append(new_note)
        new_note.marks = list(marks)   # they belong to this answer and are wiped with it
        if hint is not None:
            new_note.hint_text = hint
        self.writing = new_note
        self.spot = spot

        self.to_draw = list(marks)
        self.drawing = None
        if spot is not None:
            self._start_glide(spot, then=self._arrived_at_spot)
        else:
            self._arrived_at_spot()
        return new_note

    def set_user_strokes(self, strokes):
        """Show (or, with an empty list, remove) the owner's own pen strokes."""
        self.user_strokes = strokes
        for overlay in self.overlays:
            overlay.update()

    def remove_note(self, note):
        """Take one answer (and its marks) off the board. It no longer counts
        as being there, but it takes a moment to fade away."""
        if note in self.notes:
            self.notes.remove(note)
            note.show_hint = False
            note.leaving_since = time.monotonic()
            self.leaving.append(note)
            if self.on_note_removed is not None:
                self.on_note_removed(note)

    # --- The glass cards -----------------------------------------------------

    def _overlay_at(self, point):
        """The overlay window that covers this spot of the desktop."""
        for overlay in self.overlays:
            if overlay.geometry().contains(point.toPoint()):
                return overlay
        return self.overlays[0]

    def _drop_glass(self, note):
        if note.glass is not None:
            note.glass.remove()
            note.glass = None

    def _animate_cards(self, now):
        """Called on every tick: move each card's arriving and leaving
        animation on a step, and keep its glass panel in step with it."""
        for note in self.leaving + self.notes:
            if not note.visible:
                continue   # the buddy has not reached it yet
            moving = note.appear < 1 or note.leaving_since is not None
            note.appear = min((now - note.shown_at) / style.APPEAR_SECONDS, 1.0)
            if note.leaving_since is not None:
                note.leave = min((now - note.leaving_since) / style.LEAVE_SECONDS, 1.0)
                for mark in note.marks:      # its circles and arrows fade with it
                    mark.fade = min(mark.fade, 1 - note.leave)
                    self._repaint(mark.bounds())
            if moving:
                self._repaint(note.paint_bounds())

            # The glass: same place, same fade, same rubbed-out strips.
            if note.glass is None:
                note.glass_window = self._overlay_at(note.box.center())
                note.glass = Glass(note.glass_window, style.CARD_RADIUS)
            corner = QPointF(note.glass_window.geometry().topLeft())
            note.glass.place(
                note.card_rect().translated(-corner),
                note.card_opacity() if self.notes_visible else 0.0,
                holes=[(start - corner, end - corner) for start, end in note.erased],
                hole_width=ERASER_WIDTH,
            )

        # Forget the answers that have faded away completely.
        for note in [note for note in self.leaving if note.leave >= 1]:
            self._drop_glass(note)
            self.leaving.remove(note)

    def _rub_step(self, seconds_passed):
        """Erase with the cursor, like a cloth on a board.

        Erasing must be on purpose. Simply moving the mouse across an
        answer, even quickly, does nothing. Only SCRUBBING counts: fast
        movement that turns round and comes back several times in a row, the
        way you rub with a cloth. Once you are scrubbing, the path the cursor
        takes over an answer (or its drawings) is added to that answer's
        `erased` list, and the overlay rubs a strip out along it. When most
        of an answer is gone, the rest is removed as well.
        """
        now = time.monotonic()
        cursor = QPointF(QCursor.pos())
        previous = self.rub_cursor
        self.rub_cursor = cursor
        moved = cursor - previous
        distance = math.hypot(moved.x(), moved.y())
        speed = distance / seconds_passed if seconds_passed > 0 else 0
        if speed < RUB_SPEED:
            return

        # Has the cursor turned round? Compare this movement's direction with
        # the last fast one: if they point in roughly opposite ways, the
        # "dot product" of the two directions is negative.
        direction = moved / distance
        if self.rub_direction is not None:
            same_way = direction.x() * self.rub_direction.x() + direction.y() * self.rub_direction.y()
            if same_way < -0.3:
                self.rub_turns.append(now)
        self.rub_direction = direction
        self.rub_turns = [moment for moment in self.rub_turns if now - moment <= RUB_TURN_SECONDS]
        if len(self.rub_turns) < RUB_TURNS:
            return   # not scrubbing (yet): a single fast sweep erases nothing

        for note in list(self.notes):
            if note is self.writing or not note.visible:
                continue
            areas = [note.box.adjusted(-10, -10, 10, 10)] + [mark.bounds() for mark in note.marks]
            if not any(area.contains(cursor) or area.contains(previous) for area in areas):
                continue
            note.erased.append((previous, cursor))
            if note.box.adjusted(-10, -10, 10, 10).contains(cursor):
                note.erased_length += distance
            # Repaint the strip that was just rubbed out.
            pad = ERASER_WIDTH
            self._repaint(QRectF(previous, cursor).normalized().adjusted(-pad, -pad, pad, pad))

            # Rough share of the paper that has been rubbed: strip area / paper area.
            paper_area = note.box.width() * note.box.height()
            if note.erased_length * ERASER_WIDTH >= ERASED_ENOUGH * paper_area:
                self.remove_note(note)

    def _draw_next(self):
        """Draw the next waiting mark; when none are left, go back to the cursor."""
        if self.to_draw:
            self.drawing = self.to_draw.pop(0)
            self._start_glide(self.drawing.start_position(), then=self._start_drawing)
        else:
            self.drawing = None
            self.mode = "follow"

    def _start_drawing(self):
        self.mode = "draw"

    def dismiss(self):
        """Remove every answer at once, with no animation."""
        for old in self.leaving + self.notes:
            self._drop_glass(old)
            self._repaint(old.paint_bounds())
            for mark in old.marks:
                self._repaint(mark.bounds())
        self.notes = []
        self.leaving = []
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
        """The buddy is on the spot: the card starts to arrive; rest a moment."""
        self.writing.visible = True
        self.writing.appear = 0.0
        self.writing.shown_at = time.monotonic()
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
        self.doodle_cursor = QCursor.pos()   # where the mouse was when we began
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

        # A doodle is only interrupted when the mouse really moves away. A
        # small wobble (a hand resting on the mouse) must not stop it half-drawn.
        busy_doodling = self.doodle is not None and self.doodle_fading_since is None
        moved_away = (cursor - self.doodle_cursor).manhattanLength() > DOODLE_CANCEL_DISTANCE
        if busy_doodling and moved_away:
            self._stop_doodling(now)          # you are back: return to the cursor

        elif (
            self.mode == "follow"
            and self.doodle is None
            and not self.notes
            and not self.thinking
            and not self.listening
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
        self._animate_cards(now)
        if self.notes and self.notes_visible and self.mode != "wipe":
            self._rub_step(seconds_passed)
        else:
            self.rub_cursor = QPointF(QCursor.pos())

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
            self._repaint(note.paint_bounds())
            if note.finished():
                self.writing = None
                if self.on_note_finished is not None:
                    self.on_note_finished(note)
                self._draw_next()   # now the circles and arrows, then home

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
            self._repaint(note.paint_bounds())
            if note.wipe >= 1:
                self._drop_glass(note)
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
