"""Oyan's settings: a small file on this Mac, never uploaded.

The file is ~/.oyan/settings.json. Right now it can hold one thing: an
optional Anthropic API key, for people who do not use Claude Code.

Keeping the key safe
--------------------
* The file lives in your home folder, OUTSIDE the project folder, so git
  cannot see it and it can never be pushed to GitHub by accident.
* It is saved so that only your own Mac user account can read it.
* Oyan never prints the key.
"""

import json
import os

from oyan.capture import DATA_FOLDER

SETTINGS_PATH = DATA_FOLDER / "settings.json"


def load():
    """Read the settings file. Returns an empty dictionary if there is none."""
    try:
        return json.loads(SETTINGS_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(settings):
    DATA_FOLDER.mkdir(exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2))
    os.chmod(SETTINGS_PATH, 0o600)   # 600 = only the owner may read or write


def get_api_key():
    """The saved API key, or None if there is none."""
    return load().get("api_key") or None


def set_api_key(key):
    settings = load()
    settings["api_key"] = key
    save(settings)


def remove_api_key():
    settings = load()
    settings.pop("api_key", None)
    save(settings)
