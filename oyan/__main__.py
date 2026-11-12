"""Start Oyan.  Run from the project folder with:  python -m oyan

Two extra commands manage the optional API key:
    python -m oyan --set-key      save a key (you paste it; it is not shown)
    python -m oyan --remove-key   delete the saved key
"""

import getpass
import signal
import sys

from AppKit import NSApp, NSApplicationActivationPolicyAccessory
from PyQt6.QtWidgets import QApplication

from oyan import settings
from oyan.app import Oyan


def manage_key(option):
    if option == "--set-key":
        # getpass reads what you type or paste without showing it on screen.
        key = getpass.getpass("Paste your Anthropic API key and press Enter (it stays hidden): ").strip()
        if not key:
            print("Nothing entered; no change.")
            return
        settings.set_api_key(key)
        print(f"Saved in {settings.SETTINGS_PATH}. Oyan will now use this key.")
    else:
        settings.remove_api_key()
        print("Key removed. Oyan will use the `claude` command again.")


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("--set-key", "--remove-key"):
        manage_key(sys.argv[1])
        return

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
