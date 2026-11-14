"""Speech to text: ask your question by voice. Everything happens on this Mac.

How it works
------------
1. You hold Control + Option. Oyan records from the microphone into memory
   (not to a file) for as long as you hold them.
2. You let go. That is the signal that you have finished, so there is no
   guessing about pauses.
3. A speech-recognition model called Whisper turns the recording into text.
   The model is a file on your Mac and runs on your Mac; your voice is never
   sent anywhere. A small helper model first cuts out the parts with no
   speech, so silence or background noise is not turned into made-up words.
4. The question is sent, with a fresh screenshot, as if you had typed it.

One-time setup
--------------
The model file (about 460 MB) has to be downloaded once:

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

# The speech models Oyan can use, best first. "small" is about three times
# the size of "base" and clearly better with accents; Oyan uses the best one
# that has been downloaded.
MODEL_NAMES = ["small", "base"]
LANGUAGE = "en"            # the language you speak to Oyan. Telling the model
                           # this, instead of letting it guess, avoids a whole
                           # class of mistakes with accented speech.
# A few words given to the model as a hint of what to expect. It makes these
# and similar words more likely to be heard correctly.
EXPECTED_WORDS = (
    "Oyan, explain this exercise. Solve for x. Logarithm, equation, fraction, "
    "square root, derivative, integral, velocity, acceleration, force. "
    "Python function, variable, loop, list, error. What does this mean?"
)
SAMPLE_RATE = 16000        # sound samples per second; what Whisper expects
MAX_SECONDS = 60           # stop listening by itself after this long, whatever happens
PIECE_SAMPLES = 1600       # sound arrives in pieces this long: 1600 samples = 0.1 second
SILENCE_LEVEL = 0.0005     # below this the microphone gave us nothing at all

def downloaded_model():
    """The best model that is already on this Mac, or None. (No internet.)"""
    for name in MODEL_NAMES:
        try:
            download_model(name, local_files_only=True)
            return name
        except Exception:
            pass
    return None


def is_set_up():
    """Is any model downloaded already?"""
    return downloaded_model() is not None


def has_best_model():
    return downloaded_model() == MODEL_NAMES[0]


def set_up():
    """Download the best model. The one and only step here that uses the internet."""
    return download_model(MODEL_NAMES[0])


class Listener(QObject):
    heard = pyqtSignal(str)    # carries the text of what you said ("" if nothing)
    failed = pyqtSignal(str)   # carries a message to show the owner
    stopped = pyqtSignal()     # the microphone was switched off and the words are being worked out

    def __init__(self):
        super().__init__()
        self.stream = None     # the open microphone, while recording
        self.chunks = []       # the pieces of sound recorded so far
        self.model = None      # the speech-recognition model, once loaded
        self.model_lock = threading.Lock()   # makes sure it is loaded only once
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
                blocksize=PIECE_SAMPLES,   # hand the sound over in tenth-of-a-second pieces
                callback=self._on_sound,
            )
            self.stream.start()
        except Exception as error:
            self.stream = None
            self.failed.emit(f"Could not open the microphone: {error}")
            return
        self.limit.start(MAX_SECONDS * 1000)
        # Get the model ready while you are talking, so there is no extra
        # wait for it when you finish.
        threading.Thread(target=self._load_model, daemon=True).start()

    def _on_sound(self, data, frames, time_info, status):
        # sounddevice calls this ten times a second with the newest piece of
        # sound. We just keep a copy.
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
            self.heard.emit("")
            return
        sound = numpy.concatenate(self.chunks)[:, 0]   # one long row of numbers
        self.chunks = []

        if numpy.abs(sound).max() < SILENCE_LEVEL:
            self.failed.emit(
                "The microphone gave only silence. Allow the microphone in System Settings > "
                "Privacy & Security > Microphone for the app you start Oyan from."
            )
            return

        self.stopped.emit()
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

    def _load_model(self):
        """Load the model if it is not loaded yet. Safe to call from several
        threads at once: the lock lets only one of them do the loading."""
        with self.model_lock:
            if self.model is None:
                # local_files_only=True: use the downloaded file, never the internet.
                self.model = WhisperModel(downloaded_model(), device="cpu", compute_type="int8", local_files_only=True)

    def transcribe(self, sound):
        """Turn sound (numbers between -1 and 1, 16000 per second) into text."""
        self._load_model()
        pieces, _ = self.model.transcribe(
            sound,
            language=LANGUAGE,
            initial_prompt=EXPECTED_WORDS,
            beam_size=5,                        # consider several possible readings, keep the best
            vad_filter=True,                    # first cut out the parts with no speech in them
            condition_on_previous_text=False,   # judge each sentence on its own
        )
        return " ".join(piece.text.strip() for piece in pieces).strip()
