# ImmediPaste

Lightweight screenshot tool. Captures screen regions, windows, or fullscreen and puts them on the clipboard instantly. Runs as a system tray app with global hotkeys.

## Tech Stack

- **Python 3.10+** with **PySide6** (Qt6) for UI
- **mss** for multi-monitor screenshot capture (grabs `monitors[0]` -- the combined virtual screen on Windows)
- **pynput** for global hotkey listening (LGPL 3.0 -- fine for PyInstaller bundling)
- **PyInstaller** for building standalone executables

See `requirements.txt` for pinned deps. PySide6 is LGPL 3.0, mss is MIT. If distribution method changes from PyInstaller bundling, review LGPL compliance for pynput and PySide6.

## Project Structure

```
main.py               # Entry point, tray icon, settings dialog, config, hotkey bridge
capture.py             # CaptureOverlay widget - region/window/fullscreen capture
annotation_editor.py   # Annotation editor - drawing tools, toolbar, compositing
log.py                 # Centralized logging with rotating file handler + fallback dirs
platform_utils.py      # Cross-platform clipboard, save_qimage, default folder detection
window_utils.py        # Windows-only window detection via Win32 ctypes/DWM APIs
config.json            # User settings (gitignored, auto-created from DEFAULT_CONFIG on first run)
test_*.py              # pytest test suite (100 tests)
ImmediPaste.spec       # PyInstaller build config (excluded Qt modules, UPX, no console)
requirements.txt       # 3 deps: mss, pynput, PySide6
```

## Architecture

```
ImmediPaste (main.py) - not a QWidget, owns the QApplication
  |-- HotkeyBridge (QObject): pynput thread -> Qt signals (QueuedConnection)
  |   |-- region_triggered signal
  |   |-- window_triggered signal
  |   `-- fullscreen_triggered signal
  |-- CaptureOverlay (QWidget): fullscreen overlay for selection
  |-- AnnotationEditor (QWidget): annotation editor with drawing tools
  |   |-- AnnotationToolbar (QWidget): draggable floating toolbar
  |   |-- Drawing tools: freehand, arrow (4 styles), oval, rectangle, text
  |   |-- Undo/redo stack, compositing, coordinate transform
  |   `-- on_image_ready callback from CaptureOverlay when annotation mode on
  |-- SettingsDialog (QDialog): live config editing (debounced auto-save)
  |   |-- HotkeyEdit (QLineEdit subclass): click-to-record hotkey widget
  |   `-- Folder validation: warns on invalid/non-writable save paths
  |-- Config system: JSON with versioned schema + auto-migration
  |-- Single instance lock: tempfile + msvcrt (Win) / fcntl (Unix) + stale timeout
  |-- Capture history: last 5 file paths, shown in tray menu
  `-- Logging: file (rotating 1MB x3) + stderr, writable path fallback
```

### Thread Model

- **Main thread:** Qt event loop, all UI rendering, capture logic
- **Background thread:** `pynput.keyboard.Listener` monitors global hotkeys
- **Bridge:** `HotkeyBridge` emits Qt signals from the pynput thread. Connected with `Qt.QueuedConnection` to marshal to the main thread. **Never call Qt UI from the pynput thread directly** -- will crash with "QPixmap: Cannot be used outside GUI thread" or similar.

### Capture Flows

**Region and window capture:** `trigger_capture()` / `trigger_window_capture()` -> creates `CaptureOverlay` -> overlay shown fullscreen -> user interacts -> `_finish_capture(qimage)` -> `copy_image_to_clipboard()` + `save_qimage()` -> `on_done(filepath, error=None)` callback -> `_on_capture_done()` -> tray notification.

**Fullscreen capture (different):** `trigger_fullscreen()` -> creates `CaptureOverlay` -> calls `overlay.capture_fullscreen_direct()` -> **no overlay shown, no user interaction** -> same `_finish_capture()` path onward. This bypasses the overlay display entirely.

**With annotation mode on:** All three capture modes pass `on_image_ready` callback to `CaptureOverlay`. When set, `_finish_capture()` skips clipboard/save entirely and calls `on_image_ready(qimage)` instead. `ImmediPaste._open_annotation_editor(qimage)` creates `AnnotationEditor` -> user annotates -> Enter composites annotations + clipboard/save -> `_on_capture_done()`. Escape discards. **Nothing is saved or copied to clipboard until the user presses Enter.**

### Single Instance Lock

Uses `{tempdir}/immedipaste.lock` with `msvcrt.locking()` (Windows) or `fcntl.flock()` (Unix). Called at module load time. If another instance is running, the new process calls `sys.exit(0)` silently -- no error message, no QApplication created. **Stale lock timeout:** the lock file contains a timestamp. If the lock is held but the timestamp is older than `LOCK_TIMEOUT_SECONDS` (1 hour), the lock is considered stale and is broken automatically. This prevents permanent blocking after a crash.

### Capture History

Last 5 captures stored in `capture_history` list (`MAX_HISTORY = 5`). Shown in tray menu in reverse order. Oldest dropped silently when a 6th capture arrives. Clicking a tray notification opens the file in the platform's file explorer.

## Capture Modes

### Region Capture
- Opens fullscreen overlay with crosshair cursor
- Drag to select rectangular area
- Dimension label shown during drag
- Press Enter/Space to capture fullscreen instead
- Press Escape or right-click to cancel
- Default hotkey: `<ctrl>+<alt>+<shift>+s`

### Window Capture (Windows-only)
- Opens fullscreen overlay
- Move mouse to highlight window under cursor (blue tint)
- Click to capture highlighted window
- Uses Win32 `EnumWindows` + DWM APIs to detect windows
- Skips: desktop, shell, cloaked (UWP), transparent (`WS_EX_TRANSPARENT`), invisible, the overlay itself
- Gets tight bounds via `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)`
- Uses Win32 `GetCursorPos` (physical coords) instead of Qt coords to avoid logical/physical DPI mismatch
- On non-Windows platforms: shows warning notification and returns early
- Default hotkey: `<ctrl>+<alt>+<shift>+d`

### Fullscreen Capture
- Captures entire primary monitor immediately (no overlay, no user interaction)
- Uses `capture_fullscreen_direct()` -- different flow from region/window
- Default hotkey: `<ctrl>+<alt>+<shift>+f`

## Config System

**Not checked into git.** `config.json` is gitignored and auto-created from `DEFAULT_CONFIG` on first run. No need to ship a default -- `load_config()` handles the missing file case. Config lives next to the executable (or script in dev). Schema is versioned (`config_version` field). When new keys are added to `DEFAULT_CONFIG`, bump `CONFIG_VERSION` and `migrate_config()` auto-fills missing keys on load. Never delete keys from `DEFAULT_CONFIG` without a migration path.

**Current DEFAULT_CONFIG (v4):**
```python
{
  "config_version": 4,
  "save_folder": default_save_folder(),  # platform-specific
  "hotkey_region": "<ctrl>+<alt>+<shift>+s",
  "hotkey_window": "<ctrl>+<alt>+<shift>+d",
  "hotkey_fullscreen": "<ctrl>+<alt>+<shift>+f",
  "format": "jpg",
  "filename_prefix": "immedipaste",
  "save_to_disk": True,
  "launch_on_startup": False,
  "annotate_captures": False,
  "annotate_shift_tool": "arrow",
  "annotate_ctrl_tool": "oval",
  "annotate_alt_tool": "text",
}
```

**Modifier-to-tool mapping:** The `annotate_*_tool` keys control which drawing tool each modifier activates during annotation. Valid values: `"arrow"`, `"oval"`, `"rect"`, `"text"`, `"freehand"`, `"none"` (falls back to toolbar selection). Settings dialog has combo boxes for each modifier.

**Storage path:** Frozen exe: next to `sys.executable`. Dev mode: next to `main.py`.

**Missing fields don't crash:** `config.get("config_version", 1)` assumes v1 if absent. All settings use `.get(key, default)` throughout. Migration auto-fills and saves on next load.

## Key Classes

### HotkeyEdit (QLineEdit subclass, in main.py)
Custom widget for recording hotkey combos. Click to enter recording mode, press key combo, auto-formats for display. Requires at least one modifier key. Stores pynput format internally (`<ctrl>+<alt>+s`), displays user-friendly format (`Ctrl + Alt + S`). Emits `changed` signal.

### CaptureOverlay (QWidget, in capture.py)
Plain QWidget (not QDialog) shown fullscreen. Holds `screenshot_qimage`, `screenshot_pixmap` (unmodified), and `dimmed_pixmap` (darkened). `on_done` callback invoked after `close()`. When `on_image_ready` is set (annotation mode), `_finish_capture` hands off the QImage without saving/copying. Reference cleared to `None` in `_on_capture_done()`.

### AnnotationEditor (QWidget, in annotation_editor.py)
Fullscreen annotation editor opened when `annotate_captures` is enabled. Displays captured image with dark surround. Drawing tools: freehand (default drag), arrow (Shift+drag, 3 styles: filled/hollow/double, line/box drag modes), oval (Ctrl+drag), text (Alt+click, default), rectangle (toolbar). Modifier-to-tool mapping configurable via `annotate_*_tool` config keys and settings UI combo boxes. Draggable toolbar with tool buttons, arrow style/mode selectors, color picker (default red), stroke width (1-20), font size (8-72), undo/redo, save/cancel buttons. Text annotations: click to place, drag to reposition. Coordinates stored in image-space; screen-to-image transform via `_scale` factor. Enter composites annotations onto QImage copy and saves/copies; Escape discards. `_saved` flag prevents double-fire on closeEvent.

### Tray Icon
Drawn programmatically with `QPainter` on a `QPixmap` (camera icon). No image asset file -- if you want to change the icon, edit `create_tray_icon()` in `main.py`.

## Error Handling

### Errors Shown to User (via tray notification)
- Screenshot/capture failure
- Save failure during capture
- Clipboard failure during capture ("Copied to disk but clipboard copy failed")
- Window capture on non-Windows platform
- Hotkey listener restart failure after settings dialog ("Hotkeys stopped working. Try restarting the app.")

### Errors Logged Only (silent to user)
- Config save failures -- settings appear to work but may not persist
- Hotkey parse failures -- each hotkey falls back to its own default independently, logged with the bad value
- Startup registry update failures
- File explorer open failures
- Save folder creation failure at app start (only fails visibly during capture)

### Error Precedence in _finish_capture()
1. Neither clipboard nor save succeeded: "Capture failed: could not copy to clipboard or save to disk" (or just "...to clipboard" when `save_to_disk=False`)
2. Save succeeded but clipboard failed: "Copied to disk but clipboard copy failed"
3. Both succeeded: `error=None`
4. User cancelled: `error="cancelled"` -- `_on_capture_done` resets state silently, no notification

**Note:** Clipboard errors don't prevent save. Save always attempted if `save_to_disk=True`.

## Platform Notes

- **Window capture** (`window_utils.py`) is Windows-only. On other platforms, `trigger_window_capture()` shows a warning notification and returns early.
- **Launch on startup** uses Windows Registry (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`). No-op on other platforms. Silently ignored when running from source (not frozen exe) -- logs a debug message.
- **Log file location** tries: app dir -> `%APPDATA%/ImmediPaste` (Win) or `~/.local/state/immedipaste` (Unix) -> temp dir.
- **Font in capture overlay** uses `QFontDatabase.systemFont(FixedFont)` -- no hardcoded font names.
- **Default save folder:** Windows: `~/OneDrive/Pictures/Screenshots` (if exists), else `~/Pictures/Screenshots`. macOS: `~/Desktop`. Linux: `~/Pictures/Screenshots`.
- **File explorer:** Windows: `explorer /select,{path}`. macOS: `open -R {path}`. Linux: `xdg-open {dirname}`.
- **Multi-monitor:** `mss.monitors[0]` is the combined virtual screen on Windows. On macOS, mss returns each display separately -- `monitors[0]` is still the "all-in-one" virtual screen but compositing behavior differs. On Linux/X11 it works like Windows; on Wayland, mss has limited support. **Not verified on non-Windows -- treat as untested.**
- **Image quality:** JPEG and WebP hardcoded to quality 85 in `platform_utils.save_qimage()`. No config key for this.

## Code Conventions

- **2-space indent** throughout
- **Type hints** on all function signatures (`from __future__ import annotations` in every module)
- **Hotkey format:** pynput syntax, e.g. `<ctrl>+<alt>+<shift>+s`
- **Error handling:** all I/O wrapped in try/except. See Error Handling section for which errors are shown vs silent.
- **No Unicode in git commits** (Windows console encoding issues)
- **No emojis** in code, comments, or user-facing strings
- **String formatting:** mixed `%` and `.format()` style (no f-strings)

## Testing

```bash
python -m pytest -v                    # Run all tests
python -m pytest test_integration.py   # Integration tests only
python -m pytest test_capture.py -k save  # Filter by name
```

Tests mock `mss` (no display needed), clipboard operations, and file I/O. QApplication is created once per test module.

### What's Tested (106 tests)
| Module | Tests | Covers |
|--------|-------|--------|
| test_annotation_editor.py | 34 | Data model, compositing, undo/redo, coordinate conversion, save/cancel, tool-from-modifiers (default + custom + none fallback), toolbar tooltips |
| test_capture.py | 10 | Save formats (jpg/png/webp), custom prefix, folder creation, invalid paths, callback flow, cancel |
| test_config.py | 7 | Load default, read existing, corruption recovery, write errors, required keys |
| test_hotkey_edit.py | 8 | Key-to-pynput: letters, digits, F-keys, specials, navigation, arrows |
| test_log.py | 7 | Logger creation, handlers, naming, deduplication, log dir resolution |
| test_platform_utils.py | 4 | Clipboard success/failure, default folder platform checks |
| test_integration.py | 17 | Full capture pipeline, clipboard-only mode, double-trigger blocking, history limit, config migration (v2->v3->v4), on_image_ready callback routing |
| test_improvements.py | 20 | Lock file stale detection (mocked locking), stale break failure, no-timestamp fallback, config save debounce, dialog close flush, folder validation (incl. relative paths), listener error handling, tray icon constants |

### What's NOT Tested
- pynput.Listener threading behavior
- HotkeyEdit recording (keyPress, focusOut, mousePressEvent)
- Win32 APIs (EnumWindows, DWM) in window_utils.py
- Settings dialog UI interactions (form binding, browse button, auto-save)
- Tray menu population and clicks
- Notification display and click handling
- Registry operations (launch on startup)
- Multi-monitor screenshot capture
- Programmatic tray icon rendering
- Settings live-reload (listener restart)
- Annotation editor mouse interaction (would need pytest-qt)
- Annotation toolbar dragging and tool button clicks
- Text tool inline QLineEdit interaction
- Arrow head geometry rendering accuracy

Would need `pytest-qt` for Qt widget testing and a Windows-specific environment for Win32 tests.

## Building

```bash
pip install -r requirements.txt pyinstaller
pyinstaller ImmediPaste.spec
# Output: dist/ImmediPaste.exe
```

The spec file excludes unused Qt modules (QtNetwork, QtQml, QtQuick, QtSvg, and ~20 more) to minimize binary size. UPX compression is enabled. `console=False` suppresses the Windows console window.

## Known Gotchas

1. **Settings dialog stops hotkey listener.** `open_settings()` calls `_listener.stop()`, dialog is modal, listener restarts on close. Intentional -- prevents hotkeys firing while editing them. But if debugging "hotkeys stopped working," check if settings dialog is open.

2. **Hotkey parse failures are silent but isolated.** Invalid hotkey string in config.json -> `log.error()` + fall back to that hotkey's default. Only the broken hotkey is affected; valid hotkeys keep their custom values. User never notified via UI.

3. **Save folder validated at settings time.** SettingsDialog validates the save folder path on every change: shows a warning label if the folder doesn't exist and can't be created, or if it exists but isn't writable. Final validation still happens during capture in `_save()`.

4. **Config save is debounced.** `_emit_change()` starts a `QTimer` (150ms). Rapid edits are batched into a single `save_config()` call. If app crashes mid-save, last change could be lost, but redundant writes during keystroke bursts are eliminated.

5. **Notification click assumes file still exists.** `_on_notification_clicked()` checks `os.path.exists()` before opening. If file was deleted, silently does nothing.

6. **`_overlay` reference lifecycle.** Set to `None` in `_on_capture_done()`. `self.capturing` flag prevents double-triggers, but the QWidget may still exist in memory until Python GC runs.

7. **Stale lock file auto-recovery.** Lock file contains a timestamp. If the lock is older than `LOCK_TIMEOUT_SECONDS` (1 hour), it's automatically broken on next startup. Manual deletion is no longer needed for crash recovery.

8. **Annotation editor Enter vs text input.** When a text `QLineEdit` is active, Enter confirms the text annotation (consumed by `returnPressed`). When no text input is active, Enter saves the composited image. Escape cancels text input if active, otherwise closes the editor.

9. **Modifier key conflicts in annotation editor.** Ctrl+drag = oval tool, Ctrl+Z = undo. These don't conflict because Ctrl+Z is keyboard-only and fires on `keyPressEvent`, while Ctrl+drag is a mouse event. Undo is also blocked while `_drawing` is True.

10. **Annotation coordinates are image-space.** All annotation points are stored relative to the original QImage, not the screen. The editor uses `_scale` factor and `_image_rect` offset for display. During compositing (`_composite()`), no transform is needed.

## Common Tasks

**Adding a new setting:**
1. Add key + default value to `DEFAULT_CONFIG` in `main.py`
2. Bump `CONFIG_VERSION`
3. Add UI widget in `SettingsDialog.__init__()`, wire up `_emit_change`
4. Add to `SettingsDialog.get_config()` return dict
5. Use `self.config.get("key", default)` wherever the setting is consumed

**Adding a new capture mode:**
1. Add signal to `HotkeyBridge`
2. Add `trigger_*()` method to `ImmediPaste`
3. Connect signal in `run()` with `QueuedConnection`
4. Add hotkey config key to `DEFAULT_CONFIG` + bump version
5. Wire up in `_start_hotkey_listener()`
6. If it uses the overlay: follow region/window pattern (`overlay.start()`)
7. If it's instant (like fullscreen): call a direct method, skip overlay display

**Debugging "app won't start":**
1. Check for stale lock file: `{tempdir}/immedipaste.lock`
2. Check if another instance is running (tray icon present)
3. Check log file for errors (see Platform Notes for log locations)

**Debugging "hotkeys don't work":**
1. Check if settings dialog is open (listener stopped while modal)
2. Check log for hotkey parse errors (invalid format in config.json)
3. Verify config.json has valid pynput syntax for hotkey fields

## Pre-Commit Checklist

**Do ALL of these before every commit:**

1. **Backfill changelog hashes.** Check `CHANGELOG.md` for any `-------` placeholders. Replace with actual commit hashes from `git log`.
2. **Add changelog entry if notable.** If this commit includes a new feature, architectural change, config version bump, or build/deploy change, add an entry with `-------` as the hash (will be backfilled next commit).
3. **No Unicode in commit message.** No emojis, checkmarks, arrows, or special symbols.
4. **Run tests.** `python -m pytest -v` -- don't commit if tests fail.

## Version History

See `CHANGELOG.md` for full commit history organized by config version era (v2 current, v1, pre-Qt tkinter era). Useful context when writing new config migrations or understanding why something was built a certain way.
