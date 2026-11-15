"""Oyan's look, kept in one place: colours, fonts, and shared bits of drawing.

The look follows Apple's own design rules for macOS:

* MATERIAL  - cards are frosted glass (see glass.py), not a flat colour.
* LIGHT/DARK - everything follows the Mac's appearance. That is why the
               colours below are functions and not fixed values: each one is
               asked for again every time something is drawn, so the board
               changes the moment you switch the Mac to dark mode.
* COLOUR    - the colours are Apple's "system colours", the same reds and
               blues the rest of macOS uses.
* TYPE      - the interface is set in San Francisco, the Mac's own font.
               Answers stay in handwriting; that is Oyan's character.
* DEPTH     - a soft, wide shadow and a hairline edge lift a card off the
               screen, instead of a dark outline.
* MOTION    - things arrive with a small spring and leave with a fade.

Every other file takes its colours and fonts from here, so changing Oyan's
look means changing this file only.
"""

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QPainterPath, QPen

UI_FONT = ".AppleSystemUIFont"   # San Francisco, the font of macOS itself

CARD_RADIUS = 16         # how round the corners of an answer card are
ASK_BOX_RADIUS = 18      # ...and of the ask box
APPEAR_SECONDS = 0.32    # how long a card takes to arrive
LEAVE_SECONDS = 0.22     # how long a card takes to fade away

# Apple's system colours. Each has a slightly brighter twin for dark mode.
SYSTEM_COLOURS = {
    #          light mode            dark mode
    "red":    (QColor(255, 59, 48),  QColor(255, 69, 58)),
    "orange": (QColor(255, 149, 0),  QColor(255, 159, 10)),
    "green":  (QColor(52, 199, 89),  QColor(48, 209, 88)),
    "blue":   (QColor(0, 122, 255),  QColor(10, 132, 255)),
    "purple": (QColor(175, 82, 222), QColor(191, 90, 242)),
    "brown":  (QColor(162, 132, 94), QColor(172, 142, 104)),
}


def is_dark():
    """Is the Mac in dark mode right now?"""
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def system_colour(name):
    light, dark = SYSTEM_COLOURS[name]
    return QColor(dark if is_dark() else light)


def ink():
    """The colour of writing on a card: Apple's "label" colour."""
    return QColor(245, 245, 247) if is_dark() else QColor(29, 29, 31)


def secondary_ink():
    """Quieter text, for hints and placeholders."""
    return QColor(235, 235, 245, 150) if is_dark() else QColor(60, 60, 67, 150)


def code_ink():
    """Code is written in blue, so it stands out from the words."""
    return system_colour("blue")


def hairline():
    """The thin edge round a card. On dark glass it is a faint light line,
    on light glass a faint dark one."""
    return QColor(255, 255, 255, 46) if is_dark() else QColor(0, 0, 0, 30)


def ui_font(size, bold=False):
    font = QFont(UI_FONT)
    font.setPointSizeF(size)
    if bold:
        font.setWeight(QFont.Weight.DemiBold)
    return font


# --- Motion ------------------------------------------------------------------


def smooth(t):
    """Ease in and out: 0 -> 1, slow at both ends."""
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def spring(t):
    """0 -> 1, going a touch past 1 near the end and settling back, the way
    windows and menus arrive on a Mac."""
    t = min(max(t, 0.0), 1.0)
    overshoot = 1.4
    t -= 1
    return 1 + t * t * ((overshoot + 1) * t + overshoot)


# --- Shared drawing ----------------------------------------------------------


def rounded(rect, radius):
    path = QPainterPath()
    path.addRoundedRect(QRectF(rect), radius, radius)
    return path


def paint_card_frame(painter, rect, radius, opacity=1.0):
    """Draw what surrounds a glass card: its soft shadow and hairline edge.

    The glass itself is not drawn here (macOS draws it, see glass.py). The
    shadow is many faint rounded shapes, each a little bigger than the last,
    so it is darkest near the card and fades out gradually. It is only drawn
    OUTSIDE the card, so that it does not darken the glass.
    """
    if opacity <= 0:
        return
    rect = QRectF(rect)
    painter.save()
    painter.setOpacity(painter.opacity() * opacity)

    # Allow drawing everywhere except inside the card.
    outside = QPainterPath()
    outside.addRect(rect.adjusted(-60, -60, 60, 60))
    painter.setClipPath(outside.subtracted(rounded(rect, radius)), Qt.ClipOperation.IntersectClip)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 7 if is_dark() else 4))
    for layer in range(14):
        grow = 1 + layer * 1.8
        # The shadow falls slightly downwards, as if lit from above.
        shape = rect.adjusted(-grow, -grow * 0.6, grow, grow * 1.4)
        painter.drawRoundedRect(shape, radius + grow, radius + grow)
    painter.setClipping(False)
    painter.restore()

    painter.save()
    painter.setOpacity(painter.opacity() * opacity)
    painter.setPen(QPen(hairline(), 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    painter.restore()


PILL_FONT_SIZE = 11.5
PILL_HEIGHT = 22


def pill_width(text):
    return QFontMetricsF(ui_font(PILL_FONT_SIZE)).horizontalAdvance(text) + 22


def paint_pill(painter, top_left, text, opacity=1.0):
    """A small dark capsule with a line of help in it, like the ones macOS
    shows ("Press esc to exit full screen"). Dark in both appearances."""
    rect = QRectF(top_left.x(), top_left.y(), pill_width(text), PILL_HEIGHT)
    painter.save()
    painter.setOpacity(painter.opacity() * opacity)
    painter.setPen(QPen(QColor(255, 255, 255, 36), 1))
    painter.setBrush(QColor(28, 28, 30, 205))
    painter.drawRoundedRect(rect, PILL_HEIGHT / 2, PILL_HEIGHT / 2)
    painter.setFont(ui_font(PILL_FONT_SIZE))
    painter.setPen(QColor(255, 255, 255, 225))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
    painter.restore()
    return rect


def triangle_points(center, scale=1.0):
    """Oyan's triangle, shaped like the tip of a mouse arrow: its three
    corners around `center`."""
    shape = [(-8, -9), (10, -1), (-2, 10)]
    return [center + QPointF(x, y) * scale for x, y in shape]
