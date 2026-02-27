"""Platform-specific utilities."""

import os
import platform

SYSTEM = platform.system()


def copy_image_to_clipboard(qimage):
  """Copy a QImage to the system clipboard. Cross-platform via Qt."""
  from PySide6.QtWidgets import QApplication
  clipboard = QApplication.clipboard()
  clipboard.setImage(qimage)


def default_save_folder():
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
