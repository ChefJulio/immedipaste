"""Centralized logging for ImmediPaste."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# Mirror APP_DIR logic from main.py
if getattr(sys, "frozen", False):
  _app_dir = os.path.dirname(sys.executable)
else:
  _app_dir = os.path.dirname(os.path.abspath(__file__))

LOG_PATH = os.path.join(_app_dir, "immedipaste.log")

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


def get_logger(name):
  """Get a named logger with file and console handlers."""
  logger = logging.getLogger(f"immedipaste.{name}")
  if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    if _file_handler:
      logger.addHandler(_file_handler)
    logger.addHandler(_console_handler)
  return logger
