"""Taking the screenshot.

Privacy rule: this file is only ever called right after the owner sends a
question. Nothing here runs on a timer or in the background.

How it works
------------
We use `screencapture`, the same small program macOS itself uses when you
press Cmd+Shift+3. We ask it for exactly the rectangle of one monitor.

macOS only allows this after you grant "Screen Recording" permission to the
app that started Oyan (Terminal or VS Code). Without it, macOS quietly hands
back a picture of just your wallpaper.

Points and pixels
-----------------
A Retina screen that is 1728 points wide has 3456 real pixels. The raw
screenshot is therefore huge. We shrink it so the longest side is at most
MAX_IMAGE_SIDE pixels: it uploads faster, and the AI model would shrink it
anyway. We remember the shrink factor (`scale`) so that later, when the AI
says "look at pixel (400, 300) of the picture", we can turn that back into a
position on the real screen.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QPointF, QRect, Qt
from PyQt6.QtGui import QImage
from Quartz import CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess

# Oyan keeps its private files in a folder called ".oyan" in your home folder.
DATA_FOLDER = Path.home() / ".oyan"
SCREENSHOT_PATH = DATA_FOLDER / "last_screenshot.png"   # deleted as soon as it is sent

MAX_IMAGE_SIDE = 1280


@dataclass
class Screenshot:
    """A saved screenshot plus what we need to map it back onto the screen."""

    path: Path          # where the picture file is
    width: int          # picture size in pixels
    height: int
    screen_rect: QRect  # which part of the desktop it shows, in points
    scale: float        # picture pixels per screen point

    def to_screen(self, image_x, image_y):
        """Turn a position in the picture into a position on the desktop."""
        return QPointF(
            self.screen_rect.x() + image_x / self.scale,
            self.screen_rect.y() + image_y / self.scale,
        )


def has_permission():
    """Has the owner allowed screen recording? (Does not show any prompt.)"""
    return bool(CGPreflightScreenCaptureAccess())


def request_permission():
    """Ask macOS to show its 'allow screen recording' prompt."""
    CGRequestScreenCaptureAccess()


def delete_screenshot():
    """Remove the picture from disk; it has been handed to the AI call."""
    SCREENSHOT_PATH.unlink(missing_ok=True)


def capture_screen(screen):
    """Take a picture of one monitor and save it. Returns a Screenshot."""
    DATA_FOLDER.mkdir(exist_ok=True)
    DATA_FOLDER.chmod(0o700)   # 700 = only your Mac user account may open the folder
    rect = screen.geometry()   # this monitor's rectangle, in points

    # -x: no camera sound.  -R: capture only this rectangle.
    subprocess.run(
        [
            "/usr/sbin/screencapture",
            "-x",
            f"-R{rect.x()},{rect.y()},{rect.width()},{rect.height()}",
            str(SCREENSHOT_PATH),
        ],
        check=True,     # raise an error if screencapture fails
        timeout=10,
    )

    # Shrink the picture if it is bigger than we need.
    image = QImage(str(SCREENSHOT_PATH))
    if image.isNull():
        raise RuntimeError("The screenshot could not be read.")
    if max(image.width(), image.height()) > MAX_IMAGE_SIDE:
        image = image.scaled(
            MAX_IMAGE_SIDE,
            MAX_IMAGE_SIDE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        image.save(str(SCREENSHOT_PATH))

    return Screenshot(
        path=SCREENSHOT_PATH,
        width=image.width(),
        height=image.height(),
        screen_rect=rect,
        scale=image.width() / rect.width(),
    )
