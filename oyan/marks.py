"""Hand-drawn marks: circles, underlines and arrows (and idle doodles).

Every mark is made of "strokes". A stroke is one line drawn without lifting
the pen: simply a list of points. A circle is one stroke, an arrow is three
(the shaft and the two sides of its head).

To draw a mark live, `progress` goes from 0 to 1. At 0.5, half of the total
ink length is on screen and the buddy sits at the end of it, like a pen tip.

Why it looks hand-drawn
-----------------------
A perfect circle looks computer-made. So the shapes are slightly wrong on
purpose: the circle is a bit wobbly and overshoots where it started, lines
sag a little. This also hides small pointing errors, because a loose circle
around something still reads as "this thing" even when it is a few pixels off.

All positions here are "global" screen points (see overlay.py).
"""

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainterPath, QPen

MARKER = QColor(226, 68, 44)   # red-orange, like a board marker
MARKER_WIDTH = 3.2
CIRCLE_PADDING = 8             # how far outside the thing the circle is drawn
ARROW_HEAD = 14                # length of the arrow head's sides
SMOOTH_FROM_POINTS = 7         # pen strokes with at least this many points are rounded
LABEL_FONT = "Bradley Hand"    # the same handwriting as the answers
LABEL_SIZE = 17
LABEL_MAX_LETTERS = 30


class Mark:
    def __init__(self, strokes, color=MARKER, width=MARKER_WIDTH, outline=None):
        self.strokes = [[QPointF(p) for p in stroke] for stroke in strokes]
        self.color = color
        self.width = width
        self.outline = outline   # an optional darker colour drawn underneath
        self.progress = 0.0   # 0 = nothing drawn yet, 1 = finished
        self.fade = 1.0       # 1 = solid; goes down to 0 when being wiped

        # Measure every little segment once, so we can find "the point at 37%
        # of the ink" quickly later.
        self.total_length = 0.0
        for stroke in self.strokes:
            for a, b in zip(stroke, stroke[1:]):
                self.total_length += math.hypot(b.x() - a.x(), b.y() - a.y())
        self.total_length = max(self.total_length, 1.0)

    def bounds(self):
        """A rectangle containing the whole mark (for repainting)."""
        xs = [p.x() for stroke in self.strokes for p in stroke]
        ys = [p.y() for stroke in self.strokes for p in stroke]
        return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)).adjusted(-14, -14, 14, 14)

    def start_position(self):
        return self.strokes[0][0]

    def _walk(self):
        """Go along the strokes until `progress` of the ink is used up.

        Returns the path drawn so far and the position of the pen tip.
        """
        ink_left = min(max(self.progress, 0.0), 1.0) * self.total_length
        path = QPainterPath()
        tip = self.strokes[0][0]
        for stroke in self.strokes:
            if ink_left <= 0:
                break
            path.moveTo(stroke[0])          # lift the pen and put it down here
            tip = stroke[0]
            for a, b in zip(stroke, stroke[1:]):
                length = math.hypot(b.x() - a.x(), b.y() - a.y())
                if length <= ink_left:
                    path.lineTo(b)          # the whole segment fits
                    tip = b
                    ink_left -= length
                else:
                    part = ink_left / length if length else 0   # only part of it fits
                    tip = a + (b - a) * part
                    path.lineTo(tip)
                    ink_left = 0
                    break
        return path, tip

    def pen_position(self):
        return self._walk()[1]

    def paint(self, painter):
        if self.progress <= 0 or self.fade <= 0:
            return
        path, _ = self._walk()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Draw the outline first (if any), slightly thicker, then the line on
        # top of it. The outline keeps a light line visible on a light
        # background.
        for base_color, width in ((self.outline, self.width + 2.4), (self.color, self.width)):
            if base_color is None:
                continue
            color = QColor(base_color)
            color.setAlphaF(color.alphaF() * max(self.fade, 0.0))
            painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawPath(path)


class Label:
    """A few handwritten words, part of a sketch (for example "v = 20 m/s").

    It behaves like a Mark (it has `progress`, `fade`, `paint` and so on), so
    the overlay can draw it live in exactly the same way: here `progress`
    reveals the words from left to right.
    """

    def __init__(self, position, text):
        self.position = QPointF(position)   # where the first letter starts (its top-left)
        self.text = text[:LABEL_MAX_LETTERS]
        self.font = QFont(LABEL_FONT, LABEL_SIZE)
        metrics = QFontMetricsF(self.font)
        self.width = metrics.horizontalAdvance(self.text)
        self.height = metrics.height()
        self.ascent = metrics.ascent()
        self.progress = 0.0
        self.fade = 1.0
        # "Length of ink", so that writing a label takes about as long as
        # drawing a line of twice its width.
        self.total_length = max(self.width * 2, 1.0)

    def bounds(self):
        return QRectF(self.position.x(), self.position.y(), self.width, self.height).adjusted(-10, -10, 10, 10)

    def start_position(self):
        return self.position + QPointF(0, self.height / 2)

    def pen_position(self):
        shown = min(max(self.progress, 0.0), 1.0)
        return self.position + QPointF(self.width * shown, self.height / 2)

    def paint(self, painter):
        if self.progress <= 0 or self.fade <= 0:
            return
        shown = min(self.progress, 1.0)
        color = QColor(MARKER)
        color.setAlphaF(max(self.fade, 0.0))
        painter.save()
        painter.setClipRect(
            QRectF(self.position.x() - 2, self.position.y() - 4, self.width * shown + 4, self.height + 8),
            Qt.ClipOperation.IntersectClip,
        )
        painter.setFont(self.font)
        painter.setPen(color)
        painter.drawText(self.position + QPointF(0, self.ascent), self.text)
        painter.restore()


def label(position, text):
    return Label(position, text)


# --- Recipes for each kind of mark ------------------------------------------
# Each takes a rectangle or two points (in global screen points) and returns
# a Mark. `QRectF.normalized()` makes sure left < right and top < bottom even
# if the corners were given in the other order.


def circle(rect):
    """A loose loop around `rect`."""
    rect = QRectF(rect).normalized()
    center = rect.center()
    radius_x = rect.width() / 2 + CIRCLE_PADDING
    radius_y = rect.height() / 2 + CIRCLE_PADDING

    points = []
    steps = 48
    start_angle = -2.4                       # begin at the upper left, as a hand would
    sweep = 2 * math.pi + 0.45               # go a bit past the start: the overshoot
    for i in range(steps + 1):
        t = i / steps
        angle = start_angle + sweep * t
        # Wobble: the radius grows slightly as we go round, with a gentle wave.
        wobble = 1 + 0.06 * t + 0.025 * math.sin(angle * 3)
        points.append(QPointF(
            center.x() + radius_x * wobble * math.cos(angle),
            center.y() + radius_y * wobble * math.sin(angle),
        ))
    return Mark([points])


def underline(rect):
    """A slightly sagging line under `rect`."""
    rect = QRectF(rect).normalized()
    y = rect.bottom() + 4
    points = []
    steps = 16
    for i in range(steps + 1):
        t = i / steps
        x = rect.left() - 3 + (rect.width() + 6) * t
        sag = 2.0 * math.sin(t * math.pi) + 0.8 * math.sin(t * 9)   # dips in the middle
        points.append(QPointF(x, y + sag))
    return Mark([points])


def freehand(points):
    """A pen stroke through the given points, with the corners rounded off.

    The rounding is "Chaikin's corner cutting": replace every corner by two
    points a quarter of the way along the lines on either side of it. Doing
    that twice turns a jagged line into a smooth, hand-like curve.
    """
    points = [QPointF(p) for p in points]
    closed = len(points) > 3 and (points[0] - points[-1]).manhattanLength() < 4
    # A stroke with only a few points is meant to have sharp corners (the
    # walls of a house, say), so only strokes with many points are rounded.
    rounds = 2 if len(points) >= SMOOTH_FROM_POINTS else 0
    for _ in range(rounds):
        smoother = [points[0]]
        for a, b in zip(points, points[1:]):
            smoother.append(a * 0.75 + b * 0.25)
            smoother.append(a * 0.25 + b * 0.75)
        smoother.append(points[-1])
        points = smoother
    if closed:
        points.append(QPointF(points[0]))   # make sure a closed shape really closes
    return Mark([points])


def arrow(start, end):
    """A gently curved arrow from `start` to `end`."""
    start, end = QPointF(start), QPointF(end)
    dx, dy = end.x() - start.x(), end.y() - start.y()
    length = max(math.hypot(dx, dy), 1.0)
    # (-dy, dx) points sideways from the line; use it to bend the shaft a bit.
    side = QPointF(-dy / length, dx / length)

    shaft = []
    steps = 14
    for i in range(steps + 1):
        t = i / steps
        bend = math.sin(t * math.pi) * length * 0.06
        shaft.append(start + (end - start) * t + side * bend)

    # The head: two short strokes going back from the tip, 28 degrees apart
    # from the direction the shaft arrives in.
    last, tip = shaft[-2], shaft[-1]
    direction = math.atan2(tip.y() - last.y(), tip.x() - last.x())
    head = []
    for turn in (math.radians(152), math.radians(-152)):
        angle = direction + turn
        head.append([tip, tip + QPointF(math.cos(angle), math.sin(angle)) * ARROW_HEAD])
    return Mark([shaft] + head)
