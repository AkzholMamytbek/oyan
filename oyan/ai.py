"""Asking the AI model.

This is the only part of Oyan that talks to the internet.

How it works
------------
Oyan does not talk to the AI service directly. It starts the `claude`
command-line program (Claude Code) that is already installed and signed in on
this Mac, hands it the question and the path of the screenshot, and waits for
the reply. So Oyan itself never sees or stores a password or key.

The program is started with tight limits:
* it may only use one tool, "Read", which it needs to open the screenshot;
* it runs inside Oyan's own folder (~/.oyan), not in your projects;
* it does not save the conversation to disk.

Pointing
--------
We ask the AI to end its reply with a tag like  [POINT:640,210:Save button]
where the numbers are a pixel position in the screenshot. `parse_reply`
cuts that tag out of the text and returns the position separately.

Waiting without freezing
------------------------
The reply takes several seconds. We use QProcess, which runs the command in
the background and sends a signal when it is done, so the buddy keeps moving
while we wait.
"""

import glob
import json
import os
import re
import shutil
from dataclasses import dataclass

from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal

from oyan.capture import DATA_FOLDER

AI_MODEL = "sonnet"       # which model to ask; "haiku" is faster, "opus" is smarter
TIMEOUT_SECONDS = 90      # give up if there is no reply after this long

SYSTEM_PROMPT = (
    "You are Oyan, a small friendly helper that lives next to the cursor on a Mac. "
    "You are given a screenshot of the screen and a question about it. "
    "Read the screenshot file, then answer in one or two short plain sentences. "
    "No markdown, no lists. "
    "End your answer with exactly one tag of the form [POINT:x,y:label], where x,y "
    "are pixel coordinates in the screenshot (origin at the top-left corner) of the "
    "thing your answer is about, and label is one to three words naming it. "
    "If nothing on the screen is relevant, end with [POINT:none] instead."
)

# Matches [POINT:123,456:some label]  (the label part is optional).
POINT_TAG = re.compile(r"\[POINT:\s*(\d+)\s*,\s*(\d+)\s*(?::([^\]]*))?\]")
# Matches any [POINT:...] tag at all, so we can remove it from the text.
ANY_POINT_TAG = re.compile(r"\[POINT:[^\]]*\]")


@dataclass
class Answer:
    text: str             # the answer with the tag removed
    point: tuple = None   # (x, y) in screenshot pixels, or None
    label: str = ""       # short name of the thing pointed at


def parse_reply(reply):
    """Split the AI's reply into the answer text and the point."""
    point, label = None, ""
    match = POINT_TAG.search(reply)
    if match:
        point = (int(match.group(1)), int(match.group(2)))
        label = (match.group(3) or "").strip()
    text = ANY_POINT_TAG.sub("", reply).strip()
    return Answer(text=text, point=point, label=label)


def find_command():
    """Find the `claude` program on this Mac. Returns its path, or None."""
    found = shutil.which("claude")
    if found:
        return found
    # Not on the PATH. Try the usual install place, then the copy that comes
    # inside the VS Code extension (newest version last after sorting).
    candidates = [os.path.expanduser("~/.local/bin/claude")]
    candidates += sorted(
        glob.glob(
            os.path.expanduser(
                "~/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude"
            )
        ),
        reverse=True,
    )
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


class AskAI(QObject):
    """Sends one question at a time and reports back with a signal."""

    answered = pyqtSignal(object)   # carries an Answer
    failed = pyqtSignal(str)        # carries a message to show the owner

    def __init__(self):
        super().__init__()
        self.process = None
        self.timeout = QTimer()
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(self._on_timeout)

    def is_busy(self):
        return self.process is not None

    def ask(self, question, screenshot):
        command = find_command()
        if command is None:
            self.failed.emit(
                "The `claude` command was not found. Install Claude Code and sign in first."
            )
            return

        prompt = (
            f"Screenshot: {screenshot.path} "
            f"({screenshot.width} x {screenshot.height} pixels).\n"
            f"Question: {question}"
        )
        arguments = [
            "-p", prompt,                     # answer once and exit
            "--output-format", "json",        # reply as JSON we can parse
            "--model", AI_MODEL,
            "--system-prompt", SYSTEM_PROMPT,
            "--tools", "Read",                # the only tool that exists for it
            "--allowedTools", "Read",         # ...and it may use it without asking
            "--strict-mcp-config",            # do not load any add-on servers
            "--disable-slash-commands",       # do not load skills or commands
            "--no-session-persistence",       # do not save the conversation
        ]

        self.process = QProcess()
        self.process.setWorkingDirectory(str(DATA_FOLDER))
        self.process.setStandardInputFile(QProcess.nullDevice())   # nothing to type in
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(self._on_error)
        self.process.start(command, arguments)
        self.timeout.start(TIMEOUT_SECONDS * 1000)

    def cancel(self):
        """Stop waiting for the current reply (used by Esc)."""
        process = self._forget_process()
        if process is not None:
            process.kill()

    # --- What happens when the command ends --------------------------------

    def _forget_process(self):
        """Stop listening to the current process and return it."""
        process, self.process = self.process, None
        self.timeout.stop()
        if process is not None:
            process.finished.disconnect(self._on_finished)
            process.errorOccurred.disconnect(self._on_error)
        return process

    def _on_finished(self, exit_code, exit_status):
        process = self._forget_process()
        output = bytes(process.readAllStandardOutput()).decode("utf-8", "replace")
        try:
            data = json.loads(output)
            reply = data["result"]
            if data.get("is_error"):
                raise ValueError(reply)
        except Exception:
            # Show whatever the command said, shortened, to help find the problem.
            errors = bytes(process.readAllStandardError()).decode("utf-8", "replace")
            detail = (output or errors).strip()[:300]
            self.failed.emit(f"The AI call did not work: {detail}")
            return
        self.answered.emit(parse_reply(reply))

    def _on_error(self, error):
        if self._forget_process() is not None:
            self.failed.emit("The AI command could not be started.")

    def _on_timeout(self):
        self.cancel()
        self.failed.emit("The AI took too long to answer.")
