import settings as cfgmod

BG, CARD, BORDER = "#0e1014", "#171a21", "#262b38"
TEXT, MUTED, GOLD = "#eceef4", "#7d869a", "#ffc83d"
FONT = "Segoe UI"
AUTO_MONITOR = "Auto (follow the game)"


class SettingsWindow:
    def __init__(self, tk, root, cfg, monitor_count, on_change, set_unlocked, style_titlebar, on_close):
        self.tk, self.cfg = tk, cfg
        self.on_change, self.set_unlocked, self.on_close = on_change, set_unlocked, on_close
        self._debounce = None

        win = self.win = tk.Toplevel(root)
        win.title("Settings")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", self.close)
        try:
            win.geometry(f"+{root.winfo_x() + 28}+{root.winfo_y() + 28}")
        except Exception:
            pass
        style_titlebar(win)

        def section(title):
            tk.Label(win, text=title, bg=BG, fg=MUTED, font=(FONT, 8, "bold"),
                     anchor="w").pack(fill="x", padx=20, pady=(16, 4))

        def check(parent, text, var, command):
            return tk.Checkbutton(parent, text=text, variable=var, command=command, bg=BG, fg=TEXT,
                                  selectcolor=CARD, activebackground=BG, activeforeground=TEXT,
                                  font=(FONT, 10), anchor="w", highlightthickness=0, bd=0)

        def dropdown(parent, var, values, command):
            om = tk.OptionMenu(parent, var, *values, command=command)
            om.config(bg=CARD, fg=TEXT, activebackground=BORDER, activeforeground=TEXT,
                      highlightthickness=0, bd=0, relief="flat", font=(FONT, 9), width=22, anchor="w")
            try:
                om["menu"].config(bg=CARD, fg=TEXT, activebackground=GOLD, activeforeground="#000000",
                                  font=(FONT, 9), bd=0)
            except Exception:
                pass
            return om

        # ---- which stats show on the main window
        section("STATS ON THE MAIN WINDOW")
        grid = tk.Frame(win, bg=BG)
        grid.pack(fill="x", padx=16)
        self.stat_vars = {}
        for i, key in enumerate(["best"] + cfgmod.STAT_ORDER):
            v = tk.BooleanVar(value=cfg["stats"][key])
            self.stat_vars[key] = v
            check(grid, cfgmod.STAT_LABELS[key], v, lambda k=key: self._stat(k)).grid(
                row=i // 2, column=i % 2, sticky="w", padx=4, pady=1)
        for c in (0, 1):
            grid.grid_columnconfigure(c, weight=1, uniform="stats")

        # ---- overlay
        ov = cfg["overlay"]
        section("IN-GAME OVERLAY")
        self.enabled_var = tk.BooleanVar(value=ov["enabled"])
        check(win, "Show the overlay on top of the game", self.enabled_var, self._enabled).pack(
            anchor="w", padx=20)

        form = tk.Frame(win, bg=BG)
        form.pack(fill="x", padx=20, pady=(6, 0))

        def row(r, label):
            tk.Label(form, text=label, bg=BG, fg=MUTED, font=(FONT, 9), anchor="w", width=9).grid(
                row=r, column=0, sticky="w", pady=3)

        row(0, "Position")
        self.pos_var = tk.StringVar(value=cfgmod.preset_name(ov))
        dropdown(form, self.pos_var, list(cfgmod.PRESETS) + [cfgmod.CUSTOM], self._position).grid(
            row=0, column=1, sticky="w")

        row(1, "Monitor")
        self.mon_names = [AUTO_MONITOR] + [f"Monitor {i}" for i in range(1, monitor_count + 1)]
        self.mon_var = tk.StringVar(value=self._monitor_label())
        dropdown(form, self.mon_var, self.mon_names, self._monitor).grid(row=1, column=1, sticky="w")

        row(2, "Size")
        sizes = tk.Frame(form, bg=BG)
        sizes.grid(row=2, column=1, sticky="w")
        self.size_var = tk.StringVar(value=ov["size"])
        for name in ("small", "medium", "large"):
            tk.Radiobutton(sizes, text=name.capitalize(), value=name, variable=self.size_var,
                           command=self._size, bg=BG, fg=TEXT, selectcolor=CARD, activebackground=BG,
                           activeforeground=TEXT, font=(FONT, 9), highlightthickness=0, bd=0).pack(
                side="left", padx=(0, 10))

        row(3, "Opacity")
        self.opacity = tk.Scale(form, from_=30, to=100, orient="horizontal", showvalue=False, length=190,
                                command=self._opacity, bg=BG, fg=TEXT, troughcolor=CARD,
                                activebackground=GOLD, highlightthickness=0, bd=0)
        self.opacity.set(ov["opacity"])
        self.opacity.grid(row=3, column=1, sticky="w")

        self.session_var = tk.BooleanVar(value=ov["show_session"])
        self.ph_var = tk.BooleanVar(value=ov["show_ph"])
        check(win, "Also show this session's count", self.session_var, self._extras).pack(
            anchor="w", padx=20, pady=(8, 0))
        check(win, "Also show chests per hour", self.ph_var, self._extras).pack(anchor="w", padx=20)

        self.animate_var = tk.BooleanVar(value=ov["animate"])
        check(win, "Animate when a chest is added (+1 pop)", self.animate_var, self._animate).pack(
            anchor="w", padx=20, pady=(8, 0))

        self.unlock_var = tk.BooleanVar(value=False)
        check(win, "Unlock to drag the overlay (untick when placed)", self.unlock_var, self._unlock).pack(
            anchor="w", padx=20)
        tk.Label(win, text="The overlay shows over Fortnite in Windowed Fullscreen. Exclusive "
                           "fullscreen hides all overlays. Clicks pass through it while it's locked.",
                 bg=BG, fg=MUTED, font=(FONT, 8), wraplength=330, justify="left", anchor="w").pack(
            fill="x", padx=20, pady=(6, 0))

        # ---- this window
        section("THIS WINDOW")
        self.top_var = tk.BooleanVar(value=cfg["always_on_top"])
        check(win, "Keep the counter window on top", self.top_var, self._top).pack(anchor="w", padx=20)
        tk.Frame(win, bg=BG, height=14).pack()

    # ---- handlers: each one changes only its own setting -------------------
    def _stat(self, key):
        self.cfg["stats"][key] = bool(self.stat_vars[key].get())
        self.on_change()

    def _enabled(self):
        self.cfg["overlay"]["enabled"] = bool(self.enabled_var.get())
        self.on_change()

    def _position(self, name):
        if name in cfgmod.PRESETS:
            a, dx, dy = cfgmod.PRESETS[name]
            self.cfg["overlay"].update(anchor=a, dx=dx, dy=dy)
            self.on_change()
        else:                                       # "Custom" is only a label, not a place to go
            self.pos_var.set(cfgmod.preset_name(self.cfg["overlay"]))

    def _monitor(self, label):
        self.cfg["overlay"]["monitor"] = self.mon_names.index(label) if label in self.mon_names else 0
        self.on_change()

    def _size(self):
        self.cfg["overlay"]["size"] = self.size_var.get()
        self.on_change()

    def _opacity(self, value):
        self.cfg["overlay"]["opacity"] = int(float(value))
        if self._debounce is not None:              # dragging the slider: save once it settles
            try:
                self.win.after_cancel(self._debounce)
            except Exception:
                pass
        self.on_change(save=False)
        self._debounce = self.win.after(400, lambda: self.on_change())

    def _extras(self):
        self.cfg["overlay"]["show_session"] = bool(self.session_var.get())
        self.cfg["overlay"]["show_ph"] = bool(self.ph_var.get())
        self.on_change()

    def _animate(self):
        self.cfg["overlay"]["animate"] = bool(self.animate_var.get())
        self.on_change()

    def _unlock(self):
        self.set_unlocked(bool(self.unlock_var.get()))

    def _top(self):
        self.cfg["always_on_top"] = bool(self.top_var.get())
        self.on_change()

    # ---- helpers -------------------------------------------------------------
    def _monitor_label(self):
        i = self.cfg["overlay"]["monitor"]
        return self.mon_names[i] if 0 <= i < len(self.mon_names) else AUTO_MONITOR

    def refresh(self):
        """Re-read position/monitor after the overlay was dragged."""
        try:
            self.pos_var.set(cfgmod.preset_name(self.cfg["overlay"]))
            self.mon_var.set(self._monitor_label())
        except Exception:
            pass

    def close(self):
        self.set_unlocked(False)
        self.on_close()
        try:
            self.win.destroy()
        except Exception:
            pass