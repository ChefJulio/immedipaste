# Changelog

All notable changes to ImmediPaste, in reverse chronological order.

Format: `hash` or `-------` (pending) followed by description. Pending hashes get backfilled on the next changelog update.

## Config v2 (current)

- `0df6889` Fix lock truncation, cancel notification, hotkey parse, tray labels, error messages
  - Lock file opened with "r+" (no truncation) to preserve timestamp for other instances
  - Cancel no longer shows false "Copied to clipboard" notification (uses "cancelled" sentinel)
  - Each hotkey parsed independently -- one bad hotkey no longer resets all three to defaults
  - Tray menu labels now reflect user-configured hotkeys (format_hotkey_display helper)
  - Error message for clipboard-only mode no longer references disk save
  - Capture filename includes milliseconds to prevent same-second overwrites
  - Clipboard-only test now mocks clipboard and checks exact success message + icon type
- `0df6889` Fix stale lock detection, registry handle leak, dialog positioning, logger propagation
  - Stale lock detection: read timestamp before opening with "w" (which truncates the file)
  - Registry handle leak: use try/finally for winreg.CloseKey, log warning in dev mode
  - Settings dialog positioned after layout is built (correct height calculation)
  - trigger_fullscreen stores overlay in self._overlay (consistent with region/window)
  - set_launch_on_startup only called when the setting actually changes
  - Logger propagate=False prevents duplicate output when root logger is configured
  - Lock tests rewritten with mocked locking to exercise stale detection code paths
  - Added 2 new tests: no-timestamp fallback, stale break failure (66 total)
- `bfa9d67` Code quality improvements: type hints, lock timeout, debounce, folder validation
  - Added type hints (`from __future__ import annotations`) to all source modules
  - Lock file now stores timestamp; stale locks (>1h) auto-broken on startup
  - Config saves debounced (150ms QTimer) to prevent rapid writes during edits
  - Settings dialog validates save folder path on change (warns if invalid/non-writable)
  - Hotkey listener stop/restart wrapped in try/except with user-facing error notification
  - Tray icon drawing coordinates extracted to named constants
  - Added 18 new tests (test_improvements.py): lock timeout, debounce, dialog close flush, folder validation, listener errors, tray icon
- `351938d` Add changelog maintenance workflow with placeholder hash convention
- `1aada6f` Gitignore config.json, track ImmediPaste.spec
  - config.json removed from repo (auto-created from DEFAULT_CONFIG on first run)
  - ImmediPaste.spec was accidentally caught by *.spec gitignore glob -- now tracked
- `30da872` Expand CLAUDE.md with comprehensive codebase docs, add CHANGELOG.md
- `a6fae76` Add CLAUDE.md, block window capture on non-Windows platforms
- `408734a` Add config versioning (v2), log path fallback, integration tests, gitignore log
  - Introduced `config_version` field and `migrate_config()` auto-fill
  - Added `save_to_disk` and `launch_on_startup` keys
- `ef84fd0` Add logging, error handling, tests, and cross-platform font fix
  - Rotating file handler (1MB x3) + stderr
  - Log path fallback chain: app dir -> appdata/state dir -> temp dir
  - Replaced hardcoded font with `QFontDatabase.systemFont(FixedFont)`

## Config v1

- `1bba7b5` Add hotkey recorder (HotkeyEdit widget), auto-save settings, reduce exe size
  - PyInstaller spec excludes unused Qt modules
- `85b5df2` Add opt-in launch on startup setting (Windows Registry)
- `34aaa09` Add window capture mode (Ctrl+Alt+Shift+D)
  - Win32 EnumWindows + DWM APIs for window detection
  - Highlight-under-cursor UX in overlay
- `2ef7c40` Migrate from tkinter to PySide6 (Qt)
  - Major rewrite: replaced tkinter with PySide6 for all UI
  - HotkeyBridge signal marshalling pattern introduced

## Pre-Qt (tkinter era)

- `5f73cad` Add capture history (last 5) and clipboard-only notification
- `65216a7` Add clipboard-only mode, filename prefix to settings
- `64d1caa` Update README with download links and better feature descriptions
- `8a5e393` Prevent multiple instances from running (tempfile lock)
- `19a0241` Hot-reload settings without restart (listener restart on config change)
- `f83f2c4` Auto-create default config when missing
- `eae2c39` Add Windows code signing to CI build
- `b7d5422` Cross-platform support and CI build pipeline
- `62d9728` Add format selection (jpg/png/webp), fullscreen hotkey, settings dialog
- `5711edd` Initial commit - screenshot capture tool
