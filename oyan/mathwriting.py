"""Writing maths properly: fractions, powers, roots.

Plain text can only say "x^2" or "(a+b)/c". On paper you would write the 2
small and raised, and the fraction as one thing above another with a bar
between. This file lets Oyan's notes do the same.

The AI writes maths in LaTeX, the notation used in science everywhere, for
example  x^2,  \\frac{a}{b},  \\sqrt{x},  \\log_2(x).  We support a small,
common part of it.

Two steps
---------
1. PARSING: read the LaTeX text from left to right and build a tree of
   "boxes". `\\frac{1}{x^2}` becomes a Frac box holding a Glyphs box "1" and
   a Script box (base "x", raised "2").

2. LAYOUT AND DRAWING: every box knows three sizes:
       width    how wide it is
       ascent   how far it reaches ABOVE the line of writing (the baseline)
       descent  how far it reaches BELOW it
   and how to draw itself at a position. A box made of other boxes works its
   sizes out from theirs: a fraction is as wide as the wider of its two
   parts, and so on.

Everything is drawn with the same handwriting font as the rest of the note.
"""

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QFont, QFontMetricsF, QPen

FONT_NAME = "Bradley Hand"
SCRIPT_SCALE = 0.68     # powers and indices are this much smaller than their base
FRACTION_SCALE = 0.82   # the two parts of a fraction are this much smaller
LINE_WIDTH = 1.5        # thickness of fraction bars and root signs

# LaTeX commands that stand for one symbol.
SYMBOLS = {
    "cdot": "·", "times": "×", "div": "÷", "pm": "±", "mp": "∓",
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "ne": "≠", "neq": "≠",
    "approx": "≈", "equiv": "≡", "infty": "∞", "to": "→", "rightarrow": "→",
    "Rightarrow": "⇒", "implies": "⇒", "leftarrow": "←", "degree": "°", "circ": "°",
    "sum": "∑", "int": "∫", "partial": "∂", "angle": "∠", "perp": "⊥", "parallel": "∥",
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "theta": "θ",
    "lambda": "λ", "mu": "μ", "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ",
    "phi": "φ", "omega": "ω", "Delta": "Δ", "Sigma": "Σ", "Omega": "Ω",
    "ldots": "…", "dots": "…", "cdots": "⋯", "%": "%", "$": "$", "{": "{", "}": "}", "_": "_", "&": "&",
}
# Commands written out as a word, like the names of functions.
WORDS = {"log", "ln", "lg", "sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan",
         "lim", "max", "min", "exp", "det", "gcd", "mod"}
# Commands that only mean "a bit of space".
SPACES = {",": " ", ";": " ", ":": " ", " ": " ", "!": "", "quad": "  ", "qquad": "    "}
# Commands we can simply skip: the thing after them is what matters.
IGNORED = {"left", "right", "displaystyle", "big", "Big", "bigg", "Bigg", "limits", "nolimits"}
# Symbols that look better with a little room either side.
SPACED = set("=+−<>≤≥≠≈±→⇒")


def font_of(size):
    return QFont(FONT_NAME, round(size))


# --- The boxes --------------------------------------------------------------


class Glyphs:
    """Plain characters in one size and colour: the simplest box."""

    def __init__(self, text, size, color=None):
        self.text = text
        self.size = size
        self.color = color          # None means "whatever ink the note uses"
        self.font = font_of(size)
        metrics = QFontMetricsF(self.font)
        self.width = metrics.horizontalAdvance(text)
        self.ascent = metrics.ascent()
        self.descent = metrics.descent()
        self.plain = text           # the box as ordinary text (for history and speech)

    def draw(self, painter, x, baseline):
        painter.save()
        painter.setFont(self.font)
        if self.color is not None:
            painter.setPen(self.color)
        painter.drawText(QPointF(x, baseline), self.text)
        painter.restore()


class Row:
    """Boxes side by side on one baseline."""

    def __init__(self, children, size):
        # Symbols such as "=" carry a little space on both sides. At the very
        # start or end of a formula that space is not wanted.
        if children and isinstance(children[0], Glyphs) and children[0].text.startswith(" "):
            children[0] = Glyphs(children[0].text.lstrip(" "), children[0].size, children[0].color)
        if children and isinstance(children[-1], Glyphs) and children[-1].text.endswith(" "):
            children[-1] = Glyphs(children[-1].text.rstrip(" "), children[-1].size, children[-1].color)
        self.children = children
        self.size = size
        self.width = sum(child.width for child in children)
        self.ascent = max((child.ascent for child in children), default=size * 0.8)
        self.descent = max((child.descent for child in children), default=size * 0.2)
        self.plain = "".join(child.plain for child in children)

    def draw(self, painter, x, baseline):
        for child in self.children:
            child.draw(painter, x, baseline)
            x += child.width


class Script:
    """A base with something small raised after it (a power), lowered after
    it (an index), or both: x², log₂, aₙ²."""

    def __init__(self, base, raised, lowered, size):
        self.base, self.raised, self.lowered = base, raised, lowered
        self.lift = base.ascent * 0.45     # how far the raised part is lifted
        self.drop = size * 0.22            # how far the lowered part is dropped
        extra = max(raised.width if raised else 0, lowered.width if lowered else 0)
        self.width = base.width + extra + 1
        self.ascent = max(base.ascent, self.lift + raised.ascent if raised else 0)
        self.descent = max(base.descent, self.drop + lowered.descent if lowered else 0)
        self.plain = base.plain
        if lowered:
            self.plain += "_" + lowered.plain
        if raised:
            self.plain += "^" + raised.plain

    def draw(self, painter, x, baseline):
        self.base.draw(painter, x, baseline)
        if self.raised:
            self.raised.draw(painter, x + self.base.width + 1, baseline - self.lift)
        if self.lowered:
            self.lowered.draw(painter, x + self.base.width + 1, baseline + self.drop)


class Frac:
    """One thing over another with a bar between."""

    def __init__(self, top, bottom, size):
        self.top, self.bottom = top, bottom
        self.gap = 2.5
        self.bar_height = size * 0.30      # the bar sits this far above the baseline
        self.width = max(top.width, bottom.width) + 8
        self.ascent = self.bar_height + self.gap + top.descent + top.ascent
        self.descent = max(self.gap + bottom.ascent + bottom.descent - self.bar_height, 0)
        self.plain = f"({top.plain})/({bottom.plain})"

    def draw(self, painter, x, baseline):
        bar_y = baseline - self.bar_height
        # Each part is centred above or below the bar.
        self.top.draw(painter, x + (self.width - self.top.width) / 2, bar_y - self.gap - self.top.descent)
        self.bottom.draw(painter, x + (self.width - self.bottom.width) / 2, bar_y + self.gap + self.bottom.ascent)
        painter.save()
        pen = QPen(painter.pen().color(), LINE_WIDTH, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(x + 1, bar_y), QPointF(x + self.width - 1, bar_y))
        painter.restore()


class Sqrt:
    """A root sign drawn round its contents."""

    def __init__(self, inside, size):
        self.inside = inside
        self.hook = size * 0.55            # room for the little tick on the left
        self.roof = 3                      # space between the contents and the line over them
        self.width = self.hook + inside.width + 3
        self.ascent = inside.ascent + self.roof + 1
        self.descent = inside.descent
        self.plain = f"sqrt({inside.plain})"

    def draw(self, painter, x, baseline):
        top = baseline - self.inside.ascent - self.roof
        bottom = baseline + self.inside.descent * 0.6
        painter.save()
        pen = QPen(painter.pen().color(), LINE_WIDTH, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        # The sign in four strokes: small tick up, down to the bottom, up to
        # the top, then the roof across.
        points = [
            QPointF(x, baseline - self.inside.ascent * 0.35),
            QPointF(x + self.hook * 0.3, baseline - self.inside.ascent * 0.45),
            QPointF(x + self.hook * 0.6, bottom),
            QPointF(x + self.hook, top),
            QPointF(x + self.width, top),
        ]
        for start, end in zip(points, points[1:]):
            painter.drawLine(start, end)
        painter.restore()
        self.inside.draw(painter, x + self.hook + 1, baseline)


# --- Parsing ----------------------------------------------------------------


class Parser:
    """Reads LaTeX text and builds the boxes. `self.at` is how far it has read."""

    def __init__(self, source):
        self.source = source
        self.at = 0

    def more(self):
        return self.at < len(self.source)

    def peek(self):
        return self.source[self.at] if self.more() else ""

    def row(self, size, until_brace=False):
        """Read boxes until the end, or until the "}" that closes a group."""
        boxes = []
        while self.more():
            char = self.peek()
            if char == "}":
                if until_brace:
                    self.at += 1
                    break
                self.at += 1        # a stray "}": ignore it
                continue
            if char in "^_":
                # A power or index belongs to the box just before it.
                self.at += 1
                small = self.group(size * SCRIPT_SCALE)
                base = boxes.pop() if boxes else Glyphs("", size)
                raised, lowered = (small, None) if char == "^" else (None, small)
                if isinstance(base, Script):      # x_1^2: add to the script already there
                    raised = raised or base.raised
                    lowered = lowered or base.lowered
                    base = base.base
                boxes.append(Script(base, raised, lowered, size))
                continue
            box = self.atom(size)
            if box is not None:
                boxes.append(box)
        return Row(boxes, size)

    def group(self, size):
        """What a command applies to: either {a whole group} or one thing."""
        while self.peek() == " ":
            self.at += 1
        if self.peek() == "{":
            self.at += 1
            return self.row(size, until_brace=True)
        box = self.atom(size)
        return box if box is not None else Glyphs("", size)

    def raw_group(self):
        """The literal text inside {...}, used by \\text{...}."""
        if self.peek() != "{":
            return ""
        end = self.source.find("}", self.at)
        end = len(self.source) if end == -1 else end
        text = self.source[self.at + 1:end]
        self.at = end + 1
        return text

    def atom(self, size):
        """Read one thing: a character, a command, or a group."""
        char = self.peek()
        self.at += 1
        if char == " ":
            return None                       # spaces mean nothing in maths
        if char == "{":
            return self.row(size, until_brace=True)
        if char != "\\":
            if char == "-":
                char = "−"                    # a proper minus sign, not a hyphen
            if char == "*":
                char = "·"
            if char in SPACED:
                return Glyphs(f" {char} ", size)
            return Glyphs(char, size)

        # A command: a backslash followed by letters, or by one other character.
        start = self.at
        while self.more() and self.peek().isalpha():
            self.at += 1
        name = self.source[start:self.at]
        if not name and self.more():
            name = self.peek()
            self.at += 1

        if name == "frac" or name == "dfrac" or name == "tfrac":
            top = self.group(size * FRACTION_SCALE)
            bottom = self.group(size * FRACTION_SCALE)
            return Frac(top, bottom, size)
        if name == "sqrt":
            return Sqrt(self.group(size), size)
        if name in ("text", "mathrm", "operatorname", "textbf", "mathbf", "mathit"):
            return Glyphs(self.raw_group(), size)
        if name in SYMBOLS:
            symbol = SYMBOLS[name]
            return Glyphs(f" {symbol} " if symbol in SPACED else symbol, size)
        if name in WORDS:
            return Glyphs(name, size)
        if name in SPACES:
            return Glyphs(SPACES[name], size)
        if name in IGNORED:
            return None
        return Glyphs(name, size)             # unknown command: show its name


def math_box(latex, size):
    """Turn a piece of LaTeX into a box that can be measured and drawn."""
    return Parser(latex).row(size)
