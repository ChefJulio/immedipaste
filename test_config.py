"""Tests for config loading, saving, and error recovery."""

import json
import os
import pytest

# Patch APP_DIR/CONFIG_PATH before importing main
import main


@pytest.fixture
def config_file(tmp_path, monkeypatch):
  """Redirect config I/O to a temp directory."""
  path = tmp_path / "config.json"
  monkeypatch.setattr(main, "CONFIG_PATH", str(path))
  return path


class TestLoadConfig:
  def test_creates_default_when_missing(self, config_file):
    assert not config_file.exists()
    cfg = main.load_config()
    assert config_file.exists()
    assert cfg["format"] == "jpg"
    assert cfg["save_to_disk"] is True
    assert cfg["hotkey_region"] == "<ctrl>+<alt>+<shift>+s"

  def test_reads_existing_config(self, config_file):
    config_file.write_text(json.dumps({"format": "png", "save_folder": "/tmp"}))
    cfg = main.load_config()
    assert cfg["format"] == "png"
    assert cfg["save_folder"] == "/tmp"

  def test_recovers_from_corrupted_json(self, config_file):
    config_file.write_text("{bad json !!!")
    cfg = main.load_config()
    # Should fall back to defaults
    assert cfg == main.DEFAULT_CONFIG
    # Should have overwritten the corrupt file
    restored = json.loads(config_file.read_text())
    assert restored["format"] == "jpg"

  def test_returns_defaults_on_read_error(self, config_file, monkeypatch):
    # Point to a path that exists but can't be read (directory)
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_file.parent))
    cfg = main.load_config()
    assert cfg == main.DEFAULT_CONFIG


class TestSaveConfig:
  def test_writes_valid_json(self, config_file):
    main.save_config({"format": "webp", "save_folder": "/home"})
    data = json.loads(config_file.read_text())
    assert data["format"] == "webp"

  def test_handles_write_error_gracefully(self, config_file, monkeypatch):
    # Point to an invalid path
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_file.parent / "no" / "such" / "dir" / "config.json"))
    # Should not raise
    main.save_config({"format": "png"})


class TestDefaultConfig:
  def test_has_all_required_keys(self):
    required = [
      "save_folder", "hotkey_region", "hotkey_window",
      "hotkey_fullscreen", "format", "filename_prefix",
      "save_to_disk", "launch_on_startup",
    ]
    for key in required:
      assert key in main.DEFAULT_CONFIG, f"Missing key: {key}"
