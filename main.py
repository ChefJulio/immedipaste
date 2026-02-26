import json
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog

import pystray
from PIL import Image, ImageDraw
from pynput import keyboard

from capture import CaptureOverlay
from platform_utils import default_save_folder

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
          on_done=self._on_capture_done,
        )
        cap.capture_fullscreen_direct()
      finally:
        self.capturing = False

    threading.Thread(target=run, daemon=True).start()

  def _on_capture_done(self, filepath):
    if self.tray_icon:
      filename = os.path.basename(filepath)
      self.tray_icon.notify(f"Saved: {filename}", "ImmediPaste")

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
      win_h = 295
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

      # Buttons
      btn_frame = tk.Frame(root)
      btn_frame.grid(row=6, column=0, columnspan=3, pady=12)

      def on_save():
        self.config["save_folder"] = folder_var.get()
        self.config["hotkey_region"] = hotkey_var.get()
        self.config["hotkey_fullscreen"] = fs_hotkey_var.get()
        self.config["format"] = fmt_var.get()
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

  def run(self):
    self._start_hotkey_listener()

    # System tray
    self.tray_icon = pystray.Icon(
      "immedipaste",
      create_tray_icon_image(),
      "ImmediPaste",
      menu=pystray.Menu(
        pystray.MenuItem(
          "Capture Region  (Ctrl+Alt+Shift+S)",
          lambda: self.trigger_capture(),
        ),
        pystray.MenuItem(
          "Capture Fullscreen  (Ctrl+Alt+Shift+D)",
          lambda: self.trigger_fullscreen(),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Settings", lambda: self.open_settings()),
        pystray.MenuItem("Exit", lambda icon, item: icon.stop()),
      ),
    )

    print("ImmediPaste running. Region: Ctrl+Alt+Shift+S | Fullscreen: Ctrl+Alt+Shift+D")
    self.tray_icon.run()
    self._listener.stop()


if __name__ == "__main__":
  app = ImmediPaste()
  app.run()
