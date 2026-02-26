import json
import os
import platform
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog

import pystray
from PIL import Image, ImageDraw
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
  "hotkey_fullscreen": "<ctrl>+<alt>+<shift>+d",
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


def create_tray_icon_image():
  """Generate a simple camera-style tray icon."""
  size = 64
  img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
  draw = ImageDraw.Draw(img)
  # Camera body
  draw.rounded_rectangle([4, 16, 60, 56], radius=8, fill="#2196F3")
  # Lens
  draw.ellipse([22, 24, 42, 48], fill="white")
  draw.ellipse([27, 29, 37, 43], fill="#1565C0")
  # Flash bump
  draw.rectangle([24, 10, 40, 18], fill="#2196F3")
  return img


class ImmediPaste:
  def __init__(self):
    self.config = load_config()
    self.capturing = False
    self.tray_icon = None
    self.capture_history = []
    # Ensure save folder exists
    folder = os.path.expanduser(self.config.get("save_folder", ""))
    if folder:
      os.makedirs(folder, exist_ok=True)

  def trigger_capture(self):
    """Launch region selection overlay in a new thread."""
    if self.capturing:
      return
    self.capturing = True

    def run():
      try:
        overlay = CaptureOverlay(
          save_folder=self.config["save_folder"],
          fmt=self.config.get("format", "jpg"),
          save_to_disk=self.config.get("save_to_disk", True),
          filename_prefix=self.config.get("filename_prefix", "immedipaste"),
          on_done=self._on_capture_done,
        )
        overlay.start()
      finally:
        self.capturing = False

    threading.Thread(target=run, daemon=True).start()

  def trigger_fullscreen(self):
    """Capture full screen immediately, no overlay."""
    if self.capturing:
      return
    self.capturing = True

    def run():
      try:
        cap = CaptureOverlay(
          save_folder=self.config["save_folder"],
          fmt=self.config.get("format", "jpg"),
          save_to_disk=self.config.get("save_to_disk", True),
          filename_prefix=self.config.get("filename_prefix", "immedipaste"),
          on_done=self._on_capture_done,
        )
        cap.capture_fullscreen_direct()
      finally:
        self.capturing = False

    threading.Thread(target=run, daemon=True).start()

  def _on_capture_done(self, filepath):
    if filepath:
      self.capture_history.append(filepath)
      if len(self.capture_history) > MAX_HISTORY:
        self.capture_history = self.capture_history[-MAX_HISTORY:]
      self._rebuild_tray_menu()
    if self.tray_icon:
      if filepath:
        self.tray_icon.notify(f"Saved: {os.path.basename(filepath)}", "ImmediPaste")
      else:
        self.tray_icon.notify("Copied to clipboard", "ImmediPaste")

  @staticmethod
  def _show_in_explorer(filepath):
    """Open the file's parent folder and select the file."""
    system = platform.system()
    if system == "Windows":
      subprocess.Popen(["explorer", "/select,", os.path.normpath(filepath)])
    elif system == "Darwin":
      subprocess.Popen(["open", "-R", filepath])
    else:
      subprocess.Popen(["xdg-open", os.path.dirname(filepath)])

  def open_settings(self):
    """Open a settings dialog in a new thread."""
    def run_dialog():
      root = tk.Tk()
      root.title("ImmediPaste Settings")
      root.resizable(False, False)
      root.attributes("-topmost", True)

      # Position near the system tray (bottom-right)
      root.update_idletasks()
      screen_w = root.winfo_screenwidth()
      screen_h = root.winfo_screenheight()
      win_w = 480
      win_h = 360
      x = screen_w - win_w - 16
      y = screen_h - win_h - 60
      root.geometry(f"{win_w}x{win_h}+{x}+{y}")

      # Description
      desc = tk.Label(
        root,
        text="Screenshot tool that captures and copies to clipboard instantly.",
        fg="#555555", wraplength=380, justify="left",
      )
      desc.grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(10, 6))

      # Save folder
      tk.Label(root, text="Save folder:").grid(row=1, column=0, sticky="w", padx=8, pady=(4, 4))
      folder_var = tk.StringVar(value=self.config.get("save_folder", ""))
      folder_entry = tk.Entry(root, textvariable=folder_var, width=40)
      folder_entry.grid(row=1, column=1, padx=4, pady=(4, 4))

      def browse_folder():
        initial = os.path.expanduser(folder_var.get())
        path = filedialog.askdirectory(initialdir=initial, parent=root)
        if path:
          folder_var.set(path)

      tk.Button(root, text="Browse...", command=browse_folder).grid(row=1, column=2, padx=(0, 8), pady=(4, 4))

      # Region hotkey
      tk.Label(root, text="Region hotkey:").grid(row=2, column=0, sticky="w", padx=8, pady=4)
      hotkey_var = tk.StringVar(value=self.config.get("hotkey_region", "<ctrl>+<alt>+<shift>+s"))
      tk.Entry(root, textvariable=hotkey_var, width=40).grid(row=2, column=1, padx=4, pady=4)

      # Fullscreen hotkey
      tk.Label(root, text="Fullscreen hotkey:").grid(row=3, column=0, sticky="w", padx=8, pady=4)
      fs_hotkey_var = tk.StringVar(value=self.config.get("hotkey_fullscreen", "<ctrl>+<alt>+<shift>+d"))
      tk.Entry(root, textvariable=fs_hotkey_var, width=40).grid(row=3, column=1, padx=4, pady=4)

      tk.Label(root, text="e.g. <ctrl>+<alt>+<shift>+s", fg="gray").grid(row=4, column=1, sticky="w", padx=4)

      # Image format
      tk.Label(root, text="Save format:").grid(row=5, column=0, sticky="w", padx=8, pady=4)
      fmt_var = tk.StringVar(value=self.config.get("format", "jpg"))
      fmt_menu = tk.OptionMenu(root, fmt_var, "jpg", "png", "webp")
      fmt_menu.config(width=8)
      fmt_menu.grid(row=5, column=1, sticky="w", padx=4, pady=4)

      # Filename prefix
      tk.Label(root, text="Filename prefix:").grid(row=6, column=0, sticky="w", padx=8, pady=4)
      prefix_var = tk.StringVar(value=self.config.get("filename_prefix", "immedipaste"))
      tk.Entry(root, textvariable=prefix_var, width=40).grid(row=6, column=1, padx=4, pady=4)

      # Save to disk toggle
      save_disk_var = tk.BooleanVar(value=self.config.get("save_to_disk", True))
      tk.Checkbutton(root, text="Also save screenshots to disk", variable=save_disk_var).grid(
        row=7, column=0, columnspan=2, sticky="w", padx=8, pady=4,
      )

      # Buttons
      btn_frame = tk.Frame(root)
      btn_frame.grid(row=8, column=0, columnspan=3, pady=12)

      def on_save():
        self.config["save_folder"] = folder_var.get()
        self.config["hotkey_region"] = hotkey_var.get()
        self.config["hotkey_fullscreen"] = fs_hotkey_var.get()
        self.config["format"] = fmt_var.get()
        self.config["filename_prefix"] = prefix_var.get()
        self.config["save_to_disk"] = save_disk_var.get()
        save_config(self.config)
        root.destroy()
        self.reload_settings()
        if self.tray_icon:
          self.tray_icon.notify("Settings saved.", "ImmediPaste")

      tk.Button(btn_frame, text="Save", width=10, command=on_save).pack(side="left", padx=8)
      tk.Button(btn_frame, text="Cancel", width=10, command=root.destroy).pack(side="left", padx=8)

      root.mainloop()

    threading.Thread(target=run_dialog, daemon=True).start()

  def _start_hotkey_listener(self):
    """Create and start a keyboard listener for the current hotkey config."""
    region_str = self.config.get("hotkey_region", "<ctrl>+<alt>+<shift>+s")
    fullscreen_str = self.config.get("hotkey_fullscreen", "<ctrl>+<alt>+<shift>+d")

    hotkey_region = keyboard.HotKey(
      keyboard.HotKey.parse(region_str),
      self.trigger_capture,
    )
    hotkey_fullscreen = keyboard.HotKey(
      keyboard.HotKey.parse(fullscreen_str),
      self.trigger_fullscreen,
    )

    def on_press(k):
      key = self._listener.canonical(k)
      hotkey_region.press(key)
      hotkey_fullscreen.press(key)

    def on_release(k):
      key = self._listener.canonical(k)
      hotkey_region.release(key)
      hotkey_fullscreen.release(key)

    self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    self._listener.start()

  def reload_settings(self):
    """Reload hotkeys and settings without restarting."""
    self._listener.stop()
    self._start_hotkey_listener()

  def _build_tray_menu(self):
    """Build the tray menu, including recent captures if any."""
    items = [
      pystray.MenuItem(
        "Capture Region  (Ctrl+Alt+Shift+S)",
        lambda: self.trigger_capture(),
      ),
      pystray.MenuItem(
        "Capture Fullscreen  (Ctrl+Alt+Shift+D)",
        lambda: self.trigger_fullscreen(),
      ),
    ]

    if self.capture_history:
      items.append(pystray.Menu.SEPARATOR)
      # Most recent first
      for path in reversed(self.capture_history):
        name = os.path.basename(path)
        # Capture path in closure
        items.append(pystray.MenuItem(
          name, lambda _, p=path: self._show_in_explorer(p),
        ))

    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem("Settings", lambda: self.open_settings()))
    items.append(pystray.MenuItem("Exit", lambda icon, item: icon.stop()))
    return pystray.Menu(*items)

  def _rebuild_tray_menu(self):
    """Update the tray menu after a new capture."""
    if self.tray_icon:
      self.tray_icon.menu = self._build_tray_menu()
      self.tray_icon.update_menu()

  def run(self):
    self._start_hotkey_listener()

    # System tray
    self.tray_icon = pystray.Icon(
      "immedipaste",
      create_tray_icon_image(),
      "ImmediPaste",
      menu=self._build_tray_menu(),
    )

    print("ImmediPaste running. Region: Ctrl+Alt+Shift+S | Fullscreen: Ctrl+Alt+Shift+D")
    self.tray_icon.run()
    self._listener.stop()


def acquire_single_instance():
  """Ensure only one instance of ImmediPaste is running.

  Returns the lock file handle (must stay open for the app's lifetime).
  Exits with a message if another instance is already running.
  """
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
