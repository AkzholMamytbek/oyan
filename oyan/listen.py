"""Speech to text: ask your question by voice. Everything happens on this Mac.

How it works
------------
1. You press the voice key once. Oyan records from the microphone into
   memory (not to a file).
2. You speak. When you have been quiet for about a second, Oyan stops
   listening by itself. (Pressing the key again stops it at once.)
3. A speech-recognition model called Whisper turns the recording into text.
   The model is a file on your Mac and runs on your Mac; your voice is never
   sent anywhere.
4. The question is sent, with a fresh screenshot, as if you had typed it.

How does it know you stopped talking?
-------------------------------------
Sound arrives in pieces of a tenth of a second. For each piece we work out
how loud it is. The first moments tell us how loud the room is when nobody
speaks; anything clearly louder than that counts as your voice. Once your
voice has been heard, QUIET_SECONDS without it means "finished".

One-time setup
--------------
The model file (about 150 MB) has to be downloaded once:

    python -m oyan --setup-voice

That download is the only time this part uses the internet. While Oyan runs,
it is told to use the downloaded file only and never to fetch anything.

macOS will ask once for Microphone permission for the app you start Oyan from.
"""

import threading
import time

import numpy
import sounddevice
from faster_whisper import WhisperModel
from faster_whisper.utils import download_model
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

MODEL_NAME = "base"        # small and quick, understands many languages
SAMPLE_RATE = 16000        # sound samples per second; what Whisper expects
MAX_SECONDS = 30           # stop listening by itself after this long, whatever happens
QUIET_SECONDS = 1.0        # this much silence after speech means "I am finished"
NO_SPEECH_SECONDS = 7      # give up if nobody says anything for this long
PIECE_SAMPLES = 1600       # sound arrives in pieces this long: 1600 samples = 0.1 second
ROOM_SECONDS = 0.3         # how long we listen to the room before judging loudness
VOICE_FACTOR = 2.5         # a voice is at least this many times louder than the room
QUIETEST_VOICE = 0.012     # ...and never quieter than this, however silent the room
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
    stopped = pyqtSignal()     # the microphone was switched off and the words are being worked out

    def __init__(self):
        super().__init__()
        self.stream = None     # the open microphone, while recording
        self.chunks = []       # the pieces of sound recorded so far
        self.model = None      # the speech-recognition model, once loaded
        self.model_lock = threading.Lock()   # makes sure it is loaded only once
        self.request = 0       # goes up with every recording, to ignore cancelled ones

        # Loudness tracking, to notice when you stop talking.
        self.started_at = 0.0
        self.room_levels = []      # loudness of the first pieces, before you speak
        self.voice_level = QUIETEST_VOICE
        self.voice_heard = False
        self.last_voice_at = 0.0

        self.limit = QTimer()
        self.limit.setSingleShot(True)
        self.limit.timeout.connect(self.stop)

        # Looks ten times a second whether you have gone quiet.
        self.watch = QTimer()
        self.watch.setInterval(100)
        self.watch.timeout.connect(self._check_quiet)

    def is_listening(self):
        return self.stream is not None

    def start(self):
        """Open the microphone and start collecting sound."""
        self.chunks = []
        self.room_levels = []
        self.voice_level = QUIETEST_VOICE
        self.voice_heard = False
        self.started_at = time.monotonic()
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
        self.watch.start()
        # Get the model ready while you are talking, so there is no extra
        # wait for it when you finish.
        threading.Thread(target=self._load_model, daemon=True).start()

    def _on_sound(self, data, frames, time_info, status):
        # sounddevice calls this many times a second with the newest piece
        # of sound. We keep a copy and note how loud it was.
        self.chunks.append(data.copy())
        now = time.monotonic()
        loudness = float(numpy.sqrt(numpy.mean(data ** 2)))   # the usual measure: "RMS"
        if now - self.started_at < ROOM_SECONDS:
            # Still learning how loud the room is.
            self.room_levels.append(loudness)
            room = sum(self.room_levels) / len(self.room_levels)
            self.voice_level = max(room * VOICE_FACTOR, QUIETEST_VOICE)
        elif loudness >= self.voice_level:
            self.voice_heard = True
            self.last_voice_at = now

    def _check_quiet(self):
        """Stop by ourselves when you have finished, or never started."""
        if not self.is_listening():
            return
        now = time.monotonic()
        if self.voice_heard and now - self.last_voice_at >= QUIET_SECONDS:
            self.stop()
        elif not self.voice_heard and now - self.started_at >= NO_SPEECH_SECONDS:
            self.cancel()
            self.failed.emit("I did not hear anything. Press the voice key and try again.")

    def _close_microphone(self):
        self.limit.stop()
        self.watch.stop()
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
                self.model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8", local_files_only=True)

    def transcribe(self, sound):
        """Turn sound (numbers between -1 and 1, 16000 per second) into text."""
        self._load_model()
        pieces, _ = self.model.transcribe(sound, beam_size=5)
        return " ".join(piece.text.strip() for piece in pieces).strip()
