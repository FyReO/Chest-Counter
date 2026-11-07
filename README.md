# Chest Counter

Counts every chest you open in Fortnite, saves your total between runs, and shows
live stats (per minute, per hour, average time between chests, and more).

It reads the "+XP CHEST" popup on your screen. It never touches the game.
Set Fortnite to **Windowed Fullscreen**, or capture can come back black.

## Use it
Download `ChestCounter.exe` from the latest [Release](../../releases/latest) and run it.
Keep it in its own folder. Your total is saved next to it in `chest_count.json`.
The app checks for new versions on its own and installs them on the next launch.
Right-click the window for options (add/remove a chest, reset, updates, diagnostics).

## Settings and the in-game overlay
Click **Settings** in the window (or right-click it).
- **Stats:** tick or untick any stat (best session, session count, session time, chests per
  minute, chests per hour, average time between chests, last chest). The window resizes to fit.
- **Overlay:** a tiny badge with your chest total that sits on top of Fortnite. Choose its
  position, monitor, size, opacity, and whether it also shows this session's count and chests
  per hour. It's click-through, so it never gets in the way of your mouse.
- **Move it anywhere:** tick "Unlock to drag the overlay", drag it, then untick (or close
  Settings). It remembers the spot. The default is the top right, just under the minimap.
- The overlay shows over Fortnite in **Windowed Fullscreen**. Exclusive fullscreen hides every
  overlay, this one included.

## One-time setup (you, the developer)
1. Create a **public** repo on GitHub (for example `chest-counter`). Public matters:
   the app checks for updates without logging in, which only works for public repos.
2. In `chest_counter.py`, set `GITHUB_REPO = "your-username/chest-counter"`.
3. Upload these files to the repo and push:
   ```
   git init
   git add .
   git commit -m "First version"
   git branch -M main
   git remote add origin https://github.com/YOUR-USERNAME/chest-counter.git
   git push -u origin main
   ```
4. Publish the first version (this starts the build):
   ```
   git tag v1.0.0
   git push origin v1.0.0
   ```
   After about 3-6 minutes, a Release with `ChestCounter.exe` appears under the repo's
   **Releases** page (watch progress in the **Actions** tab).

## Shipping an update
Change the code, then:
```
git add .
git commit -m "What changed"
git push
git tag v1.0.1
git push origin v1.0.1
```
Use a higher number each time (v1.0.2, v1.1.0, ...). The version inside the app is
set automatically from the tag, so you never edit it by hand. Running copies find the
new Release, download it, check its checksum, and install it next time they start.

## Run from source instead
```
pip install -r requirements.txt
python chest_counter.py
```
Options: `--monitor N`, `--debug` (show match score), `--diagnose`, `--video clip.mp4`.

## Troubleshooting
- **Windows SmartScreen or antivirus warns about the exe.** Unsigned programs built with
  PyInstaller often trigger this. Choose "More info" then "Run anyway", or add an exclusion.
  Removing the warning for good needs a paid code-signing certificate.
- **Counter never goes up.** Right-click, then "Run diagnostics (20s)", open a chest, and check
  the `diagnose` folder next to the exe (`report.txt` plus screenshots).
