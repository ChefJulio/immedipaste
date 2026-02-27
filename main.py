import functools
import json
import os
import platform
import subprocess
import sys

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtWidgets import (
  QApplication, QSystemTrayIcon, QMenu, QDialog, QFormLayout,
  QLineEdit, QComboBox, QCheckBox, QPushButton, QHBoxLayout,
  QVBoxLayout, QLabel, QFileDialog,
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


DEFAULT_CONFIG = {
  "save_folder": default_save_folder(),
  "hotkey_region": "<ctrl>+<alt>+<shift>+s",
  "hotkey_window": "<ctrl>+<alt>+<shift>+d",
  "hotkey_fullscreen": "<ctrl>+<alt>+<shift>+f",
  "format": "jpg",
  "filename_prefix": "immedipaste",
  "save_to_disk": True,
  "launch_on_startup": False,
}

STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_REG_NAME = "ImmediPaste"


def set_launch_on_startup(enabled):
  """Add or remove ImmediPaste from the Windows startup registry."""
  if sys.platform != "win32":
    return
  import winreg
  try:
    key = winreg.OpenKey(
      winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_SET_VALUE,
    )
    if enabled:
      exe = sys.executable if getattr(sys, "frozen", False) else None
      if exe:
        winreg.SetValueEx(key, STARTUP_REG_NAME, 0, winreg.REG_SZ, f'"{exe}"')
    else:
      try:
        winreg.DeleteValue(key, STARTUP_REG_NAME)
      except FileNotFoundError:
        pass
    winreg.CloseKey(key)
  except OSError as e:
    log.warning("Failed to update startup registry: %s", e)


def load_config():
  if not os.path.exists(CONFIG_PATH):
    log.info("No config found, creating defaults at %s", CONFIG_PATH)
    save_config(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)
  try:
    with open(CONFIG_PATH) as f:
      return json.load(f)
  except json.JSONDecodeError as e:
    log.error("Corrupted config file, resetting to defaults: %s", e)
    save_config(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)
  except OSError as e:
    log.error("Cannot read config file: %s", e)
    return dict(DEFAULT_CONFIG)


def save_config(config):
  try:
    with open(CONFIG_PATH, "w") as f:
      json.dump(config, f, indent=2)
      f.write("\n")
  except OSError as e:
    log.error("Failed to save config: %s", e)


def create_tray_icon():
  """Generate a simple camera-style tray icon using QPainter."""
  size = 64
  pixmap = QPixmap(size, size)
  pixmap.fill(QColor(0, 0, 0, 0))

  painter = QPainter(pixmap)
  painter.setRenderHint(QPainter.RenderHint.Antialiasing)
  painter.setPen(Qt.PenStyle.NoPen)

  # Camera body
  painter.setBrush(QColor("#2196F3"))
  painter.drawRoundedRect(4, 16, 56, 40, 8, 8)

  # Lens outer
  painter.setBrush(QColor("white"))
  painter.drawEllipse(22, 24, 20, 24)

  # Lens inner
  painter.setBrush(QColor("#1565C0"))
  painter.drawEllipse(27, 29, 10, 14)

  # Flash bump
  painter.setBrush(QColor("#2196F3"))
  painter.drawRect(24, 10, 16, 8)

  painter.end()
  return QIcon(pixmap)


class HotkeyBridge(QObject):
  """Bridge pynput hotkey events to Qt's main thread via signals."""
  region_triggered = Signal()
  window_triggered = Signal()
  fullscreen_triggered = Signal()


class HotkeyEdit(QLineEdit):
  """Read-only line edit that records a key combination on press."""
  changed = Signal()

  def __init__(self, value="", parent=None):
    super().__init__(parent)
    self.setReadOnly(True)
    self.setCursor(Qt.CursorShape.PointingHandCursor)
    self._value = value
    self._recording = False
    self._update_display()

  def hotkey(self):
    """Return the pynput-format hotkey string."""
    return self._value

  def _update_display(self):
    if not self._value:
      self.setText("")
      return
    parts = self._value.split("+")
    nice = []
    for p in parts:
      p = p.strip()
      if p.startswith("<") and p.endswith(">"):
        nice.append(p[1:-1].capitalize())
      else:
        nice.append(p.upper())
    self.setText(" + ".join(nice))

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
  def _key_to_pynput(key):
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


class SettingsDialog(QDialog):
  def __init__(self, config, on_change=None, parent=None):
    super().__init__(parent)
    self._on_change = on_change
    self.setWindowTitle("ImmediPaste Settings")
    self.setFixedWidth(480)
    self._position_near_tray()

    layout = QVBoxLayout(self)

    # Form
    form = QFormLayout()

    # Save folder + browse
    folder_row = QHBoxLayout()
    self.folder_edit = QLineEdit(config.get("save_folder", ""))
    browse_btn = QPushButton("Browse...")
    browse_btn.clicked.connect(self._browse_folder)
    folder_row.addWidget(self.folder_edit)
    folder_row.addWidget(browse_btn)
    form.addRow("Save folder:", folder_row)

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
    self.prefix_edit = QLineEdit(config.get("filename_prefix", "immedipaste"))
    form.addRow("Filename prefix:", self.prefix_edit)

    layout.addLayout(form)

    # Save to disk checkbox
    self.save_disk_check = QCheckBox("Also save screenshots to disk")
    self.save_disk_check.setChecked(config.get("save_to_disk", True))
    layout.addWidget(self.save_disk_check)

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

    # Auto-save on any change
    self.folder_edit.editingFinished.connect(self._emit_change)
    self.hotkey_edit.changed.connect(self._emit_change)
    self.win_hotkey_edit.changed.connect(self._emit_change)
    self.fs_hotkey_edit.changed.connect(self._emit_change)
    self.fmt_combo.currentTextChanged.connect(self._emit_change)
    self.prefix_edit.editingFinished.connect(self._emit_change)
    self.save_disk_check.stateChanged.connect(self._emit_change)
    self.startup_check.stateChanged.connect(self._emit_change)

  def _position_near_tray(self):
    screen = QApplication.primaryScreen().geometry()
    x = screen.width() - self.width() - 16
    y = screen.height() - self.height() - 60
    self.move(x, y)

  def _emit_change(self, *_args):
    if self._on_change:
      self._on_change(self.get_config())

  def _browse_folder(self):
    path = QFileDialog.getExistingDirectory(
      self, "Select Save Folder",
      os.path.expanduser(self.folder_edit.text()),
    )
    if path:
      self.folder_edit.setText(path)
      self._emit_change()

  def get_config(self):
    return {
      "save_folder": self.folder_edit.text(),
      "hotkey_region": self.hotkey_edit.hotkey(),
      "hotkey_window": self.win_hotkey_edit.hotkey(),
      "hotkey_fullscreen": self.fs_hotkey_edit.hotkey(),
      "format": self.fmt_combo.currentText(),
      "filename_prefix": self.prefix_edit.text(),
      "save_to_disk": self.save_disk_check.isChecked(),
      "launch_on_startup": self.startup_check.isChecked(),
    }


class ImmediPaste:
  def __init__(self):
    self.config = load_config()
    self.capturing = False
    self.tray_icon = None
    self.capture_history = []
    self._overlay = None
    self._last_capture_path = None

    # Ensure save folder exists
    folder = os.path.expanduser(self.config.get("save_folder", ""))
    if folder:
      try:
        os.makedirs(folder, exist_ok=True)
      except OSError as e:
        log.warning("Cannot create save folder '%s': %s", folder, e)

  def trigger_capture(self):
    """Open the region selection overlay."""
    if self.capturing:
      return
    self.capturing = True

    self._overlay = CaptureOverlay(
      save_folder=self.config["save_folder"],
      fmt=self.config.get("format", "jpg"),
      save_to_disk=self.config.get("save_to_disk", True),
      filename_prefix=self.config.get("filename_prefix", "immedipaste"),
      on_done=self._on_capture_done,
    )
    self._overlay.start()

  def trigger_window_capture(self):
    """Open the window capture overlay."""
    if self.capturing:
      return
    self.capturing = True

    self._overlay = CaptureOverlay(
      save_folder=self.config["save_folder"],
      fmt=self.config.get("format", "jpg"),
      save_to_disk=self.config.get("save_to_disk", True),
      filename_prefix=self.config.get("filename_prefix", "immedipaste"),
      on_done=self._on_capture_done,
      mode="window",
    )
    self._overlay.start()

  def trigger_fullscreen(self):
    """Capture full screen immediately, no overlay."""
    if self.capturing:
      return
    self.capturing = True

    overlay = CaptureOverlay(
      save_folder=self.config["save_folder"],
      fmt=self.config.get("format", "jpg"),
      save_to_disk=self.config.get("save_to_disk", True),
      filename_prefix=self.config.get("filename_prefix", "immedipaste"),
      on_done=self._on_capture_done,
    )
    overlay.capture_fullscreen_direct()

  def _on_capture_done(self, filepath, error=None):
    self.capturing = False
    self._overlay = None

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

  def _on_notification_clicked(self):
    """Open the most recent capture in file explorer."""
    if self._last_capture_path and os.path.exists(self._last_capture_path):
      self._show_in_explorer(self._last_capture_path)

  @staticmethod
  def _show_in_explorer(filepath):
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

  def _apply_settings(self, new_config):
    """Called on every settings change for live auto-save."""
    old_config = dict(self.config)
    self.config.update(new_config)
    save_config(self.config)
    set_launch_on_startup(self.config.get("launch_on_startup", False))
    log.debug("Settings updated: %s",
      {k: v for k, v in new_config.items() if old_config.get(k) != v})

  def open_settings(self):
    # Pause hotkey listener so keypresses don't trigger captures
    self._listener.stop()

    dialog = SettingsDialog(self.config, on_change=self._apply_settings)
    dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    dialog.exec()

    # Restart listener with (possibly new) hotkeys
    self._start_hotkey_listener()

  def _start_hotkey_listener(self):
    region_str = self.config.get("hotkey_region", "<ctrl>+<alt>+<shift>+s")
    window_str = self.config.get("hotkey_window", "<ctrl>+<alt>+<shift>+d")
    fullscreen_str = self.config.get("hotkey_fullscreen", "<ctrl>+<alt>+<shift>+f")

    try:
      hotkey_region = keyboard.HotKey(
        keyboard.HotKey.parse(region_str),
        self.hotkey_bridge.region_triggered.emit,
      )
      hotkey_window = keyboard.HotKey(
        keyboard.HotKey.parse(window_str),
        self.hotkey_bridge.window_triggered.emit,
      )
      hotkey_fullscreen = keyboard.HotKey(
        keyboard.HotKey.parse(fullscreen_str),
        self.hotkey_bridge.fullscreen_triggered.emit,
      )
    except ValueError as e:
      log.error("Invalid hotkey configuration: %s", e)
      # Fall back to defaults
      hotkey_region = keyboard.HotKey(
        keyboard.HotKey.parse("<ctrl>+<alt>+<shift>+s"),
        self.hotkey_bridge.region_triggered.emit,
      )
      hotkey_window = keyboard.HotKey(
        keyboard.HotKey.parse("<ctrl>+<alt>+<shift>+d"),
        self.hotkey_bridge.window_triggered.emit,
      )
      hotkey_fullscreen = keyboard.HotKey(
        keyboard.HotKey.parse("<ctrl>+<alt>+<shift>+f"),
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

  def reload_settings(self):
    self._listener.stop()
    self._start_hotkey_listener()

  def _rebuild_tray_menu(self):
    self.tray_menu.clear()

    region_action = self.tray_menu.addAction("Capture Region  (Ctrl+Alt+Shift+S)")
    region_action.triggered.connect(self.trigger_capture)

    window_action = self.tray_menu.addAction("Capture Window  (Ctrl+Alt+Shift+D)")
    window_action.triggered.connect(self.trigger_window_capture)

    fullscreen_action = self.tray_menu.addAction("Capture Fullscreen  (Ctrl+Alt+Shift+F)")
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

  def run(self):
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

    log.info("ImmediPaste running (region=%s, window=%s, fullscreen=%s)",
      self.config.get("hotkey_region"), self.config.get("hotkey_window"),
      self.config.get("hotkey_fullscreen"))

    exit_code = self.app.exec()
    self._listener.stop()
    log.info("ImmediPaste exiting")
    sys.exit(exit_code)


def acquire_single_instance():
  """Ensure only one instance of ImmediPaste is running."""
  import tempfile
  lock_path = os.path.join(tempfile.gettempdir(), "immedipaste.lock")
  lock_file = open(lock_path, "w")
  try:
    if sys.platform == "win32":
      import msvcrt
      msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
    else:
      import fcntl
      fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
  except (OSError, IOError):
    log.info("Another instance is already running, exiting")
    sys.exit(0)
  return lock_file


if __name__ == "__main__":
  _lock = acquire_single_instance()
  app = ImmediPaste()
  app.run()
