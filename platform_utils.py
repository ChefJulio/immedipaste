"""Platform-specific utilities for clipboard and DPI handling."""

import io
import platform
import shutil
import subprocess

SYSTEM = platform.system()


def set_dpi_awareness():
  """Set DPI awareness on Windows so coordinates match screen pixels."""
  if SYSTEM == "Windows":
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)


def copy_image_to_clipboard(image):
  """Copy a PIL Image to the system clipboard.

  Windows: win32clipboard (CF_DIB)
  macOS: osascript via temp file
  Linux: xclip or xsel with PNG pipe
  """
  if SYSTEM == "Windows":
    _clipboard_windows(image)
  elif SYSTEM == "Darwin":
    _clipboard_macos(image)
  else:
    _clipboard_linux(image)


def _clipboard_windows(image):
  import win32clipboard
  buf = io.BytesIO()
  image.convert("RGB").save(buf, "BMP")
  bmp_data = buf.getvalue()[14:]  # Strip 14-byte BMP file header
  buf.close()

  win32clipboard.OpenClipboard()
  win32clipboard.EmptyClipboard()
  win32clipboard.SetClipboardData(win32clipboard.CF_DIB, bmp_data)
  win32clipboard.CloseClipboard()


def _clipboard_macos(image):
  import tempfile
  with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
    image.save(f, "PNG")
    tmp_path = f.name

  script = (
    'set the clipboard to '
    f'(read (POSIX file "{tmp_path}") as TIFF picture)'
  )
  subprocess.run(["osascript", "-e", script], check=True)

  import os
  os.unlink(tmp_path)


def _clipboard_linux(image):
  # Try xclip first, then xsel
  buf = io.BytesIO()
  image.save(buf, "PNG")
  png_data = buf.getvalue()
  buf.close()

  if shutil.which("xclip"):
    proc = subprocess.Popen(
      ["xclip", "-selection", "clipboard", "-t", "image/png"],
      stdin=subprocess.PIPE,
    )
    proc.communicate(png_data)
  elif shutil.which("xsel"):
    proc = subprocess.Popen(
      ["xsel", "--clipboard", "--input"],
      stdin=subprocess.PIPE,
    )
    proc.communicate(png_data)
  elif shutil.which("wl-copy"):
    # Wayland
    proc = subprocess.Popen(
      ["wl-copy", "--type", "image/png"],
      stdin=subprocess.PIPE,
    )
    proc.communicate(png_data)
  else:
    raise RuntimeError(
      "No clipboard tool found. Install xclip, xsel, or wl-copy."
    )


def default_save_folder():
  """Return a sensible default screenshot folder per platform."""
  import os
  home = os.path.expanduser("~")

  if SYSTEM == "Windows":
    # Check OneDrive first, then local
    onedrive = os.path.join(home, "OneDrive", "Pictures", "Screenshots")
    if os.path.isdir(onedrive):
      return "~/OneDrive/Pictures/Screenshots"
    return "~/Pictures/Screenshots"
  elif SYSTEM == "Darwin":
    return "~/Desktop"
  else:
    # XDG screenshots or Pictures
    pictures = os.path.join(home, "Pictures", "Screenshots")
    return "~/Pictures/Screenshots"
