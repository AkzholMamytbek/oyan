"""Start Oyan.  Run from the project folder with:  python -m oyan

Extra commands:
    python -m oyan --log          show everything Oyan has sent to the AI
    python -m oyan --clear-log    delete that record
    python -m oyan --blocked      list the apps Oyan refuses to photograph
    python -m oyan --block NAME   add an app to that list
    python -m oyan --unblock NAME remove an app from it
    python -m oyan --set-key      save an optional API key (it is not shown)
    python -m oyan --remove-key   delete the saved key
"""

import getpass
import signal
import sys

from AppKit import NSApp, NSApplicationActivationPolicyAccessory
from PyQt6.QtWidgets import QApplication

from oyan import blocked, sent_log, settings
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
    option = sys.argv[1] if len(sys.argv) > 1 else ""
    if option in ("--set-key", "--remove-key"):
        manage_key(option)
        return
    if option in ("--blocked", "--block", "--unblock"):
        name = " ".join(sys.argv[2:]).strip()
        if option == "--block" and name:
            blocked.add(name)
        elif option == "--unblock" and name:
            if not blocked.remove(name):
                print(f'"{name}" was not on the list.')
        elif option != "--blocked":
            print(f'Give the app name, for example:  python -m oyan {option} "App Name"')
            return
        print("Oyan will not take a screenshot while any of these is on screen:")
        for item in blocked.get_list():
            print(f"  - {item}")
        return
    if option == "--log":
        path = sent_log.open_page()
        print(f"Opened {path} in your browser ({len(sent_log.read_entries())} request(s) recorded).")
        return
    if option == "--clear-log":
        print(f"Deleted the log ({sent_log.clear()} request(s)).")
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
