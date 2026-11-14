"""Your own pen: hold Option + D and drag to draw on the screen.

Circle a piece of code, underline a word, draw an arrow at a button. When
you let go of the keys, the ask box opens next to what you drew. Your marks
are then part of the screenshot, so the AI sees exactly what you mean.

How it works
------------
Oyan's normal overlay lets every click pass through to the app underneath,
so it cannot be drawn on. While Option + D are held down, this second
see-through window is put on top instead, and it DOES catch the mouse. Let
go of the keys and it disappears again, handing the finished strokes over.

It never takes the keyboard, so the app you are working in stays active.
"""

from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from oyan.overlay import show_on_every_desktop

PEN_COLOR = QColor(30, 144, 255)   # bright blue: easy to tell apart from Oyan's red marker
PEN_WIDTH = 3.5
SMALLEST_STROKE = 6                # shorter than this (in points) is a slip, not a stroke


def stroke_path(points):
    """Turn a list of points into one connected line the painter can draw."""
    path = QPainterPath(points[0])
    for point in points[1:]:
        path.lineTo(point)
    return path


def paint_strokes(painter, strokes):
    """Draw pen strokes (lists of points). Used here and by the overlay."""
    painter.setPen(QPen(PEN_COLOR, PEN_WIDTH, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for points in strokes:
        if len(points) > 1:
            painter.drawPath(stroke_path(points))


class DrawLayer(QWidget):
    # Carries the finished strokes: a list of strokes, each a list of
    # positions (QPointF) on the desktop.
    finished = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.strokes = []     # strokes drawn so far, in positions inside this window
        self.current = None   # the stroke being drawn right now

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus   # the mouse, yes; the keyboard, no
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def begin(self, screen):
        """Option + D went down: cover this monitor and wait for strokes."""
        self.strokes = []
        self.current = None
        self.setGeometry(screen.geometry())
        self.show()
        show_on_every_desktop(self)

    def end(self):
        """The keys were released: hide, and hand over what was drawn."""
        if not self.isVisible():
            return
        if self.current is not None:
            self.strokes.append(self.current)
            self.current = None
        self.hide()
        corner = QPointF(self.geometry().topLeft())
        # Keep real strokes only, and turn window positions into desktop positions.
        real = [
            [point + corner for point in stroke]
            for stroke in self.strokes
            if len(stroke) > 1 and stroke_path(stroke).length() >= SMALLEST_STROKE
        ]
        self.strokes = []
        if real:
            self.finished.emit(real)

    # --- The mouse -----------------------------------------------------------
    # We accept any mouse button.

    def mousePressEvent(self, event):
        self.current = [event.position()]

    def mouseMoveEvent(self, event):
        if self.current is not None:
            self.current.append(event.position())
            self.update()

    def mouseReleaseEvent(self, event):
        if self.current is not None:
            self.strokes.append(self.current)
            self.current = None
            self.update()

    def contextMenuEvent(self, event):
        event.accept()   # no right-click menu here

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # An almost invisible fill: a completely see-through window would let
        # the mouse fall through to the app underneath on macOS.
        painter.fillRect(self.rect(), QColor(0, 0, 0, 2))
        everything = self.strokes + ([self.current] if self.current else [])
        paint_strokes(painter, everything)
