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
    NSEventMaskFlagsChanged,
    NSEventMaskKeyDown,
    NSEventMaskLeftMouseDown,
    NSEventModifierFlagCommand,
    NSEventModifierFlagControl,
    NSEventModifierFlagOption,
    NSEventModifierFlagShift,
)
from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt

# --- The hotkey: Control + Option + O (O for Oyan) ------------------------
# It used to be Control + Option + Space, but macOS itself uses that one for
# "select the next keyboard layout". Oyan only listens to keys and cannot
# stop macOS from acting on them too, so every press also switched the
# typing language. Control + Option + O is not used by macOS.

HOTKEY_KEY_CODE = 31  # macOS's number for the O key
HOTKEY_MODIFIERS = NSEventModifierFlagControl | NSEventModifierFlagOption
HOTKEY_NAME = "Control + Option + O"
ESCAPE_KEY_CODE = 53  # macOS's number for the Esc key

# --- The voice hotkey: Control + Option + V (same modifier keys) ----------
VOICE_KEY_CODE = 9    # macOS's number for the V key
VOICE_HOTKEY_NAME = "Control + Option + V"

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

    def __init__(self, on_pressed, on_escape, on_click=None, on_voice=None, on_pen=None):
        # Called with True when Control + Shift (and nothing else) go down,
        # and with False when that stops being the case. Used for drawing.
        self.on_pen = on_pen
        self._pen_down = False
        self.on_pressed = on_pressed
        self.on_escape = on_escape
        self.on_voice = on_voice   # called when the voice hotkey is pressed
        # Called when the mouse button goes down in another app. Used by the
        # step-by-step mode to notice that you did a step. We learn only THAT
        # a click happened; the other app still receives it as usual.
        self.on_click = on_click
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
        if self.on_pen is not None:
            # "Flags changed" is what macOS calls pressing or releasing a
            # modifier key such as Shift or Control.
            self._monitors.append(
                NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                    NSEventMaskFlagsChanged, self._on_flags_changed
                )
            )
            # The same for when Oyan itself is the active app (after a click
            # on the drawing layer, for example): a global monitor does not
            # hear those, so we need a local one as well.
            self._monitors.append(
                NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                    NSEventMaskFlagsChanged, self._on_local_flags_changed
                )
            )
        if self.on_click is not None:
            self._monitors.append(
                NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                    NSEventMaskLeftMouseDown, lambda event: self.on_click()
                )
            )

    def stop(self):
        for monitor in self._monitors:
            if monitor is not None:
                NSEvent.removeMonitor_(monitor)
        self._monitors = []

    def _is_hotkey(self, event):
        modifiers = event.modifierFlags() & ALL_MODIFIERS
        return event.keyCode() == HOTKEY_KEY_CODE and modifiers == HOTKEY_MODIFIERS

    def _on_flags_changed(self, event):
        held = event.modifierFlags() & ALL_MODIFIERS
        pen_down = held == (NSEventModifierFlagControl | NSEventModifierFlagShift)
        if pen_down != self._pen_down:
            self._pen_down = pen_down
            self.on_pen(pen_down)

    def _on_local_flags_changed(self, event):
        self._on_flags_changed(event)
        return event   # hand it back so the app still receives it

    def _is_voice_hotkey(self, event):
        modifiers = event.modifierFlags() & ALL_MODIFIERS
        return (
            self.on_voice is not None
            and event.keyCode() == VOICE_KEY_CODE
            and modifiers == HOTKEY_MODIFIERS
        )

    def _on_global_key(self, event):
        if self._is_hotkey(event) and not event.isARepeat():
            self.on_pressed()
        elif self._is_voice_hotkey(event) and not event.isARepeat():
            self.on_voice()
        elif event.keyCode() == ESCAPE_KEY_CODE:
            self.on_escape()

    def _on_local_key(self, event):
        # A local monitor must hand the event back so the app still receives
        # it. Returning None instead "swallows" the key press, which is what
        # we want for the hotkey itself (no stray letter typed in the box).
        if self._is_hotkey(event):
            if not event.isARepeat():
                self.on_pressed()
            return None
        if self._is_voice_hotkey(event):
            if not event.isARepeat():
                self.on_voice()
            return None
        return event
