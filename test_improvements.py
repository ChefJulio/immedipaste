"""Tests for lock file timeout, settings debounce, and folder validation."""

import json
import os
import time
from unittest.mock import patch, MagicMock, PropertyMock

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import main
from main import (
  acquire_single_instance, SettingsDialog, ImmediPaste,
  LOCK_TIMEOUT_SECONDS, SAVE_DEBOUNCE_MS,
)


# -- Lock file timeout -------------------------------------------------------

class TestLockFileTimeout:
  def _patch_tempdir(self, monkeypatch, tmp_path):
    import tempfile as _tempfile
    monkeypatch.setattr(_tempfile, "gettempdir", lambda: str(tmp_path))

  def test_writes_timestamp_on_acquire(self, tmp_path, monkeypatch):
    self._patch_tempdir(monkeypatch, tmp_path)
    lock_path = str(tmp_path / "immedipaste.lock")

    # Capture what _write_timestamp writes
    written = []
    original_write = open.__class__

    lock = acquire_single_instance()
    try:
      # Verify lock file exists and has content
      assert os.path.exists(lock_path)
      # On Windows, we can't read a locked file from another handle,
      # so verify the lock file size is non-zero (timestamp was written)
      assert os.path.getsize(lock_path) > 0
    finally:
      lock.close()

  def test_stale_lock_is_broken(self, tmp_path, monkeypatch):
    self._patch_tempdir(monkeypatch, tmp_path)
    lock_path = str(tmp_path / "immedipaste.lock")

    # Write a very old timestamp
    with open(lock_path, "w") as f:
      f.write(str(time.time() - LOCK_TIMEOUT_SECONDS - 100))

    # Should succeed (stale lock broken)
    lock = acquire_single_instance()
    try:
      assert lock is not None
    finally:
      lock.close()

  def test_fresh_lock_blocks(self, tmp_path, monkeypatch):
    self._patch_tempdir(monkeypatch, tmp_path)

    # Acquire first lock
    lock1 = acquire_single_instance()
    try:
      # Second acquire should exit
      with pytest.raises(SystemExit):
        acquire_single_instance()
    finally:
      lock1.close()


# -- Config save debounce ----------------------------------------------------

class TestSettingsDebounce:
  def test_debounce_timer_exists(self, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CONFIG_PATH", str(tmp_path / "config.json"))
    config = dict(main.DEFAULT_CONFIG)
    config["save_folder"] = str(tmp_path)
    dialog = SettingsDialog(config)
    assert hasattr(dialog, "_save_timer")
    assert isinstance(dialog._save_timer, QTimer)
    assert dialog._save_timer.isSingleShot()
    assert dialog._save_timer.interval() == SAVE_DEBOUNCE_MS

  def test_emit_change_starts_timer(self, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CONFIG_PATH", str(tmp_path / "config.json"))
    config = dict(main.DEFAULT_CONFIG)
    config["save_folder"] = str(tmp_path)
    called = []
    dialog = SettingsDialog(config, on_change=lambda c: called.append(c))
    dialog._emit_change()
    # Timer should be active but callback not yet called
    assert dialog._save_timer.isActive()
    assert len(called) == 0

  def test_flush_change_calls_on_change(self, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CONFIG_PATH", str(tmp_path / "config.json"))
    config = dict(main.DEFAULT_CONFIG)
    config["save_folder"] = str(tmp_path)
    called = []
    dialog = SettingsDialog(config, on_change=lambda c: called.append(c))
    dialog._flush_change()
    assert len(called) == 1
    assert "save_folder" in called[0]

  def test_done_flushes_pending_timer(self, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CONFIG_PATH", str(tmp_path / "config.json"))
    config = dict(main.DEFAULT_CONFIG)
    config["save_folder"] = str(tmp_path)
    called = []
    dialog = SettingsDialog(config, on_change=lambda c: called.append(c))
    # Start the debounce timer (simulates a pending edit)
    dialog._emit_change()
    assert dialog._save_timer.isActive()
    assert len(called) == 0
    # Closing the dialog should flush the pending change
    dialog.done(0)
    assert not dialog._save_timer.isActive()
    assert len(called) == 1

  def test_done_noop_when_no_pending_timer(self, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CONFIG_PATH", str(tmp_path / "config.json"))
    config = dict(main.DEFAULT_CONFIG)
    config["save_folder"] = str(tmp_path)
    called = []
    dialog = SettingsDialog(config, on_change=lambda c: called.append(c))
    # No pending edits -- done should not call on_change
    dialog.done(0)
    assert len(called) == 0


# -- Save folder validation --------------------------------------------------

class TestFolderValidation:
  def test_valid_folder_no_warning(self, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CONFIG_PATH", str(tmp_path / "config.json"))
    config = dict(main.DEFAULT_CONFIG)
    config["save_folder"] = str(tmp_path)
    dialog = SettingsDialog(config)
    dialog.folder_edit.setText(str(tmp_path))
    dialog._validate_folder()
    assert dialog.folder_warning.isHidden()

  def test_nonexistent_folder_shows_warning(self, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CONFIG_PATH", str(tmp_path / "config.json"))
    config = dict(main.DEFAULT_CONFIG)
    bad_path = str(tmp_path / "no" / "such" / "deep" / "path")
    config["save_folder"] = bad_path
    dialog = SettingsDialog(config)
    dialog.folder_edit.setText(bad_path)
    dialog._validate_folder()
    assert not dialog.folder_warning.isHidden()
    assert "cannot be created" in dialog.folder_warning.text().lower()

  def test_creatable_folder_no_warning(self, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CONFIG_PATH", str(tmp_path / "config.json"))
    config = dict(main.DEFAULT_CONFIG)
    # Parent exists, child doesn't -- folder can be created on capture
    new_folder = str(tmp_path / "new_sub")
    config["save_folder"] = new_folder
    dialog = SettingsDialog(config)
    dialog.folder_edit.setText(new_folder)
    dialog._validate_folder()
    assert dialog.folder_warning.isHidden()

  def test_empty_folder_no_warning(self, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CONFIG_PATH", str(tmp_path / "config.json"))
    config = dict(main.DEFAULT_CONFIG)
    config["save_folder"] = ""
    dialog = SettingsDialog(config)
    dialog.folder_edit.setText("")
    dialog._validate_folder()
    assert dialog.folder_warning.isHidden()

  def test_relative_path_resolves_correctly(self, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CONFIG_PATH", str(tmp_path / "config.json"))
    config = dict(main.DEFAULT_CONFIG)
    config["save_folder"] = str(tmp_path)
    dialog = SettingsDialog(config)
    # A bare name like "screenshots" should resolve relative to cwd
    # and not crash on os.path.dirname returning ""
    dialog.folder_edit.setText("screenshots")
    dialog._validate_folder()
    # Should not crash -- the warning state depends on cwd writability
    # but the key thing is no exception is raised


# -- Hotkey listener error handling -------------------------------------------

class TestListenerErrorHandling:
  def _make_app(self, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CONFIG_PATH", str(tmp_path / "config.json"))
    config = dict(main.DEFAULT_CONFIG)
    config["save_folder"] = str(tmp_path)
    main.save_config(config)
    ip = ImmediPaste()
    ip.tray_icon = MagicMock()
    return ip

  def test_open_settings_handles_listener_stop_error(self, tmp_path, monkeypatch):
    ip = self._make_app(tmp_path, monkeypatch)
    ip.hotkey_bridge = main.HotkeyBridge()

    # Mock listener that raises on stop
    mock_listener = MagicMock()
    mock_listener.stop.side_effect = RuntimeError("stop failed")
    ip._listener = mock_listener

    # Mock SettingsDialog to avoid screen geometry access
    mock_dialog = MagicMock()
    with patch("main.SettingsDialog", return_value=mock_dialog):
      ip.open_settings()

  def test_open_settings_handles_listener_start_error(self, tmp_path, monkeypatch):
    ip = self._make_app(tmp_path, monkeypatch)
    ip.hotkey_bridge = main.HotkeyBridge()

    mock_listener = MagicMock()
    ip._listener = mock_listener

    mock_dialog = MagicMock()
    # Make _start_hotkey_listener raise
    with patch("main.SettingsDialog", return_value=mock_dialog), \
         patch.object(ip, "_start_hotkey_listener", side_effect=RuntimeError("start failed")):
      ip.open_settings()

    # Should show warning notification
    ip.tray_icon.showMessage.assert_called_once()
    msg = ip.tray_icon.showMessage.call_args[0][1]
    assert "restart" in msg.lower() or "hotkey" in msg.lower()

  def test_reload_settings_handles_errors(self, tmp_path, monkeypatch):
    ip = self._make_app(tmp_path, monkeypatch)
    ip.hotkey_bridge = main.HotkeyBridge()

    mock_listener = MagicMock()
    mock_listener.stop.side_effect = RuntimeError("stop failed")
    ip._listener = mock_listener

    # Should not raise even if stop fails
    ip.reload_settings()


# -- Tray icon constants ------------------------------------------------------

class TestTrayIconConstants:
  def test_icon_constants_defined(self):
    assert main._ICON_SIZE == 64
    assert isinstance(main._ICON_BODY_RECT, tuple)
    assert len(main._ICON_BODY_RECT) == 4
    assert isinstance(main._ICON_LENS_OUTER, tuple)
    assert isinstance(main._ICON_LENS_INNER, tuple)
    assert isinstance(main._ICON_FLASH_RECT, tuple)

  def test_create_tray_icon_returns_icon(self):
    from PySide6.QtGui import QIcon
    icon = main.create_tray_icon()
    assert isinstance(icon, QIcon)
    assert not icon.isNull()
