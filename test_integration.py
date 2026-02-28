"""Integration tests for the capture pipeline and config migration."""

import json
import os
from unittest.mock import patch, MagicMock

import pytest
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

app = QApplication.instance() or QApplication([])

import main
from main import ImmediPaste, migrate_config, CONFIG_VERSION


# -- Integration: trigger -> overlay -> callback ----------------------------

class TestCapturePipeline:
  """Test the full trigger -> CaptureOverlay -> _on_capture_done wiring."""

  def _make_app(self, tmp_path, monkeypatch):
    """Create an ImmediPaste instance with config pointing to tmp_path."""
    monkeypatch.setattr(main, "CONFIG_PATH", str(tmp_path / "config.json"))
    config = dict(main.DEFAULT_CONFIG)
    config["save_folder"] = str(tmp_path)
    config["save_to_disk"] = True
    main.save_config(config)
    ip = ImmediPaste()
    ip.tray_icon = MagicMock()
    return ip

  def test_fullscreen_capture_saves_and_calls_done(self, tmp_path, monkeypatch):
    ip = self._make_app(tmp_path, monkeypatch)

    # Mock the screenshot to avoid needing a display
    fake_img = QImage(200, 150, QImage.Format.Format_ARGB32)
    fake_img.fill(QColor(0, 128, 255))

    with patch("capture.mss.mss") as mock_mss, \
         patch("capture.copy_image_to_clipboard", return_value=True):
      ctx = MagicMock()
      ctx.monitors = [{"left": 0, "top": 0, "width": 200, "height": 150}]
      grab_result = MagicMock()
      grab_result.bgra = bytes(200 * 150 * 4)
      grab_result.width = 200
      grab_result.height = 150
      ctx.grab.return_value = grab_result
      mock_mss.return_value.__enter__ = lambda s: ctx
      mock_mss.return_value.__exit__ = MagicMock(return_value=False)

      ip.trigger_fullscreen()

    # Should no longer be capturing
    assert ip.capturing is False
    # Verify success notification (not error)
    ip.tray_icon.showMessage.assert_called_once()
    call_args = ip.tray_icon.showMessage.call_args[0]
    assert call_args[0] == "ImmediPaste"
    assert call_args[2] == QSystemTrayIcon.MessageIcon.Information

  def test_fullscreen_capture_clipboard_only(self, tmp_path, monkeypatch):
    ip = self._make_app(tmp_path, monkeypatch)
    ip.config["save_to_disk"] = False

    with patch("capture.mss.mss") as mock_mss, \
         patch("capture.copy_image_to_clipboard", return_value=True):
      ctx = MagicMock()
      ctx.monitors = [{"left": 0, "top": 0, "width": 100, "height": 100}]
      grab_result = MagicMock()
      grab_result.bgra = bytes(100 * 100 * 4)
      grab_result.width = 100
      grab_result.height = 100
      ctx.grab.return_value = grab_result
      mock_mss.return_value.__enter__ = lambda s: ctx
      mock_mss.return_value.__exit__ = MagicMock(return_value=False)

      ip.trigger_fullscreen()

    assert ip.capturing is False
    assert len(ip.capture_history) == 0  # No file saved
    ip.tray_icon.showMessage.assert_called_once()
    # Verify success notification (Information icon, "Copied to clipboard")
    call_args = ip.tray_icon.showMessage.call_args[0]
    assert call_args[1] == "Copied to clipboard"
    assert call_args[2] == QSystemTrayIcon.MessageIcon.Information

  def test_screenshot_failure_shows_error(self, tmp_path, monkeypatch):
    ip = self._make_app(tmp_path, monkeypatch)

    with patch("capture.mss.mss", side_effect=RuntimeError("no display")):
      ip.trigger_fullscreen()

    assert ip.capturing is False
    ip.tray_icon.showMessage.assert_called_once()
    call_args = ip.tray_icon.showMessage.call_args
    assert "failed" in call_args[0][1].lower() or "Screenshot" in call_args[0][1]

  def test_double_trigger_blocked(self, tmp_path, monkeypatch):
    ip = self._make_app(tmp_path, monkeypatch)
    ip.capturing = True
    # Should be a no-op when already capturing
    ip.trigger_capture()
    ip.trigger_window_capture()
    ip.trigger_fullscreen()
    assert ip.capturing is True  # unchanged
    ip.tray_icon.showMessage.assert_not_called()

  def test_capture_history_limited(self, tmp_path, monkeypatch):
    ip = self._make_app(tmp_path, monkeypatch)
    # Simulate many captures
    for i in range(10):
      ip._on_capture_done(f"/tmp/shot_{i}.png")
    assert len(ip.capture_history) == main.MAX_HISTORY

  def test_error_callback_shows_critical_notification(self, tmp_path, monkeypatch):
    ip = self._make_app(tmp_path, monkeypatch)
    ip._on_capture_done(None, error="Something broke")
    assert ip.capturing is False
    call_args = ip.tray_icon.showMessage.call_args
    assert "Something broke" in call_args[0][1]

  def test_window_capture_blocked_on_non_windows(self, tmp_path, monkeypatch):
    ip = self._make_app(tmp_path, monkeypatch)
    monkeypatch.setattr("main.platform.system", lambda: "Linux")
    ip.trigger_window_capture()
    assert ip.capturing is False  # never entered capturing state
    ip.tray_icon.showMessage.assert_called_once()
    msg = ip.tray_icon.showMessage.call_args[0][1]
    assert "Windows" in msg


# -- Config migration -------------------------------------------------------

class TestConfigMigration:
  def test_adds_missing_keys(self):
    old_config = {"save_folder": "~/Pictures", "format": "png"}
    changed = migrate_config(old_config)
    assert changed is True
    assert "hotkey_region" in old_config
    assert "hotkey_window" in old_config
    assert "hotkey_fullscreen" in old_config
    assert "save_to_disk" in old_config
    assert "config_version" in old_config
    # Existing values are preserved
    assert old_config["save_folder"] == "~/Pictures"
    assert old_config["format"] == "png"

  def test_bumps_version(self):
    old_config = dict(main.DEFAULT_CONFIG)
    old_config["config_version"] = 1
    changed = migrate_config(old_config)
    assert changed is True
    assert old_config["config_version"] == CONFIG_VERSION

  def test_no_change_when_current(self):
    current_config = dict(main.DEFAULT_CONFIG)
    changed = migrate_config(current_config)
    assert changed is False

  def test_load_triggers_migration(self, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CONFIG_PATH", str(tmp_path / "config.json"))
    # Write a v1 config missing new keys
    old = {"save_folder": "~/Desktop", "format": "jpg", "filename_prefix": "shot"}
    (tmp_path / "config.json").write_text(json.dumps(old))

    config = main.load_config()
    assert config["config_version"] == CONFIG_VERSION
    assert config["hotkey_region"] == "<ctrl>+<alt>+<shift>+s"
    assert config["save_folder"] == "~/Desktop"  # preserved

    # File should have been updated on disk
    on_disk = json.loads((tmp_path / "config.json").read_text())
    assert on_disk["config_version"] == CONFIG_VERSION
