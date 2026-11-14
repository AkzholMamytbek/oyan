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
from PyQt6.QtGui import QColor, QPainterPath, QPen

MARKER = QColor(226, 68, 44)   # red-orange, like a board marker
MARKER_WIDTH = 3.2
CIRCLE_PADDING = 8             # how far outside the thing the circle is drawn
ARROW_HEAD = 14                # length of the arrow head's sides


class Mark:
    def __init__(self, strokes, color=MARKER, width=MARKER_WIDTH):
        self.strokes = [[QPointF(p) for p in stroke] for stroke in strokes]
        self.color = color
        self.width = width
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
        color = QColor(self.color)
        color.setAlphaF(color.alphaF() * self.fade)
        pen = QPen(color, self.width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)


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
