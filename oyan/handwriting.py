"""The handwritten note: the answer, written beside the thing it is about.

A Note knows three things:
* where it sits on the screen (worked out once, in __init__);
* how much of the text has been "written" so far (`progress`, in letters);
* how to draw itself at that point in time (`paint`).

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

PAPER = QColor(255, 250, 235, 240)   # warm paper, very slightly see-through
INK = QColor(60, 40, 20)             # dark brown, like pencil


class Note:
    def __init__(self, text, anchor, screen_rect, has_point):
        """
        text        - the answer to write
        anchor      - the spot on screen the answer is about (QPointF)
        screen_rect - the monitor the note must stay inside (QRect)
        has_point   - False if the AI did not point at anything; then no
                      pointer line is drawn and `anchor` is just "near here"
        """
        self.anchor = QPointF(anchor)
        self.has_point = has_point
        self.visible = False    # the overlay switches this on when the buddy arrives
        self.progress = 0.0     # how many letters have been written so far

        self.font = QFont(FONT_NAME, FONT_SIZE)
        self.metrics = QFontMetricsF(self.font)
        self.line_height = self.metrics.lineSpacing()

        self.lines = self._wrap(text)
        self.total_letters = sum(len(line) for line in self.lines)

        # Size of the paper: the widest line plus padding all round.
        text_width = max(self.metrics.horizontalAdvance(line) for line in self.lines)
        width = text_width + 2 * PADDING
        height = len(self.lines) * self.line_height + 2 * PADDING
        self.box = self._place_box(width, height, screen_rect)

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

    def _place_box(self, width, height, screen_rect):
        """Put the paper to the right of the anchor, or to the left if there
        is no room, and never off the edge of the screen."""
        left_limit = screen_rect.left() + SCREEN_MARGIN
        right_limit = screen_rect.right() - SCREEN_MARGIN - width
        top_limit = screen_rect.top() + SCREEN_MARGIN
        bottom_limit = screen_rect.bottom() - SCREEN_MARGIN - height

        x = self.anchor.x() + GAP
        if x > right_limit:
            x = self.anchor.x() - GAP - width
        x = min(max(x, left_limit), right_limit)
        y = min(max(self.anchor.y() - height / 2, top_limit), bottom_limit)
        return QRectF(x, y, width, height)

    def bounds(self):
        """A rectangle containing everything the note draws (for repainting)."""
        return self.box.united(QRectF(self.anchor, self.anchor)).adjusted(-12, -12, 12, 12)

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

    def paint(self, painter):
        if not self.visible:
            return

        # A dot on the spot, and a line from it to the paper.
        if self.has_point and not self.box.contains(self.anchor):
            near_x = min(max(self.anchor.x(), self.box.left()), self.box.right())
            near_y = min(max(self.anchor.y(), self.box.top()), self.box.bottom())
            painter.setPen(QPen(INK, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(self.anchor, QPointF(near_x, near_y))
            painter.setBrush(INK)
            painter.drawEllipse(self.anchor, 4, 4)

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
