"""Tests for platform utilities."""

import platform
from unittest.mock import patch

from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from platform_utils import copy_image_to_clipboard, default_save_folder


class TestCopyImageToClipboard:
  def test_returns_true_on_success(self):
    img = QImage(10, 10, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 255))
    assert copy_image_to_clipboard(img) is True

  def test_returns_false_on_exception(self):
    with patch("PySide6.QtWidgets.QApplication.clipboard", side_effect=RuntimeError("no clipboard")):
      result = copy_image_to_clipboard(QImage())
      assert result is False


class TestDefaultSaveFolder:
  def test_returns_string(self):
    folder = default_save_folder()
    assert isinstance(folder, str)
    assert len(folder) > 0

  def test_starts_with_tilde(self):
    folder = default_save_folder()
    assert folder.startswith("~")
