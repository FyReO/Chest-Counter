"""
In-game overlay: a tiny always-on-top badge showing your chest total.

  * Transparent around the badge, and click-through (clicks go to the game).
  * Unlock it in Settings to drag it somewhere else; it remembers the spot.
  * Works with Fortnite in "Windowed Fullscreen". True exclusive fullscreen
    hides every other window, overlays included.
  * It has no text that looks like the XP popup, so it can't confuse the detector.
"""
import sys
import time

import settings as cfg

KEY = "#010203"                       # this exact color is made see-through
BG, BORDER = "#0e1014", "#262b38"
GOLD, TEXT, MUTED = "#ffc83d", "#eceef4", "#9aa3b8"
FONT = "Segoe UI"


class Overlay:
    def __init__(self, tk, root, on_moved):
        self.tk, self.root, self.on_moved = tk, root, on_moved
        self.win = self.cv = None
        self.visible = False
        self.unlocked = False
        self.monitors = []
        self._mon = None
        self._last_key = None
        self._last_total = None
        self._last_top = 0.0
        self._drag = None
        self._size = (0, 0)
        self._num = None

    # ---- window plumbing ---------------------------------------------------
    def _create(self):
        tk = self.tk
        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-transparentcolor", KEY)
        except Exception:
            pass
        self.win.configure(bg=KEY)
        self.cv = tk.Canvas(self.win, bg=KEY, highlightthickness=0, bd=0)
        self.cv.pack()
        self.cv.bind("<ButtonPress-1>", self._press)
        self.cv.bind("<B1-Motion>", self._motion)
        self.cv.bind("<ButtonRelease-1>", self._release)

    def _apply_styles(self):
        """Windows only: hide from the taskbar, never steal focus, and let clicks pass through."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            self.win.update_idletasks()
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.win.winfo_id()) or self.win.winfo_id()
            style = user32.GetWindowLongW(hwnd, -20)
            style |= 0x00080000 | 0x00000080 | 0x08000000      # layered, tool window, no-activate
            if self.unlocked:
                style &= ~0x00000020                           # draggable: catch clicks
            else:
                style |= 0x00000020                            # locked: clicks pass through
            user32.SetWindowLongW(hwnd, -20, style)
        except Exception:
            pass

    def hide(self):
        if self.win is not None and self.visible:
            self.win.withdraw()
            self.visible = False
            self._last_key = None

    def destroy(self):
        try:
            if self.win is not None:
                self.win.destroy()
        except Exception:
            pass
        self.win = None

    # ---- drawing -----------------------------------------------------------
    def update(self, ov, total, session, per_hour, mon, unlocked, monitors):
        """Redraw if anything changed. Cheap to call often."""
        if not ov["enabled"]:
            self.hide()
            return
        self.monitors, self._mon = monitors, mon
        changed_lock = unlocked != self.unlocked
        self.unlocked = unlocked
        key = (total, session if ov["show_session"] else None,
               None if not ov["show_ph"] else (None if per_hour is None else round(per_hour)),
               ov["show_session"], ov["show_ph"], ov["size"], ov["opacity"], ov["anchor"],
               ov["dx"], ov["dy"], mon["left"], mon["top"], mon["width"], mon["height"], unlocked)
        now = time.monotonic()
        if self.win is None:
            self._create()
        if key == self._last_key and self.visible:
            if now - self._last_top > 3.0:                     # keep it above the game
                self._last_top = now
                try:
                    self.win.attributes("-topmost", True)
                except Exception:
                    pass
            return
        self._last_key = key
        grew = self._last_total is not None and total > self._last_total
        self._last_total = total
        self._draw(ov, total, session, per_hour, mon)
        was_visible = self.visible
        if not was_visible:
            self.win.deiconify()
            self.visible = True
        self.win.attributes("-alpha", ov["opacity"] / 100.0)
        self.win.attributes("-topmost", True)
        if changed_lock or not was_visible:          # (re)apply click-through / no-focus styles
            self._apply_styles()
        self._last_top = now
        if grew:
            self._pulse()

    def _draw(self, ov, total, session, per_hour, mon):
        from tkinter import font as tkfont
        osf = mon["height"] / 1080.0 * cfg.SIZES[ov["size"]]       # scale with the screen
        px = lambda v: max(1, int(round(v * osf)))
        num_font = (FONT, -px(22), "bold")
        sub_font = (FONT, -px(11), "bold")
        number = f"{total:,}"
        parts = []
        if ov["show_session"]:
            parts.append(f"Session {session}")
        if ov["show_ph"]:
            parts.append("--/hr" if per_hour is None else f"{per_hour:.0f}/hr")
        sub = "  \u00b7  ".join(parts)

        pad, icon_w, gap = px(11), px(26), px(8)
        nw = tkfont.Font(family=FONT, size=-px(22), weight="bold").measure(number)
        w = pad + icon_w + gap + nw + pad
        h, cy = px(38), px(19)
        if sub:
            sw = tkfont.Font(family=FONT, size=-px(11), weight="bold").measure(sub)
            w, h = max(w, pad * 2 + sw), px(52)
        self._size = (w, h)

        cv = self.cv
        cv.delete("all")
        cv.config(width=w, height=h)
        r = px(12)
        pts = [r, 1, w - r, 1, w - 1, 1, w - 1, r, w - 1, h - r, w - 1, h - 1, w - r, h - 1,
               r, h - 1, 1, h - 1, 1, h - r, 1, r, 1, 1]
        cv.create_polygon(pts, smooth=True, fill=BG,
                          outline=GOLD if self.unlocked else BORDER, width=2 if self.unlocked else 1)
        # tiny treasure chest icon (drawn with shapes, so there is no text to misread)
        x0 = pad
        cv.create_rectangle(x0, cy - px(3), x0 + icon_w, cy + px(9), fill="#d99a1c", outline="#7a5200")
        cv.create_rectangle(x0, cy - px(10), x0 + icon_w, cy - px(3), fill=GOLD, outline="#7a5200")
        cv.create_rectangle(x0 + icon_w // 2 - px(3), cy - px(5), x0 + icon_w // 2 + px(3), cy + px(2),
                            fill="#fff3c4", outline="#7a5200")
        self._num = cv.create_text(pad + icon_w + gap, cy, text=number, fill=GOLD,
                                   font=num_font, anchor="w")
        if sub:
            cv.create_text(pad, px(41), text=sub, fill=MUTED, font=sub_font, anchor="w")

        x, y = cfg.overlay_origin(ov["anchor"], ov["dx"], ov["dy"], mon, w, h)
        self.win.geometry(f"{w}x{h}+{x}+{y}")

    def _pulse(self, step=0, steps=8):
        if self.win is None or step > steps:
            return
        from_c, to_c = (255, 255, 255), (255, 200, 61)
        t = step / steps
        col = "#%02x%02x%02x" % tuple(int(a + (b - a) * t) for a, b in zip(from_c, to_c))
        try:
            self.cv.itemconfig(self._num, fill=col)
            self.win.after(45, lambda: self._pulse(step + 1, steps))
        except Exception:
            pass

    # ---- dragging (only while unlocked) -----------------------------------
    def _press(self, e):
        if self.unlocked and self.win is not None:
            self._drag = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())

    def _motion(self, e):
        if self._drag:
            self.win.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _release(self, e):
        if not self._drag:
            return
        self._drag = None
        w, h = self._size
        x, y = self.win.winfo_x(), self.win.winfo_y()
        idx = cfg.monitor_index_at(x + w // 2, y + h // 2, self.monitors)
        mon = self.monitors[idx - 1] if idx else self._mon
        anchor, dx, dy = cfg.nearest_anchor(x, y, w, h, mon)
        self._last_key = None                       # force a redraw at the snapped position
        self.on_moved(anchor, dx, dy, idx)
