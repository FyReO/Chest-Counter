import sys
import time

import settings as cfg

KEY = "#010203"
BG, BORDER = "#0e1014", "#262b38"
GOLD, TEXT, MUTED, GREEN = "#ffc83d", "#eceef4", "#9aa3b8", "#4ade80"
FONT = "Segoe UI"

# animation timeline
T_IN = 0.15
T_RISE = 0.27
T_POP = 0.30
FRAME_MS = 16


def mix(c1, c2, t):
    """Blend two #rrggbb colors (t=0 -> c1, t=1 -> c2)."""
    t = min(1.0, max(0.0, t))
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def ease_out_back(t):
    c1 = 1.70158
    return 1 + (c1 + 1) * (t - 1) ** 3 + c1 * (t - 1) ** 2


def ease_out_cubic(t):
    return 1 - (1 - t) ** 3


def ease_in_out(t):
    return t * t * (3 - 2 * t)


def pop_scale(p):
    """Number size during the pop: 1.0 -> 1.3 -> 1.0."""
    if p < 0.4:
        return 1.0 + 0.3 * ease_out_cubic(p / 0.4)
    return 1.3 - 0.3 * ease_in_out((p - 0.4) / 0.6)


class Overlay:
    def __init__(self, tk, root, on_moved):
        self.tk, self.root, self.on_moved = tk, root, on_moved
        self.win = self.cv = None
        self.visible = False
        self.unlocked = False
        self.monitors = []
        self._mon = None
        self._ctx = None
        self._last_key = None
        self._last_top = 0.0
        self._drag = None
        self._size = (0, 0)
        self._shown = None
        self._anim = None
        self._job = None
        self._geo = {}
        self._num = self._plus = self._plus_sh = self._pill = None

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
            style |= 0x00080000 | 0x00000080 | 0x08000000      
            if self.unlocked:
                style &= ~0x00000020                           
            else:
                style |= 0x00000020                            
            user32.SetWindowLongW(hwnd, -20, style)
        except Exception:
            pass

    def hide(self):
        self._stop_anim()
        if self.win is not None and self.visible:
            self.win.withdraw()
            self.visible = False
            self._last_key = None
        self._shown = None

    def destroy(self):
        self._stop_anim()
        try:
            if self.win is not None:
                self.win.destroy()
        except Exception:
            pass
        self.win = None

    # ---- public entry point ------------------------------------------------
    def update(self, ov, total, session, per_hour, mon, unlocked, monitors):
        """Redraw if anything changed, and start the +1 animation when the total went up."""
        if not ov["enabled"]:
            self.hide()
            return
        self.monitors, self._mon = monitors, mon
        self._ctx = (ov, session, per_hour, mon)
        changed_lock = unlocked != self.unlocked
        self.unlocked = unlocked
        now = time.monotonic()
        if self.win is None:
            self._create()

        start_anim = False
        target = self._anim["to"] if self._anim else self._shown
        if self._shown is None or not self.visible:
            self._stop_anim()
            self._shown = total                                  
        elif total > target:                                     
            if ov.get("animate", True):
                if self._anim:                                   
                    self._finish_anim()                          
                start_anim = True
            else:
                self._stop_anim()
                self._shown = total
        elif total < target:                                     
            self._stop_anim()
            self._shown = total

        key = self._key(ov, self._shown, session, per_hour, mon)
        if key == self._last_key and self.visible:
            if now - self._last_top > 3.0:                       
                self._last_top = now
                try:
                    self.win.attributes("-topmost", True)
                except Exception:
                    pass
        else:
            self._last_key = key
            self._draw(ov, self._shown, session, per_hour, mon)
            was_visible = self.visible
            if not was_visible:
                self.win.deiconify()
                self.visible = True
            self.win.attributes("-alpha", ov["opacity"] / 100.0)
            self.win.attributes("-topmost", True)
            if changed_lock or not was_visible:                  
                self._apply_styles()
            self._last_top = now
        if start_anim:
            self._start_anim(total)

    def _key(self, ov, shown, session, per_hour, mon):
        return (shown, session if ov["show_session"] else None,
                None if not ov["show_ph"] else (None if per_hour is None else round(per_hour)),
                ov["show_session"], ov["show_ph"], ov["size"], ov["opacity"], ov["anchor"],
                ov["dx"], ov["dy"], mon["left"], mon["top"], mon["width"], mon["height"], self.unlocked)

    # ---- drawing -----------------------------------------------------------
    def _draw(self, ov, total, session, per_hour, mon):
        from tkinter import font as tkfont
        osf = mon["height"] / 1080.0 * cfg.SIZES[ov["size"]]       
        px = lambda v: max(1, int(round(v * osf)))
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
        room = px(26)                   
        self._size = (w, h)
        cx = pad + icon_w + gap + nw / 2
        self._geo = {"cx": cx, "cy": cy, "h": h, "room": room, "num_px": px(22), "plus_px": px(16)}

        cv = self.cv
        cv.delete("all")
        cv.config(width=w, height=h + room)
        r = px(12)
        pts = [r, 1, w - r, 1, w - 1, 1, w - 1, r, w - 1, h - r, w - 1, h - 1, w - r, h - 1,
               r, h - 1, 1, h - 1, 1, h - r, 1, r, 1, 1]
        self._pill = cv.create_polygon(pts, smooth=True, fill=BG,
                                       outline=GOLD if self.unlocked else BORDER,
                                       width=2 if self.unlocked else 1)
        
        x0 = pad
        cv.create_rectangle(x0, cy - px(3), x0 + icon_w, cy + px(9), fill="#d99a1c", outline="#7a5200")
        cv.create_rectangle(x0, cy - px(10), x0 + icon_w, cy - px(3), fill=GOLD, outline="#7a5200")
        cv.create_rectangle(x0 + icon_w // 2 - px(3), cy - px(5), x0 + icon_w // 2 + px(3), cy + px(2),
                            fill="#fff3c4", outline="#7a5200")
        self._num = cv.create_text(cx, cy, text=number, fill=GOLD, font=(FONT, -px(22), "bold"),
                                   anchor="center")
        if sub:
            cv.create_text(pad, px(41), text=sub, fill=MUTED, font=(FONT, -px(11), "bold"), anchor="w")
        
        plus_font = (FONT, -px(16), "bold")
        self._plus_sh = cv.create_text(cx + 1, h + room // 2 + 1, text="+1", fill="#000000",
                                       font=plus_font, anchor="center", state="hidden")
        self._plus = cv.create_text(cx, h + room // 2, text="+1", fill=GREEN, font=plus_font,
                                    anchor="center", state="hidden")

        x, y = cfg.overlay_origin(ov["anchor"], ov["dx"], ov["dy"], mon, w, h)
        self.win.geometry(f"{w}x{h + room}+{x}+{y}")

    # ---- the +1 animation --------------------------------------------------
    def _start_anim(self, to_total):
        delta = to_total - self._shown
        self._anim = {"start": time.monotonic(), "to": to_total, "swapped": False,
                      "label": f"+{delta}"}
        self._frame()

    def _stop_anim(self):
        self._anim = None
        if self._job is not None and self.win is not None:
            try:
                self.win.after_cancel(self._job)
            except Exception:
                pass
        self._job = None

    def _finish_anim(self):
        """Jump straight to the end state (used when another chest arrives mid-animation)."""
        a, self._anim = self._anim, None
        if self._job is not None and self.win is not None:
            try:
                self.win.after_cancel(self._job)
            except Exception:
                pass
        self._job = None
        if a is not None and self._ctx is not None:
            self._shown = a["to"]
            ov, session, per_hour, mon = self._ctx
            self._last_key = self._key(ov, self._shown, session, per_hour, mon)
            self._draw(ov, self._shown, session, per_hour, mon)

    def _frame(self):
        self._job = None
        a = self._anim
        if a is None or self.win is None or self._ctx is None:
            return
        g, cv = self._geo, self.cv
        e = time.monotonic() - a["start"]
        font = lambda base, s: (FONT, -max(1, int(round(base * s))), "bold")
        y_start = g["h"] + g["room"] // 2
        try:
            if e < T_IN + T_RISE:
                if e < T_IN:                                   
                    s, y, col = 0.45 + 0.55 * ease_out_back(e / T_IN), y_start, GREEN
                else:                                          
                    q = ((e - T_IN) / T_RISE) ** 2             
                    s, y, col = 1.0 - 0.35 * q, y_start + (g["cy"] - y_start) * q, mix(GREEN, GOLD, q)
                inside = y < g["h"] - 4
                for item, dx in ((self._plus_sh, 1), (self._plus, 0)):
                    cv.coords(item, g["cx"] + dx, y + dx)
                    cv.itemconfig(item, text=a["label"], font=font(g["plus_px"], s),
                                  state="hidden" if (item == self._plus_sh and inside) else "normal")
                cv.itemconfig(self._plus, fill=col)
            else:
                if not a["swapped"]:                           
                    a["swapped"] = True
                    self._shown = a["to"]
                    ov, session, per_hour, mon = self._ctx
                    self._last_key = self._key(ov, self._shown, session, per_hour, mon)
                    self._draw(ov, self._shown, session, per_hour, mon)    
                    g = self._geo
                p = (e - T_IN - T_RISE) / T_POP
                if p >= 1.0:
                    cv.itemconfig(self._num, fill=GOLD, font=(FONT, -g["num_px"], "bold"))
                    cv.itemconfig(self._pill, outline=GOLD if self.unlocked else BORDER)
                    self._anim = None
                    return
                cv.itemconfig(self._num, font=font(g["num_px"], pop_scale(p)), fill=mix("#ffffff", GOLD, p))
                if not self.unlocked:
                    cv.itemconfig(self._pill, outline=mix(GOLD, BORDER, p))
            self._job = self.win.after(FRAME_MS, self._frame)
        except Exception:
            self._anim = None

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
        self._last_key = None
        self.on_moved(anchor, dx, dy, idx)