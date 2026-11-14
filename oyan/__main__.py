"""Start Oyan.  Run from the project folder with:  python -m oyan

Extra commands:
    python -m oyan --log          show everything Oyan has sent to the AI
    python -m oyan --clear-log    delete that record
    python -m oyan --history      open past questions and answers, with search
    python -m oyan --history WORDS   print the entries containing those words
    python -m oyan --clear-history   delete the history
    python -m oyan --blocked      list the apps Oyan refuses to photograph
    python -m oyan --block NAME   add an app to that list
    python -m oyan --unblock NAME remove an app from it
    python -m oyan --setup-voice  download the speech-recognition model (once)
    python -m oyan --voice MODE   read answers aloud: on, off, or auto (only
                                  when you asked by voice; the default)
    python -m oyan --set-key      save an optional API key (it is not shown)
    python -m oyan --remove-key   delete the saved key
"""

import getpass
import signal
import sys

from AppKit import NSApp, NSApplicationActivationPolicyAccessory
from PyQt6.QtWidgets import QApplication

from oyan import blocked, history, sent_log, settings, speak
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
    if option == "--setup-voice":
        from oyan import listen   # imported here because it is slow to load
        if listen.is_set_up():
            print("Voice is already set up.")
        else:
            print("Downloading the speech-recognition model (about 150 MB). This is the only")
            print("time voice uses the internet; afterwards it runs entirely on this Mac.")
            listen.set_up()
            print("Done.")
        print("Press Option + S while Oyan runs, speak, and press it again.")
        return
    if option == "--voice":
        mode = sys.argv[2].lower() if len(sys.argv) > 2 else ""
        if mode in speak.MODES:
            speak.set_mode(mode)
        elif mode:
            print("Choose one of: on, off, auto")
            return
        print(f"Reading answers aloud: {speak.get_mode()}")
        return
    if option == "--history":
        words = sys.argv[2:]
        if not words:
            path = history.open_page()
            print(f"Opened {path} in your browser ({len(history.read_entries())} question(s)).")
            return
        found = history.search(words)
        print(f"{len(found)} match(es) for: {' '.join(words)}")
        for entry in found:
            print(f"\n{entry['time']}\n  Q: {entry['question']}\n  A: {entry['answer']}")
        return
    if option == "--clear-history":
        print(f"Deleted the history ({history.clear()} question(s)).")
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
