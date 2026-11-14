"""Oyan's keys: they work in any app.

    Option + A              Ask by typing (open the ask box)
    hold Control + Option   Talk and draw: Oyan listens for as long as you
                            hold both keys, and you can draw by dragging the
                            mouse. Let go and your question is sent.
    Esc                     wipe the board / stop

Control and Option sit next to each other at the bottom left of the keyboard.

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

Holding Control + Option is noticed differently: those two are "modifier"
keys, and macOS reports them with a "flags changed" event whenever one goes
down or comes up. We simply watch for the moment exactly those two are held.

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
KEY_ESCAPE = 53

HOTKEY_NAME = "Option + A"
HOLD_NAME = "Control + Option"

# macOS calls the Option key "Alternate". When comparing, look only at these
# four modifier keys (and ignore Caps Lock and the like).
OPTION = kCGEventFlagMaskAlternate
HOLD = kCGEventFlagMaskControl | kCGEventFlagMaskAlternate
ALL_MODIFIERS = kCGEventFlagMaskControl | kCGEventFlagMaskAlternate | kCGEventFlagMaskCommand | kCGEventFlagMaskShift


def has_permission(ask=False):
    """Is Oyan allowed to see key presses in other apps?

    With ask=True, macOS shows its own window that offers to open
    System Settings, if permission has not been granted yet.
    """
    return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: ask}))


class GlobalHotkey:
    """Watches the keyboard and calls the right function for each of Oyan's keys.

    on_pressed()        - Option + A
    on_hold(True)       - Control + Option have just been pressed together
    on_hold(False)      - ...and have been let go: "I have finished"
    on_hold_cancelled() - another key was pressed while they were held, so it
                          was a keyboard shortcut for some app, not for Oyan
    on_escape()         - Esc (the other app still receives its Esc as usual)
    on_click()          - the mouse button went down in another app; used by
                          the step-by-step mode to notice that you did a step
    """

    def __init__(self, on_pressed, on_escape, on_click=None, on_hold=None, on_hold_cancelled=None):
        self.on_pressed = on_pressed
        self.on_escape = on_escape
        self.on_click = on_click
        self.on_hold = on_hold
        self.on_hold_cancelled = on_hold_cancelled
        self.holding = False
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

            if event_type == kCGEventFlagsChanged:
                # A modifier key went down or came up. Are exactly Control and
                # Option held now?
                holding_now = held == HOLD
                if holding_now and not self.holding:
                    self.holding = True
                    self._later(self.on_hold, True)
                elif self.holding and not holding_now:
                    self.holding = False
                    self._later(self.on_hold, False)
                return event

            key = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
            repeat = bool(CGEventGetIntegerValueField(event, kCGKeyboardEventAutorepeat))

            if event_type == kCGEventKeyUp:
                if held == OPTION and key == KEY_A:
                    return None        # the key-up belonging to the key we took
                return event

            # From here on: a key went down.
            if self.holding:
                # Control + Option + another key is some app's shortcut (or
                # Esc, to give up). Either way this hold is not a question.
                self.holding = False
                self._later(self.on_hold_cancelled)
                return event
            if key == KEY_ESCAPE and held == 0:
                self._later(self.on_escape)
                return event           # Esc is shared: the app gets it as well
            if held == OPTION and key == KEY_A:
                if not repeat:         # holding the key down must not fire again and again
                    self._later(self.on_pressed)
                return None
            return event
        except Exception:
            # Whatever goes wrong here, never block the keyboard.
            return event
