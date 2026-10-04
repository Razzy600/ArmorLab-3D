"""Widget set on top of DirectGUI in a dark engineering theme."""
from __future__ import annotations
import math
from direct.gui.DirectGui import DirectFrame, DirectButton, DirectSlider, DirectEntry
from direct.gui.OnscreenText import OnscreenText
from direct.gui import DirectGuiGlobals as DGG
from panda3d.core import TextNode

BG = (0.050, 0.060, 0.075, 0.92)
BG2 = (0.085, 0.100, 0.120, 1)
BG3 = (0.115, 0.135, 0.160, 1)
LINE = (0.17, 0.20, 0.24, 1)
FG = (0.88, 0.92, 0.95, 1)
DIM = (0.52, 0.60, 0.67, 1)
ACCENT = (1.0, 0.64, 0.18, 1)
TEAL = (0.22, 0.76, 0.78, 1)
RED = (1.0, 0.38, 0.32, 1)
GREEN = (0.45, 0.88, 0.52, 1)
BLUE = (0.50, 0.72, 1.0, 1)
CLEAR = (0, 0, 0, 0)


def shade(c, k):
    return (min(c[0] * k, 1), min(c[1] * k, 1), min(c[2] * k, 1), c[3])


class UI:
    def __init__(self, app, font, mono):
        self.app = app
        self.font = font
        self.mono = mono
        self.entries = []

    def label(self, parent, text, pos, scale=0.036, fg=FG, align=TextNode.ALeft, font=None, wrap=None, mayChange=True):
        return OnscreenText(text=text, parent=parent, pos=pos, scale=scale, fg=fg, align=align,
                            font=font or self.font, mayChange=mayChange, wordwrap=wrap)

    def group(self, parent):
        return DirectFrame(parent=parent, frameColor=CLEAR, relief=DGG.FLAT)

    def button(self, parent, text, pos, size, cmd, color=BG2, fg=FG, scale=0.034, align=TextNode.ACenter, extra=None):
        w, h = size
        kw = dict(parent=parent, pos=(pos[0], 0, pos[1]), frameSize=(0, w, -h / 2, h / 2), text=text,
                  text_scale=scale, text_fg=fg, text_font=self.font, relief=DGG.FLAT,
                  frameColor=(color, shade(color, 1.5), shade(color, 1.25), shade(color, 0.7)),
                  command=cmd, pressEffect=0)
        if align == TextNode.ACenter:
            kw.update(text_pos=(w / 2, -scale * 0.3), text_align=TextNode.ACenter)
        else:
            kw.update(text_pos=(0.018, -scale * 0.3), text_align=TextNode.ALeft)
        if extra:
            kw.update(extra)
        return DirectButton(**kw)

    def panel(self, parent, size, pos=(0, 0), color=BG):
        return DirectFrame(parent=parent, frameSize=size, pos=(pos[0], 0, pos[1]), frameColor=color, relief=DGG.FLAT)

    def hline(self, parent, x0, x1, y, color=LINE):
        return DirectFrame(parent=parent, frameSize=(x0, x1, -0.0015, 0.0015), pos=(0, 0, y), frameColor=color, relief=DGG.FLAT)

    def entry(self, parent, pos, w, text="", cmd=None, scale=0.032, chars=None):
        chars = chars or max(4, int(w / (scale * 0.55)))
        e = DirectEntry(parent=parent, pos=(pos[0], 0, pos[1]), scale=scale, width=chars, initialText=text,
                        numLines=1, focus=0, relief=DGG.FLAT, frameColor=(0.10, 0.125, 0.155, 1), text_fg=FG,
                        text_font=self.font, command=cmd, focusOutCommand=(lambda: cmd(e.get())) if cmd else None,
                        suppressKeys=1, text_pos=(0.3, 0), cursorKeys=1)
        e["frameSize"] = (0, w / scale, -0.45, 1.05)
        self.entries.append(e)
        return e

    def blur_all(self):
        for e in self.entries:
            try:
                if e["focus"]:
                    e["focus"] = 0
            except Exception:
                pass


class SliderRow:
    """Caption, number entry field and slider."""

    def __init__(self, ui, parent, pos, w, label, vmin, vmax, value, step, cb, fmt="{:.0f}", zero_text=None):
        self.ui = ui
        self.cb = cb
        self.fmt = fmt
        self.zero_text = zero_text
        self.w = w
        self.vmin, self.vmax = vmin, vmax
        x, y = pos
        self.lab = ui.label(parent, label, (x, y), 0.031, DIM)
        ew = 0.19
        self.ent = ui.entry(parent, (x + w - ew, y - 0.012), ew, "", self._enter, 0.031)
        self.sl = DirectSlider(parent=parent, pos=(x, 0, y - 0.045), frameSize=(0, w, -0.007, 0.007),
                               range=(vmin, vmax), value=value, pageSize=step,
                               command=self._chg, frameColor=LINE, relief=DGG.FLAT,
                               thumb_frameSize=(-0.011, 0.011, -0.024, 0.024), thumb_frameColor=ACCENT,
                               thumb_relief=DGG.FLAT, scrollSize=step)
        self._lock = False
        self.step = step
        self.set(value)

    def _text(self, v):
        if self.zero_text is not None and v <= self.vmin + 1e-9:
            return self.zero_text
        return self.fmt.format(v)

    def _chg(self):
        if self._lock:
            return
        v = self.get()
        self.ent.enterText(self._text(v))
        self.cb(v)

    def _enter(self, txt):
        try:
            v = float(str(txt).replace(",", ".").strip())
        except ValueError:
            self.ent.enterText(self._text(self.get()))
            return
        v = max(self.vmin, min(self.vmax, v))
        if self.step >= 1:
            v = round(v / self.step) * self.step
        self._lock = True
        self.sl["value"] = v
        self._lock = False
        self.ent.enterText(self._text(v))
        self.cb(v)

    def set(self, v):
        self._lock = True
        self.sl["value"] = v
        self._lock = False
        self.ent.enterText(self._text(v))

    def set_range(self, a, b):
        self.vmin, self.vmax = a, b
        self._lock = True
        self.sl["range"] = (a, b)
        self._lock = False

    def get(self):
        v = self.sl["value"]
        return round(v / self.step) * self.step if self.step >= 1 else v

    def show(self):
        for n in (self.lab, self.ent, self.sl):
            n.show()

    def hide(self):
        for n in (self.lab, self.ent, self.sl):
            n.hide()

    def set_label(self, s):
        self.lab.setText(s)


class Dropdown:
    """Drop-down list; long lists are laid out in several columns."""

    def __init__(self, ui, parent, pos, w, items, index, cb, h=0.062, scale=0.034, rows_h=0.056, per_col=16):
        self.ui = ui
        self.items = items
        self.index = index
        self.cb = cb
        self.w = w
        self.h = h
        self.rh = rows_h
        self.scale = scale
        self.per_col = per_col
        self.btn = ui.button(parent, "", pos, (w, h), self.open, color=BG2, scale=scale, align=TextNode.ALeft)
        self.arrow = ui.label(self.btn, "v", (w - 0.03, -scale * 0.3), scale, DIM, TextNode.ACenter)
        self.popup = None
        self.catcher = None
        self._text()

    def _text(self):
        if self.items:
            self.btn["text"] = self.items[min(self.index, len(self.items) - 1)][1]

    def set_index(self, i):
        self.index = i
        self._text()

    def set_items(self, items, index=0):
        self.items = items
        self.index = index
        self._text()

    def key_index(self, key):
        for i, (k, _) in enumerate(self.items):
            if k == key:
                return i
        return 0

    def open(self):
        if self.popup is not None:
            self.close()
            return
        a2d = self.ui.app.aspect2d
        p = self.btn.getPos(a2d)
        n = len(self.items)
        cols = max(1, math.ceil(n / self.per_col))
        rows = min(n, self.per_col)
        H = rows * self.rh
        Wd = cols * self.w
        top = p[2] - self.h / 2
        if top - H < -0.97:
            top = min(0.97, -0.97 + H)
        x = p[0]
        ar = self.ui.app.getAspectRatio()
        if x + Wd > ar - 0.02:
            x = ar - 0.02 - Wd
        self.catcher = DirectButton(parent=a2d, frameSize=(-4, 4, -2, 2), frameColor=(0, 0, 0, 0.35), relief=DGG.FLAT,
                                    command=self.close, pressEffect=0, sortOrder=60)
        self.popup = DirectFrame(parent=a2d, pos=(x, 0, top), frameSize=(0, Wd, -H, 0),
                                 frameColor=(0.06, 0.07, 0.09, 1), relief=DGG.FLAT, sortOrder=61)
        for i, (k, lab) in enumerate(self.items):
            col, row = divmod(i, self.per_col)
            c = (0.12, 0.17, 0.2, 1) if i == self.index else (0.06, 0.07, 0.09, 1)
            DirectButton(parent=self.popup, pos=(col * self.w, 0, -(row + 0.5) * self.rh),
                         frameSize=(0, self.w, -self.rh / 2, self.rh / 2),
                         text=lab, text_scale=self.scale, text_fg=FG if i != self.index else TEAL, text_font=self.ui.font,
                         text_align=TextNode.ALeft, text_pos=(0.018, -self.scale * 0.3), relief=DGG.FLAT,
                         frameColor=(c, shade(c, 2.2), shade(c, 1.8), c), command=self.pick, extraArgs=[i], pressEffect=0)

    def pick(self, i):
        self.close()
        self.index = i
        self._text()
        self.cb(self.items[i][0])

    def close(self):
        if self.popup is not None:
            self.popup.destroy(); self.popup = None
        if self.catcher is not None:
            self.catcher.destroy(); self.catcher = None
