"""The conductor: connects the parts of Oyan to each other.

Each part lives in its own file and knows nothing about the others:
* overlay.py  - the see-through window and the buddy dot
* hotkey.py   - the global key combination
* ask_box.py  - the small text box

This file decides what happens when: hotkey pressed -> open the box,
question entered -> (next step) take a screenshot, and so on.
"""

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QCursor

from oyan import hotkey
from oyan.ask_box import AskBox, app_in_front, bring_to_front
from oyan.overlay import OverlayController


class Oyan:
    def __init__(self, app):
        self.overlay = OverlayController(app)

        self.ask_box = AskBox()
        self.ask_box.submitted.connect(self.on_question)

        self.hotkey = hotkey.GlobalHotkey(self.on_hotkey)

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

    def on_hotkey(self):
        """The hotkey opens the box; pressing it again closes the box."""
        if self.ask_box.isVisible():
            self.ask_box.close_box()
        else:
            self.ask_box.open_near(QCursor.pos())

    def on_question(self, question):
        # Next step: take a screenshot here and send both to the AI model.
        print(f"Question: {question}")
