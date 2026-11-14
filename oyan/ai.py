"""Asking the AI model.

This is the only part of Oyan that talks to the internet.

How it works
------------
By default Oyan does not talk to the AI service directly. It starts the
`claude` command-line program (Claude Code) that is already installed and
signed in on this Mac, hands it the question and the screenshot, and waits
for the reply. So Oyan itself never sees or stores a password or key.

If an API key has been saved (see settings.py), Oyan uses that instead and
calls the service itself; that code is in ai_direct.py.

The program is started with tight limits:
* it has NO tools: it cannot read files, run commands or browse. This
  matters because text inside a screenshot (a web page, an email) could try
  to trick the AI into doing something; with no tools there is nothing it
  can do except answer;
* it ignores your personal Claude Code settings, add-ons and hooks;
* it runs inside Oyan's own folder (~/.oyan), not in your projects;
* it does not save the conversation to disk.

The question and the picture are handed over through the program's "standard
input" (the same channel a keyboard would use), not written on its command
line, so other programs on the Mac cannot see them in the process list.

Pointing and drawing
--------------------
We ask the AI to end its reply with a tag like  [POINT:640,210:Save button]
where the numbers are a pixel position in the screenshot. It may also add
drawing tags such as  [CIRCLE:600,190,680,230]. `parse_reply` cuts the tags
out of the text and returns the positions separately.

Waiting without freezing
------------------------
The reply takes several seconds. We use QProcess, which runs the command in
the background and sends a signal when it is done, so the buddy keeps moving
while we wait. The API-key way does its waiting in a separate "thread" (a
second line of work running alongside the main one) for the same reason.
"""

import base64
import glob
import json
import os
import re
import shutil
import threading
from dataclasses import dataclass, field

from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal

from oyan import sent_log, settings
from oyan.ai_direct import API_MODEL, AIError, ask_with_key
from oyan.capture import DATA_FOLDER

AI_MODEL = "sonnet"       # for the `claude` command; "haiku" is faster, "opus" is smarter
TIMEOUT_SECONDS = 90      # give up if there is no reply after this long
WARM_SECONDS = 120        # how long a program started in advance may wait for a question

SYSTEM_PROMPT = (
    "You are Oyan, a small helper that lives next to the cursor on a Mac. "
    "Your manner is calm, kind and patient: plain words, no hype, no "
    "exclamation marks, never talking down. "
    "You are given a screenshot of the screen and a question about it. "
    "Look at the screenshot, then answer in one or two short plain sentences. "
    "No markdown, no lists. "
    "All coordinates below are pixel coordinates in the screenshot, with the "
    "origin at the top-left corner. "
    "End your answer with exactly one tag of the form [POINT:x,y:label], where x,y "
    "is the thing your answer is about and label is one to three words naming it. "
    "If nothing on the screen is relevant, end with [POINT:none] instead. "
    "Before the POINT tag you may add up to three drawing tags, only where they "
    "truly help: [CIRCLE:x1,y1,x2,y2] draws a circle around the box with those "
    "corners (use it for a button, icon or field); [UNDERLINE:x1,y1,x2,y2] "
    "underlines the text inside that box; [ARROW:x1,y1,x2,y2] draws an arrow "
    "from the first point to the second (use it to show a direction or to "
    "connect two things). Make boxes fit the thing tightly. "
    "If the user asks you to draw or sketch something, really draw it, with "
    "pen strokes: each [DRAW:x,y x,y x,y ...] tag is one stroke, a list of "
    "points separated by spaces that the pen passes through without lifting. "
    "A stroke may name its colour first, [DRAW:blue:x,y x,y ...], choosing "
    "from red, blue, green, orange, purple, brown and black; use different "
    "colours to tell the parts of a drawing apart. "
    "Use ten or more points for a curve so it looks smooth, and [CIRCLE:...] "
    "for round outlines. Draw every part needed to recognise the thing (a face "
    "needs its outline, two eyes, a nose and a mouth; a house needs walls, a "
    "roof, a door and a window), using up to fourteen drawing tags. Make the "
    "drawing 200 to 350 pixels across and place it in an emptier part of the "
    "screenshot. Then add one short sentence and put the POINT tag just beside "
    "the drawing, not on it. "
    "You are also the user's tutor. When the screen shows an exercise or a "
    "problem (maths, physics, programming) and the user wants help with it, do "
    "not give the final answer. Give ONE concrete next step for this exact "
    "exercise: name the rule and say exactly what to write, for example "
    "'Combine the two logs into one: log2(x(x-2)) = 3', never a vague tip like "
    "'think about log rules'. Mark the place it applies to with a drawing tag. "
    "If the user shows or types their own attempt, say whether it is right and "
    "point at the first mistake. Give the complete worked solution only when "
    "the user asks for it (for example 'show me the solution' or 'just tell "
    "me'). When a small sketch makes the idea clearer (two cars on a road, the "
    "forces on a block, the shape of a graph), draw it in an empty area with "
    "DRAW, CIRCLE and ARROW tags, and name its parts with [LABEL:x,y:short "
    "text] tags, which write up to 25 characters starting at that point. "
    "Always answer in English. "
    "Exception, for how-to questions about using an app: if doing what is asked needs two or more "
    "separate clicks or actions, do not write sentences and do not use the tags "
    "above. Reply only with step tags, in order, at most six: "
    "[STEP:x,y:short instruction] where x,y is where to click for that step on "
    "this screenshot, or [STEP:none:short instruction] when that place is not "
    "visible yet (for example inside a menu that is still closed). Keep each "
    "instruction under ten words."
)

# Matches [POINT:123,456:some label]  (the label part is optional).
POINT_TAG = re.compile(r"\[POINT:\s*(\d+)\s*,\s*(\d+)\s*(?::([^\]]*))?\]")
# Matches [CIRCLE:1,2,3,4], [UNDERLINE:1,2,3,4] and [ARROW:1,2,3,4].
MARK_TAG = re.compile(r"\[(CIRCLE|UNDERLINE|ARROW):\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]")
# Matches [DRAW:10,20 30,40 50,60] and [DRAW:blue:10,20 30,40]: one freehand pen stroke.
DRAW_TAG = re.compile(r"\[DRAW:(?:\s*([a-zA-Z]+)\s*:)?([\d\s,]+)\]")
PAIR = re.compile(r"(\d+)\s*,\s*(\d+)")
# Matches [LABEL:300,200:v = 20 m/s]: a few words written at that point.
LABEL_TAG = re.compile(r"\[LABEL:\s*(\d+)\s*,\s*(\d+)\s*:([^\]]*)\]")
# Matches [STEP:120,45:Open the File menu] and [STEP:none:Choose Export].
STEP_TAG = re.compile(r"\[STEP:\s*(?:(\d+)\s*,\s*(\d+)|none)\s*:([^\]]*)\]")
# Matches any of our tags at all, so we can remove them from the text.
ANY_TAG = re.compile(r"\[(?:POINT|CIRCLE|UNDERLINE|ARROW|DRAW|LABEL|STEP):[^\]]*\]")
MAX_STEPS = 6
MAX_MARKS = 20        # the most circles, lines, arrows, pen strokes and labels in one answer
MAX_REMEMBERED = 6     # how many earlier questions are sent along with a follow-up


@dataclass
class Answer:
    text: str             # the answer with the tags removed
    point: tuple = None   # (x, y) in screenshot pixels, or None
    label: str = ""       # short name of the thing pointed at
    # e.g. [("circle", x1, y1, x2, y2), ("draw", [(x, y), (x, y), ...], "blue")], in drawing order
    marks: list = field(default_factory=list)
    steps: list = field(default_factory=list)   # e.g. [((x, y), "Open File"), (None, "Choose Export")]


def parse_reply(reply):
    """Split the AI's reply into the answer text, the point and the marks."""
    point, label = None, ""
    match = POINT_TAG.search(reply)
    if match:
        point = (int(match.group(1)), int(match.group(2)))
        label = (match.group(3) or "").strip()

    # Collect the drawing tags together with where each one sits in the
    # reply, so that they can be drawn in the order the AI wrote them.
    found = []
    for match in MARK_TAG.finditer(reply):
        kind = match.group(1).lower()                           # "circle", ...
        numbers = [int(match.group(i)) for i in (2, 3, 4, 5)]   # x1, y1, x2, y2
        found.append((match.start(), (kind, *numbers)))
    for match in DRAW_TAG.finditer(reply):
        colour = (match.group(1) or "red").lower()
        points = [(int(x), int(y)) for x, y in PAIR.findall(match.group(2))]
        if len(points) >= 2:
            found.append((match.start(), ("draw", points, colour)))
    for match in LABEL_TAG.finditer(reply):
        words = match.group(3).strip()
        if words:
            found.append((match.start(), ("label", int(match.group(1)), int(match.group(2)), words)))
    marks = [mark for _, mark in sorted(found, key=lambda item: item[0])]

    steps = []
    for match in STEP_TAG.finditer(reply):
        where = (int(match.group(1)), int(match.group(2))) if match.group(1) else None
        steps.append((where, match.group(3).strip()))
    steps = steps[:MAX_STEPS]

    text = ANY_TAG.sub("", reply).strip()
    if len(steps) >= 2:
        # A step-by-step answer: the "text" is the numbered list of steps
        # (used for the history and for follow-up questions).
        text = " ".join(f"{number}. {instruction}" for number, (_, instruction) in enumerate(steps, 1))
    else:
        steps = []
    return Answer(text=text, point=point, label=label, marks=marks[:MAX_MARKS], steps=steps)


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

    # Used only inside this class: the background thread reports its result
    # with this signal, and Qt delivers it safely on the main thread.
    _direct_finished = pyqtSignal(int, str, str)   # request number, reply, error

    def __init__(self):
        super().__init__()
        self.process = None
        self.direct_request = 0      # goes up by one for every API-key request
        self.direct_waiting = False
        self._direct_finished.connect(self._on_direct_finished)
        self.last_picture_name = None   # file name of the last picture in the sent log
        self.timeout = QTimer()
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(self._on_timeout)

        self.warm = None   # a program started in advance, waiting for a question
        self.warm_limit = QTimer()
        self.warm_limit.setSingleShot(True)
        self.warm_limit.timeout.connect(self._close_warm)

    def is_busy(self):
        return self.process is not None or self.direct_waiting

    def ask(self, question, screenshot, image_bytes, earlier=(), user_drew=False):
        """Send the question and the picture.

        `image_bytes` is the picture file's content. `earlier` is a list of
        (question, answer) pairs from before in this conversation; they are
        sent along so the AI remembers what was said. `user_drew` says that
        the owner's own blue pen marks are in the picture.
        """
        # base64 writes the picture's bytes as plain letters and digits, which
        # is how pictures travel inside a text message to the AI.
        image_data = base64.standard_b64encode(image_bytes).decode("utf-8")
        text = f"The screenshot is {screenshot.width} x {screenshot.height} pixels.\n"
        if earlier:
            text += (
                "Earlier in this conversation (those questions were about earlier "
                "screenshots; the screen may look different now):\n"
            )
            for old_question, old_answer in earlier[-MAX_REMEMBERED:]:
                text += f"Q: {old_question}\nA: {old_answer}\n"
            text += "Now answer the new question about the screenshot attached to this message.\n"
        if user_drew:
            text += (
                "The user drew the bright blue pen marks in the screenshot by hand, "
                "to show what the question is about. Answer about what they marked.\n"
            )
        text += f"Question: {question}"

        # Decide which way the request will go.
        api_key = settings.get_api_key()
        command = None if api_key else find_command()
        if not api_key and command is None:
            self.failed.emit(
                "The `claude` command was not found. Install Claude Code and sign in, "
                "or save an API key with:  python -m oyan --set-key"
            )
            return

        # Privacy rule: write down what is about to leave the Mac BEFORE
        # sending it. If the note cannot be written, nothing is sent.
        try:
            self.last_picture_name = sent_log.record(
                text, image_bytes, screenshot.width, screenshot.height,
                sent_via="Anthropic API key" if api_key else "claude command",
                model=API_MODEL if api_key else AI_MODEL,
                system_prompt=SYSTEM_PROMPT,
            )
        except OSError as error:
            self.failed.emit(f"Could not write the sent-items log, so nothing was sent: {error}")
            return

        if api_key:
            self._ask_with_key(api_key, image_data, text)
        else:
            self._ask_with_command(command, image_data, text)

    # --- Way 1: an API key --------------------------------------------------

    def _ask_with_key(self, api_key, image_data, text):
        self.direct_request += 1
        self.direct_waiting = True
        request = self.direct_request

        def work():
            # This function runs in the background thread.
            try:
                reply = ask_with_key(api_key, SYSTEM_PROMPT, image_data, text, TIMEOUT_SECONDS)
                self._direct_finished.emit(request, reply, "")
            except AIError as error:
                self._direct_finished.emit(request, "", str(error))
            except Exception:
                self._direct_finished.emit(request, "", "The AI call did not work.")

        threading.Thread(target=work, daemon=True).start()

    def _on_direct_finished(self, request, reply, error):
        if request != self.direct_request or not self.direct_waiting:
            return   # an old or cancelled request; ignore its result
        self.direct_waiting = False
        if error:
            self.failed.emit(error)
        else:
            self.answered.emit(parse_reply(reply))

    # --- Way 2: the `claude` command ----------------------------------------

    def _ask_with_command(self, command, image_data, text):
        # The message, in the format the program expects: a picture and a text.
        message = {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data},
                    },
                    {"type": "text", "text": text},
                ],
            },
        }
        # Use the program that was started in advance if it is still waiting
        # (see prepare); otherwise start one now.
        if self.warm is not None and self.warm.state() == QProcess.ProcessState.Running:
            self.process, self.warm = self.warm, None
        else:
            self.process = self._start_program(command)
        self.warm_limit.stop()
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(self._on_error)
        # Hand over the message, then close the channel to say "that is all".
        self.process.write((json.dumps(message) + "\n").encode("utf-8"))
        self.process.closeWriteChannel()
        self.timeout.start(TIMEOUT_SECONDS * 1000)

    def _start_program(self, command):
        """Start the `claude` program. It then waits for a message on its input."""
        arguments = [
            "-p",                               # answer once and exit
            "--input-format", "stream-json",    # we send the message as JSON...
            "--output-format", "stream-json",   # ...and get JSON lines back
            "--verbose",                        # (required with stream-json output)
            "--model", AI_MODEL,
            "--system-prompt", SYSTEM_PROMPT,
            "--tools", "",                      # no tools at all
            "--restricted",                     # ignore personal settings and hooks
            "--strict-mcp-config",              # do not load any add-on servers
            "--disable-slash-commands",         # do not load skills or commands
            "--no-session-persistence",         # do not save the conversation
        ]
        process = QProcess()
        process.setWorkingDirectory(str(DATA_FOLDER))
        process.start(command, arguments)
        return process

    def prepare(self):
        """Start the program ahead of time, while you are still typing.

        Starting it takes most of a second. If it is already running and
        waiting when you press Enter, the answer comes that much sooner.
        Nothing is sent to it (or to anyone) until you ask. If you do not
        ask within WARM_SECONDS, it is closed again.
        """
        if settings.get_api_key():
            return   # the API-key way has no program to start
        if self.warm is not None and self.warm.state() != QProcess.ProcessState.NotRunning:
            self.warm_limit.start(WARM_SECONDS * 1000)   # already waiting: keep it a bit longer
            return
        command = find_command()
        if command is not None:
            self.warm = self._start_program(command)
            self.warm_limit.start(WARM_SECONDS * 1000)

    def _close_warm(self):
        if self.warm is not None:
            self.warm.kill()
            self.warm.waitForFinished(500)   # give it a moment to really stop
            self.warm = None

    def cancel(self):
        """Stop waiting for the current reply (used by Esc)."""
        self.direct_waiting = False   # a late API-key reply will be ignored
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
            # The output is several lines of JSON; the one we want has
            # "type": "result" and carries the final answer.
            results = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
            data = next(item for item in results if item.get("type") == "result")
            reply = data["result"]
            if data.get("is_error"):
                raise ValueError(reply)
        except Exception:
            # Show whatever the command said, shortened, to help find the problem.
            errors = bytes(process.readAllStandardError()).decode("utf-8", "replace")
            detail = (errors or output).strip()[-300:]
            self.failed.emit(f"The AI call did not work: {detail}")
            return
        self.answered.emit(parse_reply(reply))

    def _on_error(self, error):
        if self._forget_process() is not None:
            self.failed.emit("The AI command could not be started.")

    def _on_timeout(self):
        self.cancel()
        self.failed.emit("The AI took too long to answer.")
