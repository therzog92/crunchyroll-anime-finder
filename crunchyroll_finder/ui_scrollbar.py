"""Custom orange-on-black scrollbars (Windows native scrollbars ignore theme colors)."""

from __future__ import annotations

import tkinter as tk

CR_BLACK = "#000000"
CR_ORANGE = "#F47521"
CR_ORANGE_HOVER = "#d96518"

MIN_THUMB = 24
BAR_SIZE = 12


class ModernScrollbar(tk.Canvas):
    def __init__(self, parent, orient: str = tk.VERTICAL, command=None, **kwargs):
        self._orient = orient
        self._command = command
        self._first = 0.0
        self._last = 1.0
        self._dragging = False
        self._drag_offset = 0.0
        self._hover = False
        self._thumb = (0.0, 0.0, 0.0, 0.0)

        if orient == tk.VERTICAL:
            super().__init__(
                parent, width=BAR_SIZE, highlightthickness=0,
                bg=CR_BLACK, bd=0, relief=tk.FLAT, cursor="hand2", **kwargs,
            )
        else:
            super().__init__(
                parent, height=BAR_SIZE, highlightthickness=0,
                bg=CR_BLACK, bd=0, relief=tk.FLAT, cursor="hand2", **kwargs,
            )

        self.bind("<Configure>", self._on_configure)
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_motion)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))

    def configure(self, cnf=None, **kw):
        if cnf:
            kw = {**cnf, **kw}
        if "command" in kw:
            self._command = kw.pop("command")
        if kw:
            super().configure(**kw)

    config = configure

    def set(self, first, last=None) -> None:
        if last is None:
            if not isinstance(first, str):
                return
            parts = first.split()
            if len(parts) != 2:
                return
            first, last = parts
        new_first = float(first)
        new_last = float(last)
        if abs(new_first - self._first) < 1e-6 and abs(new_last - self._last) < 1e-6:
            return
        self._first = new_first
        self._last = new_last
        self._draw()

    def _set_hover(self, hover: bool) -> None:
        self._hover = hover
        self._draw()

    def _on_configure(self, _event=None) -> None:
        self._draw()

    def _needs_thumb(self) -> bool:
        return self._last - self._first < 0.999

    def _track(self) -> tuple[float, float, float, float]:
        pad = 2
        return pad, pad, max(pad + 1, self.winfo_width() - pad), max(pad + 1, self.winfo_height() - pad)

    def _draw(self) -> None:
        self.delete("all")
        if not self._needs_thumb():
            return

        x0, y0, x1, y1 = self._track()
        track_w = x1 - x0
        track_h = y1 - y0
        if track_w <= 0 or track_h <= 0:
            return

        if self._orient == tk.VERTICAL:
            thumb_h = max(MIN_THUMB, track_h * (self._last - self._first))
            thumb_y0 = y0 + track_h * self._first
            thumb_y1 = min(thumb_y0 + thumb_h, y1)
            tx0, ty0, tx1, ty1 = x0 + 1, thumb_y0, x1 - 1, thumb_y1
        else:
            thumb_w = max(MIN_THUMB, track_w * (self._last - self._first))
            thumb_x0 = x0 + track_w * self._first
            thumb_x1 = min(thumb_x0 + thumb_w, x1)
            tx0, ty0, tx1, ty1 = thumb_x0, y0 + 1, thumb_x1, y1 - 1

        self._thumb = (tx0, ty0, tx1, ty1)
        fill = CR_ORANGE_HOVER if self._hover or self._dragging else CR_ORANGE
        self.create_rectangle(tx0, ty0, tx1, ty1, fill=fill, outline=fill)

    def _in_thumb(self, x: float, y: float) -> bool:
        tx0, ty0, tx1, ty1 = self._thumb
        return tx0 <= x <= tx1 and ty0 <= y <= ty1

    def _on_press(self, event) -> None:
        if not self._needs_thumb():
            return
        if self._in_thumb(event.x, event.y):
            self._dragging = True
            self._drag_offset = (event.y if self._orient == tk.VERTICAL else event.x) - (
                self._thumb[1] if self._orient == tk.VERTICAL else self._thumb[0]
            )
        else:
            self._page_click(event.x, event.y)
        self._draw()

    def _on_motion(self, event) -> None:
        if not self._dragging or not self._command:
            return
        x0, y0, x1, y1 = self._track()
        if self._orient == tk.VERTICAL:
            track_h = y1 - y0
            thumb_h = self._thumb[3] - self._thumb[1]
            span = track_h - thumb_h
            if span <= 0:
                return
            pos = max(0.0, min(event.y - y0 - self._drag_offset, span))
            self._command("moveto", pos / span)
        else:
            track_w = x1 - x0
            thumb_w = self._thumb[2] - self._thumb[0]
            span = track_w - thumb_w
            if span <= 0:
                return
            pos = max(0.0, min(event.x - x0 - self._drag_offset, span))
            self._command("moveto", pos / span)

    def _on_release(self, _event) -> None:
        self._dragging = False
        self._draw()

    def _page_click(self, x: float, y: float) -> None:
        if not self._command:
            return
        if self._orient == tk.VERTICAL:
            before = y < self._thumb[1]
        else:
            before = x < self._thumb[0]
        self._command("scroll", -1 if before else 1, "pages")


def vscrollbar(parent, command=None) -> ModernScrollbar:
    return ModernScrollbar(parent, orient=tk.VERTICAL, command=command)


def hscrollbar(parent, command=None) -> ModernScrollbar:
    return ModernScrollbar(parent, orient=tk.HORIZONTAL, command=command)
