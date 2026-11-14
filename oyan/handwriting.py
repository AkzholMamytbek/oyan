"""The handwritten note: the answer, written beside the thing it is about.

A Note knows three things:
* where it sits on the screen (worked out once, in __init__);
* how much of the text has been "written" so far (`progress`, in letters);
* how to draw itself at that point in time (`paint`).

Notes stay on the screen like writing on a school board until they are wiped.
Rubbing the cursor quickly over a note erases a strip where the cursor went,
like a cloth; the strips are remembered in `erased` (the overlay does the
actual rubbing out, see overlay.py).
Wiping works like writing in reverse: `wipe` goes from 0 to 1 and everything
to the left of the "wipe front" is no longer drawn, while the buddy scrubs up
and down along that front like a board eraser.

The writing effect
------------------
We use a handwriting font that comes with macOS. To make it look written
rather than typed, each line is revealed from left to right: we tell the
painter "you may only draw inside this rectangle" (that is called clipping)
and make the rectangle a little wider on every frame. The buddy rides on the
right edge of that rectangle, wobbling slightly, like the tip of a pen.

All positions here are "global" screen points (see overlay.py).
"""

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPen

# --- Things you can tweak -------------------------------------------------

FONT_NAME = "Bradley Hand"   # others on a Mac: "Noteworthy", "Marker Felt"
FONT_SIZE = 20
MAX_TEXT_WIDTH = 320         # wrap lines longer than this, in points
PADDING = 14                 # space between the text and the paper edge
GAP = 40                     # distance between the pointed-at spot and the note
SCREEN_MARGIN = 10           # keep the note this far from the screen edges

# A small reminder shown under the note once it is written.
HINT_TEXT = "Type below to ask more    Rub fast to erase    Esc: wipe all"
HINT_SIZE = 11
HINT_HEIGHT = 24             # room kept free under the note for the reminder
SPACE_FOR_ASK_BOX = 56       # room kept free under that for the typing box
GAP_BETWEEN_NOTES = 14       # when a new note has to move out of an old one's way
WIPE_STROKES = 3             # how many times the eraser goes up and down per note

PAPER = QColor(255, 250, 235, 240)   # warm paper, very slightly see-through
INK = QColor(60, 40, 20)             # dark brown, like pencil


class Note:
    def __init__(self, text, anchor, screen_rect, has_point, avoid=(), clear_of=None):
        """
        text        - the answer to write
        anchor      - the spot on screen the answer is about (QPointF)
        screen_rect - the monitor the note must stay inside (QRect)
        has_point   - False if the AI did not point at anything; then no
                      pointer line is drawn and `anchor` is just "near here"
        avoid       - rectangles of notes already on the board; the new note
                      is moved so it does not cover them
        clear_of    - a rectangle around this answer's own circles and arrows;
                      the note is placed beside it, not on top of it
        """
        self.anchor = QPointF(anchor)
        self.has_point = has_point
        self.visible = False    # the overlay switches this on when the buddy arrives
        self.progress = 0.0     # how many letters have been written so far
        self.wipe = 0.0         # 0 = untouched, 1 = completely wiped away
        self.erased = []        # strips rubbed out with the cursor: [(from point, to point), ...]
        self.erased_length = 0.0   # how far the cursor has rubbed over this note in total
        self.show_hint = True   # only the newest note shows the reminder
        self.hint_text = HINT_TEXT
        self.marks = []         # circles, underlines and arrows drawn for this answer

        self.font = QFont(FONT_NAME, FONT_SIZE)
        self.metrics = QFontMetricsF(self.font)
        self.line_height = self.metrics.lineSpacing()

        self.lines = self._wrap(text)
        self.total_letters = sum(len(line) for line in self.lines)

        # Size of the paper: the widest line plus padding all round.
        text_width = max(self.metrics.horizontalAdvance(line) for line in self.lines)
        width = text_width + 2 * PADDING
        height = len(self.lines) * self.line_height + 2 * PADDING
        self.box = self._place_box(width, height, screen_rect, avoid, clear_of)

    # --- Layout ------------------------------------------------------------

    def _wrap(self, text):
        """Break the text into lines no wider than MAX_TEXT_WIDTH."""
        lines = []
        for paragraph in text.splitlines():
            current = ""
            for word in paragraph.split():
                longer = f"{current} {word}".strip()
                if current and self.metrics.horizontalAdvance(longer) > MAX_TEXT_WIDTH:
                    lines.append(current)   # the line is full, start a new one
                    current = word
                else:
                    current = longer
            if current:
                lines.append(current)
        return lines or ["..."]

    def _place_box(self, width, height, screen_rect, avoid, clear_of):
        """Find a place for the paper: near the spot, on the screen, and not
        on top of any other answer or drawing.

        We make a list of candidate places, nearest first, and take the first
        one that touches nothing. The first candidates are the natural ones
        (right of the spot, left, below, above); after those we simply try
        every position on a grid across the screen.
        """
        left_limit = screen_rect.left() + SCREEN_MARGIN
        right_limit = screen_rect.right() - SCREEN_MARGIN - width
        top_limit = screen_rect.top() + SCREEN_MARGIN
        bottom_limit = screen_rect.bottom() - SCREEN_MARGIN - height - HINT_HEIGHT - SPACE_FOR_ASK_BOX

        def on_screen(x, y):
            return QRectF(
                min(max(x, left_limit), right_limit),
                min(max(y, top_limit), bottom_limit),
                width, height,
            )

        # Everything the new note must keep away from.
        obstacles = [QRectF(rect) for rect in avoid]
        if clear_of is not None:
            obstacles.append(QRectF(clear_of))

        def footprint(box):
            """The paper plus the room under it for the reminder and the typing box."""
            return box.adjusted(-GAP_BETWEEN_NOTES, -GAP_BETWEEN_NOTES, GAP_BETWEEN_NOTES,
                                HINT_HEIGHT + SPACE_FOR_ASK_BOX)

        def is_free(box):
            area = footprint(box)
            return not any(area.intersects(obstacle) for obstacle in obstacles)

        ax, ay = self.anchor.x(), self.anchor.y()
        keep_clear = clear_of if clear_of is not None else QRectF(self.anchor, self.anchor)
        natural = [
            on_screen(max(ax + GAP, keep_clear.right() + 10), ay - height / 2),           # right
            on_screen(min(ax - GAP, keep_clear.left() - 10) - width, ay - height / 2),    # left
            on_screen(ax - width / 2, max(ay + GAP, keep_clear.bottom() + 10)),           # below
            on_screen(ax - width / 2, min(ay - GAP, keep_clear.top() - 10) - height),     # above
        ]
        for box in natural:
            if is_free(box):
                return box

        # No natural place is free: try a grid of positions, nearest first.
        step = 40
        grid = []
        y = top_limit
        while y <= bottom_limit:
            x = left_limit
            while x <= right_limit:
                grid.append(QRectF(x, y, width, height))
                x += step
            y += step
        grid.sort(key=lambda box: (box.center().x() - ax) ** 2 + (box.center().y() - ay) ** 2)
        for box in grid:
            if is_free(box):
                return box

        return natural[0]   # the screen is full; overlapping cannot be avoided

    def bounds(self):
        """A rectangle containing everything the note draws (for repainting)."""
        return self.box.united(QRectF(self.anchor, self.anchor)).adjusted(-12, -12, 12, 12 + HINT_HEIGHT)

    # --- Writing -----------------------------------------------------------

    def finished(self):
        return self.progress >= self.total_letters

    def _written_width(self, line, letters_before):
        """How many points of this line are written, given the progress."""
        written = min(max(self.progress - letters_before, 0), len(line))
        whole = int(written)                 # letters completely written
        part = written - whole               # how far into the next letter
        width = self.metrics.horizontalAdvance(line[:whole])
        if whole < len(line):
            width += part * self.metrics.horizontalAdvance(line[whole])
        return width

    def pen_position(self):
        """Where the tip of the pen is right now."""
        letters_before = 0
        for number, line in enumerate(self.lines):
            is_last = number == len(self.lines) - 1
            if self.progress < letters_before + len(line) or is_last:
                x = self.box.left() + PADDING + self._written_width(line, letters_before)
                y = self.box.top() + PADDING + (number + 0.5) * self.line_height
                wobble = math.sin(self.progress * 2.5) * 4   # up and down like a pen
                return QPointF(x, y + wobble)
            letters_before += len(line)

    # --- Drawing -----------------------------------------------------------

    # --- Wiping ------------------------------------------------------------

    def _wipe_front(self):
        """The x position the eraser has reached."""
        area = self.bounds()
        return area.left() + self.wipe * area.width()

    def eraser_position(self):
        """Where the eraser (the buddy) is: on the wipe front, scrubbing up and down."""
        box = self.box
        swing = math.sin(self.wipe * math.pi * 2 * WIPE_STROKES)   # -1 .. 1
        return QPointF(self._wipe_front(), box.center().y() + swing * box.height() / 2)

    def _begin(self, painter):
        """Settings shared by both drawing steps: paleness and the wipe."""
        painter.save()
        if self.wipe > 0:
            # Only draw what the eraser has not reached yet.
            area = self.bounds()
            area.setLeft(self._wipe_front())
            painter.setClipRect(area, Qt.ClipOperation.IntersectClip)

    def paint_pointer(self, painter):
        """Draw a small dot on the spot the answer is about.

        (There used to be a line from the dot to the paper as well. The
        circles and underlines already show the place, so the line is gone.)
        """
        if not self.visible or self.wipe >= 1:
            return
        if self.has_point and not self.box.contains(self.anchor):
            self._begin(painter)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(INK)
            painter.drawEllipse(self.anchor, 4, 4)
            painter.restore()

    def paint(self, painter):
        """Draw the paper, the text and the reminder."""
        if not self.visible or self.wipe >= 1:
            return
        self._begin(painter)

        # The paper.
        painter.setPen(QPen(INK, 1.5))
        painter.setBrush(PAPER)
        painter.drawRoundedRect(self.box, 10, 10)

        # The text, each line revealed only as far as it has been written.
        painter.setFont(self.font)
        painter.setPen(INK)
        letters_before = 0
        for number, line in enumerate(self.lines):
            top = self.box.top() + PADDING + number * self.line_height
            left = self.box.left() + PADDING
            written_width = self._written_width(line, letters_before)
            if written_width > 0:
                painter.save()
                painter.setClipRect(
                    QRectF(left, top, written_width, self.line_height),
                    Qt.ClipOperation.IntersectClip,
                )
                painter.drawText(QPointF(left, top + self.metrics.ascent()), line)
                painter.restore()
            letters_before += len(line)

        # Once everything is written, a small reminder of what you can do next.
        if self.finished() and self.show_hint:
            painter.setFont(QFont(".AppleSystemUIFont", HINT_SIZE))
            hint_width = painter.fontMetrics().horizontalAdvance(self.hint_text) + 16
            hint = QRectF(self.box.left(), self.box.bottom() + 5, hint_width, HINT_HEIGHT - 6)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(40, 30, 20, 190))        # dark, slightly see-through
            painter.drawRoundedRect(hint, 9, 9)
            painter.setPen(QColor(255, 250, 235))
            painter.drawText(hint, Qt.AlignmentFlag.AlignCenter, self.hint_text)

        painter.restore()
