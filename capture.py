import ctypes
import io
import os
import tkinter as tk
from datetime import datetime

import mss
import win32clipboard
from PIL import Image, ImageTk
from pynput import keyboard as kb

# Make tkinter DPI-aware so coordinates match actual screen pixels
ctypes.windll.shcore.SetProcessDpiAwareness(2)


class CaptureOverlay:
  """Fullscreen overlay for region selection. Also supports full-screen capture."""

  def __init__(self, save_folder, fmt="jpg", on_done=None):
    self.save_folder = save_folder
    self.fmt = fmt.lower()
    self.on_done = on_done
    self.start_x = 0
    self.start_y = 0
    self.rect_id = None
    self.dim_ids = []
    self.bright_id = None
    self.screenshot = None
    self.root = None

  def start(self):
    """Take a screenshot and show the selection overlay."""
    with mss.mss() as sct:
      monitor = sct.monitors[0]
      raw = sct.grab(monitor)
      self.screenshot = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
      self.screen_left = monitor["left"]
      self.screen_top = monitor["top"]

    self.width, self.height = self.screenshot.size

    # Pre-compute dimmed overlay
    dimmed = self.screenshot.copy()
    dark = Image.new("RGBA", dimmed.size, (0, 0, 0, 120))
    dimmed = Image.alpha_composite(dimmed.convert("RGBA"), dark).convert("RGB")

    # Set up tkinter window
    self.root = tk.Tk()
    self.root.withdraw()
    self.root.overrideredirect(True)
    self.root.attributes("-topmost", True)
    self.root.configure(cursor="crosshair")
    self.root.geometry(
      f"{self.width}x{self.height}+{self.screen_left}+{self.screen_top}"
    )

    # Canvas with dimmed screenshot as background
    self.canvas = tk.Canvas(
      self.root, width=self.width, height=self.height, highlightthickness=0
    )
    self.canvas.pack()

    self.bg_image = ImageTk.PhotoImage(dimmed)
    self.canvas.create_image(0, 0, anchor=tk.NW, image=self.bg_image)

    # Keep a reference to the bright image for the selection preview
    self.bright_image_full = self.screenshot.copy()

    # Bind mouse events
    self.canvas.bind("<ButtonPress-1>", self._on_press)
    self.canvas.bind("<B1-Motion>", self._on_drag)
    self.canvas.bind("<ButtonRelease-1>", self._on_release)
    self.root.bind("<Button-3>", lambda e: self._cancel())

    # Use pynput for keyboard since overrideredirect windows
    # don't receive keyboard events on Windows
    def on_key_press(key):
      if key == kb.Key.esc:
        self.root.after(0, self._cancel)
        return False  # stop listener
      if key in (kb.Key.enter, kb.Key.space):
        self.root.after(0, self._capture_fullscreen)
        return False
    self._kb_listener = kb.Listener(on_press=on_key_press)
    self._kb_listener.start()

    self.root.deiconify()
    self.root.mainloop()
    # Clean up after mainloop exits (quit was called)
    try:
      self.root.destroy()
    except tk.TclError:
      pass

  def _on_press(self, event):
    self.start_x = event.x
    self.start_y = event.y

  def _on_drag(self, event):
    # Clean up previous selection visuals
    if self.rect_id:
      self.canvas.delete(self.rect_id)
    for dim_id in self.dim_ids:
      self.canvas.delete(dim_id)
    self.dim_ids.clear()
    if self.bright_id:
      self.canvas.delete(self.bright_id)
      self.bright_id = None

    x1, y1 = min(self.start_x, event.x), min(self.start_y, event.y)
    x2, y2 = max(self.start_x, event.x), max(self.start_y, event.y)

    if (x2 - x1) < 2 or (y2 - y1) < 2:
      return

    # Show bright (original) image in the selected region
    cropped = self.bright_image_full.crop((x1, y1, x2, y2))
    self._bright_photo = ImageTk.PhotoImage(cropped)
    self.bright_id = self.canvas.create_image(
      x1, y1, anchor=tk.NW, image=self._bright_photo
    )

    # Selection border
    self.rect_id = self.canvas.create_rectangle(
      x1, y1, x2, y2, outline="#00aaff", width=2
    )

    # Dimension label
    w, h = x2 - x1, y2 - y1
    label_y = y1 - 20 if y1 > 25 else y2 + 5
    self.dim_ids.append(
      self.canvas.create_text(
        x1, label_y,
        text=f"{w} x {h}",
        anchor=tk.NW,
        fill="#00aaff",
        font=("Consolas", 11, "bold"),
      )
    )

  def _on_release(self, event):
    x1, y1 = min(self.start_x, event.x), min(self.start_y, event.y)
    x2, y2 = max(self.start_x, event.x), max(self.start_y, event.y)

    if (x2 - x1) < 3 or (y2 - y1) < 3:
      self._cancel()
      return

    self._stop_kb_listener()
    self.root.quit()
    cropped = self.screenshot.crop((x1, y1, x2, y2))
    filepath = self._save(cropped)
    self._copy_to_clipboard(cropped)

    if self.on_done:
      self.on_done(filepath)

  def _capture_fullscreen(self):
    """Capture the entire screen without selection."""
    self._stop_kb_listener()
    self.root.quit()
    filepath = self._save(self.screenshot)
    self._copy_to_clipboard(self.screenshot)

    if self.on_done:
      self.on_done(filepath)

  def _save(self, image):
    folder = os.path.expanduser(self.save_folder)
    os.makedirs(folder, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    ext = self.fmt
    filepath = os.path.join(folder, f"immedipaste_{timestamp}.{ext}")
    if ext in ("jpg", "jpeg"):
      image.convert("RGB").save(filepath, "JPEG", quality=85)
    elif ext == "webp":
      image.save(filepath, "WEBP", quality=85)
    else:
      image.save(filepath, "PNG")
    return filepath

  def _copy_to_clipboard(self, image):
    buf = io.BytesIO()
    image.convert("RGB").save(buf, "BMP")
    bmp_data = buf.getvalue()[14:]  # Strip 14-byte BMP file header
    buf.close()

    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardData(win32clipboard.CF_DIB, bmp_data)
    win32clipboard.CloseClipboard()

  def capture_fullscreen_direct(self):
    """Capture entire screen immediately, no overlay."""
    with mss.mss() as sct:
      monitor = sct.monitors[0]
      raw = sct.grab(monitor)
      screenshot = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    filepath = self._save(screenshot)
    self._copy_to_clipboard(screenshot)

    if self.on_done:
      self.on_done(filepath)

  def _cancel(self):
    self._stop_kb_listener()
    self.root.quit()

  def _stop_kb_listener(self):
    if hasattr(self, '_kb_listener') and self._kb_listener.running:
      self._kb_listener.stop()
