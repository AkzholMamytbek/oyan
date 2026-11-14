"""Idle sketches: small doodles Oyan draws in a corner when you are not using it.

Privacy rule: these use NO AI and no internet. Every doodle is written out
below as plain lists of points. Nothing is captured and nothing is sent.

How a doodle is described
-------------------------
Each doodle is a list of strokes, and each stroke is a list of (x, y) points
inside a square that goes from 0 to 1 in both directions, with (0, 0) at the
top-left. `make_doodle` stretches that square to the size and place wanted on
screen and hands back a Mark (see marks.py), which already knows how to draw
itself stroke by stroke.

To add your own doodle: write a function that returns a list of strokes and
add it to DOODLES at the bottom.
"""

import math
import random

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QColor

from oyan.marks import Mark

PENCIL = QColor(255, 250, 235, 240)   # chalk white
SHADOW = QColor(40, 30, 20, 150)      # dark edge, so the chalk shows on light wallpapers too
PENCIL_WIDTH = 2.6


def arc(cx, cy, radius, start_degrees, end_degrees, steps=18, squash=1.0):
    """Points along part of a circle. 0 degrees is to the right, 90 is down.

    `squash` below 1 flattens the circle into an oval.
    """
    points = []
    for i in range(steps + 1):
        angle = math.radians(start_degrees + (end_degrees - start_degrees) * i / steps)
        points.append((cx + radius * math.cos(angle), cy + radius * squash * math.sin(angle)))
    return points


def smiley():
    return [
        arc(0.5, 0.5, 0.45, -100, 265, steps=30),   # the face
        arc(0.34, 0.38, 0.045, 0, 360, steps=10),   # left eye
        arc(0.66, 0.38, 0.045, 0, 360, steps=10),   # right eye
        arc(0.5, 0.52, 0.25, 25, 155),              # the smile
    ]


def star():
    # Five points, drawn in one go by jumping two corners each time.
    points = []
    for i in range(6):
        angle = math.radians(-90 + i * 144)
        points.append((0.5 + 0.48 * math.cos(angle), 0.52 + 0.48 * math.sin(angle)))
    return [points]


def house():
    return [
        [(0.15, 0.95), (0.15, 0.45), (0.85, 0.45), (0.85, 0.95), (0.15, 0.95)],   # walls
        [(0.05, 0.48), (0.5, 0.08), (0.95, 0.48)],                                # roof
        [(0.42, 0.95), (0.42, 0.65), (0.6, 0.65), (0.6, 0.95)],                   # door
        [(0.68, 0.2), (0.68, 0.06), (0.78, 0.06), (0.78, 0.3)],                   # chimney
    ]


def heart():
    points = []
    for i in range(41):
        t = math.radians(i * 9)
        # A well-known formula that traces a heart shape.
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        points.append((0.5 + x / 36, 0.47 - y / 36))
    return [points]


def sun():
    strokes = [arc(0.5, 0.5, 0.22, -90, 280, steps=24)]
    for i in range(8):   # eight rays
        angle = math.radians(i * 45)
        strokes.append([
            (0.5 + 0.3 * math.cos(angle), 0.5 + 0.3 * math.sin(angle)),
            (0.5 + 0.47 * math.cos(angle), 0.5 + 0.47 * math.sin(angle)),
        ])
    return strokes


def cat():
    return [
        arc(0.5, 0.58, 0.36, -60, 240, steps=28),                 # head (open at the top)
        [(0.32, 0.27), (0.24, 0.05), (0.42, 0.22)],               # left ear
        [(0.58, 0.22), (0.76, 0.05), (0.68, 0.27)],               # right ear
        arc(0.37, 0.52, 0.04, 0, 360, steps=10),                  # left eye
        arc(0.63, 0.52, 0.04, 0, 360, steps=10),                  # right eye
        [(0.46, 0.64), (0.54, 0.64), (0.5, 0.69), (0.46, 0.64)],  # nose
        [(0.3, 0.66), (0.05, 0.6)], [(0.3, 0.71), (0.05, 0.76)],  # whiskers, left
        [(0.7, 0.66), (0.95, 0.6)], [(0.7, 0.71), (0.95, 0.76)],  # whiskers, right
    ]


def fish():
    return [
        arc(0.42, 0.5, 0.36, 20, 340, steps=28, squash=0.6),      # body
        [(0.76, 0.43), (0.97, 0.25), (0.97, 0.75), (0.76, 0.57)], # tail
        arc(0.24, 0.44, 0.03, 0, 360, steps=8),                   # eye
        arc(0.4, 0.5, 0.14, -50, 50, steps=8),                    # gill
    ]


def spiral():
    points = []
    for i in range(70):
        angle = i * 0.32
        radius = 0.03 + i * 0.0064
        points.append((0.5 + radius * math.cos(angle), 0.5 + radius * math.sin(angle)))
    return [points]


def flower():
    strokes = []
    for i in range(6):   # six petals around the middle
        angle = math.radians(i * 60)
        strokes.append(arc(0.5 + 0.19 * math.cos(angle), 0.36 + 0.19 * math.sin(angle), 0.11, 0, 360, steps=12))
    strokes.append(arc(0.5, 0.36, 0.07, 0, 360, steps=12))        # the middle
    strokes.append([(0.5, 0.62), (0.47, 0.8), (0.5, 0.98)])        # the stem
    strokes.append([(0.48, 0.82), (0.3, 0.72), (0.36, 0.86), (0.48, 0.84)])   # a leaf
    return strokes


def rocket():
    return [
        [(0.5, 0.03), (0.66, 0.3), (0.66, 0.72), (0.34, 0.72), (0.34, 0.3), (0.5, 0.03)],   # body
        arc(0.5, 0.36, 0.07, 0, 360, steps=12),                                               # window
        [(0.34, 0.5), (0.17, 0.78), (0.34, 0.72)],                                            # left fin
        [(0.66, 0.5), (0.83, 0.78), (0.66, 0.72)],                                            # right fin
        [(0.4, 0.74), (0.44, 0.9), (0.5, 0.8), (0.56, 0.97), (0.6, 0.74)],                    # flame
    ]


DOODLES = [smiley, star, house, heart, sun, cat, fish, spiral, flower, rocket]


def make_doodle(top_left, size, previous=None):
    """Pick a doodle (not the same one as last time) and place it on screen.

    Returns (mark, name). `top_left` is a QPointF, `size` is in points.
    """
    choices = [doodle for doodle in DOODLES if doodle.__name__ != previous]
    doodle = random.choice(choices)
    strokes = [
        [QPointF(top_left.x() + x * size, top_left.y() + y * size) for x, y in stroke]
        for stroke in doodle()
    ]
    return Mark(strokes, color=PENCIL, width=PENCIL_WIDTH, outline=SHADOW), doodle.__name__
