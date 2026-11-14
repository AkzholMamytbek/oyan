"""The ask box: a small text field for typing a question.

It appears in two ways:
* next to the cursor when you press the hotkey. Enter sends the question,
  Esc closes the box, and clicking anywhere outside closes it too;
* "attached" under a finished answer, waiting quietly. It does not take the
  keyboard until you click in it (or press the hotkey), and it stays there
  until the board is wiped.

The tricky part is keyboard focus. To type into the box, Oyan has to become
the "active" app for a moment. Before it does, we remember which app was in
front, and when the box closes we put that app back in front. That way you
carry on exactly where you were.
"""

import objc
from AppKit import NSApp, NSApplicationActivateIgnoringOtherApps, NSWorkspace
from PyQt6.QtCore import QEvent, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QWidget

from oyan.overlay import show_on_every_desktop

BOX_WIDTH = 400
BOX_HEIGHT = 44
OFFSET_FROM_CURSOR = QPoint(18, 34)   # below the cursor and the buddy dot

PLACEHOLDER_NEW = "Ask about your screen…   (Shift+Enter: pick an area)"   # /green and /burgundy change Oyan's colour
PLACEHOLDER_FOLLOW_UP = "Ask more…   (Shift+Enter: pick an area)"

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
    # Enter: carries the question, and whether the box was attached under an answer.
    submitted = pyqtSignal(str, bool)
    submitted_for_area = pyqtSignal(str)   # Shift+Enter: choose part of the screen first
    submitted_fresh = pyqtSignal(str)      # Option+Enter: take a new picture of the screen
    cancelled = pyqtSignal()      # the owner pressed Esc or clicked away
    escaped = pyqtSignal()        # the owner pressed Esc while typing in the box

    def __init__(self):
        super().__init__()
        self._previous_app = None
        self.attached = False     # True while the box sits under an answer

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        # Showing the window must not grab the keyboard by itself. When we do
        # want the keyboard (open_at), we ask for it explicitly.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(BOX_WIDTH, BOX_HEIGHT)

        self.input = QLineEdit()
        self.input.setPlaceholderText(PLACEHOLDER_NEW)
        self.input.setFrame(False)
        self.input.setStyleSheet(
            f"background: transparent; color: {INK.name()}; font-size: 15px;"
        )
        self.input.returnPressed.connect(self._submit)
        # Let us hear about mouse clicks on the text field (see eventFilter).
        self.input.installEventFilter(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.addWidget(self.input)

    # --- Opening and closing ----------------------------------------------

    def open_near(self, cursor_pos):
        """Show the box next to the cursor and start typing into it."""
        self.open_at(cursor_pos + OFFSET_FROM_CURSOR)

    def open_at(self, top_left):
        """Show the box with its top-left corner here and start typing into it."""
        # Remember the app that is in front right now.
        self._previous_app = app_in_front()

        self.input.clear()
        self.input.setPlaceholderText(PLACEHOLDER_FOLLOW_UP if self.attached else PLACEHOLDER_NEW)
        self.move(self._keep_on_screen(top_left))
        self.show()
        show_on_every_desktop(self, takes_keyboard=True)   # also over full-screen apps
        self._take_keyboard()

    def _take_keyboard(self):
        """Make key presses come to this box."""
        if not self.isVisible():
            return   # the box was closed in the meantime
        window = self._mac_window()
        # By default a helper panel avoids taking the keyboard; tell it not to.
        window.setBecomesKeyOnlyIfNeeded_(False)
        self.raise_()
        NSApp.activateIgnoringOtherApps_(True)   # Oyan becomes the active app
        self.activateWindow()
        window.makeKeyAndOrderFront_(None)       # ...and this its typing window
        self.input.setFocus()

    def _mac_window(self):
        """The real macOS window behind this Qt widget."""
        return objc.objc_object(c_void_p=int(self.winId())).window()

    def show_attached(self, top_left):
        """Show the box under an answer WITHOUT taking the keyboard.

        You keep working in your app. The box waits; click in it to type.
        """
        self.attached = True
        self._previous_app = None   # decided afresh when you start typing
        self.input.clear()
        self.input.setPlaceholderText(PLACEHOLDER_FOLLOW_UP)
        self.move(self._keep_on_screen(top_left))
        self.show()
        show_on_every_desktop(self, takes_keyboard=True)
        # (No raise_() here: on macOS that would pull Oyan in front of your
        # app and take the keyboard away from you.)

    def is_typing(self):
        """Is the keyboard going into this box right now?

        We ask macOS whether our window is the "key window" (the one that
        receives key presses). Qt's own isActiveWindow() is not reliable for
        a window that was shown without being activated.
        """
        if not self.isVisible():
            return False
        return bool(self._mac_window().isKeyWindow())

    def close_box(self):
        """Hide the box and give the keyboard back to the previous app."""
        # If Oyan is the active app (you were typing here), hand the keyboard
        # back to the app you came from. If you have already clicked into
        # another app yourself, leave you where you are.
        oyan_is_active = bool(NSApp.isActive())
        go_back_to = self._previous_app or app_in_front()
        self.attached = False
        self.hide()
        if oyan_is_active:
            bring_to_front(go_back_to)
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
        # Which extra keys are held down right now? We ask macOS directly
        # (queryKeyboardModifiers) instead of trusting what Qt last saw: after
        # drawing with Option + D, Qt may not have noticed the release.
        held = QGuiApplication.queryKeyboardModifiers()
        was_attached = self.attached
        self.close_box()
        if held & Qt.KeyboardModifier.ShiftModifier:
            self.submitted_for_area.emit(question)
        elif held & Qt.KeyboardModifier.AltModifier:      # Alt is the Option key
            self.submitted_fresh.emit(question)
        else:
            self.submitted.emit(question, was_attached)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close_box()
            self.escaped.emit()
        else:
            super().keyPressEvent(event)

    def _clicked(self):
        """You clicked in the box while it was only waiting: start typing."""
        if not self.is_typing():
            # Remember where you came from, so the keyboard can go back there.
            self._previous_app = app_in_front()
            # Wait until macOS has finished handling the click itself, then
            # take the keyboard; doing it in the middle of the click fails.
            QTimer.singleShot(50, self._take_keyboard)

    def mousePressEvent(self, event):
        self._clicked()
        super().mousePressEvent(event)

    def eventFilter(self, watched, event):
        # Qt calls this for events of the text field, before the field
        # handles them. Returning False means "carry on as normal".
        if watched is self.input and event.type() == QEvent.Type.MouseButtonPress:
            self._clicked()
        return False

    def changeEvent(self, event):
        # If you click on another window, a box opened at the cursor closes
        # itself. A box attached under an answer stays where it is.
        if event.type() == QEvent.Type.ActivationChange and self.isVisible():
            if not self.isActiveWindow():
                if not self.attached:
                    self.hide()
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
