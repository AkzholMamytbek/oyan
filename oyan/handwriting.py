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
import re

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPen

from oyan.mathwriting import Glyphs, math_box

# --- Things you can tweak -------------------------------------------------

FONT_NAME = "Bradley Hand"   # others on a Mac: "Noteworthy", "Marker Felt"
FONT_SIZE = 20
MAX_TEXT_WIDTH = 360         # wrap lines longer than this, in points
PADDING = 14                 # space between the text and the paper edge
GAP = 40                     # distance between the pointed-at spot and the note
SCREEN_MARGIN = 10           # keep the note this far from the screen edges

# A small reminder shown under the note once it is written.
HINT_TEXT = "Type below to ask more    Scrub to erase    Esc: wipe all"
HINT_SIZE = 11
HINT_HEIGHT = 24             # room kept free under the note for the reminder
SPACE_FOR_ASK_BOX = 56       # room kept free under that for the typing box
GAP_BETWEEN_NOTES = 14       # when a new note has to move out of an old one's way
WIPE_STROKES = 3             # how many times the eraser goes up and down per note
# Choosing a place: covering a fully busy area costs COVERING_COST points,
# and every point of distance from the spot costs DISTANCE_COST. With these
# numbers, hiding a patch of ordinary text is as bad as being about 2000
# points away, so an empty area nearly always wins.
COVERING_COST = 10.0
DISTANCE_COST = 0.001

PAPER = QColor(255, 250, 235, 240)   # warm paper, very slightly see-through
INK = QColor(60, 40, 20)             # dark brown, like pencil
CODE_INK = QColor(30, 70, 150)       # blue ink for code, so it stands out from the words
CODE_SIZE = 18                       # code is written slightly smaller
ROW_GAP = 5                          # extra space between rows

# Finds the special parts of a paragraph: $maths$ and `code`. The brackets
# make re.split keep those parts in its result instead of dropping them.
SPECIAL = re.compile(r"(\$[^$]+\$|`[^`]+`)")


class Row:
    """One row of writing: boxes side by side (words, maths, code).

    Rows can have different heights: a row with a fraction in it is taller
    than a row of plain words.
    """

    def __init__(self, boxes, metrics):
        self.boxes = boxes
        self.width = sum(box.width for box in boxes)
        # Never lower than an ordinary line of text, so rows line up evenly.
        self.ascent = max([metrics.ascent()] + [box.ascent for box in boxes])
        self.descent = max([metrics.descent()] + [box.descent for box in boxes])
        self.height = self.ascent + self.descent + ROW_GAP
        self.plain = "".join(box.plain for box in boxes)

    def draw(self, painter, left, top):
        x = left
        for box in self.boxes:
            box.draw(painter, x, top + self.ascent)
            x += box.width


class Note:
    def __init__(self, text, anchor, screen_rect, has_point, avoid=(), clear_of=None, clutter=None):
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
        clutter     - knows which parts of the screen are busy (clutter.py),
                      so the note can go to an empty area; may be None
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
        # "Progress" is counted in letters. Maths and code are not made of
        # ordinary letters, so we count every LETTER_WIDTH points of writing
        # as one letter.
        self.letter_width = self.metrics.averageCharWidth()

        self.rows = self._lay_out(text)
        self.lines = [row.plain for row in self.rows]   # the same rows as plain text
        self.total_letters = sum(row.width for row in self.rows) / self.letter_width

        # Size of the paper: the widest row plus padding all round.
        text_width = max(row.width for row in self.rows)
        width = text_width + 2 * PADDING
        height = sum(row.height for row in self.rows) + 2 * PADDING
        self.box = self._place_box(width, height, screen_rect, avoid, clear_of, clutter)

    # --- Layout ------------------------------------------------------------

    def _lay_out(self, text):
        """Turn the answer into rows of boxes, ready to be drawn.

        The answer may contain three special things besides ordinary words:
          $ ... $        maths, written in LaTeX (see mathwriting.py)
          ` ... `        a few words of code inside a sentence
          ``` ... ```    a block of code on its own lines
        Ordinary text is broken into rows no wider than MAX_TEXT_WIDTH.
        Code blocks keep their own line breaks and their indentation.
        """
        rows = []
        # Splitting on ``` gives: text, code, text, code, ... (code at odd positions).
        for number, part in enumerate(text.split("```")):
            if number % 2 == 1:
                rows += self._code_rows(part)
            else:
                for paragraph in part.splitlines():
                    rows += self._text_rows(paragraph)
        return rows or [Row([Glyphs("...", FONT_SIZE)], self.metrics)]

    def _code_rows(self, code):
        """One row per line of code, exactly as written."""
        lines = code.strip("\n").splitlines()
        if lines and lines[0].strip().isalpha():
            lines = lines[1:]            # the language name after ```, e.g. "python"
        rows = []
        for line in lines:
            # Ordinary spaces at the start of a line would be dropped when
            # drawing; "non-breaking" spaces (\u00a0) are kept, so the
            # indentation survives.
            indent = len(line) - len(line.lstrip(" "))
            shown = "\u00a0" * (indent * 2) + line.strip()
            rows.append(Row([Glyphs(shown, CODE_SIZE, CODE_INK)], self.metrics))
        return rows

    def _text_rows(self, paragraph):
        """Break one paragraph into rows. Maths and inline code are never split."""
        # Cut the paragraph into pieces: maths, inline code, and ordinary text.
        boxes = []
        for piece in SPECIAL.split(paragraph):
            if not piece:
                continue
            if len(piece) > 2 and piece[0] == "$" and piece[-1] == "$":
                boxes.append(math_box(piece.strip("$"), FONT_SIZE))
            elif len(piece) > 2 and piece[0] == "`" and piece[-1] == "`":
                boxes.append(Glyphs(piece.strip("`"), CODE_SIZE, CODE_INK))
            else:
                boxes += [Glyphs(word, FONT_SIZE) for word in piece.split()]

        space = self.metrics.horizontalAdvance(" ")
        rows, current, width = [], [], 0.0
        for box in boxes:
            needed = box.width + (space if current else 0)
            if current and width + needed > MAX_TEXT_WIDTH:
                rows.append(Row(current, self.metrics))   # the row is full, start a new one
                current, width = [], 0.0
                needed = box.width
            # A space between boxes, except before punctuation: "x = 4." not "x = 4 ."
            starts_with_punctuation = isinstance(box, Glyphs) and box.text[:1] in ",.;:!?)"
            if current and not starts_with_punctuation:
                current.append(Glyphs(" ", FONT_SIZE))
            current.append(box)
            width += needed
        if current:
            rows.append(Row(current, self.metrics))
        return rows

    def _place_box(self, width, height, screen_rect, avoid, clear_of, clutter):
        """Find a place for the paper: near the spot, on the screen, and not
        on top of any other answer or drawing.

        We make a list of candidate places: the natural ones (right of the
        spot, left, below, above) and then every position on a grid across
        the screen. Places that touch another answer or drawing are thrown
        out. Of the rest we take the best one (see the end of this function).
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

        # After the natural places, every position on a grid across the screen.
        step = 40
        grid = []
        y = top_limit
        while y <= bottom_limit:
            x = left_limit
            while x <= right_limit:
                grid.append(QRectF(x, y, width, height))
                x += step
            y += step

        def distance(box):
            return math.hypot(box.center().x() - ax, box.center().y() - ay)

        if clutter is None:
            # We know nothing about what is on the screen: take the nearest
            # free place, trying the natural ones first.
            grid.sort(key=distance)
            for box in natural + grid:
                if is_free(box):
                    return box
            return natural[0]   # the screen is full; overlapping cannot be avoided

        # We know which parts of the screen are busy (see clutter.py). Give
        # every free place a score and take the lowest: covering text or
        # pictures costs a lot, being far from the spot costs a little. So
        # the answer goes to the nearest EMPTY area, not onto what you are
        # reading.
        def score(box):
            hidden = clutter.covered(footprint(box))    # 0 = empty area, about 0.2 = text
            return hidden * COVERING_COST + distance(box) * DISTANCE_COST

        free = [box for box in natural + grid if is_free(box)]
        if not free:
            return natural[0]
        return min(free, key=score)

    def bounds(self):
        """A rectangle containing everything the note draws (for repainting)."""
        return self.box.united(QRectF(self.anchor, self.anchor)).adjusted(-12, -12, 12, 12 + HINT_HEIGHT)

    # --- Writing -----------------------------------------------------------

    def finished(self):
        return self.progress >= self.total_letters

    def _written_width(self, row, letters_before):
        """How many points of this row are written, given the progress."""
        written = (self.progress - letters_before) * self.letter_width
        return min(max(written, 0.0), row.width)

    def pen_position(self):
        """Where the tip of the pen is right now."""
        letters_before = 0.0
        top = self.box.top() + PADDING
        for number, row in enumerate(self.rows):
            letters = row.width / self.letter_width
            is_last = number == len(self.rows) - 1
            if self.progress < letters_before + letters or is_last:
                x = self.box.left() + PADDING + self._written_width(row, letters_before)
                y = top + row.height / 2
                wobble = math.sin(self.progress * 2.5) * 4   # up and down like a pen
                return QPointF(x, y + wobble)
            letters_before += letters
            top += row.height

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

        # The writing, each row revealed only as far as it has been written.
        painter.setFont(self.font)
        painter.setPen(INK)
        letters_before = 0.0
        top = self.box.top() + PADDING
        left = self.box.left() + PADDING
        for row in self.rows:
            written_width = self._written_width(row, letters_before)
            if written_width > 0:
                painter.save()
                painter.setClipRect(
                    QRectF(left, top - 2, written_width, row.height + 4),
                    Qt.ClipOperation.IntersectClip,
                )
                row.draw(painter, left, top)
                painter.restore()
            letters_before += row.width / self.letter_width
            top += row.height

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
