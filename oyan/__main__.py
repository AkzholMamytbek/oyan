"""Start Oyan.  Run from the project folder with:  python -m oyan"""

import signal
import sys

from PyQt6.QtWidgets import QApplication

from oyan.overlay import OverlayController


def main():
    app = QApplication(sys.argv)

    # Oyan has no normal window to close, so let Ctrl+C in Terminal quit it.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Keep a reference in a variable, otherwise Python would delete the
    # controller (and its windows) as soon as this line finished.
    controller = OverlayController(app)
    controller.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
