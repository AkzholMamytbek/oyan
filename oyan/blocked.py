"""Blocked apps: Oyan refuses to take a screenshot while one of them is on screen.

Some windows should never be photographed and sent anywhere: a password
manager showing your passwords, for example. Before every capture Oyan asks
macOS which apps have a window on the screen right now. If any of them is on
the blocked list, no picture is taken and nothing is sent; Oyan just says why.

This check reads only the NAMES of the apps that own windows. It does not
look at what is inside them.

The list is yours to edit:
    python -m oyan --blocked             show the list
    python -m oyan --block "App Name"    add an app
    python -m oyan --unblock "App Name"  remove an app

A limit to know about: a bank's website inside Safari or Chrome is just a
browser window to macOS, so this cannot recognise it. Use Shift+Enter to send
only part of the screen when something private is open in a browser.
"""

from Quartz import (
    CGWindowListCopyWindowInfo,
    kCGNullWindowID,
    kCGWindowListExcludeDesktopElements,
    kCGWindowListOptionOnScreenOnly,
)

from oyan import settings

# Used until you change the list yourself.
DEFAULT_BLOCKED = [
    "1Password",
    "Bitwarden",
    "Dashlane",
    "Enpass",
    "KeePassXC",
    "Keychain Access",
    "LastPass",
    "NordPass",
    "Passwords",
    "Proton Pass",
]


def get_list():
    saved = settings.load().get("blocked_apps")
    return list(DEFAULT_BLOCKED) if saved is None else saved


def _save_list(names):
    all_settings = settings.load()
    all_settings["blocked_apps"] = sorted(set(names), key=str.lower)
    settings.save(all_settings)


def add(name):
    _save_list(get_list() + [name])


def remove(name):
    """Take an app off the list. Returns False if it was not on it."""
    current = get_list()
    kept = [item for item in current if item.lower() != name.lower()]
    _save_list(kept)
    return len(kept) != len(current)


def apps_on_screen():
    """Names of the apps that have an ordinary window on screen right now."""
    windows = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
        kCGNullWindowID,
    )
    names = set()
    for window in windows or []:
        # Layer 0 is where normal app windows live (menus, the Dock and
        # overlays like Oyan's own are on other layers).
        if window.get("kCGWindowLayer") == 0 and window.get("kCGWindowOwnerName"):
            names.add(str(window["kCGWindowOwnerName"]))
    return names


def blocked_app_on_screen():
    """The name of a blocked app that is visible now, or None."""
    blocked = [name.lower() for name in get_list()]
    for app_name in sorted(apps_on_screen()):
        lowered = app_name.lower()
        # "in" also matches longer names, e.g. "1Password 7" for "1Password".
        if any(name in lowered for name in blocked):
            return app_name
    return None
