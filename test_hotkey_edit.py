"""Tests for HotkeyEdit key-to-pynput conversion."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from main import HotkeyEdit


class TestKeyToPynput:
  def test_letters(self):
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_A) == "a"
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_Z) == "z"
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_M) == "m"

  def test_digits(self):
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_0) == "0"
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_9) == "9"
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_5) == "5"

  def test_function_keys(self):
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_F1) == "<f1>"
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_F5) == "<f5>"
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_F12) == "<f12>"

  def test_special_keys(self):
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_Space) == "<space>"
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_Tab) == "<tab>"
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_Return) == "<enter>"
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_Enter) == "<enter>"
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_Backspace) == "<backspace>"
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_Delete) == "<delete>"

  def test_navigation_keys(self):
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_Home) == "<home>"
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_End) == "<end>"
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_PageUp) == "<page_up>"
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_PageDown) == "<page_down>"

  def test_arrow_keys(self):
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_Up) == "<up>"
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_Down) == "<down>"
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_Left) == "<left>"
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_Right) == "<right>"

  def test_unmapped_key_returns_none(self):
    # Key_Pause is not in the mapping
    assert HotkeyEdit._key_to_pynput(Qt.Key.Key_Pause) is None
