"""Where is the screen busy, and where is it empty?

Oyan should not write its answer on top of the thing you are reading. To
avoid that, it needs to know which parts of the screen hold text or pictures
and which are blank. This file works that out from the screenshot Oyan has
just taken, on your Mac, with simple arithmetic (no AI involved).

The idea
--------
Blank areas are smooth: neighbouring pixels have nearly the same brightness.
Text and pictures are full of sudden changes from light to dark. So:

1. turn the screenshot into shades of grey;
2. for every pixel, measure how different it is from its neighbour to the
   right and the one below;
3. call a pixel "busy" if that difference is big.

`covered(rect)` then answers: of all the pixels under this rectangle, what
share is busy? Nearly 0 means an empty patch; text is typically 0.1 to 0.3.

To answer quickly for hundreds of candidate rectangles we use a classic
trick called an "integral image": a table where each cell holds the number
of busy pixels above and to the left of it. The count inside any rectangle
is then just four look-ups in that table.
"""

import numpy
from PyQt6.QtGui import QImage

BUSY_DIFFERENCE = 14   # brightness (0-255) jump between neighbours that counts as "busy"


class Clutter:
    def __init__(self, image_bytes, screenshot):
        """`image_bytes` is the picture file; `screenshot` says which part of
        the desktop it shows and how much it was shrunk (see capture.py)."""
        self.screenshot = screenshot
        image = QImage.fromData(image_bytes).convertToFormat(QImage.Format.Format_Grayscale8)
        width, height = image.width(), image.height()

        # Look at the picture's memory as a grid of numbers, one per pixel.
        memory = image.constBits()
        memory.setsize(image.sizeInBytes())
        grey = numpy.frombuffer(memory, dtype=numpy.uint8).reshape(height, image.bytesPerLine())[:, :width]
        grey = grey.astype(numpy.int16)

        # How different is each pixel from its right and lower neighbour?
        busy = numpy.zeros((height, width), dtype=bool)
        busy[:, :-1] |= numpy.abs(grey[:, 1:] - grey[:, :-1]) > BUSY_DIFFERENCE
        busy[:-1, :] |= numpy.abs(grey[1:, :] - grey[:-1, :]) > BUSY_DIFFERENCE

        # The integral image, with an extra row and column of zeros at the
        # top and left so the look-ups below need no special cases.
        self.table = numpy.zeros((height + 1, width + 1), dtype=numpy.int64)
        self.table[1:, 1:] = busy.cumsum(axis=0).cumsum(axis=1)
        self.width, self.height = width, height

    def covered(self, rect):
        """Share (0 to 1) of busy pixels under `rect`, a rectangle in global
        screen points. Parts outside the screenshot count as empty."""
        shot = self.screenshot
        # From screen points to picture pixels.
        left = int((rect.left() - shot.screen_rect.x()) * shot.scale)
        right = int((rect.right() - shot.screen_rect.x()) * shot.scale)
        top = int((rect.top() - shot.screen_rect.y()) * shot.scale)
        bottom = int((rect.bottom() - shot.screen_rect.y()) * shot.scale)
        left, right = max(left, 0), min(right, self.width)
        top, bottom = max(top, 0), min(bottom, self.height)
        if right <= left or bottom <= top:
            return 0.0
        table = self.table
        count = table[bottom, right] - table[top, right] - table[bottom, left] + table[top, left]
        return float(count) / ((right - left) * (bottom - top))
