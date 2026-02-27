"""Centralized logging for ImmediPaste."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from logging.handlers import RotatingFileHandler

LOG_FILENAME = "immedipaste.log"


def _resolve_log_dir() -> str:
  """Pick a writable directory for the log file.

  Priority: app dir (next to exe) > %APPDATA%/ImmediPaste > temp dir.
  """
  if getattr(sys, "frozen", False):
    app_dir = os.path.dirname(sys.executable)
  else:
    app_dir = os.path.dirname(os.path.abspath(__file__))

  # Try app dir first (works in dev and portable installs)
  test_path = os.path.join(app_dir, LOG_FILENAME)
  try:
    with open(test_path, "a"):
      pass
    return app_dir
  except OSError:
    pass

  # Fall back to platform-appropriate app data dir
  if sys.platform == "win32":
    appdata = os.environ.get("APPDATA", "")
    if appdata:
      log_dir = os.path.join(appdata, "ImmediPaste")
      try:
        os.makedirs(log_dir, exist_ok=True)
        return log_dir
      except OSError:
        pass
  else:
    xdg = os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state"))
    log_dir = os.path.join(xdg, "immedipaste")
    try:
      os.makedirs(log_dir, exist_ok=True)
      return log_dir
    except OSError:
      pass

  # Last resort: temp dir
  return tempfile.gettempdir()


_log_dir = _resolve_log_dir()
LOG_PATH = os.path.join(_log_dir, LOG_FILENAME)

_formatter = logging.Formatter(
  "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
  datefmt="%Y-%m-%d %H:%M:%S",
)

# File handler with rotation (1 MB, 3 backups)
try:
  _file_handler = RotatingFileHandler(
    LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8",
  )
  _file_handler.setFormatter(_formatter)
except OSError:
  _file_handler = None

# Console handler (stderr)
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_formatter)


def get_logger(name: str) -> logging.Logger:
  """Get a named logger with file and console handlers."""
  logger = logging.getLogger(f"immedipaste.{name}")
  if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if _file_handler:
      logger.addHandler(_file_handler)
    logger.addHandler(_console_handler)
  return logger
