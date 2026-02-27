"""Platform-specific utilities."""

from __future__ import annotations

import os
import platform
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
