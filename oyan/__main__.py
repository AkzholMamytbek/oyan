"""Start Oyan.  Run from the project folder with:  python -m oyan"""

import signal
import sys

from AppKit import NSApp, NSApplicationActivationPolicyAccessory
from PyQt6.QtWidgets import QApplication

from oyan.app import Oyan


def main():
    app = QApplication(sys.argv)

    # Oyan has no normal window. Closing the text box must not quit the app.
    app.setQuitOnLastWindowClosed(False)

    # "Accessory" means: no Dock icon and no menu bar of its own, like the
    # little helper apps that live in the background.
    NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    # Let Ctrl+C in Terminal quit Oyan.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Keep a reference in a variable, otherwise Python would delete the
    # object (and its windows) as soon as this line finished.
    oyan = Oyan(app)
    oyan.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
