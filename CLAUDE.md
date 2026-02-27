# ImmediPaste

Lightweight screenshot tool. Captures screen regions, windows, or fullscreen and puts them on the clipboard instantly. Runs as a system tray app with global hotkeys.

## Tech Stack

- **Python 3.10+** with **PySide6** (Qt6) for UI
- **mss** for multi-monitor screenshot capture
- **pynput** for global hotkey listening
- **PyInstaller** for building standalone executables

## Project Structure

```
main.py             # Entry point, tray icon, settings dialog, config, hotkey bridge
capture.py          # CaptureOverlay widget - region/window/fullscreen capture + save
log.py              # Centralized logging with rotating file handler + fallback dirs
platform_utils.py   # Cross-platform clipboard and default folder detection
window_utils.py     # Windows-only window detection via Win32 ctypes/DWM APIs
config.json         # User settings (auto-created, auto-migrated)
test_*.py           # pytest test suite (46 tests)
```

## Architecture

```
ImmediPaste (main.py)
  |-- HotkeyBridge: pynput thread -> Qt signals (QueuedConnection)
  |-- CaptureOverlay: fullscreen QWidget overlay for selection
  |-- SettingsDialog: live config editing (auto-saves on change)
  |-- Config system: JSON with versioned schema + auto-migration
  `-- Logging: file (rotating 1MB x3) + stderr, writable path fallback
```

**Key pattern:** pynput runs on a background thread. `HotkeyBridge` emits Qt signals to marshal hotkey events to the main thread. Never call Qt UI from the pynput thread directly.

**Capture flow:** `trigger_*()` -> `CaptureOverlay` -> `_finish_capture()` -> `copy_image_to_clipboard()` + `_save()` -> `on_done(filepath, error=None)` callback -> tray notification.

## Config System

Config lives next to the executable (or script in dev). Schema is versioned (`config_version` field). When new keys are added to `DEFAULT_CONFIG`, bump `CONFIG_VERSION` and `migrate_config()` auto-fills missing keys on load. Never delete keys from `DEFAULT_CONFIG` without a migration path.

## Code Conventions

- **2-space indent** throughout
- **Hotkey format:** pynput syntax, e.g. `<ctrl>+<alt>+<shift>+s`
- **Error handling:** all I/O wrapped in try/except, errors logged + surfaced to user via tray notifications. `copy_image_to_clipboard()` returns bool, `_save()` returns filepath or None.
- **No Unicode in git commits** (Windows console encoding issues)
- **No emojis** in code, comments, or user-facing strings

## Platform Notes

- **Window capture** (`window_utils.py`) is Windows-only. On other platforms, `trigger_window_capture()` shows a warning notification and returns early.
- **Launch on startup** uses Windows Registry (`HKCU\...\Run`). No-op on other platforms.
- **Log file location** tries: app dir -> `%APPDATA%/ImmediPaste` (Win) or `~/.local/state/immedipaste` (Unix) -> temp dir.
- **Font in capture overlay** uses `QFontDatabase.systemFont(FixedFont)` -- no hardcoded font names.

## Testing

```bash
python -m pytest -v                    # Run all tests
python -m pytest test_integration.py   # Integration tests only
python -m pytest test_capture.py -k save  # Filter by name
```

Tests mock `mss` (no display needed), clipboard operations, and file I/O. QApplication is created once per test module.

## Building

```bash
pip install -r requirements.txt pyinstaller
pyinstaller ImmediPaste.spec
# Output: dist/ImmediPaste.exe
```

The spec file excludes unused Qt modules (QtNetwork, QtQml, QtQuick, QtSvg, etc.) to minimize binary size. UPX compression is enabled.

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
