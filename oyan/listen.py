"""Speech to text: ask your question by voice. Everything happens on this Mac.

How it works
------------
1. You press the voice hotkey. Oyan records from the microphone into memory
   (not to a file) until you press the hotkey again.
2. A speech-recognition model called Whisper turns the recording into text.
   The model is a file on your Mac and runs on your Mac; your voice is never
   sent anywhere.
3. The text is put into the ask box so you can check it. Nothing is captured
   or sent to the AI until you press Enter there, exactly as when you type.

One-time setup
--------------
The model file (about 150 MB) has to be downloaded once:

    python -m oyan --setup-voice

That download is the only time this part uses the internet. While Oyan runs,
it is told to use the downloaded file only and never to fetch anything.

macOS will ask once for Microphone permission for the app you start Oyan from.
"""

import threading

import numpy
import sounddevice
from faster_whisper import WhisperModel
from faster_whisper.utils import download_model
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

MODEL_NAME = "base"        # small and quick, understands many languages
SAMPLE_RATE = 16000        # sound samples per second; what Whisper expects
MAX_SECONDS = 30           # stop listening by itself after this long
SILENCE_LEVEL = 0.0005     # below this the microphone gave us nothing at all


def is_set_up():
    """Has the model been downloaded already? (Does not use the internet.)"""
    try:
        download_model(MODEL_NAME, local_files_only=True)
        return True
    except Exception:
        return False


def set_up():
    """Download the model. The one and only step here that uses the internet."""
    return download_model(MODEL_NAME)


class Listener(QObject):
    heard = pyqtSignal(str)    # carries the text of what you said
    failed = pyqtSignal(str)   # carries a message to show the owner

    def __init__(self):
        super().__init__()
        self.stream = None     # the open microphone, while recording
        self.chunks = []       # the pieces of sound recorded so far
        self.model = None      # loaded the first time it is needed
        self.request = 0       # goes up with every recording, to ignore cancelled ones

        self.limit = QTimer()
        self.limit.setSingleShot(True)
        self.limit.timeout.connect(self.stop)

    def is_listening(self):
        return self.stream is not None

    def start(self):
        """Open the microphone and start collecting sound."""
        self.chunks = []
        try:
            self.stream = sounddevice.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,            # one channel: mono
                dtype="float32",
                callback=self._on_sound,
            )
            self.stream.start()
        except Exception as error:
            self.stream = None
            self.failed.emit(f"Could not open the microphone: {error}")
            return
        self.limit.start(MAX_SECONDS * 1000)

    def _on_sound(self, data, frames, time_info, status):
        # sounddevice calls this many times a second with the newest piece
        # of sound. We just keep a copy.
        self.chunks.append(data.copy())

    def _close_microphone(self):
        self.limit.stop()
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def cancel(self):
        """Stop listening and throw the recording away."""
        self._close_microphone()
        self.chunks = []
        self.request += 1   # any transcription still running will be ignored

    def stop(self):
        """Stop listening and turn the recording into text (in the background)."""
        if not self.is_listening():
            return
        self._close_microphone()
        if not self.chunks:
            self.failed.emit("I did not hear anything.")
            return
        sound = numpy.concatenate(self.chunks)[:, 0]   # one long row of numbers
        self.chunks = []

        if numpy.abs(sound).max() < SILENCE_LEVEL:
            self.failed.emit(
                "The microphone gave only silence. Allow the microphone in System Settings > "
                "Privacy & Security > Microphone for the app you start Oyan from."
            )
            return

        self.request += 1
        request = self.request

        def work():
            # Runs in a background thread, so the buddy keeps moving.
            try:
                text = self.transcribe(sound)
            except Exception as error:
                if request == self.request:
                    self.failed.emit(f"Could not understand the recording: {error}")
                return
            if request == self.request:
                self.heard.emit(text)

        threading.Thread(target=work, daemon=True).start()

    def transcribe(self, sound):
        """Turn sound (numbers between -1 and 1, 16000 per second) into text."""
        if self.model is None:
            # local_files_only=True: use the downloaded file, never the internet.
            self.model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8", local_files_only=True)
        pieces, _ = self.model.transcribe(sound, beam_size=5)
        return " ".join(piece.text.strip() for piece in pieces).strip()
