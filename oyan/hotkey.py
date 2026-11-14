"""Oyan's keys: they work in any app.

    Option + A        Ask   (open the ask box)
    Option + S        Speak (start listening; press again to stop)
    Option + D        Draw  (hold both keys and drag the mouse)
    Esc               wipe the board / stop

A, S and D sit next to each other under the left hand, with Option under
the thumb.

How it works
------------
We put an "event tap" on the keyboard. An event tap is a checkpoint that
macOS runs every key press through before any app receives it. Our function
`_on_key` looks at each key and returns one of two things:

* the event itself  -> "carry on, this key is not for me";
* None              -> "this key was mine": no app ever sees it.

That second answer is why Option + A opens Oyan WITHOUT also typing "å" into
the app you are working in. (An earlier version could only listen to keys,
not take them, which is why it needed awkward three-key combinations.)

Because every key on the Mac passes through `_on_key`, it must be quick. It
only decides "mine or not" and asks Qt to run the real work a moment later
(QTimer.singleShot(0, ...)), so typing never has to wait for Oyan.

macOS allows an event tap only after you grant "Accessibility" permission in
System Settings to the app that starts Oyan (Terminal or VS Code).

We use PyObjC here, a bridge that lets Python call macOS's own functions.
"""

from AppKit import NSEvent, NSEventMaskLeftMouseDown
from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
from PyQt6.QtCore import QTimer
from Quartz import (
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetMain,
    CGEventGetFlags,
    CGEventGetIntegerValueField,
    CGEventMaskBit,
    CGEventTapCreate,
    CGEventTapEnable,
    kCFRunLoopCommonModes,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskCommand,
    kCGEventFlagMaskControl,
    kCGEventFlagMaskShift,
    kCGEventFlagsChanged,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGEventTapDisabledByTimeout,
    kCGEventTapDisabledByUserInput,
    kCGEventTapOptionDefault,
    kCGHeadInsertEventTap,
    kCGKeyboardEventAutorepeat,
    kCGKeyboardEventKeycode,
    kCGSessionEventTap,
)

# macOS's numbers for the keys we use.
KEY_A = 0
KEY_S = 1
KEY_D = 2
KEY_ESCAPE = 53

HOTKEY_NAME = "Option + A"
VOICE_HOTKEY_NAME = "Option + S"
PEN_HOTKEY_NAME = "Option + D"

# macOS calls the Option key "Alternate". When comparing, look only at these
# four modifier keys (and ignore Caps Lock and the like).
OPTION = kCGEventFlagMaskAlternate
ALL_MODIFIERS = kCGEventFlagMaskControl | kCGEventFlagMaskAlternate | kCGEventFlagMaskCommand | kCGEventFlagMaskShift


def has_permission(ask=False):
    """Is Oyan allowed to see key presses in other apps?

    With ask=True, macOS shows its own window that offers to open
    System Settings, if permission has not been granted yet.
    """
    return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: ask}))


class GlobalHotkey:
    """Watches the keyboard and calls the right function for each of Oyan's keys.

    on_pressed()   - Option + A
    on_voice()     - Option + S
    on_pen(down)   - Option + D went down (True) or was let go (False)
    on_escape()    - Esc (the other app still receives its Esc as usual)
    on_click()     - the mouse button went down in another app; used by the
                     step-by-step mode to notice that you did a step
    """

    def __init__(self, on_pressed, on_escape, on_click=None, on_voice=None, on_pen=None):
        self.on_pressed = on_pressed
        self.on_escape = on_escape
        self.on_click = on_click
        self.on_voice = on_voice
        self.on_pen = on_pen
        self.pen_is_down = False
        self.tap = None
        self._click_monitor = None

    def start(self):
        """Install the keyboard checkpoint. Returns False if macOS refused."""
        events = (
            CGEventMaskBit(kCGEventKeyDown)
            | CGEventMaskBit(kCGEventKeyUp)
            | CGEventMaskBit(kCGEventFlagsChanged)   # a modifier key pressed or released
        )
        self.tap = CGEventTapCreate(
            kCGSessionEventTap,         # all keys of this login session
            kCGHeadInsertEventTap,      # look at them first, before the apps
            kCGEventTapOptionDefault,   # "default" = we may also take keys away
            events,
            self._on_key,
            None,
        )
        if self.tap is None:
            return False   # no Accessibility permission
        source = CFMachPortCreateRunLoopSource(None, self.tap, 0)
        CFRunLoopAddSource(CFRunLoopGetMain(), source, kCFRunLoopCommonModes)
        CGEventTapEnable(self.tap, True)

        if self.on_click is not None:
            # Mouse clicks we only need to hear about, so a plain listener is enough.
            self._click_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                NSEventMaskLeftMouseDown, lambda event: self.on_click()
            )
        return True

    def stop(self):
        if self.tap is not None:
            tap, self.tap = self.tap, None   # forget it first, then switch it off
            CGEventTapEnable(tap, False)
        if self._click_monitor is not None:
            NSEvent.removeMonitor_(self._click_monitor)
            self._click_monitor = None

    @staticmethod
    def _later(function, *arguments):
        """Run a function as soon as Qt is free, not inside the key checkpoint."""
        if function is not None:
            QTimer.singleShot(0, lambda: function(*arguments))

    def _set_pen(self, down):
        if down != self.pen_is_down:
            self.pen_is_down = down
            self._later(self.on_pen, down)

    def _on_key(self, proxy, event_type, event, _):
        """Called by macOS for every key event. Return None to take the key."""
        try:
            # Two special messages tell us the tap was switched off. If macOS
            # did it because we once answered too slowly, switch it back on.
            # If we did it ourselves (stop), leave it off.
            if event_type in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
                if event_type == kCGEventTapDisabledByTimeout and self.tap is not None:
                    CGEventTapEnable(self.tap, True)
                return event

            held = CGEventGetFlags(event) & ALL_MODIFIERS
            only_option = held == OPTION

            if event_type == kCGEventFlagsChanged:
                # Letting go of Option while drawing ends the drawing too.
                if self.pen_is_down and not only_option:
                    self._set_pen(False)
                return event

            key = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
            repeat = bool(CGEventGetIntegerValueField(event, kCGKeyboardEventAutorepeat))

            if event_type == kCGEventKeyUp:
                if key == KEY_D and self.pen_is_down:
                    self._set_pen(False)
                    return None
                if only_option and key in (KEY_A, KEY_S, KEY_D):
                    return None        # the key-up belonging to a key we took
                return event

            # From here on: a key went down.
            if key == KEY_ESCAPE and held == 0:
                self._later(self.on_escape)
                return event           # Esc is shared: the app gets it as well
            if only_option and key == KEY_A:
                if not repeat:         # holding the key down must not fire again and again
                    self._later(self.on_pressed)
                return None
            if only_option and key == KEY_S:
                if not repeat:
                    self._later(self.on_voice)
                return None
            if only_option and key == KEY_D:
                self._set_pen(True)
                return None
            return event
        except Exception:
            # Whatever goes wrong here, never block the keyboard.
            return event
