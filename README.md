# Hera

NFL live game tracker and parlay entry app (PySide6 desktop).

## Run

From the repo root:

```
pip install PySide6 requests pygame
python Hera/Scripts/hera.py
```

Run the same file in PyCharm if that is how you launch it. Audio is `Hera/HERA_AUDIO.mp3`.

## Desktop shortcut (no PyCharm)

Use the **same Python** that already runs Hera from a terminal (`pip install PySide6 requests pygame` then `python Hera/Scripts/hera.py`). The launchers live in the **repo root** (the folder that contains the `Hera` folder).

### Windows

**One-time: confirm Python works**

1. Open **Command Prompt**.
2. `cd` into your Hera repo (example: `cd C:\Users\chris\hera`).
3. Run `python Hera\Scripts\hera.py`. If Hera opens, you are done with this check. Close it.
4. If that fails with “python is not recognized”:
   - Install Python 3 from https://www.python.org/downloads/windows/
   - On the installer, check **Add python.exe to PATH**
   - Open a **new** Command Prompt and run `python -m pip install PySide6 requests pygame`

**Put a launcher on the Desktop**

1. In File Explorer, open the repo root. You should see `launch-hera.bat` next to the `Hera` folder.
2. Right-click `launch-hera.bat` → **Send to** → **Desktop (create shortcut)**.
3. On the Desktop, right-click the new shortcut → **Rename** → `Hera`.
4. Optional icon: right-click the shortcut → **Properties** → **Change Icon** → **Browse** to `Hera\hera_loading_screen.png` (or any `.ico` you make from that image). Windows 10 often wants a `.ico`; Windows 11 will sometimes take the PNG.
5. Double-click **Hera** on the Desktop. The splash should play, then the app. You should not need PyCharm.

**Pin to taskbar**

1. Double-click the Desktop shortcut once so Hera is running.
2. On the taskbar, right-click the Hera window icon → **Pin to taskbar**.

`launch-hera.bat` starts `pythonw` when it exists (no black console). If `pythonw` is missing it falls back to `python`.

**If a black window flashes and nothing opens**

- Right-click `launch-hera.bat` → **Edit** and confirm the `Hera\Scripts\hera.py` path is under the same folder as the `.bat`.
- In Command Prompt, from the repo root, run `python Hera\Scripts\hera.py` and read the error.

### Mac

**One-time: confirm Python works**

1. Open **Terminal**.
2. `cd` into your Hera repo (example: `cd ~/hera`).
3. Run `python3 Hera/Scripts/hera.py`. If Hera opens, close it and continue.
4. If `command not found`:
   - Install Python 3 from https://www.python.org/downloads/macos/ **or** Homebrew (`brew install python`)
   - Then: `python3 -m pip install PySide6 requests pygame`

**Put a launcher on the Desktop**

1. In Finder, open the repo root. You should see `launch-hera.command` next to the `Hera` folder.
2. Right-click `launch-hera.command` → **Get Info**. If **Open with** is TextEdit, change it to **Terminal**.
3. Make it executable. In Terminal, from the repo root:

```
chmod +x launch-hera.command
```

4. Drag `launch-hera.command` to the **Desktop** (hold **Option+Command** while dragging if you want an alias and to leave the original in the repo).
5. Rename the Desktop item to **Hera** if you want.
6. First launch: right-click → **Open**. macOS will warn that it is an unidentified script. Click **Open**. After that, double-click works.
7. If it still refuses: **System Settings** → **Privacy & Security** → scroll to the blocked-app message → **Open Anyway**.

**Dock**

1. Double-click the Desktop launcher so Hera is running.
2. Right-click the Hera icon in the Dock → **Options** → **Keep in Dock**.
   Note: the Dock tile is the Python process. Clicking it later may not start Hera unless you use the Desktop alias. The Desktop / `launch-hera.command` file is the reliable start button.

**Optional: make a real .app (nicer Dock icon)**

1. Open **Automator** (Spotlight: Automator).
2. **New Document** → **Application**.
3. Add **Run Shell Script**.
4. Set **Pass input** to **as arguments**.
5. Paste this, and change `/Users/chris/hera` to your real repo path:

```
cd /Users/chris/hera
/usr/bin/env python3 Hera/Scripts/hera.py
```

6. File → **Save** → name it `Hera` → save to **Desktop** (file format: Application).
7. Optional icon: copy `Hera/hera_loading_screen.png`, Get Info on the new app, click the small icon in the Get Info window, paste.

Do not move `launch-hera.bat` / `launch-hera.command` out of the repo without keeping them next to the `Hera` folder. They find `Hera/Scripts/hera.py` from their own location.

## Bet Entry

- Pick a slot **P1–P10**.
- **+ ADD LEG** adds one editable row immediately. Type odds on each row; **LEGS**, **PARLAY ODDS**, **TO WIN**, and **PAYOUT** update as you type.
- **NEW PARLAY** (bottom of the tab) clears the current slot.
- **SUBMIT PARLAY** saves the ticket as live.
