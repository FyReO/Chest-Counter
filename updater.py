"""
Self-updater for the packaged ChestCounter.exe, using GitHub Releases.

Flow
  1. Ask GitHub for the latest release of your repo (public repos need no login).
  2. If its version is newer, download ChestCounter.exe plus its .sha256 file.
  3. Only keep the download if its SHA-256 matches. It is saved next to the exe
     as ChestCounter-update-<version>.exe.
  4. To install: rename the running exe to ChestCounter.exe.old (Windows allows
     renaming a running program), move the new exe into place, start it, exit.
     The .old file is deleted on the next launch.
Nothing here touches the game. It only talks to github.com.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

API_URL = "https://api.github.com/repos/{repo}/releases/latest"
ASSET_NAME = "ChestCounter.exe"
HASH_NAME = ASSET_NAME + ".sha256"
MAX_BYTES = 400 * 1024 * 1024
HEADERS = {"User-Agent": "ChestCounter-Updater", "Accept": "application/vnd.github+json"}


class UpdateError(Exception):
    pass


# ---- versions -------------------------------------------------------------
def parse_version(text):
    """'v1.2.3' -> (1, 2, 3). Anything after a '-' (like -beta) is ignored."""
    nums = re.findall(r"\d+", str(text).split("-")[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(remote, local):
    a, b = parse_version(remote), parse_version(local)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


# ---- talking to GitHub ----------------------------------------------------
def _get(url, timeout=10):
    return urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout)


def _trusted(url, repo):
    prefix = f"https://github.com/{repo}/releases/download/"
    return isinstance(url, str) and url.lower().startswith(prefix.lower())


def fetch_latest(repo):
    """Newest published release: {'version', 'exe_url', 'sha_url'} (urls may be None)."""
    with _get(API_URL.format(repo=repo)) as r:
        data = json.loads(r.read().decode("utf-8"))
    assets = {a.get("name"): a for a in data.get("assets", [])}
    tag = str(data.get("tag_name", ""))
    return {
        "version": tag.lstrip("vV"),
        "exe_url": (assets.get(ASSET_NAME) or {}).get("browser_download_url"),
        "sha_url": (assets.get(HASH_NAME) or {}).get("browser_download_url"),
    }


def download_update(info, repo, dest_dir):
    """Download + verify. Returns the path of the verified update file."""
    exe_url, sha_url = info.get("exe_url"), info.get("sha_url")
    if not exe_url or not sha_url:
        raise UpdateError("release is missing the exe or its checksum")
    if not (_trusted(exe_url, repo) and _trusted(sha_url, repo)):
        raise UpdateError("download link is not from the project's GitHub releases")
    version = "".join(re.findall(r"[0-9.]", info.get("version", ""))) or "0"

    with _get(sha_url) as r:
        words = r.read(1024).decode("utf-8", "ignore").split()
    expected = words[0].lower() if words else ""
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise UpdateError("checksum file is not valid")

    dest_dir = Path(dest_dir)
    part = dest_dir / f"ChestCounter-update-{version}.part"
    final = dest_dir / f"ChestCounter-update-{version}.exe"
    digest, total, first = hashlib.sha256(), 0, True
    try:
        with _get(exe_url, timeout=30) as r, open(part, "wb") as f:
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                if first:
                    if chunk[:2] != b"MZ":
                        raise UpdateError("download is not a Windows program")
                    first = False
                total += len(chunk)
                if total > MAX_BYTES:
                    raise UpdateError("download is too large")
                digest.update(chunk)
                f.write(chunk)
        if digest.hexdigest() != expected:
            raise UpdateError("checksum mismatch, download discarded")
        os.replace(part, final)              # only a complete, verified file gets the final name
        return final
    except BaseException:
        try:
            part.unlink()
        except OSError:
            pass
        raise


# ---- installing -----------------------------------------------------------
def pending_update(app_dir, current_version):
    """A verified update left from an earlier run that is newer than us: (path, version)."""
    best = None
    for p in Path(app_dir).glob("ChestCounter-update-*"):
        m = re.fullmatch(r"ChestCounter-update-([0-9.]+)\.exe", p.name)
        if m and is_newer(m.group(1), current_version):
            if best is None or is_newer(m.group(1), best[1]):
                best = (p, m.group(1))
        elif p.suffix in (".exe", ".part"):      # stale or half-finished leftovers
            try:
                p.unlink()
            except OSError:
                pass
    return best


def cleanup_old(exe):
    try:
        Path(str(exe) + ".old").unlink()
    except OSError:
        pass


def apply_update(staged, exe):
    """Swap the new exe in. The running exe is renamed, not overwritten."""
    exe, staged = Path(exe), Path(staged)
    old = Path(str(exe) + ".old")
    cleanup_old(exe)
    os.replace(exe, old)
    try:
        os.replace(staged, exe)
    except Exception:
        os.replace(old, exe)                 # put the original back if anything went wrong
        raise


def relaunch(exe):
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"   # new copy must unpack itself, not reuse ours
    flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0   # DETACHED | NEW_GROUP
    subprocess.Popen([str(exe)], env=env, close_fds=True, creationflags=flags)
