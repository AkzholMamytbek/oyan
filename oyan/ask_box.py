"""The ask box: a small text field that appears next to the cursor.

Enter sends the question, Esc closes the box. Clicking anywhere outside the
box closes it too.

The tricky part is keyboard focus. To type into the box, Oyan has to become
the "active" app for a moment. Before it does, we remember which app was in
front, and when the box closes we put that app back in front. That way you
carry on exactly where you were.
"""

from AppKit import NSApp, NSApplicationActivateIgnoringOtherApps, NSWorkspace
from PyQt6.QtCore import QEvent, QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QWidget

from oyan.overlay import show_on_every_desktop

BOX_WIDTH = 360
BOX_HEIGHT = 44
OFFSET_FROM_CURSOR = QPoint(18, 34)   # below the cursor and the buddy dot

PAPER = QColor(255, 250, 235)         # warm paper colour
INK = QColor(60, 40, 20)              # dark brown, like pencil


def app_in_front():
    """The app the owner is working in right now.

    We ask who owns the menu bar at the top of the screen. Oyan has no menu
    bar of its own, so this is always the owner's real app, never Oyan.
    """
    return NSWorkspace.sharedWorkspace().menuBarOwningApplication()


def bring_to_front(other_app):
    """Give the keyboard back to another app."""
    if other_app is not None:
        other_app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)


class AskBox(QWidget):
    # Signals are how a Qt object tells the rest of the program something
    # happened. Other code "connects" a function to them.
    submitted = pyqtSignal(str)   # the owner pressed Enter; carries the question
    cancelled = pyqtSignal()      # the owner pressed Esc or clicked away

    def __init__(self):
        super().__init__()
        self._previous_app = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setFixedSize(BOX_WIDTH, BOX_HEIGHT)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask about your screen…")
        self.input.setFrame(False)
        self.input.setStyleSheet(
            f"background: transparent; color: {INK.name()}; font-size: 15px;"
        )
        self.input.returnPressed.connect(self._submit)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.addWidget(self.input)

    # --- Opening and closing ----------------------------------------------

    def open_near(self, cursor_pos):
        """Show the box next to the cursor and start typing into it."""
        self.open_at(cursor_pos + OFFSET_FROM_CURSOR)

    def open_at(self, top_left):
        """Show the box with its top-left corner at this position."""
        # Remember the app that is in front right now.
        self._previous_app = app_in_front()

        self.input.clear()
        self.move(self._keep_on_screen(top_left))
        self.show()
        show_on_every_desktop(self)   # also over full-screen apps
        self.raise_()

        # Become the active app so key presses come to us.
        NSApp.activateIgnoringOtherApps_(True)
        self.activateWindow()
        self.input.setFocus()

    def close_box(self):
        """Hide the box and give the keyboard back to the previous app."""
        self.hide()
        bring_to_front(self._previous_app)
        self._previous_app = None

    def _keep_on_screen(self, pos):
        """Nudge the position so the box is never off the edge of the screen."""
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()   # the screen minus menu bar and Dock
        x = min(max(pos.x(), area.left() + 8), area.right() - BOX_WIDTH - 8)
        y = min(max(pos.y(), area.top() + 8), area.bottom() - BOX_HEIGHT - 8)
        return QPoint(x, y)

    # --- Reacting to the owner ---------------------------------------------

    def _submit(self):
        question = self.input.text().strip()
        if not question:
            return   # ignore Enter on an empty box
        self.close_box()
        self.submitted.emit(question)

    def _cancel(self):
        if self.isVisible():
            self.close_box()
            self.cancelled.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
        else:
            super().keyPressEvent(event)

    def changeEvent(self, event):
        # If the owner clicks on another window, the box is no longer the
        # active window. Treat that like Esc.
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            if self.isVisible():
                self.hide()
                self._previous_app = None   # they chose where to go; don't jump back
                self.cancelled.emit()
        super().changeEvent(event)

    # --- Drawing -----------------------------------------------------------

    def paintEvent(self, event):
        """Draw the rounded paper-coloured background behind the text field."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(INK, 1.5))
        painter.setBrush(PAPER)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)
