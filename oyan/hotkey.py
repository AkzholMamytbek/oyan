"""The global hotkey: a key combination that works in any app.

How it works
------------
macOS lets a program ask to be told about every key press on the Mac, even
when another app is in front. That is powerful, so macOS only allows it after
you grant "Accessibility" permission in System Settings. The permission is
given to the app that started Oyan (Terminal or VS Code), not to Oyan itself.

We register two "monitors":
* a global one, which hears key presses meant for OTHER apps;
* a local one, which hears key presses meant for Oyan (while its text box
  is open).

We use PyObjC here, a bridge that lets Python call macOS's own functions.
"""

from AppKit import (
    NSEvent,
    NSEventMaskKeyDown,
    NSEventModifierFlagCommand,
    NSEventModifierFlagControl,
    NSEventModifierFlagOption,
    NSEventModifierFlagShift,
)
from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt

# --- The hotkey: Control + Option + Space ---------------------------------

HOTKEY_KEY_CODE = 49  # macOS's number for the Space bar
HOTKEY_MODIFIERS = NSEventModifierFlagControl | NSEventModifierFlagOption
HOTKEY_NAME = "Control + Option + Space"
ESCAPE_KEY_CODE = 53  # macOS's number for the Esc key

# When comparing, look only at these four modifier keys (ignore Caps Lock etc.).
ALL_MODIFIERS = (
    NSEventModifierFlagControl
    | NSEventModifierFlagOption
    | NSEventModifierFlagCommand
    | NSEventModifierFlagShift
)


def has_permission(ask=False):
    """Is Oyan allowed to hear key presses in other apps?

    With ask=True, macOS shows its own window that offers to open
    System Settings, if permission has not been granted yet.
    """
    return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: ask}))


class GlobalHotkey:
    """Calls `on_pressed()` every time the hotkey is pressed, in any app.

    Also calls `on_escape()` when Esc is pressed while another app is in
    front. We only listen: the other app still receives its Esc as usual.
    """

    def __init__(self, on_pressed, on_escape):
        self.on_pressed = on_pressed
        self.on_escape = on_escape
        self._monitors = []

    def start(self):
        self._monitors = [
            NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                NSEventMaskKeyDown, self._on_global_key
            ),
            NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                NSEventMaskKeyDown, self._on_local_key
            ),
        ]

    def stop(self):
        for monitor in self._monitors:
            if monitor is not None:
                NSEvent.removeMonitor_(monitor)
        self._monitors = []

    def _is_hotkey(self, event):
        modifiers = event.modifierFlags() & ALL_MODIFIERS
        return event.keyCode() == HOTKEY_KEY_CODE and modifiers == HOTKEY_MODIFIERS

    def _on_global_key(self, event):
        if self._is_hotkey(event) and not event.isARepeat():
            self.on_pressed()
        elif event.keyCode() == ESCAPE_KEY_CODE:
            self.on_escape()

    def _on_local_key(self, event):
        # A local monitor must hand the event back so the app still receives
        # it. Returning None instead "swallows" the key press, which is what
        # we want for the hotkey itself (no stray space typed in the box).
        if self._is_hotkey(event):
            if not event.isARepeat():
                self.on_pressed()
            return None
        return event
