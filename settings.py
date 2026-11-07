"""
User settings: defaults, validation, and overlay position math. No GUI in here,
so it is easy to test. The settings are stored inside chest_count.json.
"""
import copy

STAT_ORDER = ["session", "time", "pm", "ph", "gap", "last"]
STAT_LABELS = {
    "best": "Best session",
    "session": "This session",
    "time": "Session time",
    "pm": "Chests / minute",
    "ph": "Chests / hour",
    "gap": "Avg time between chests",
    "last": "Last chest",
}
SIZES = {"small": 0.8, "medium": 1.0, "large": 1.3}
ANCHORS = ("tr", "tl", "br", "bl")          # which screen corner the overlay hugs

DEFAULTS = {
    "stats": {"best": True, "session": True, "time": True, "pm": True,
              "ph": True, "gap": True, "last": True},
    "overlay": {
        "enabled": False,        # in-game overlay is off until you turn it on
        "monitor": 0,            # 0 = follow the game's monitor, else 1, 2, ...
        "anchor": "tr", "dx": 0.012, "dy": 0.22,   # top right, just under the minimap
        "size": "medium",
        "opacity": 90,           # percent
        "show_session": False,   # extra line under the total
        "show_ph": False,
    },
    "always_on_top": True,
}

# name -> (anchor, dx, dy), where dx/dy are fractions of the screen width/height
PRESETS = {
    "Top right (below minimap)": ("tr", 0.012, 0.22),
    "Top right corner": ("tr", 0.010, 0.012),
    "Top left": ("tl", 0.010, 0.012),
    "Bottom right": ("br", 0.012, 0.030),
    "Bottom left": ("bl", 0.010, 0.030),
}
CUSTOM = "Custom (dragged)"


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def clean_settings(raw):
    """Merge saved settings onto the defaults, ignoring anything invalid."""
    s = copy.deepcopy(DEFAULTS)
    if not isinstance(raw, dict):
        return s
    st = raw.get("stats")
    if isinstance(st, dict):
        for k in s["stats"]:
            if isinstance(st.get(k), bool):
                s["stats"][k] = st[k]
    ov, o = raw.get("overlay"), s["overlay"]
    if isinstance(ov, dict):
        for k in ("enabled", "show_session", "show_ph"):
            if isinstance(ov.get(k), bool):
                o[k] = ov[k]
        if isinstance(ov.get("monitor"), int) and not isinstance(ov["monitor"], bool):
            o["monitor"] = min(16, max(0, ov["monitor"]))
        if ov.get("anchor") in ANCHORS:
            o["anchor"] = ov["anchor"]
        for k in ("dx", "dy"):
            if _num(ov.get(k)):
                o[k] = min(0.9, max(0.0, float(ov[k])))
        if ov.get("size") in SIZES:
            o["size"] = ov["size"]
        if _num(ov.get("opacity")):
            o["opacity"] = int(min(100, max(30, ov["opacity"])))
    if isinstance(raw.get("always_on_top"), bool):
        s["always_on_top"] = raw["always_on_top"]
    return s


def preset_name(ov):
    for name, (a, dx, dy) in PRESETS.items():
        if ov["anchor"] == a and abs(ov["dx"] - dx) < 0.002 and abs(ov["dy"] - dy) < 0.002:
            return name
    return CUSTOM


def overlay_origin(anchor, dx, dy, mon, w, h):
    """Top-left pixel of the overlay for a corner anchor, kept inside the monitor."""
    W, H = mon["width"], mon["height"]
    x = W - dx * W - w if anchor[1] == "r" else dx * W
    y = H - dy * H - h if anchor[0] == "b" else dy * H
    x = min(max(0, x), max(0, W - w))
    y = min(max(0, y), max(0, H - h))
    return int(mon["left"] + x), int(mon["top"] + y)


def nearest_anchor(x, y, w, h, mon):
    """Turn a dragged position (screen pixels) back into (anchor, dx, dy)."""
    W, H = mon["width"], mon["height"]
    rx, ry = x - mon["left"], y - mon["top"]
    right = rx + w / 2 > W / 2
    bottom = ry + h / 2 > H / 2
    dx = (W - (rx + w)) / W if right else rx / W
    dy = (H - (ry + h)) / H if bottom else ry / H
    clamp = lambda v: round(min(0.9, max(0.0, v)), 4)
    return ("b" if bottom else "t") + ("r" if right else "l"), clamp(dx), clamp(dy)


def monitor_index_at(px, py, monitors):
    """1-based index of the monitor containing a screen point, or 0 if none."""
    for i, m in enumerate(monitors, 1):
        if m["left"] <= px < m["left"] + m["width"] and m["top"] <= py < m["top"] + m["height"]:
            return i
    return 0
