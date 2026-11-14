"""The conductor: connects the parts of Oyan to each other.

Each part lives in its own file and knows nothing about the others:
* overlay.py  - the see-through window and the buddy dot
* handwriting.py - the written answer
* marks.py    - circles, underlines and arrows
* doodles.py  - the idle sketches
* region.py   - dragging a box to send only part of the screen
* hotkey.py   - the global key combination
* ask_box.py  - the small text box
* capture.py  - the screenshot
* ai.py       - sending the question and screenshot to the AI model

This file decides what happens when: hotkey pressed -> open the box,
question entered -> take a screenshot -> ask the AI model -> show the answer.
"""

from PyQt6.QtCore import QPoint, QRectF, QTimer
from PyQt6.QtGui import QCursor, QGuiApplication

from oyan import capture, hotkey, marks
from oyan.ai import AskAI
from oyan.ask_box import BOX_HEIGHT, AskBox, app_in_front, bring_to_front
from oyan.overlay import OverlayController
from oyan.region import RegionSelector


NEXT_QUESTION_GAP = 30   # space between an answer and the box for the next question


class Oyan:
    def __init__(self, app):
        self.overlay = OverlayController(app)

        self.overlay.on_note_finished = self.show_box_under
        # No idle doodles while you are typing a question or waiting for an answer.
        self.overlay.may_doodle = lambda: not self.ask_box.isVisible() and not self.ai.is_busy()

        self.ask_box = AskBox()
        self.ask_box.submitted.connect(self.on_question)
        self.ask_box.submitted_for_area.connect(self.on_question_for_area)

        self.region = RegionSelector()
        self.region.selected.connect(self.on_area_selected)
        self.region.cancelled.connect(self.on_area_cancelled)
        self.area = None         # the rectangle chosen with Shift+Enter, if any
        self.ask_box.escaped.connect(self.on_escape)

        self.hotkey = hotkey.GlobalHotkey(self.on_hotkey, self.on_escape)

        self.ai = AskAI()
        self.ai.answered.connect(self.on_answer)
        self.ai.failed.connect(self.on_ai_failed)

        self.question = None     # the question being worked on right now
        self.screenshot = None   # the latest screenshot

    def start(self):
        self.overlay.start()
        self.hotkey.start()

        # Starting a program makes macOS put it in front. Oyan should stay in
        # the background, so hand the keyboard back a moment later (once
        # macOS has finished bringing Oyan forward).
        QTimer.singleShot(300, lambda: bring_to_front(app_in_front()))

        if hotkey.has_permission(ask=True):
            print(f"Oyan is running. Press {hotkey.HOTKEY_NAME} to ask a question.")
        else:
            print(
                "Oyan needs Accessibility permission for the hotkey to work.\n"
                "  1. Open System Settings > Privacy & Security > Accessibility.\n"
                "  2. Switch on the app you started Oyan from (Terminal or Visual Studio Code).\n"
                "  3. Quit Oyan with Ctrl+C and start it again."
            )
        print("Press Ctrl+C here to quit.")

    def _place_under(self, note):
        """Where the typing box goes for this answer: under it, or above it
        if there is no room below."""
        screen = QGuiApplication.screenAt(note.box.center().toPoint()) or QGuiApplication.primaryScreen()
        x = round(note.box.left())
        y = round(note.box.bottom()) + NEXT_QUESTION_GAP
        if y + BOX_HEIGHT > screen.availableGeometry().bottom():
            y = round(note.box.top()) - NEXT_QUESTION_GAP - BOX_HEIGHT
        return QPoint(x, y)

    def show_box_under(self, note):
        """An answer has just been written: put a waiting typing box under it.
        It does not take the keyboard until you click in it."""
        if not self.ask_box.is_typing():   # do not disturb if you are typing
            self.ask_box.show_attached(self._place_under(note))

    def on_hotkey(self):
        """The hotkey starts typing; pressing it again while typing closes the box."""
        if self.ask_box.is_typing():
            self.ask_box.close_box()
            return

        note = self.overlay.note
        if note is not None and note.visible:
            # An answer is on screen: type right under it.
            self.ask_box.attached = True
            self.ask_box.open_at(self._place_under(note))
        else:
            self.ask_box.open_near(QCursor.pos())

    def on_escape(self):
        """Esc: stop waiting for the AI and wipe the board clean."""
        if self.ai.is_busy():
            self.ai.cancel()
            self.overlay.thinking = False
        if self.ask_box.isVisible():
            self.ask_box.close_box()
        self.overlay.wipe_board()

    def _ready_to_capture(self):
        """Check the Screen Recording permission; explain if it is missing."""
        if capture.has_permission():
            return True
        capture.request_permission()
        print(
            "Oyan needs Screen Recording permission to see your screen.\n"
            "  1. Open System Settings > Privacy & Security > Screen & System Audio Recording.\n"
            "  2. Switch on the app you started Oyan from (Terminal or Visual Studio Code).\n"
            "  3. Quit Oyan with Ctrl+C and start it again."
        )
        return False

    # Privacy rule: a capture starts ONLY in the two functions below, and both
    # run only because the owner pressed Enter in the ask box.

    def on_question(self, question):
        """Enter: send the whole screen the cursor is on."""
        if not self._ready_to_capture():
            return
        self.ai.cancel()   # forget an earlier question that is still waiting
        self.overlay.thinking = False
        self.question = question
        self.area = None

        # Hide the buddy and the answers on the board so they are not in the
        # picture, and wait a moment so the ask box has really gone and your
        # app is back in front.
        self.overlay.set_board_visible(False)
        QTimer.singleShot(250, self.take_screenshot)

    def on_question_for_area(self, question):
        """Shift+Enter: let the owner drag a box first; only that part is sent."""
        if not self._ready_to_capture():
            return
        self.ai.cancel()
        self.overlay.thinking = False
        self.question = question
        self.overlay.set_board_visible(False)
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self.region.open_on(screen)

    def on_area_selected(self, rect):
        self.area = rect
        bring_to_front(app_in_front())   # give the keyboard back to your app
        # Wait for the dimming to disappear before taking the picture.
        QTimer.singleShot(250, self.take_screenshot)

    def on_area_cancelled(self):
        """Esc while choosing an area: nothing is captured, nothing is sent."""
        self.overlay.set_board_visible(True)
        bring_to_front(app_in_front())

    def take_screenshot(self):
        # Capture the chosen area, or else the whole monitor the cursor is on.
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        rect = self.area if self.area is not None else screen.geometry()
        self.area = None
        try:
            self.screenshot = capture.capture_rect(rect)
        except Exception as error:
            print(f"Could not take the screenshot: {error}")
            return
        finally:
            self.overlay.set_board_visible(True)   # always bring everything back

        # Send the question and the screenshot to the AI model. The buddy
        # pulses while we wait for the reply.
        self.overlay.thinking = True
        try:
            self.ai.ask(self.question, self.screenshot)
        finally:
            # The picture has been read into memory for sending; do not leave
            # a copy of your screen lying on the disk.
            capture.delete_screenshot()

    def on_answer(self, answer):
        """The AI replied. `answer` has the text and the point (see ai.py)."""
        self.overlay.thinking = False
        spot = None
        if answer.point is not None:
            # Turn the position in the picture into a position on the screen.
            spot = self.screenshot.to_screen(*answer.point)

        # Build the circles, underlines and arrows, also in screen positions.
        drawn = []
        for kind, x1, y1, x2, y2 in answer.marks:
            first = self.screenshot.to_screen(x1, y1)
            second = self.screenshot.to_screen(x2, y2)
            if kind == "circle":
                drawn.append(marks.circle(QRectF(first, second)))
            elif kind == "underline":
                drawn.append(marks.underline(QRectF(first, second)))
            elif kind == "arrow":
                drawn.append(marks.arrow(first, second))

        self.overlay.show_answer(answer.text, spot, drawn)

    def on_ai_failed(self, message):
        self.overlay.thinking = False
        print(message)
        self.overlay.show_answer("Sorry, that did not work. See the Terminal window.", None)
