"""The conductor: connects the parts of Oyan to each other.

Each part lives in its own file and knows nothing about the others:
* overlay.py  - the see-through window and the buddy dot
* handwriting.py - the written answer
* marks.py    - circles, underlines and arrows
* doodles.py  - the idle sketches
* region.py   - dragging a box to send only part of the screen
* sent_log.py - the record of everything sent to the AI
* blocked.py  - apps Oyan refuses to photograph
* history.py  - past questions and answers, searchable
* speak.py    - reading answers aloud with the Mac's own voice
* listen.py   - turning your spoken question into text, on this Mac
* hotkey.py   - the global key combination
* ask_box.py  - the small text box
* capture.py  - the screenshot
* ai.py       - sending the question and screenshot to the AI model

This file decides what happens when: hotkey pressed -> open the box,
question entered -> take a screenshot -> ask the AI model -> show the answer.
"""

import math

from PyQt6.QtCore import QPoint, QPointF, QRectF, QTimer
from PyQt6.QtGui import QCursor, QGuiApplication

from oyan import blocked, capture, history, hotkey, marks
from oyan.ai import AskAI
from oyan.ask_box import BOX_HEIGHT, AskBox, app_in_front, bring_to_front
from oyan.overlay import OverlayController
from oyan.region import RegionSelector
from oyan.speak import Speaker


NEXT_QUESTION_GAP = 30   # space between an answer and the box for the next question
STEP_CLICK_RADIUS = 90   # a click this close to a step's spot counts as doing the step
STEP_CIRCLE = 16         # half the size of the circle drawn around a step's spot


class Oyan:
    def __init__(self, app):
        self.overlay = OverlayController(app)

        self.overlay.on_note_finished = self.show_box_under
        # No idle doodles while you are typing a question or waiting for an answer.
        self.overlay.may_doodle = lambda: not self.ask_box.isVisible() and not self.ai.is_busy()

        self.ask_box = AskBox()
        self.ask_box.submitted.connect(self.on_question)
        self.ask_box.submitted_for_area.connect(self.on_question_for_area)
        self.ask_box.submitted_fresh.connect(self.on_question)

        self.region = RegionSelector()
        self.region.selected.connect(self.on_area_selected)
        self.region.cancelled.connect(self.on_area_cancelled)
        self.area = None         # the rectangle chosen with Shift+Enter, if any
        self.ask_box.escaped.connect(self.on_escape)

        self.hotkey = hotkey.GlobalHotkey(self.on_hotkey, self.on_escape, self.on_click, self.on_voice_hotkey)
        self.listener = None             # the microphone part, created on first use
        self.next_question_by_voice = False

        # Step-by-step mode (see start_steps).
        self.steps = []          # [(spot on screen or None, instruction), ...]
        self.step_index = 0      # which step is showing
        self.step_note = None    # the note of the step that is showing

        self.ai = AskAI()
        self.ai.answered.connect(self.on_answer)
        self.ai.failed.connect(self.on_ai_failed)

        self.speaker = Speaker()
        self.asked_by_voice = False   # was the current question spoken?

        self.question = None     # the question being worked on right now
        self.screenshot = None   # the latest screenshot (its size and place on screen)
        self.image_bytes = None  # that picture's content, kept in memory only
        self.exchanges = []      # (question, answer) pairs about that picture

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
        print(f"To ask by voice, press {hotkey.VOICE_HOTKEY_NAME}, speak, and press it again.")
        print("To see everything Oyan has sent:  python -m oyan --log")
        print("To search past questions:         python -m oyan --history")
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
        if self.steps and self.step_index < len(self.steps) - 1:
            return   # in the middle of a step-by-step answer: no box yet
        if not self.ask_box.is_typing():   # do not disturb if you are typing
            self.ask_box.show_attached(self._place_under(note))

    def on_hotkey(self):
        """The hotkey starts typing; pressing it again while typing closes the box."""
        if self.ask_box.is_typing():
            self.ask_box.close_box()
            return
        self.next_question_by_voice = False
        self._open_box()

    def _open_box(self):
        """Open the ask box for typing: under the newest answer, or at the cursor."""
        note = self.overlay.note
        if note is not None and note.visible:
            # An answer is on screen: type right under it.
            self.ask_box.attached = True
            self.ask_box.open_at(self._place_under(note))
        else:
            self.ask_box.open_near(QCursor.pos())

    # --- Asking by voice -----------------------------------------------------
    # Press the voice hotkey, speak, press it again. What you said is put into
    # the ask box for you to check; nothing is captured or sent until you
    # press Enter there, exactly as when you type.

    def on_voice_hotkey(self):
        if self.listener is None:
            try:
                # Loaded only now, because these packages are big and would
                # slow down every start of Oyan otherwise.
                from oyan import listen
            except ImportError:
                self.overlay.show_answer("Voice needs extra packages. Run: pip install -r requirements.txt", None)
                return
            if not listen.is_set_up():
                self.overlay.show_answer("Voice is not set up yet. Run once: python -m oyan --setup-voice", None)
                return
            self.listener = listen.Listener()
            self.listener.heard.connect(self.on_heard)
            self.listener.failed.connect(self.on_voice_failed)

        if self.listener.is_listening():
            # Second press: stop recording and work out what was said.
            self.overlay.listening = False
            self.overlay.thinking = True
            self.listener.stop()
        else:
            self.speaker.stop()
            if self.ask_box.isVisible() and not self.ask_box.attached:
                self.ask_box.close_box()
            self.overlay.listening = True   # the buddy turns red: the microphone is on
            self.listener.start()

    def on_heard(self, text):
        self.overlay.thinking = False
        if not text:
            self.overlay.show_answer("I did not catch any words. Try again a little closer to the microphone.", None)
            return
        self.next_question_by_voice = True
        self._open_box()
        self.ask_box.input.setText(text)   # check it, change it if needed, press Enter

    def on_voice_failed(self, message):
        self.overlay.listening = False
        self.overlay.thinking = False
        self.overlay.show_answer(message, None)

    def on_escape(self):
        """Esc: stop waiting for the AI and wipe the board clean."""
        if self.listener is not None and self.listener.is_listening():
            self.listener.cancel()          # throw the recording away
            self.overlay.listening = False
            return
        if self.ai.is_busy():
            self.ai.cancel()
            self.overlay.thinking = False
        if self.ask_box.isVisible():
            self.ask_box.close_box()
        self.steps = []
        self.speaker.stop()
        self.overlay.wipe_board()
        # A clean board is a clean start: forget the picture and the conversation.
        self.image_bytes = None
        self.exchanges = []

    def _note_how_it_was_asked(self):
        """Remember whether this question was spoken (then the answer is too)."""
        self.asked_by_voice = self.next_question_by_voice
        self.next_question_by_voice = False

    def _ready_to_capture(self):
        """May we take a picture now? Explains why not, if not."""
        # Never photograph a blocked app (a password manager, for example).
        blocked_app = blocked.blocked_app_on_screen()
        if blocked_app is not None:
            self.overlay.show_answer(
                f"I am not looking while {blocked_app} is on screen. "
                "Close or hide it and ask again. Nothing was captured or sent.",
                None,
            )
            return False

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

    def on_question(self, question, attached=False):
        """Enter: send the whole screen the cursor is on.

        Exception: Enter in the box under an answer is a FOLLOW-UP. It takes
        no new picture; it asks again about the one already sent, together
        with the earlier questions and answers.
        """
        self.steps = []   # a new question ends any step-by-step answer
        self.speaker.stop()
        self._note_how_it_was_asked()
        if attached and self.image_bytes is not None and self.exchanges:
            self.ask_follow_up(question)
            return
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

    def ask_follow_up(self, question):
        self.ai.cancel()
        self.question = question
        self.overlay.thinking = True
        self.ai.ask(question, self.screenshot, self.image_bytes, earlier=self.exchanges)

    def on_question_for_area(self, question):
        """Shift+Enter: let the owner drag a box first; only that part is sent."""
        self.steps = []
        self.speaker.stop()
        self._note_how_it_was_asked()
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
        try:
            # Keep the picture in memory (for follow-up questions) and remove
            # the working file; the "what left my Mac" log keeps its own copy.
            self.image_bytes = self.screenshot.path.read_bytes()
        finally:
            capture.delete_screenshot()
        self.exchanges = []   # a new picture starts a new conversation

        self.overlay.thinking = True
        self.ai.ask(self.question, self.screenshot, self.image_bytes)

    def on_answer(self, answer):
        """The AI replied. `answer` has the text and the point (see ai.py)."""
        self.overlay.thinking = False
        self._remember(answer)
        if not answer.steps and self.speaker.should_speak(self.asked_by_voice):
            self.speaker.speak(answer.text)

        if answer.steps:
            self.start_steps(answer.steps)
            return

        spot = None
        if answer.point is not None:
            # Turn the position in the picture into a position on the screen.
            spot = self.screenshot.to_screen(*answer.point)

        # Build the circles, underlines and arrows, also in screen positions.
        drawn = []
        for kind, *numbers in answer.marks:
            if kind == "draw":
                # A freehand pen stroke: a list of points.
                points = [self.screenshot.to_screen(x, y) for x, y in numbers[0]]
                drawn.append(marks.freehand(points))
                continue
            x1, y1, x2, y2 = numbers
            first = self.screenshot.to_screen(x1, y1)
            second = self.screenshot.to_screen(x2, y2)
            if kind == "circle":
                drawn.append(marks.circle(QRectF(first, second)))
            elif kind == "underline":
                drawn.append(marks.underline(QRectF(first, second)))
            elif kind == "arrow":
                drawn.append(marks.arrow(first, second))

        self.overlay.show_answer(answer.text, spot, drawn)

    def _remember(self, answer):
        """Write the question and answer to the history, and keep them for follow-ups."""
        try:
            history.record(
                self.question, answer.text, self.ai.last_picture_name,
                follow_up=len(self.exchanges) > 0,
            )
        except OSError as error:
            print(f"Could not write the history: {error}")
        self.exchanges.append((self.question, answer.text))

    # --- Step-by-step mode ---------------------------------------------------
    # For "how do I..." questions the AI may answer with a list of steps.
    # Oyan shows one step at a time: it circles the place to click, waits
    # until you click there, then moves on to the next step.
    #
    # Privacy rule: Oyan does NOT take a new screenshot after each click. All
    # steps were planned from the one picture you sent. A step whose place
    # was not visible in it (inside a closed menu, say) is shown in words only.

    def start_steps(self, steps):
        self.steps = []
        for where, instruction in steps:
            spot = self.screenshot.to_screen(*where) if where is not None else None
            self.steps.append((spot, instruction))
        self.step_note = None
        self.show_step(0)

    def show_step(self, index):
        if index >= len(self.steps):
            return
        self.step_index = index
        if self.step_note is not None:
            self.overlay.remove_note(self.step_note)   # the step just done

        spot, instruction = self.steps[index]
        text = f"Step {index + 1} of {len(self.steps)}: {instruction}"
        if self.speaker.should_speak(self.asked_by_voice):
            self.speaker.speak(text)
        drawn = []
        if spot is not None:
            around = QRectF(spot.x() - STEP_CIRCLE, spot.y() - STEP_CIRCLE, 2 * STEP_CIRCLE, 2 * STEP_CIRCLE)
            drawn.append(marks.circle(around))

        if index == len(self.steps) - 1:
            hint = None   # the last step: the usual reminder and typing box
        elif spot is not None:
            hint = "Click it to continue    Esc: stop"
        else:
            hint = "Click anywhere to continue    Esc: stop"
        self.step_note = self.overlay.show_answer(text, spot, drawn, hint=hint)

    def on_click(self):
        """The mouse was clicked somewhere in another app."""
        if not self.steps or self.step_index >= len(self.steps) - 1:
            return   # not in step-by-step mode, or already on the last step
        if self.overlay.mode != "follow":
            return   # the current step is still being drawn or written
        spot, _ = self.steps[self.step_index]
        if spot is not None:
            away = QPointF(QCursor.pos()) - spot
            if math.hypot(away.x(), away.y()) > STEP_CLICK_RADIUS:
                return   # a click somewhere else; keep waiting
        # Give the app a moment to react to the click, then show the next step.
        next_index = self.step_index + 1
        QTimer.singleShot(350, lambda: self._advance_to(next_index))

    def _advance_to(self, index):
        if self.steps and index == self.step_index + 1:   # still the step we expect
            self.show_step(index)

    def on_ai_failed(self, message):
        self.overlay.thinking = False
        print(message)
        self.overlay.show_answer("Sorry, that did not work. See the Terminal window.", None)
