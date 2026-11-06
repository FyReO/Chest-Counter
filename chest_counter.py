"""
Fortnite Chest Counter
============================
A small always-on-top window that counts every chest you open, saves your
total between runs, and shows live stats (per minute, per hour, and more).

How it works: whenever you open a chest, Fortnite shows a "+600 XP  CHEST"
popup on your HUD. This app watches your screen, looks for the word "CHEST"
in that popup, and adds 1 each time a new popup appears.
It only reads screen pixels (like OBS does). It never touches the game.

Run:        python chest_counter.py
Options:    --monitor N    only watch monitor N (default: watch ALL monitors)
            --debug        show the live match score in the status line
            --diagnose     20-second self-test that saves screenshots + scores
            --video FILE   test on a recorded clip instead of the screen

Right-click the window for options (add/remove a chest, updates, reset, always on top).
The packaged ChestCounter.exe updates itself from GitHub Releases (see README.md).

Tip: set Fortnite to "Windowed Fullscreen". True exclusive fullscreen can show
up as a black image to screen-capture tools.
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

import updater

# --------------------------------------------------------------------------
# Version + update source
# --------------------------------------------------------------------------
__version__ = "1.0.0"                        # the release workflow stamps this from your git tag
GITHUB_REPO = "FyReO/Chest-Counter"  # <- change to your public GitHub repo
FROZEN = getattr(sys, "frozen", False)       # True when running as the packaged .exe
UPDATES_ENABLED = "YOUR-USERNAME" not in GITHUB_REPO
UPDATE_CHECK_EVERY = 6 * 3600                # seconds between checks while the app stays open

# --------------------------------------------------------------------------
# Detection settings
# --------------------------------------------------------------------------
POLL_SECONDS = 0.10      # how often the screen is checked
ON_THRESHOLD = 0.68      # match score needed to say "popup is showing"
OFF_THRESHOLD = 0.50     # score below this = popup is gone
CONFIRM_POLLS = 3        # popup must be seen this many checks in a row
RELEASE_SECONDS = 0.6    # popup must be gone this long before the next count
HUD_SCALES = (0.8, 0.9, 1.0, 1.1, 1.25)   # tolerate different HUD scales

# Template of the word "CHEST" (white-text mask, captured at 1080p, HUD scale 100%)
TEMPLATE_B64 = "iVBORw0KGgoAAAANSUhEUgAAADQAAAAYCAAAAACQfYF6AAAApElEQVQ4EZ3BgWHDMAAEIW7/ob+RE3cAQS7kQi7kQi7kQn6GfE0mkyEWlke+5sjEZI7maB555DEamYyGGJmv/OQxGY1MRhgZmbxyjJhGJpOPkcfklWPymJjMR8xHmLxyTB7zyHyE+YjJK8fEaB6Z/IyMvHJMTCYjE0ZGRl45RqOR0bwyMvLKMUcmJnNkjpj8y9fkZ/JYjHxM/uVCLuRCLuRCLvwB1KVOGTVMogAAAAAASUVORK5CYII="

APP_DIR = Path(sys.executable if FROZEN else __file__).resolve().parent


# --------------------------------------------------------------------------
# Detector (pure image logic, no GUI)
# --------------------------------------------------------------------------
def white_text_mask(bgr):
    """Near-white, low-saturation pixels = the popup text (ignores the background)."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    return (((hsv[..., 2] > 215) & (hsv[..., 1] < 110)) * 255).astype(np.uint8)


def search_box(screen_w, screen_h):
    """Area to search, as (left, top, width, height) in screen pixels.

    The Fortnite HUD scales with screen HEIGHT and is centered horizontally, so the
    box is defined relative to the screen center (works on ultrawide too). The popup
    normally sits ~0.32*H right of center and ~0.31*H down from the top.
    """
    left = max(0, int(screen_w / 2 + 0.18 * screen_h))
    right = min(screen_w, int(screen_w / 2 + 0.50 * screen_h))
    top = int(0.15 * screen_h)
    bottom = int(0.50 * screen_h)
    return left, top, right - left, bottom - top


class ChestDetector:
    def __init__(self):
        raw = base64.b64decode(TEMPLATE_B64)
        base = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
        self.templates = [cv2.resize(base, None, fx=s, fy=s, interpolation=cv2.INTER_LINEAR)
                          for s in HUD_SCALES]
        self.active = False
        self.streak = 0
        self.last_seen = 0.0
        self.score = 0.0

    def score_region(self, region_bgr, screen_h):
        """Best template match (0..1) inside the captured region."""
        k = 1080.0 / screen_h                      # normalize to 1080p
        if abs(k - 1.0) > 0.01:
            interp = cv2.INTER_AREA if k < 1 else cv2.INTER_LINEAR
            region_bgr = cv2.resize(region_bgr, None, fx=k, fy=k, interpolation=interp)
        mask = white_text_mask(region_bgr)
        best = 0.0
        for t in self.templates:
            if mask.shape[0] < t.shape[0] or mask.shape[1] < t.shape[1]:
                continue
            res = cv2.matchTemplate(mask, t, cv2.TM_CCOEFF_NORMED)
            best = max(best, float(res.max()))
        return best

    def update(self, region_bgr, screen_h, now):
        """Feed one capture. Returns True exactly once per new chest popup."""
        self.score = self.score_region(region_bgr, screen_h)
        counted = False
        if self.score >= ON_THRESHOLD:
            self.last_seen = now
            self.streak += 1
            if not self.active and self.streak >= CONFIRM_POLLS:
                self.active = True
                counted = True
        elif self.score < OFF_THRESHOLD:
            self.streak = 0
            if self.active and now - self.last_seen >= RELEASE_SECONDS:
                self.active = False
        return counted


# --------------------------------------------------------------------------
# Video test mode: python chest_counter.py --video clip.mp4
# --------------------------------------------------------------------------
def run_video(path):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        sys.exit(f"Could not open {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    det = ChestDetector()
    count, idx, next_t = 0, 0, 0.0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = idx / fps
        idx += 1
        if t < next_t:
            continue
        next_t = t + POLL_SECONDS
        h, w = frame.shape[:2]
        l, tp, bw, bh = search_box(w, h)
        if det.update(frame[tp:tp + bh, l:l + bw], h, t):
            count += 1
            print(f"chest #{count} detected at {t:5.2f}s  (score {det.score:.2f})")
    print(f"Total chests: {count}")


# --------------------------------------------------------------------------
# Screen capture helpers
# --------------------------------------------------------------------------
def enable_dpi_awareness():
    if sys.platform == "win32":      # capture real pixels on scaled displays
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


def grab_bgr(sct, box):
    return np.ascontiguousarray(np.array(sct.grab(box))[:, :, :3])   # BGRA -> BGR


# --------------------------------------------------------------------------
# Diagnose mode: python chest_counter.py --diagnose
# --------------------------------------------------------------------------
def run_diagnose(seconds=20):
    import mss
    enable_dpi_awareness()
    out = APP_DIR / "diagnose"
    out.mkdir(exist_ok=True)
    lines = []

    def log(msg=""):
        print(msg)                           # does nothing in the windowed .exe, so also saved below
        lines.append(str(msg))

    sct = mss.mss()
    mons = sct.monitors[1:]
    log(f"Found {len(mons)} monitor(s):")
    for i, m in enumerate(mons, 1):
        log(f"  monitor {i}: {m['width']}x{m['height']} at ({m['left']},{m['top']})")
    log(f"\nOpen a chest in Fortnite NOW. Watching for {seconds} seconds...\n")
    dets = [ChestDetector() for _ in mons]
    best = [(-1.0, None)] * len(mons)
    t0, last_print = time.monotonic(), 0
    shots = 0
    while time.monotonic() - t0 < seconds:
        now = time.monotonic() - t0
        for i, m in enumerate(mons):
            W, H = m["width"], m["height"]
            l, t, bw, bh = search_box(W, H)
            region = grab_bgr(sct, {"left": m["left"] + l, "top": m["top"] + t, "width": bw, "height": bh})
            sc = dets[i].score_region(region, H)
            if sc > best[i][0]:
                best[i] = (sc, region.copy())
            if int(now) > last_print or shots == 0:
                full = grab_bgr(sct, m)
                bright = float(full.mean())
                small = cv2.resize(full, (960, int(960 * H / W)), interpolation=cv2.INTER_AREA)
                cv2.imwrite(str(out / f"monitor{i+1}_t{int(now):02d}.jpg"), small)
                flag = "   <-- BLACK IMAGE (use Windowed Fullscreen)" if bright < 3 else ""
                log(f"t={now:4.1f}s  monitor {i+1}: brightness {bright:5.1f}  match score {sc:.2f}{flag}")
        if int(now) > last_print or shots == 0:
            last_print = int(now)
            shots += 1
        time.sleep(0.1)
    log("\nSummary:")
    for i, (sc, reg) in enumerate(best):
        log(f"  monitor {i+1}: best match score {sc:.2f}  (needs {ON_THRESHOLD} to count)")
        if reg is not None:
            cv2.imwrite(str(out / f"monitor{i+1}_best_region.png"), reg)
    log(f"\nScreenshots saved in: {out}")
    (out / "report.txt").write_text("\n".join(lines), encoding="utf-8")
    if sys.stdout is None:                   # packaged .exe: no console, so tell the user another way
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk()
            r.withdraw()
            messagebox.showinfo("Chest Counter diagnostics", f"Done. Report and screenshots are in:\n{out}")
            r.destroy()
        except Exception:
            pass
        try:
            os.startfile(out)
        except Exception:
            pass


# --------------------------------------------------------------------------
# Stats + saving (no GUI, so it is easy to test)
# --------------------------------------------------------------------------
def fmt_clock(sec):
    sec = int(max(0, sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_ago(sec):
    sec = int(max(0, sec))
    if sec < 60:
        return f"{sec}s ago"
    m, s = divmod(sec, 60)
    if m < 60:
        return f"{m}m {s:02d}s ago"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m ago"


class SessionStats:
    """Stats for one run of the app. Pace is measured from your first chest
    of the session, so time spent in the lobby doesn't drag the numbers down."""
    MIN_SECONDS_FOR_RATE = 30

    def __init__(self, now):
        self.start = now
        self.count = 0
        self.first = None
        self.last = None

    def add(self, now):
        self.count += 1
        if self.first is None:
            self.first = now
        self.last = now

    def remove(self):
        self.count = max(0, self.count - 1)
        if self.count == 0:
            self.first = self.last = None

    def per_minute(self, now):
        if self.count < 2 or self.first is None:
            return None
        elapsed = now - self.first
        if elapsed < self.MIN_SECONDS_FOR_RATE:
            return None
        return self.count / (elapsed / 60.0)

    def avg_gap(self):
        if self.count < 2 or self.first is None or self.last is None:
            return None
        return (self.last - self.first) / (self.count - 1)

    def since_last(self, now):
        return None if self.last is None else now - self.last


class Store:
    """Saves your all-time total and best session so they survive restarts."""

    def __init__(self):
        self.path = self._pick_path()
        self.total = 0
        self.best_session = 0
        self.load()

    @staticmethod
    def _pick_path():
        primary = APP_DIR / "chest_count.json"
        try:
            with open(primary, "a"):
                pass
            return primary
        except OSError:                      # folder not writable: use AppData instead
            base = Path(os.environ.get("APPDATA") or Path.home()) / "ChestCounter"
            base.mkdir(parents=True, exist_ok=True)
            return base / "chest_count.json"

    def load(self):
        try:
            data = json.loads(self.path.read_text())
            self.total = max(0, int(data.get("total", data.get("count", 0))))   # old files used "count"
            self.best_session = max(0, int(data.get("best_session", 0)))
        except Exception:
            pass

    def save(self):
        try:
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps({"total": self.total, "best_session": self.best_session}))
            os.replace(tmp, self.path)       # atomic: a crash can't corrupt the save
            return True
        except Exception:
            return False


# --------------------------------------------------------------------------
# Window
# --------------------------------------------------------------------------
BG, CARD, BORDER = "#0e1014", "#171a21", "#262b38"
TEXT, MUTED, GOLD = "#eceef4", "#7d869a", "#ffc83d"
GREEN, AMBER, RED = "#4ade80", "#fbbf24", "#f87171"
FONT = "Segoe UI"


def mix(c1, c2, t):
    """Blend two #rrggbb colors (t=0 -> c1, t=1 -> c2)."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def apply_pending_update_at_launch():
    """If a verified update was downloaded earlier, install it now. True = we are restarting."""
    if not FROZEN:
        return False
    exe = Path(sys.executable)
    updater.cleanup_old(exe)
    found = updater.pending_update(APP_DIR, __version__)
    if not found:
        return False
    try:
        updater.apply_update(found[0], exe)
        updater.relaunch(exe)
        return True
    except Exception:
        return False


def style_titlebar(root):
    """Dark title bar on Windows 10/11 so the window looks like one piece."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        set_attr = ctypes.windll.dwmapi.DwmSetWindowAttribute
        for attr, val in ((20, 1), (19, 1), (35, 0x0014100E)):   # dark mode x2, caption color
            try:
                set_attr(hwnd, attr, ctypes.byref(ctypes.c_int(val)), 4)
            except Exception:
                pass
    except Exception:
        pass


def run_app(monitor_index, debug):
    import tkinter as tk
    from tkinter import messagebox

    import mss

    enable_dpi_awareness()
    root = tk.Tk()
    root.title("Chest Counter")
    root.configure(bg=BG)
    root.resizable(False, False)
    root.attributes("-topmost", True)

    sf = max(1.0, root.winfo_fpixels("1i") / 96.0)       # display scaling (125%, 150%...)
    S = lambda v: int(round(v * sf))
    F = lambda size, weight="normal": (FONT, -int(round(size * 4 / 3 * sf)), weight)   # size in points
    W, H, PAD = 340, 452, 16
    root.geometry(f"{S(W)}x{S(H)}")
    style_titlebar(root)

    cv = tk.Canvas(root, width=S(W), height=S(H), bg=BG, highlightthickness=0, bd=0)
    cv.pack()

    def rrect(x1, y1, x2, y2, r, fill, outline=""):
        x1, y1, x2, y2, r = S(x1), S(y1), S(x2), S(y2), S(r)
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
               x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return cv.create_polygon(pts, smooth=True, fill=fill, outline=outline, width=1)

    def text(x, y, s, size, color, weight="normal", anchor="center"):
        return cv.create_text(S(x), S(y), text=s, fill=color, font=F(size, weight), anchor=anchor)

    # ---- header
    text(PAD, 22, "CHEST COUNTER", 10, TEXT, "bold", "w")
    text(W - PAD, 22, "right-click for options", 8, MUTED, "normal", "e")

    # ---- hero card: all-time total
    hero = rrect(PAD, 40, W - PAD, 170, 16, CARD, BORDER)
    text(W / 2, 62, "TOTAL CHESTS OPENED", 8, MUTED, "bold")
    total_id = text(W / 2, 106, "0", 46, GOLD, "bold")
    best_id = text(W / 2, 152, "", 8, MUTED, "bold")

    # ---- stat cards (2 x 3)
    cards = [("session", "THIS SESSION"), ("time", "SESSION TIME"),
             ("pm", "CHESTS / MINUTE"), ("ph", "CHESTS / HOUR"),
             ("gap", "AVG TIME BETWEEN"), ("last", "LAST CHEST")]
    cw, ch, gap = (W - 2 * PAD - 10) / 2, 72, 10
    value_ids = {}
    for i, (key, label) in enumerate(cards):
        col, row = i % 2, i // 2
        x, y = PAD + col * (cw + gap), 184 + row * (ch + gap)
        rrect(x, y, x + cw, y + ch, 14, CARD, BORDER)
        text(x + 14, y + 18, label, 8, MUTED, "bold", "w")
        value_ids[key] = text(x + 14, y + 46, "--", 15, TEXT, "bold", "w")

    # ---- status row
    dot = cv.create_oval(S(PAD), S(431), S(PAD + 8), S(439), fill=GREEN, outline="")
    status_id = text(PAD + 16, 435, "Starting...", 9, MUTED, "normal", "w")
    text(W - PAD, 435, f"v{__version__}", 8, MUTED, "normal", "e")

    # ---- data
    store = Store()
    t0 = time.monotonic()
    stats = SessionStats(t0)

    def render(now):
        cv.itemconfig(total_id, text=f"{store.total:,}")
        cv.itemconfig(best_id, text=f"BEST SESSION  {store.best_session}")
        pm = stats.per_minute(now)
        gap_s = stats.avg_gap()
        since = stats.since_last(now)
        vals = {
            "session": str(stats.count),
            "time": fmt_clock(now - stats.start),
            "pm": "--" if pm is None else f"{pm:.2f}",
            "ph": "--" if pm is None else f"{pm * 60:.0f}",
            "gap": "--" if gap_s is None else fmt_clock(gap_s),
            "last": "--" if since is None else fmt_ago(since),
        }
        for k, v in vals.items():
            cv.itemconfig(value_ids[k], text=v)

    def pulse(step=0, steps=8):
        if step > steps:
            cv.itemconfig(hero, outline=BORDER)
            cv.itemconfig(total_id, fill=GOLD)
            return
        t = step / steps
        cv.itemconfig(hero, outline=mix(GOLD, BORDER, t))
        cv.itemconfig(total_id, fill=mix("#ffffff", GOLD, t))
        root.after(45, lambda: pulse(step + 1, steps))

    def chest_added(now, animate=True):
        stats.add(now)
        store.total += 1
        store.best_session = max(store.best_session, stats.count)
        store.save()
        render(now)
        if animate:
            pulse()

    def chest_removed():
        if store.total > 0:
            stats.remove()
            store.total -= 1
            store.save()
            render(time.monotonic())

    def reset_session():
        nonlocal stats
        stats = SessionStats(time.monotonic())
        render(time.monotonic())

    def reset_all():
        nonlocal stats
        if messagebox.askyesno("Reset everything",
                               "Reset the total, best session, and this session to 0?", parent=root):
            stats = SessionStats(time.monotonic())
            store.total = 0
            store.best_session = 0
            store.save()
            render(time.monotonic())

    # ---- updates (runs in a background thread; the window never waits on the network)
    up = {"state": "idle", "version": None, "path": None, "note": "", "note_color": MUTED, "note_until": 0.0}

    def note(msg, color=MUTED, secs=6):
        up.update(note=msg, note_color=color, note_until=time.monotonic() + secs)

    def check_for_updates(manual=False):
        if up["state"] in ("checking", "downloading", "ready"):
            return
        try:
            up["state"] = "checking"
            info = updater.fetch_latest(GITHUB_REPO)
            if not updater.is_newer(info["version"], __version__):
                up["state"] = "current"
                if manual:
                    note(f"You're up to date (v{__version__})", GREEN)
                return
            up["version"] = info["version"]
            if not FROZEN:                           # running from source: just tell the user
                up["state"] = "available"
                return
            up["state"] = "downloading"
            up["path"] = updater.download_update(info, GITHUB_REPO, APP_DIR)
            up["state"] = "ready"
        except Exception:
            up["state"] = "error"
            if manual:
                note("Couldn't check for updates right now", AMBER)

    def update_loop():
        while True:
            check_for_updates()
            if up["state"] in ("ready", "available"):
                return
            time.sleep(UPDATE_CHECK_EVERY)

    def check_now():
        if not UPDATES_ENABLED:
            note("Set GITHUB_REPO in chest_counter.py first", AMBER)
        else:
            note("Checking for updates...")
            threading.Thread(target=check_for_updates, args=(True,), daemon=True).start()

    def install_update_now():
        if up["state"] != "ready":
            note("No update downloaded yet. Use 'Check for updates'", AMBER)
            return
        try:
            store.save()
            exe = Path(sys.executable)
            updater.apply_update(up["path"], exe)
            updater.relaunch(exe)
            root.destroy()
        except Exception:
            note("Update couldn't be installed. Try again later", RED)

    def run_diagnostics():
        cmd = [sys.executable, "--diagnose"] if FROZEN else [sys.executable, str(Path(__file__).resolve()), "--diagnose"]
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
        try:
            subprocess.Popen(cmd, env=env, close_fds=True)
            note("Diagnostics running 20s: switch to Fortnite, open a chest", AMBER, 20)
        except Exception:
            note("Couldn't start diagnostics", RED)

    # ---- right-click menu
    on_top = tk.BooleanVar(value=True)
    menu = tk.Menu(root, tearoff=0)
    menu.add_command(label="Add 1 chest", command=lambda: chest_added(time.monotonic()))
    menu.add_command(label="Remove 1 chest", command=chest_removed)
    menu.add_separator()
    menu.add_checkbutton(label="Always on top", variable=on_top,
                         command=lambda: root.attributes("-topmost", on_top.get()))
    menu.add_separator()
    menu.add_command(label="Check for updates", command=check_now)
    menu.add_command(label="Install update and restart", command=install_update_now)
    menu.add_command(label="Run diagnostics (20s)", command=run_diagnostics)
    menu.add_separator()
    menu.add_command(label="Reset session stats", command=reset_session)
    menu.add_command(label="Reset everything...", command=reset_all)

    def show_menu(event):
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    cv.bind("<Button-3>", show_menu)

    def on_close():
        store.save()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    # ---- screen capture + detection loop
    sct = mss.mss()
    all_mons = sct.monitors[1:]
    watch = [all_mons[monitor_index - 1]] if 1 <= monitor_index <= len(all_mons) else all_mons
    dets = [ChestDetector() for _ in watch]
    boxes = []
    for m in watch:
        l, t, bw, bh = search_box(m["width"], m["height"])
        boxes.append({"left": m["left"] + l, "top": m["top"] + t, "width": bw, "height": bh})

    state = {"last_black_check": 0.0, "black": False, "last_render": 0.0}

    def set_status(msg, color):
        cv.itemconfig(status_id, text=msg)
        cv.itemconfig(dot, fill=color)

    def tick():
        try:
            now = time.monotonic()
            best = 0.0
            for m, box, det in zip(watch, boxes, dets):
                if det.update(grab_bgr(sct, box), m["height"], now):
                    chest_added(now)
                best = max(best, det.score)
            if now - state["last_black_check"] > 3.0:       # is the game capturing as black?
                state["last_black_check"] = now
                state["black"] = all(grab_bgr(sct, m).mean() < 3 for m in watch)
            if state["black"]:
                set_status("Screen is black. Use Windowed Fullscreen", AMBER)
            elif now < up["note_until"]:
                set_status(up["note"], up["note_color"])
            elif up["state"] == "ready":
                set_status(f"Update v{up['version']} ready (right-click)", GOLD)
            elif up["state"] == "downloading":
                set_status(f"Downloading update v{up['version']}...", MUTED)
            elif up["state"] == "available":
                set_status(f"Update v{up['version']} available on GitHub", GOLD)
            else:
                set_status("Watching for chests" + (f"   match {best:.2f}" if debug else ""), GREEN)
            if now - state["last_render"] >= 0.5:           # keep the timers ticking
                state["last_render"] = now
                render(now)
        except Exception as e:                                   # keep the window alive
            set_status(f"Capture error: {str(e)[:34]}", RED)
        root.after(int(POLL_SECONDS * 1000), tick)

    render(time.monotonic())
    root.after(200, tick)
    if UPDATES_ENABLED:
        threading.Thread(target=update_loop, daemon=True).start()
    root.mainloop()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Fortnite chest counter")
    ap.add_argument("--monitor", type=int, default=0, help="only watch this monitor (default: all)")
    ap.add_argument("--debug", action="store_true", help="show the live match score")
    ap.add_argument("--diagnose", action="store_true", help="20-second self-test")
    ap.add_argument("--video", help="test on a video file instead of the screen")
    a = ap.parse_args()
    if a.video:
        run_video(a.video)
    elif a.diagnose:
        run_diagnose()
    elif apply_pending_update_at_launch():
        pass                                  # an update was installed; the new version is starting
    else:
        run_app(a.monitor, a.debug)
