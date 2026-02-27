"""Tests for the logging module."""

import logging
import os

from log import get_logger, LOG_PATH, _resolve_log_dir


class TestGetLogger:
  def test_returns_logger(self):
    logger = get_logger("test_module")
    assert isinstance(logger, logging.Logger)

  def test_logger_has_handlers(self):
    logger = get_logger("test_handlers")
    assert len(logger.handlers) > 0

  def test_logger_name_prefixed(self):
    logger = get_logger("mymodule")
    assert logger.name == "immedipaste.mymodule"

  def test_same_logger_returned_on_repeat(self):
    a = get_logger("same")
    b = get_logger("same")
    assert a is b

  def test_no_duplicate_handlers(self):
    name = "no_dupes"
    get_logger(name)
    get_logger(name)
    logger = get_logger(name)
    # Should only have handlers added once
    handler_count = len(logger.handlers)
    assert handler_count <= 2  # file + console at most

  def test_log_path_is_string(self):
    assert isinstance(LOG_PATH, str)
    assert LOG_PATH.endswith("immedipaste.log")


class TestResolveLogDir:
  def test_returns_writable_directory(self):
    log_dir = _resolve_log_dir()
    assert os.path.isdir(log_dir)
    assert os.access(log_dir, os.W_OK)
