"""Tests for capture save logic and error handling."""

import os
import pytest
from unittest.mock import MagicMock, patch

from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication

# Need a QApplication instance for QImage operations
app = QApplication.instance() or QApplication([])


def make_test_image(w=100, h=100):
  """Create a small solid-color QImage for testing."""
  img = QImage(w, h, QImage.Format.Format_ARGB32)
  img.fill(QColor(255, 0, 0))
  return img


class TestSave:
  def test_saves_jpg(self, tmp_path):
    from capture import CaptureOverlay
    overlay = CaptureOverlay(save_folder=str(tmp_path), fmt="jpg")
    img = make_test_image()
    path = overlay._save(img)
    assert path is not None
    assert path.endswith(".jpg")
    assert os.path.isfile(path)
    assert os.path.getsize(path) > 0

  def test_saves_png(self, tmp_path):
    from capture import CaptureOverlay
    overlay = CaptureOverlay(save_folder=str(tmp_path), fmt="png")
    img = make_test_image()
    path = overlay._save(img)
    assert path is not None
    assert path.endswith(".png")
    assert os.path.isfile(path)

  def test_saves_webp(self, tmp_path):
    from capture import CaptureOverlay
    overlay = CaptureOverlay(save_folder=str(tmp_path), fmt="webp")
    img = make_test_image()
    path = overlay._save(img)
    assert path is not None
    assert path.endswith(".webp")
    assert os.path.isfile(path)

  def test_custom_prefix(self, tmp_path):
    from capture import CaptureOverlay
    overlay = CaptureOverlay(save_folder=str(tmp_path), filename_prefix="test_shot")
    img = make_test_image()
    path = overlay._save(img)
    assert "test_shot_" in os.path.basename(path)

  def test_creates_missing_folder(self, tmp_path):
    from capture import CaptureOverlay
    nested = str(tmp_path / "sub" / "dir")
    overlay = CaptureOverlay(save_folder=nested)
    img = make_test_image()
    path = overlay._save(img)
    assert path is not None
    assert os.path.isfile(path)

  def test_returns_none_on_invalid_folder(self):
    from capture import CaptureOverlay
    # Use a path that can't be created (invalid chars on Windows, or /dev/null/x on Unix)
    if os.name == "nt":
      bad_folder = "Z:\\:::invalid:::\\path"
    else:
      bad_folder = "/dev/null/impossible"
    overlay = CaptureOverlay(save_folder=bad_folder)
    img = make_test_image()
    path = overlay._save(img)
    assert path is None


class TestFinishCapture:
  def test_callback_receives_filepath(self, tmp_path):
    from capture import CaptureOverlay
    results = {}

    def on_done(filepath, error=None):
      results["filepath"] = filepath
      results["error"] = error

    overlay = CaptureOverlay(
      save_folder=str(tmp_path), fmt="png",
      save_to_disk=True, on_done=on_done,
    )
    img = make_test_image()

    with patch.object(overlay, "close"):
      overlay._finish_capture(img)

    assert results["filepath"] is not None
    assert results["error"] is None
    assert os.path.isfile(results["filepath"])

  def test_callback_receives_none_when_clipboard_only(self, tmp_path):
    from capture import CaptureOverlay
    results = {}

    def on_done(filepath, error=None):
      results["filepath"] = filepath
      results["error"] = error

    overlay = CaptureOverlay(
      save_folder=str(tmp_path), save_to_disk=False, on_done=on_done,
    )
    img = make_test_image()

    with patch.object(overlay, "close"):
      overlay._finish_capture(img)

    assert results["filepath"] is None
    assert results["error"] is None

  def test_callback_receives_error_on_clipboard_failure(self, tmp_path):
    from capture import CaptureOverlay
    results = {}

    def on_done(filepath, error=None):
      results["filepath"] = filepath
      results["error"] = error

    overlay = CaptureOverlay(
      save_folder=str(tmp_path), save_to_disk=False, on_done=on_done,
    )
    img = make_test_image()

    with patch.object(overlay, "close"), \
         patch("capture.copy_image_to_clipboard", return_value=False):
      overlay._finish_capture(img)

    assert results["error"] is not None
    assert "clipboard" in results["error"].lower()

  def test_cancel_calls_done_with_cancelled(self):
    from capture import CaptureOverlay
    results = {}

    def on_done(filepath, error=None):
      results["filepath"] = filepath
      results["error"] = error

    overlay = CaptureOverlay(save_folder="/tmp", on_done=on_done)

    with patch.object(overlay, "close"):
      overlay._cancel()

    assert results["filepath"] is None
    assert results["error"] == "cancelled"
