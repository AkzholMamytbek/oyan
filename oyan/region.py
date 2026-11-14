"""Region select: drag a box so only that part of the screen is sent.

When you send a question with Shift+Enter instead of Enter, the screen dims
slightly and the cursor becomes a crosshair. Drag over the part you want
Oyan to look at and let go. Only that rectangle is captured and sent.
Esc (or a right-click, or a tiny accidental drag) cancels and sends nothing.

Unlike the overlay, this window does catch the mouse and the keyboard, but it
only exists for the few seconds you are dragging.
"""

import objc
from AppKit import NSApp
from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from oyan.overlay import show_on_every_desktop

DIM = QColor(0, 0, 0, 70)             # how dark the rest of the screen gets
BORDER = QColor(255, 153, 51)         # orange, like the buddy
SMALLEST_SIDE = 12                    # drags smaller than this count as a mistake
HELP_TEXT = "Drag over the part to send     Esc: cancel"


class RegionSelector(QWidget):
    selected = pyqtSignal(QRect)   # carries the chosen rectangle, in global screen points
    cancelled = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.drag_start = None   # where the mouse went down (inside this window)
        self.drag_now = None     # where the mouse is now

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def open_on(self, screen):
        """Cover this monitor and wait for a drag."""
        self.drag_start = self.drag_now = None
        self.setGeometry(screen.geometry())
        self.show()
        show_on_every_desktop(self, takes_keyboard=True)
        # Take the keyboard, so that Esc reaches this window.
        self.raise_()
        NSApp.activateIgnoringOtherApps_(True)
        self.activateWindow()
        objc.objc_object(c_void_p=int(self.winId())).window().makeKeyAndOrderFront_(None)
        self.setFocus()

    def _selection(self):
        """The dragged rectangle inside this window, or None."""
        if self.drag_start is None or self.drag_now is None:
            return None
        # normalized() fixes the rectangle when you drag up or to the left.
        return QRect(self.drag_start, self.drag_now).normalized()

    # --- Mouse and keyboard --------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._cancel()
        else:
            self.drag_start = self.drag_now = event.position().toPoint()
            self.update()

    def mouseMoveEvent(self, event):
        if self.drag_start is not None:
            self.drag_now = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        chosen = self._selection()
        if chosen is None:
            return
        if chosen.width() < SMALLEST_SIDE or chosen.height() < SMALLEST_SIDE:
            self._cancel()   # a click or a tiny slip, not a real selection
            return
        self.hide()
        # Turn the position inside this window into a position on the desktop.
        self.selected.emit(chosen.translated(self.geometry().topLeft()))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()

    def _cancel(self):
        self.hide()
        self.cancelled.emit()

    # --- Drawing -------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        chosen = self._selection()

        if chosen is None:
            painter.fillRect(self.rect(), DIM)
        else:
            # Dim everything except the chosen rectangle: paint four dark
            # strips around it (above, below, left, right).
            full = self.rect()
            painter.fillRect(QRect(full.left(), full.top(), full.width(), chosen.top() - full.top()), DIM)
            painter.fillRect(QRect(full.left(), chosen.bottom() + 1, full.width(), full.bottom() - chosen.bottom()), DIM)
            painter.fillRect(QRect(full.left(), chosen.top(), chosen.left() - full.left(), chosen.height()), DIM)
            painter.fillRect(QRect(chosen.right() + 1, chosen.top(), full.right() - chosen.right(), chosen.height()), DIM)
            painter.setPen(QPen(BORDER, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(chosen)

        # A line of help near the top of the screen.
        painter.setFont(QFont(".AppleSystemUIFont", 13))
        width = painter.fontMetrics().horizontalAdvance(HELP_TEXT) + 28
        pill = QRect((self.width() - width) // 2, 48, width, 30)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(40, 30, 20, 215))
        painter.drawRoundedRect(pill, 15, 15)
        painter.setPen(QColor(255, 250, 235))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, HELP_TEXT)
