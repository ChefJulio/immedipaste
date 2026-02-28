"""Platform-specific utilities."""

from __future__ import annotations

import os
import platform
from datetime import datetime
from typing import TYPE_CHECKING

from log import get_logger

if TYPE_CHECKING:
  from PySide6.QtGui import QImage

SYSTEM = platform.system()
log = get_logger("platform")


def copy_image_to_clipboard(qimage: QImage) -> bool:
  """Copy a QImage to the system clipboard. Returns True on success."""
  try:
    from PySide6.QtWidgets import QApplication
    clipboard = QApplication.clipboard()
    clipboard.setImage(qimage)
    return True
  except Exception as e:
    log.error("Failed to copy image to clipboard: %s", e)
    return False


def save_qimage(qimage: QImage, save_folder: str, fmt: str = "jpg",
                filename_prefix: str = "immedipaste") -> str | None:
  """Save a QImage to disk. Returns the filepath on success, None on failure."""
  try:
    folder = os.path.expanduser(save_folder)
    os.makedirs(folder, exist_ok=True)
  except OSError as e:
    log.error("Cannot create save folder '%s': %s", save_folder, e)
    return None

  timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")[:-3]  # milliseconds
  ext = fmt.lower()
  # Strip path separators and traversal from prefix to prevent writing outside save folder
  safe_prefix = filename_prefix.replace("/", "_").replace("\\", "_").replace("..", "_")
  filepath = os.path.join(folder, "%s_%s.%s" % (safe_prefix, timestamp, ext))

  if ext in ("jpg", "jpeg"):
    ok = qimage.save(filepath, "JPEG", 85)
  elif ext == "webp":
    ok = qimage.save(filepath, "WEBP", 85)
  else:
    ok = qimage.save(filepath, "PNG")

  if not ok:
    log.error("Failed to save screenshot to %s", filepath)
    return None

  log.debug("Saved screenshot: %s", filepath)
  return filepath


def default_save_folder() -> str:
  """Return a sensible default screenshot folder per platform."""
  home = os.path.expanduser("~")

  if SYSTEM == "Windows":
    onedrive = os.path.join(home, "OneDrive", "Pictures", "Screenshots")
    if os.path.isdir(onedrive):
      return "~/OneDrive/Pictures/Screenshots"
    return "~/Pictures/Screenshots"
  elif SYSTEM == "Darwin":
    return "~/Desktop"
  else:
    return "~/Pictures/Screenshots"
