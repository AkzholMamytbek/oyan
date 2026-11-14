"""Spoken answers, using the voice that is built into macOS.

Nothing here uses the internet: we run `say`, the small program that comes
with every Mac and turns text into speech on the Mac itself.

When does Oyan speak?
    off   (the default) never; answers are only written
    on    every answer
    auto  only when you ASKED by voice
Change it with:  python -m oyan --voice on   (or off, or auto)
"""

import subprocess

from oyan import settings

MODES = ("auto", "on", "off")


def get_mode():
    mode = settings.load().get("voice", "off")
    return mode if mode in MODES else "off"


def set_mode(mode):
    all_settings = settings.load()
    all_settings["voice"] = mode
    settings.save(all_settings)


class Speaker:
    def __init__(self):
        self.process = None   # the `say` program while it is talking

    def should_speak(self, asked_by_voice):
        mode = get_mode()
        return mode == "on" or (mode == "auto" and asked_by_voice)

    def speak(self, text):
        """Say the text aloud. Anything still being said is cut off first."""
        self.stop()
        try:
            # We hand the text over through the program's input rather than
            # on its command line, so other programs cannot see it there.
            self.process = subprocess.Popen(["/usr/bin/say"], stdin=subprocess.PIPE)
            self.process.stdin.write(text.encode("utf-8"))
            self.process.stdin.close()
        except OSError as error:
            print(f"Could not speak: {error}")
            self.process = None

    def stop(self):
        """Stop talking at once (used by Esc and when a new question starts)."""
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
        self.process = None

    def is_speaking(self):
        return self.process is not None and self.process.poll() is None
