"""The ask box: a small text field for typing a question.

It appears in two ways:
* next to the cursor when you press the hotkey. Enter sends the question,
  Esc closes the box, and clicking anywhere outside closes it too;
* "attached" under a finished answer, waiting quietly. It does not take the
  keyboard until you click in it (or press the hotkey), and it stays there
  until the board is wiped.

It looks like Spotlight: a bar of frosted glass (see glass.py) with Oyan's
triangle at the left, and it fades in when it opens.

The tricky part is keyboard focus. To type into the box, Oyan has to become
the "active" app for a moment. Before it does, we remember which app was in
front, and when the box closes we put that app back in front. That way you
carry on exactly where you were.
"""

import objc
from AppKit import NSApp, NSApplicationActivateIgnoringOtherApps, NSWorkspace
from PyQt6.QtCore import QEvent, QPoint, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QWidget

from oyan import style
from oyan.glass import Glass
from oyan.overlay import show_on_every_desktop

BOX_WIDTH = 440
BOX_HEIGHT = 48
OFFSET_FROM_CURSOR = QPoint(18, 34)   # below the cursor and the buddy
ICON_ROOM = 46                        # space at the left for Oyan's triangle
FADE_IN_MS = 160                      # how long the box takes to fade in
TEXT_SIZE = 16

PLACEHOLDER_NEW = "Ask about your screen"   # /green and /burgundy change Oyan's colour
PLACEHOLDER_FOLLOW_UP = "Ask more"
SHORTCUT_HINT = "⇧⏎  pick area"            # shown faintly at the right of the box


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

        self.accent = QColor(128, 0, 32)   # the colour of the triangle; the app sets it
        self.glass = None                  # the frosted glass behind the box, made when first shown

        self.input = QLineEdit()
        self.input.setPlaceholderText(PLACEHOLDER_NEW)
        self.input.setFrame(False)
        self.input.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)   # no blue focus ring
        self.input.setFont(style.ui_font(TEXT_SIZE))
        self.input.returnPressed.connect(self._submit)
        # Let us hear about mouse clicks on the text field (see eventFilter).
        self.input.installEventFilter(self)

        # A faint reminder of the shortcut, at the right-hand end.
        self.shortcut = QLabel(SHORTCUT_HINT)
        self.shortcut.setFont(style.ui_font(12))
        self.shortcut.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(ICON_ROOM, 0, 16, 0)
        layout.addWidget(self.input)
        layout.addWidget(self.shortcut)

        # Fading in: Qt changes the window's opacity from 0 to 1 for us.
        self.fade = QPropertyAnimation(self, b"windowOpacity")
        self.fade.setDuration(FADE_IN_MS)
        self.fade.setStartValue(0.0)
        self.fade.setEndValue(1.0)

        self._use_colours()
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._use_colours)

    # --- The look ------------------------------------------------------------

    def _use_colours(self, *_):
        """Set the text colours for light or dark mode (see style.py)."""
        def css(color):
            return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"
        self.input.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none; color: {css(style.ink())};"
            f" selection-background-color: {css(style.system_colour('blue'))}; }}"
        )
        # The placeholder ("Ask about your screen") is quieter than typed text.
        palette = self.input.palette()
        palette.setColor(palette.ColorRole.PlaceholderText, style.secondary_ink())
        self.input.setPalette(palette)
        self.shortcut.setStyleSheet(f"color: {css(style.secondary_ink())};")
        self.update()

    def set_accent(self, color):
        """Use this colour for the triangle (the same as the buddy's)."""
        self.accent = QColor(color)
        self.update()

    def _appear(self):
        """Show the box: put the glass behind it and fade in."""
        self.setWindowOpacity(0.0)
        self.show()
        if self.glass is None:
            self.glass = Glass(self, style.ASK_BOX_RADIUS)
            self.glass.place(QRectF(self.rect()))
        self.fade.stop()
        self.fade.start()

    def _add_shadow(self):
        """Let macOS draw its own window shadow round the box, the same one
        every Mac window has. (For Oyan's other windows it is switched off.)"""
        window = self._mac_window()
        window.setHasShadow_(True)
        window.invalidateShadow()   # "work the shadow out again for the current shape"

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
        self._appear()
        show_on_every_desktop(self, takes_keyboard=True)   # also over full-screen apps
        self._add_shadow()
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
        self._appear()
        show_on_every_desktop(self, takes_keyboard=True)
        self._add_shadow()
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
        # holding Control + Option, Qt may not have noticed the release.
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
        """Draw the thin edge of the box and Oyan's triangle at the left.
        (The glass behind them is drawn by macOS, see glass.py.)"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(style.hairline(), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        edge = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.drawRoundedRect(edge, style.ASK_BOX_RADIUS, style.ASK_BOX_RADIUS)

        # A dark colour such as burgundy would be hard to see on dark glass,
        # so in dark mode the triangle is drawn in a lighter shade of it.
        color = self.accent.lighter(170) if style.is_dark() else self.accent
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        middle = QPointF(ICON_ROOM / 2 + 2, self.height() / 2)
        painter.drawPolygon(QPolygonF(style.triangle_points(middle, 0.9)))
