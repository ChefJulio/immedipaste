# Changelog

All notable changes to ImmediPaste, in reverse chronological order.

## Config v2 (current)

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
