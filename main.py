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
from platform_utils import default_save_folder

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
}


def load_config():
  if not os.path.exists(CONFIG_PATH):
    save_config(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)
  with open(CONFIG_PATH) as f:
    return json.load(f)


def save_config(config):
  with open(CONFIG_PATH, "w") as f:
    json.dump(config, f, indent=2)
    f.write("\n")


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


class SettingsDialog(QDialog):
  def __init__(self, config, parent=None):
    super().__init__(parent)
    self.setWindowTitle("ImmediPaste Settings")
    self.setFixedSize(480, 420)
    self._position_near_tray()

    layout = QVBoxLayout(self)

    # Description
    desc = QLabel("Screenshot tool that captures and copies to clipboard instantly.")
    desc.setStyleSheet("color: #555555;")
    desc.setWordWrap(True)
    layout.addWidget(desc)

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
    self.hotkey_edit = QLineEdit(config.get("hotkey_region", "<ctrl>+<alt>+<shift>+s"))
    form.addRow("Region hotkey:", self.hotkey_edit)

    # Window hotkey
    self.win_hotkey_edit = QLineEdit(config.get("hotkey_window", "<ctrl>+<alt>+<shift>+d"))
    form.addRow("Window hotkey:", self.win_hotkey_edit)

    # Fullscreen hotkey
    self.fs_hotkey_edit = QLineEdit(config.get("hotkey_fullscreen", "<ctrl>+<alt>+<shift>+f"))
    form.addRow("Fullscreen hotkey:", self.fs_hotkey_edit)

    # Hint
    hint = QLabel("e.g. <ctrl>+<alt>+<shift>+s")
    hint.setStyleSheet("color: gray;")
    form.addRow("", hint)

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

    # Buttons
    btn_layout = QHBoxLayout()
    btn_layout.addStretch()
    save_btn = QPushButton("Save")
    save_btn.clicked.connect(self.accept)
    cancel_btn = QPushButton("Cancel")
    cancel_btn.clicked.connect(self.reject)
    btn_layout.addWidget(save_btn)
    btn_layout.addWidget(cancel_btn)
    layout.addLayout(btn_layout)

  def _position_near_tray(self):
    screen = QApplication.primaryScreen().geometry()
    x = screen.width() - self.width() - 16
    y = screen.height() - self.height() - 60
    self.move(x, y)

  def _browse_folder(self):
    path = QFileDialog.getExistingDirectory(
      self, "Select Save Folder",
      os.path.expanduser(self.folder_edit.text()),
    )
    if path:
      self.folder_edit.setText(path)

  def get_config(self):
    return {
      "save_folder": self.folder_edit.text(),
      "hotkey_region": self.hotkey_edit.text(),
      "hotkey_window": self.win_hotkey_edit.text(),
      "hotkey_fullscreen": self.fs_hotkey_edit.text(),
      "format": self.fmt_combo.currentText(),
      "filename_prefix": self.prefix_edit.text(),
      "save_to_disk": self.save_disk_check.isChecked(),
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
      os.makedirs(folder, exist_ok=True)

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

  def _on_capture_done(self, filepath):
    self.capturing = False
    self._overlay = None

    if filepath:
      self.capture_history.append(filepath)
      if len(self.capture_history) > MAX_HISTORY:
        self.capture_history = self.capture_history[-MAX_HISTORY:]
      self._last_capture_path = filepath

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
    system = platform.system()
    if system == "Windows":
      subprocess.Popen(["explorer", "/select,", os.path.normpath(filepath)])
    elif system == "Darwin":
      subprocess.Popen(["open", "-R", filepath])
    else:
      subprocess.Popen(["xdg-open", os.path.dirname(filepath)])

  def open_settings(self):
    dialog = SettingsDialog(self.config)
    dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    if dialog.exec() == QDialog.DialogCode.Accepted:
      new_config = dialog.get_config()
      self.config.update(new_config)
      save_config(self.config)
      self.reload_settings()
      if self.tray_icon:
        self.tray_icon.showMessage(
          "ImmediPaste", "Settings saved.",
          QSystemTrayIcon.MessageIcon.Information, 2000,
        )

  def _start_hotkey_listener(self):
    region_str = self.config.get("hotkey_region", "<ctrl>+<alt>+<shift>+s")
    window_str = self.config.get("hotkey_window", "<ctrl>+<alt>+<shift>+d")
    fullscreen_str = self.config.get("hotkey_fullscreen", "<ctrl>+<alt>+<shift>+f")

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

    print("ImmediPaste running. Region: Ctrl+Alt+Shift+S | Window: Ctrl+Alt+Shift+D | Fullscreen: Ctrl+Alt+Shift+F")

    exit_code = self.app.exec()
    self._listener.stop()
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
    print("ImmediPaste is already running.")
    sys.exit(0)
  return lock_file


if __name__ == "__main__":
  _lock = acquire_single_instance()
  app = ImmediPaste()
  app.run()
