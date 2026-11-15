"""Frosted glass: the blurred, see-through material of macOS panels.

Qt cannot blur what is behind a window, but macOS can: it has a ready-made
view for exactly this, called NSVisualEffectView. It is what the menu bar,
Spotlight and the Control Centre are made of. It blurs whatever is behind
the window, tints it, and follows light and dark mode by itself.

A Glass object is one such panel placed INSIDE one of Oyan's windows,
underneath everything Qt draws. So the order, from back to front, is:

    your screen  ->  the glass (blurred screen)  ->  Oyan's writing

Qt paints the writing, the shadow and the edge; macOS paints the glass.

Positions given to a Glass are measured inside the window, from its top-left
corner, in points (the same as Qt uses).
"""

import objc
from AppKit import (
    NSData,
    NSImage,
    NSMakeRect,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectMaterialPopover,
    NSVisualEffectStateActive,
    NSVisualEffectView,
    NSWindowBelow,
)
from PyQt6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PyQt6.QtGui import QImage, QPainter, QPen


class Glass:
    def __init__(self, widget, radius):
        """Add a (so far invisible) glass panel to the window of `widget`."""
        qt_view = objc.objc_object(c_void_p=int(widget.winId()))   # where Qt draws
        self.parent = qt_view.superview()                           # the window's frame
        self.view = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 1))
        self.view.setMaterial_(NSVisualEffectMaterialPopover)
        self.view.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)   # blur what is BEHIND the window
        self.view.setState_(NSVisualEffectStateActive)   # stay glassy when Oyan is not the active app
        # Round corners, with Apple's "continuous" curve (smoother than a
        # plain quarter circle).
        self.view.setWantsLayer_(True)
        self.view.layer().setCornerRadius_(radius)
        self.view.layer().setCornerCurve_("continuous")
        self.view.layer().setMasksToBounds_(True)
        self.view.setAlphaValue_(0.0)
        # Put it under the view Qt draws into, so the writing is on top.
        self.parent.addSubview_positioned_relativeTo_(self.view, NSWindowBelow, qt_view)
        self._last = None   # what place() was last asked for, to skip repeats

    def place(self, rect, opacity=1.0, holes=(), hole_width=0):
        """Move, resize and fade the panel.

        rect       - where the panel is, inside the window (QRectF)
        opacity    - 0 = invisible, 1 = fully there
        holes      - lines rubbed out of the glass, [(from point, to point), ...]
        hole_width - how wide those lines are
        """
        rect = QRectF(rect)
        asked = (rect.x(), rect.y(), rect.width(), rect.height(), round(opacity, 3), len(holes))
        if asked == self._last:
            return   # nothing changed since last time
        self._last = asked

        # macOS measures from the BOTTOM of the window, Qt from the top.
        window_height = self.parent.bounds().size.height
        self.view.setFrame_(NSMakeRect(rect.x(), window_height - rect.bottom(), rect.width(), rect.height()))
        self.view.setAlphaValue_(opacity)
        self.view.setMaskImage_(self._mask(rect, holes, hole_width) if holes else None)

    def _mask(self, rect, holes, hole_width):
        """A picture that says where the glass exists: solid everywhere,
        except along the rubbed-out lines. macOS shows the glass only where
        this picture is solid."""
        scale = 2   # draw at Retina sharpness
        image = QImage(max(int(rect.width() * scale), 1), max(int(rect.height() * scale), 1),
                       QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.black)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(scale, scale)
        painter.translate(-rect.topLeft())
        # "Clear" removes what is there instead of adding colour.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.setPen(QPen(Qt.GlobalColor.black, hole_width, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        for start, end in holes:
            painter.drawLine(QPointF(start), QPointF(end))
        painter.end()

        # Hand the picture from Qt to macOS, as a PNG file kept in memory.
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        data = bytes(buffer.data())
        picture = NSImage.alloc().initWithData_(NSData.dataWithBytes_length_(data, len(data)))
        picture.setSize_((rect.width(), rect.height()))
        return picture

    def remove(self):
        """Take the panel out of the window for good."""
        if self.view is not None:
            self.view.removeFromSuperview()
            self.view = None
