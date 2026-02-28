from __future__ import annotations

import functools
import json
import os
import platform
import subprocess
import sys
from typing import Any, Callable, IO

from PySide6.QtCore import Qt, QObject, Signal, QTimer
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtWidgets import (
  QApplication, QSystemTrayIcon, QMenu, QDialog, QFormLayout,
  QLineEdit, QComboBox, QCheckBox, QPushButton, QHBoxLayout,
  QVBoxLayout, QLabel, QFileDialog, QWidget,
)
from pynput import keyboard

from capture import CaptureOverlay
from log import get_logger
from platform_utils import default_save_folder

log = get_logger("main")

MAX_HISTORY = 5

# When frozen as exe, config lives next to the executable
if getattr(sys, "frozen", False):
  APP_DIR = os.path.dirname(sys.executable)
else:
  APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")


CONFIG_VERSION = 5

DEFAULT_CONFIG = {
  "config_version": CONFIG_VERSION,
  "save_folder": default_save_folder(),
  "hotkey_region": "<ctrl>+<alt>+<shift>+s",
  "hotkey_window": "<ctrl>+<alt>+<shift>+d",
  "hotkey_fullscreen": "<ctrl>+<alt>+<shift>+f",
  "format": "jpg",
  "filename_prefix": "screenshot",
  "filename_suffix": "%Y-%m-%d_%H-%M-%S",
  "save_to_disk": True,
  "launch_on_startup": False,
  "annotate_captures": False,
  "annotate_default_tool": "freehand",
  "annotate_shift_tool": "arrow",
  "annotate_ctrl_tool": "oval",
  "annotate_alt_tool": "text",
}

STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_REG_NAME = "ImmediPaste"


def set_launch_on_startup(enabled: bool) -> None:
  """Add or remove ImmediPaste from the Windows startup registry."""
  if sys.platform != "win32":
    return
  import winreg
  try:
    key = winreg.OpenKey(
      winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_SET_VALUE,
    )
  except OSError as e:
    log.warning("Failed to open startup registry key: %s", e)
    return
  try:
    if enabled:
      exe = sys.executable if getattr(sys, "frozen", False) else None
      if exe:
        winreg.SetValueEx(key, STARTUP_REG_NAME, 0, winreg.REG_SZ, f'"{exe}"')
      else:
        log.debug("Launch on startup ignored: not running as frozen executable")
    else:
      try:
        winreg.DeleteValue(key, STARTUP_REG_NAME)
      except FileNotFoundError:
        pass
  except OSError as e:
    log.warning("Failed to update startup registry: %s", e)
  finally:
    winreg.CloseKey(key)


def migrate_config(config: dict[str, Any]) -> bool:
  """Fill in missing keys from defaults and bump version. Returns True if changed."""
  version = config.get("config_version", 1)
  changed = False

  # Add any keys introduced in newer versions
  for key, default_val in DEFAULT_CONFIG.items():
    if key not in config:
      config[key] = default_val
      log.info("Config migration: added '%s' = %r", key, default_val)
      changed = True

  if version < CONFIG_VERSION:
    config["config_version"] = CONFIG_VERSION
    changed = True
    log.info("Config migrated from v%d to v%d", version, CONFIG_VERSION)

  return changed


def load_config() -> dict[str, Any]:
  if not os.path.exists(CONFIG_PATH):
    log.info("No config found, creating defaults at %s", CONFIG_PATH)
    save_config(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)
  try:
    with open(CONFIG_PATH) as f:
      config = json.load(f)
  except json.JSONDecodeError as e:
    log.error("Corrupted config file, resetting to defaults: %s", e)
    save_config(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)
  except OSError as e:
    log.error("Cannot read config file: %s", e)
    return dict(DEFAULT_CONFIG)

  if migrate_config(config):
    save_config(config)
  return config


def save_config(config: dict[str, Any]) -> None:
  try:
    with open(CONFIG_PATH, "w") as f:
      json.dump(config, f, indent=2)
      f.write("\n")
  except OSError as e:
    log.error("Failed to save config: %s", e)


# Tray icon geometry (64x64 canvas)
_ICON_SIZE = 64
_ICON_BODY_COLOR = "#2196F3"
_ICON_LENS_OUTER_COLOR = "white"
_ICON_LENS_INNER_COLOR = "#1565C0"
_ICON_BODY_RECT = (4, 16, 56, 40)
_ICON_BODY_RADIUS = 8
_ICON_LENS_OUTER = (22, 24, 20, 24)
_ICON_LENS_INNER = (27, 29, 10, 14)
_ICON_FLASH_RECT = (24, 10, 16, 8)


def create_tray_icon() -> QIcon:
  """Generate a simple camera-style tray icon using QPainter."""
  pixmap = QPixmap(_ICON_SIZE, _ICON_SIZE)
  pixmap.fill(QColor(0, 0, 0, 0))

  painter = QPainter(pixmap)
  painter.setRenderHint(QPainter.RenderHint.Antialiasing)
  painter.setPen(Qt.PenStyle.NoPen)

  # Camera body
  painter.setBrush(QColor(_ICON_BODY_COLOR))
  painter.drawRoundedRect(*_ICON_BODY_RECT, _ICON_BODY_RADIUS, _ICON_BODY_RADIUS)

  # Lens outer
  painter.setBrush(QColor(_ICON_LENS_OUTER_COLOR))
  painter.drawEllipse(*_ICON_LENS_OUTER)

  # Lens inner
  painter.setBrush(QColor(_ICON_LENS_INNER_COLOR))
  painter.drawEllipse(*_ICON_LENS_INNER)

  # Flash bump
  painter.setBrush(QColor(_ICON_BODY_COLOR))
  painter.drawRect(*_ICON_FLASH_RECT)

  painter.end()
  return QIcon(pixmap)


class HotkeyBridge(QObject):
  """Bridge pynput hotkey events to Qt's main thread via signals."""
  region_triggered = Signal()
  window_triggered = Signal()
  fullscreen_triggered = Signal()


def format_hotkey_display(pynput_str: str) -> str:
  """Convert pynput hotkey format to user-friendly display format.

  '<ctrl>+<alt>+<shift>+s' -> 'Ctrl + Alt + Shift + S'
  """
  if not pynput_str:
    return ""
  parts = pynput_str.split("+")
  nice = []
  for p in parts:
    p = p.strip()
    if p.startswith("<") and p.endswith(">"):
      nice.append(p[1:-1].capitalize())
    else:
      nice.append(p.upper())
  return " + ".join(nice)


class HotkeyEdit(QLineEdit):
  """Read-only line edit that records a key combination on press."""
  changed = Signal()

  def __init__(self, value: str = "", parent: QWidget | None = None):
    super().__init__(parent)
    self.setReadOnly(True)
    self.setCursor(Qt.CursorShape.PointingHandCursor)
    self._value = value
    self._recording = False
    self._update_display()

  def hotkey(self) -> str:
    """Return the pynput-format hotkey string."""
    return self._value

  def _update_display(self) -> None:
    self.setText(format_hotkey_display(self._value))

  def mousePressEvent(self, event):
    super().mousePressEvent(event)
    self._recording = True
    self.setText("Press a key combination...")
    self.setStyleSheet("QLineEdit { background-color: #fff3cd; color: #856404; }")

  def focusOutEvent(self, event):
    super().focusOutEvent(event)
    if self._recording:
      self._recording = False
      self._update_display()
      self.setStyleSheet("")

  def keyPressEvent(self, event):
    if not self._recording:
      return

    key = event.key()
    mods = event.modifiers()

    # Ignore standalone modifier presses
    if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift,
               Qt.Key.Key_Alt, Qt.Key.Key_Meta):
      return

    # Escape cancels recording
    if key == Qt.Key.Key_Escape:
      self._recording = False
      self._update_display()
      self.setStyleSheet("")
      self.clearFocus()
      return

    parts = []
    if mods & Qt.KeyboardModifier.ControlModifier:
      parts.append("<ctrl>")
    if mods & Qt.KeyboardModifier.AltModifier:
      parts.append("<alt>")
    if mods & Qt.KeyboardModifier.ShiftModifier:
      parts.append("<shift>")
    if mods & Qt.KeyboardModifier.MetaModifier:
      parts.append("<cmd>")

    # Require at least one modifier for a global hotkey
    if not parts:
      return

    key_str = self._key_to_pynput(key)
    if not key_str:
      return

    parts.append(key_str)
    self._value = "+".join(parts)
    self._recording = False
    self._update_display()
    self.setStyleSheet("")
    self.clearFocus()
    self.changed.emit()

  @staticmethod
  def _key_to_pynput(key: Qt.Key) -> str | None:
    """Convert a Qt key code to a pynput hotkey token."""
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
      return chr(key).lower()
    if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
      return chr(key)
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
      return f"<f{key - Qt.Key.Key_F1 + 1}>"
    return {
      Qt.Key.Key_Space: "<space>",
      Qt.Key.Key_Tab: "<tab>",
      Qt.Key.Key_Return: "<enter>",
      Qt.Key.Key_Enter: "<enter>",
      Qt.Key.Key_Backspace: "<backspace>",
      Qt.Key.Key_Delete: "<delete>",
      Qt.Key.Key_Home: "<home>",
      Qt.Key.Key_End: "<end>",
      Qt.Key.Key_PageUp: "<page_up>",
      Qt.Key.Key_PageDown: "<page_down>",
      Qt.Key.Key_Up: "<up>",
      Qt.Key.Key_Down: "<down>",
      Qt.Key.Key_Left: "<left>",
      Qt.Key.Key_Right: "<right>",
      Qt.Key.Key_Insert: "<insert>",
    }.get(key)


SAVE_DEBOUNCE_MS = 150


class SettingsDialog(QDialog):
  def __init__(self, config: dict[str, Any],
               on_change: Callable[[dict[str, Any]], None] | None = None,
               parent: QWidget | None = None):
    super().__init__(parent)
    self._on_change = on_change
    self.setWindowTitle("ImmediPaste Settings")
    self.setFixedWidth(480)

    # Debounce timer for config saves
    self._save_timer = QTimer(self)
    self._save_timer.setSingleShot(True)
    self._save_timer.setInterval(SAVE_DEBOUNCE_MS)
    self._save_timer.timeout.connect(self._flush_change)

    layout = QVBoxLayout(self)

    # Form
    form = QFormLayout()

    # Save folder + browse + validation
    folder_row = QHBoxLayout()
    self.folder_edit = QLineEdit(config.get("save_folder", ""))
    browse_btn = QPushButton("Browse...")
    browse_btn.clicked.connect(self._browse_folder)
    folder_row.addWidget(self.folder_edit)
    folder_row.addWidget(browse_btn)
    form.addRow("Save folder:", folder_row)

    self.folder_warning = QLabel("")
    self.folder_warning.setStyleSheet("QLabel { color: #cc6600; font-size: 11px; }")
    self.folder_warning.setWordWrap(True)
    self.folder_warning.hide()
    form.addRow("", self.folder_warning)

    # Region hotkey
    self.hotkey_edit = HotkeyEdit(config.get("hotkey_region", "<ctrl>+<alt>+<shift>+s"))
    form.addRow("Region hotkey:", self.hotkey_edit)

    # Window hotkey
    self.win_hotkey_edit = HotkeyEdit(config.get("hotkey_window", "<ctrl>+<alt>+<shift>+d"))
    form.addRow("Window hotkey:", self.win_hotkey_edit)

    # Fullscreen hotkey
    self.fs_hotkey_edit = HotkeyEdit(config.get("hotkey_fullscreen", "<ctrl>+<alt>+<shift>+f"))
    form.addRow("Fullscreen hotkey:", self.fs_hotkey_edit)

    # Format
    self.fmt_combo = QComboBox()
    self.fmt_combo.addItems(["jpg", "png", "webp"])
    self.fmt_combo.setCurrentText(config.get("format", "jpg"))
    form.addRow("Save format:", self.fmt_combo)

    # Filename prefix
    self.prefix_edit = QLineEdit(config.get("filename_prefix", "screenshot"))
    form.addRow("Filename prefix:", self.prefix_edit)

    # Filename suffix (strftime format)
    self.suffix_edit = QLineEdit(config.get("filename_suffix", "%Y-%m-%d_%H-%M-%S"))
    self.suffix_edit.setToolTip("strftime format for date/time in filename (e.g. %%Y-%%m-%%d_%%H-%%M-%%S)")
    form.addRow("Filename suffix:", self.suffix_edit)

    layout.addLayout(form)

    # Save to disk checkbox
    self.save_disk_check = QCheckBox("Also save screenshots to disk")
    self.save_disk_check.setChecked(config.get("save_to_disk", True))
    layout.addWidget(self.save_disk_check)

    # Annotation editor checkbox
    self.annotate_check = QCheckBox("Open annotation editor after capture")
    self.annotate_check.setChecked(config.get("annotate_captures", False))
    layout.addWidget(self.annotate_check)

    # Modifier-to-tool mapping combos (indented under annotation checkbox)
    _TOOL_ITEMS = [
      ("Arrow", "arrow"), ("Oval", "oval"), ("Rectangle", "rect"),
      ("Text", "text"), ("Freehand", "freehand"),
      ("None (toolbar default)", "none"),
    ]
    _tool_value_to_label = {v: lbl for lbl, v in _TOOL_ITEMS}

    mod_layout = QFormLayout()
    mod_layout.setContentsMargins(24, 0, 0, 0)

    self._default_tool_combo = QComboBox()
    self._shift_tool_combo = QComboBox()
    self._ctrl_tool_combo = QComboBox()
    self._alt_tool_combo = QComboBox()
    for combo, cfg_key, default in [
      (self._default_tool_combo, "annotate_default_tool", "freehand"),
      (self._shift_tool_combo, "annotate_shift_tool", "arrow"),
      (self._ctrl_tool_combo, "annotate_ctrl_tool", "oval"),
      (self._alt_tool_combo, "annotate_alt_tool", "text"),
    ]:
      for label, value in _TOOL_ITEMS:
        combo.addItem(label, value)
      saved = config.get(cfg_key, default)
      idx = combo.findData(saved)
      combo.setCurrentIndex(idx if idx >= 0 else 0)

    mod_layout.addRow("Default (no modifier):", self._default_tool_combo)
    mod_layout.addRow("Shift + drag:", self._shift_tool_combo)
    mod_layout.addRow("Ctrl + drag:", self._ctrl_tool_combo)
    mod_layout.addRow("Alt + click/drag:", self._alt_tool_combo)
    layout.addLayout(mod_layout)

    # Launch on startup checkbox
    self.startup_check = QCheckBox("Launch on startup")
    self.startup_check.setChecked(config.get("launch_on_startup", False))
    layout.addWidget(self.startup_check)

    # Close button
    btn_layout = QHBoxLayout()
    btn_layout.addStretch()
    close_btn = QPushButton("Close")
    close_btn.clicked.connect(self.accept)
    btn_layout.addWidget(close_btn)
    layout.addLayout(btn_layout)

    # Position after layout is built so self.height() reflects actual content
    self._position_near_tray()

    # Auto-save on any change
    self.folder_edit.editingFinished.connect(self._emit_change)
    self.hotkey_edit.changed.connect(self._emit_change)
    self.win_hotkey_edit.changed.connect(self._emit_change)
    self.fs_hotkey_edit.changed.connect(self._emit_change)
    self.fmt_combo.currentTextChanged.connect(self._emit_change)
    self.prefix_edit.editingFinished.connect(self._emit_change)
    self.suffix_edit.editingFinished.connect(self._emit_change)
    self.save_disk_check.stateChanged.connect(self._emit_change)
    self.annotate_check.stateChanged.connect(self._emit_change)
    self._default_tool_combo.currentIndexChanged.connect(self._emit_change)
    self._shift_tool_combo.currentIndexChanged.connect(self._emit_change)
    self._ctrl_tool_combo.currentIndexChanged.connect(self._emit_change)
    self._alt_tool_combo.currentIndexChanged.connect(self._emit_change)
    self.startup_check.stateChanged.connect(self._emit_change)

  def done(self, result: int) -> None:
    # Flush any pending debounced save before the dialog closes
    if self._save_timer.isActive():
      self._save_timer.stop()
      self._flush_change()
    super().done(result)

  def _position_near_tray(self) -> None:
    screen = QApplication.primaryScreen().geometry()
    x = screen.x() + screen.width() - self.width() - 16
    y = screen.y() + screen.height() - self.height() - 60
    self.move(x, y)

  def _emit_change(self, *_args: Any) -> None:
    self._validate_folder()
    if self._on_change:
      self._save_timer.start()

  def _flush_change(self) -> None:
    """Actually push the config change after the debounce delay."""
    if self._on_change:
      self._on_change(self.get_config())

  def _validate_folder(self) -> None:
    """Check if the save folder path is writable and show a warning if not."""
    raw = self.folder_edit.text().strip()
    if not raw:
      self.folder_warning.hide()
      return
    folder = os.path.abspath(os.path.expanduser(raw))
    if os.path.isdir(folder):
      if os.access(folder, os.W_OK):
        self.folder_warning.hide()
      else:
        self.folder_warning.setText("Folder exists but is not writable")
        self.folder_warning.show()
    else:
      # Check if the parent exists and is writable (folder could be created)
      parent = os.path.dirname(folder)
      if os.path.isdir(parent) and os.access(parent, os.W_OK):
        self.folder_warning.hide()
      else:
        self.folder_warning.setText("Folder does not exist and cannot be created")
        self.folder_warning.show()

  def _browse_folder(self) -> None:
    path = QFileDialog.getExistingDirectory(
      self, "Select Save Folder",
      os.path.expanduser(self.folder_edit.text()),
    )
    if path:
      self.folder_edit.setText(path)
      self._emit_change()

  def get_config(self) -> dict[str, Any]:
    return {
      "save_folder": self.folder_edit.text(),
      "hotkey_region": self.hotkey_edit.hotkey(),
      "hotkey_window": self.win_hotkey_edit.hotkey(),
      "hotkey_fullscreen": self.fs_hotkey_edit.hotkey(),
      "format": self.fmt_combo.currentText(),
      "filename_prefix": self.prefix_edit.text(),
      "filename_suffix": self.suffix_edit.text(),
      "save_to_disk": self.save_disk_check.isChecked(),
      "annotate_captures": self.annotate_check.isChecked(),
      "annotate_default_tool": self._default_tool_combo.currentData(),
      "annotate_shift_tool": self._shift_tool_combo.currentData(),
      "annotate_ctrl_tool": self._ctrl_tool_combo.currentData(),
      "annotate_alt_tool": self._alt_tool_combo.currentData(),
      "launch_on_startup": self.startup_check.isChecked(),
    }


class ImmediPaste:
  def __init__(self) -> None:
    self.config: dict[str, Any] = load_config()
    self.capturing: bool = False
    self.tray_icon: QSystemTrayIcon | None = None
    self.capture_history: list[str] = []
    self._overlay: CaptureOverlay | None = None
    self._editor = None
    self._last_capture_path: str | None = None

    # Ensure save folder exists
    folder = os.path.expanduser(self.config.get("save_folder", ""))
    if folder:
      try:
        os.makedirs(folder, exist_ok=True)
      except OSError as e:
        log.warning("Cannot create save folder '%s': %s", folder, e)

  def _get_image_ready_callback(self) -> Callable | None:
    """Return an image callback if annotation mode is enabled, else None."""
    if not self.config.get("annotate_captures", False):
      return None
    return self._open_annotation_editor

  def _open_annotation_editor(self, qimage) -> None:
    """Open the annotation editor with the captured image."""
    from annotation_editor import AnnotationEditor
    modifier_tools = {
      "shift": self.config.get("annotate_shift_tool", "arrow"),
      "ctrl": self.config.get("annotate_ctrl_tool", "oval"),
      "alt": self.config.get("annotate_alt_tool", "text"),
    }
    self._editor = AnnotationEditor(
      qimage=qimage,
      save_folder=self.config["save_folder"],
      fmt=self.config.get("format", "jpg"),
      save_to_disk=self.config.get("save_to_disk", True),
      filename_prefix=self.config.get("filename_prefix", "screenshot"),
      filename_suffix=self.config.get("filename_suffix", "%Y-%m-%d_%H-%M-%S"),
      on_done=self._on_capture_done,
      modifier_tools=modifier_tools,
      default_tool=self.config.get("annotate_default_tool", "freehand"),
    )
    self._editor.show()
    self._editor.raise_()
    self._editor.activateWindow()
    self._editor.setFocus()

  def trigger_capture(self) -> None:
    """Open the region selection overlay."""
    if self.capturing:
      return
    self.capturing = True

    self._overlay = CaptureOverlay(
      save_folder=self.config["save_folder"],
      fmt=self.config.get("format", "jpg"),
      save_to_disk=self.config.get("save_to_disk", True),
      filename_prefix=self.config.get("filename_prefix", "screenshot"),
      filename_suffix=self.config.get("filename_suffix", "%Y-%m-%d_%H-%M-%S"),
      on_done=self._on_capture_done,
      on_image_ready=self._get_image_ready_callback(),
    )
    self._overlay.start()

  def trigger_window_capture(self) -> None:
    """Open the window capture overlay."""
    if self.capturing:
      return

    if platform.system() != "Windows":
      log.warning("Window capture is not supported on this platform")
      if self.tray_icon:
        self.tray_icon.showMessage(
          "ImmediPaste", "Window capture is only available on Windows",
          QSystemTrayIcon.MessageIcon.Warning, 3000,
        )
      return

    self.capturing = True

    self._overlay = CaptureOverlay(
      save_folder=self.config["save_folder"],
      fmt=self.config.get("format", "jpg"),
      save_to_disk=self.config.get("save_to_disk", True),
      filename_prefix=self.config.get("filename_prefix", "screenshot"),
      filename_suffix=self.config.get("filename_suffix", "%Y-%m-%d_%H-%M-%S"),
      on_done=self._on_capture_done,
      on_image_ready=self._get_image_ready_callback(),
      mode="window",
    )
    self._overlay.start()

  def trigger_fullscreen(self) -> None:
    """Capture full screen immediately, no overlay."""
    if self.capturing:
      return
    self.capturing = True

    self._overlay = CaptureOverlay(
      save_folder=self.config["save_folder"],
      fmt=self.config.get("format", "jpg"),
      save_to_disk=self.config.get("save_to_disk", True),
      filename_prefix=self.config.get("filename_prefix", "screenshot"),
      filename_suffix=self.config.get("filename_suffix", "%Y-%m-%d_%H-%M-%S"),
      on_done=self._on_capture_done,
      on_image_ready=self._get_image_ready_callback(),
    )
    self._overlay.capture_fullscreen_direct()

  def _on_capture_done(self, filepath: str | None, error: str | None = None) -> None:
    self.capturing = False
    self._overlay = None
    self._editor = None

    # User cancelled -- reset state silently, no notification
    if error == "cancelled":
      return

    if error:
      log.error("Capture error: %s", error)
      if self.tray_icon:
        self.tray_icon.showMessage(
          "ImmediPaste", error,
          QSystemTrayIcon.MessageIcon.Critical, 4000,
        )
      return

    if filepath:
      self.capture_history.append(filepath)
      if len(self.capture_history) > MAX_HISTORY:
        self.capture_history = self.capture_history[-MAX_HISTORY:]
      self._last_capture_path = filepath
      log.info("Captured: %s", filepath)

    if self.tray_icon:
      msg = os.path.basename(filepath) if filepath else "Copied to clipboard"
      self.tray_icon.showMessage(
        "ImmediPaste", msg,
        QSystemTrayIcon.MessageIcon.Information, 3000,
      )

  def _on_notification_clicked(self) -> None:
    """Open the most recent capture in file explorer."""
    if self._last_capture_path and os.path.exists(self._last_capture_path):
      self._show_in_explorer(self._last_capture_path)

  @staticmethod
  def _show_in_explorer(filepath: str) -> None:
    try:
      system = platform.system()
      if system == "Windows":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(filepath)])
      elif system == "Darwin":
        subprocess.Popen(["open", "-R", filepath])
      else:
        subprocess.Popen(["xdg-open", os.path.dirname(filepath)])
    except OSError as e:
      log.warning("Failed to open file explorer: %s", e)

  def _apply_settings(self, new_config: dict[str, Any]) -> None:
    """Called on every settings change for live auto-save."""
    old_config = dict(self.config)
    self.config.update(new_config)
    save_config(self.config)
    if new_config.get("launch_on_startup") != old_config.get("launch_on_startup"):
      set_launch_on_startup(self.config.get("launch_on_startup", False))
    log.debug("Settings updated: %s",
      {k: v for k, v in new_config.items() if old_config.get(k) != v})

  def open_settings(self) -> None:
    # Pause hotkey listener so keypresses don't trigger captures
    try:
      self._listener.stop()
    except Exception as e:
      log.warning("Failed to stop hotkey listener: %s", e)

    dialog = SettingsDialog(self.config, on_change=self._apply_settings)
    dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    dialog.exec()

    # Restart listener with (possibly new) hotkeys
    try:
      self._start_hotkey_listener()
    except Exception as e:
      log.error("Failed to restart hotkey listener: %s", e)
      if self.tray_icon:
        self.tray_icon.showMessage(
          "ImmediPaste",
          "Hotkeys stopped working. Try restarting the app.",
          QSystemTrayIcon.MessageIcon.Warning, 5000,
        )

  def _start_hotkey_listener(self) -> None:
    region_str = self.config.get("hotkey_region", "<ctrl>+<alt>+<shift>+s")
    window_str = self.config.get("hotkey_window", "<ctrl>+<alt>+<shift>+d")
    fullscreen_str = self.config.get("hotkey_fullscreen", "<ctrl>+<alt>+<shift>+f")

    def _parse_hotkey(hotkey_str, default_str, signal):
      try:
        return keyboard.HotKey(keyboard.HotKey.parse(hotkey_str), signal)
      except ValueError as e:
        log.error("Invalid hotkey '%s': %s -- using default '%s'", hotkey_str, e, default_str)
        return keyboard.HotKey(keyboard.HotKey.parse(default_str), signal)

    hotkey_region = _parse_hotkey(
      region_str, "<ctrl>+<alt>+<shift>+s",
      self.hotkey_bridge.region_triggered.emit,
    )
    hotkey_window = _parse_hotkey(
      window_str, "<ctrl>+<alt>+<shift>+d",
      self.hotkey_bridge.window_triggered.emit,
    )
    hotkey_fullscreen = _parse_hotkey(
      fullscreen_str, "<ctrl>+<alt>+<shift>+f",
      self.hotkey_bridge.fullscreen_triggered.emit,
    )

    def on_press(k):
      key = self._listener.canonical(k)
      hotkey_region.press(key)
      hotkey_window.press(key)
      hotkey_fullscreen.press(key)

    def on_release(k):
      key = self._listener.canonical(k)
      hotkey_region.release(key)
      hotkey_window.release(key)
      hotkey_fullscreen.release(key)

    self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    self._listener.start()
    log.debug("Hotkey listener started (region=%s, window=%s, fullscreen=%s)",
      region_str, window_str, fullscreen_str)

  def reload_settings(self) -> None:
    try:
      self._listener.stop()
    except Exception as e:
      log.warning("Failed to stop hotkey listener during reload: %s", e)
    try:
      self._start_hotkey_listener()
    except Exception as e:
      log.error("Failed to restart hotkey listener during reload: %s", e)

  def _rebuild_tray_menu(self) -> None:
    self.tray_menu.clear()

    region_hk = format_hotkey_display(self.config.get("hotkey_region", ""))
    window_hk = format_hotkey_display(self.config.get("hotkey_window", ""))
    fullscreen_hk = format_hotkey_display(self.config.get("hotkey_fullscreen", ""))

    region_action = self.tray_menu.addAction("Capture Region  (%s)" % region_hk)
    region_action.triggered.connect(self.trigger_capture)

    window_action = self.tray_menu.addAction("Capture Window  (%s)" % window_hk)
    window_action.triggered.connect(self.trigger_window_capture)

    fullscreen_action = self.tray_menu.addAction("Capture Fullscreen  (%s)" % fullscreen_hk)
    fullscreen_action.triggered.connect(self.trigger_fullscreen)

    if self.capture_history:
      self.tray_menu.addSeparator()
      for path in reversed(self.capture_history):
        name = os.path.basename(path)
        action = self.tray_menu.addAction(name)
        action.triggered.connect(functools.partial(self._show_in_explorer, path))

    self.tray_menu.addSeparator()
    settings_action = self.tray_menu.addAction("Settings")
    settings_action.triggered.connect(self.open_settings)

    exit_action = self.tray_menu.addAction("Exit")
    exit_action.triggered.connect(self.app.quit)

  def run(self) -> None:
    self.app = QApplication(sys.argv)
    self.app.setQuitOnLastWindowClosed(False)

    # Hotkey bridge: pynput thread -> Qt main thread
    self.hotkey_bridge = HotkeyBridge()
    self.hotkey_bridge.region_triggered.connect(
      self.trigger_capture, Qt.ConnectionType.QueuedConnection,
    )
    self.hotkey_bridge.window_triggered.connect(
      self.trigger_window_capture, Qt.ConnectionType.QueuedConnection,
    )
    self.hotkey_bridge.fullscreen_triggered.connect(
      self.trigger_fullscreen, Qt.ConnectionType.QueuedConnection,
    )

    self._start_hotkey_listener()

    # System tray
    self.tray_icon = QSystemTrayIcon(create_tray_icon(), self.app)
    self.tray_icon.setToolTip("ImmediPaste")

    self.tray_menu = QMenu()
    self.tray_menu.aboutToShow.connect(self._rebuild_tray_menu)
    self.tray_icon.setContextMenu(self.tray_menu)

    self.tray_icon.messageClicked.connect(self._on_notification_clicked)
    self.tray_icon.show()

    self.app.aboutToQuit.connect(self._shutdown)

    log.info("ImmediPaste running (region=%s, window=%s, fullscreen=%s)",
      self.config.get("hotkey_region"), self.config.get("hotkey_window"),
      self.config.get("hotkey_fullscreen"))

    exit_code = self.app.exec()
    sys.exit(exit_code)

  def _shutdown(self) -> None:
    """Clean up resources before the application exits."""
    try:
      self._listener.stop()
    except Exception as e:
      log.warning("Failed to stop hotkey listener on shutdown: %s", e)
    log.info("ImmediPaste exiting")


LOCK_TIMEOUT_SECONDS = 3600  # 1 hour


def acquire_single_instance() -> IO[str]:
  """Ensure only one instance of ImmediPaste is running.

  Uses a lock file with a timestamp. If the lock is held but the timestamp
  is older than LOCK_TIMEOUT_SECONDS, the stale lock is broken and reacquired.
  """
  import tempfile
  lock_path = os.path.join(tempfile.gettempdir(), "immedipaste.lock")

  def _try_lock(fh):
    if sys.platform == "win32":
      import msvcrt
      msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    else:
      import fcntl
      fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)

  def _write_timestamp(fh):
    import time
    fh.seek(0)
    fh.truncate()
    fh.write(str(time.time()))
    fh.flush()

  # Read existing timestamp and open without truncation to preserve it
  # for other instances. Use "r+" (no truncation) for existing files,
  # "w" only when creating a new lock file.
  saved_timestamp = None
  if os.path.exists(lock_path):
    try:
      lock_file = open(lock_path, "r+")
      content = lock_file.read().strip()
      if content:
        saved_timestamp = float(content)
      lock_file.seek(0)
    except (OSError, ValueError):
      # File unreadable or bad content -- create fresh
      try:
        lock_file.close()
      except Exception:
        pass
      lock_file = open(lock_path, "w")
  else:
    lock_file = open(lock_path, "w")

  try:
    _try_lock(lock_file)
  except OSError:
    # Lock is held -- check if it's stale
    import time
    if saved_timestamp is not None:
      age = time.time() - saved_timestamp
      if age > LOCK_TIMEOUT_SECONDS:
        log.warning("Stale lock file (%.0fs old), breaking lock", age)
        lock_file.close()
        try:
          os.remove(lock_path)
        except OSError:
          pass
        lock_file = open(lock_path, "w")
        try:
          _try_lock(lock_file)
        except OSError:
          lock_file.close()
          log.info("Another instance is already running, exiting")
          sys.exit(0)
      else:
        lock_file.close()
        log.info("Another instance is already running, exiting")
        sys.exit(0)
    else:
      # No readable timestamp -- assume active
      lock_file.close()
      log.info("Another instance is already running, exiting")
      sys.exit(0)

  _write_timestamp(lock_file)
  return lock_file


if __name__ == "__main__":
  _lock = acquire_single_instance()
  app = ImmediPaste()
  app.run()
