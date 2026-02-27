from __future__ import annotations

import os
from datetime import datetime
from typing import Callable, TYPE_CHECKING

import mss
from PySide6.QtCore import Qt, QRect, QPoint
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QFont, QFontDatabase, QCursor
from PySide6.QtWidgets import QWidget

from log import get_logger
from platform_utils import copy_image_to_clipboard

if TYPE_CHECKING:
  from PySide6.QtGui import QPaintEvent, QMouseEvent, QKeyEvent

log = get_logger("capture")


class CaptureOverlay(QWidget):
  """Fullscreen overlay for region or window capture."""

  def __init__(self, save_folder: str, fmt: str = "jpg", save_to_disk: bool = True,
               filename_prefix: str = "immedipaste",
               on_done: Callable[..., None] | None = None,
               mode: str = "region"):
    super().__init__()
    self.save_folder = save_folder
    self.fmt = fmt.lower()
    self.save_to_disk = save_to_disk
    self.filename_prefix = filename_prefix
    self.on_done = on_done
    self.mode = mode  # "region" or "window"

    # Region mode state
    self.start_pos = QPoint()
    self.current_pos = QPoint()
    self.is_selecting = False

    # Window mode state
    self.highlight_rect = None
    self._overlay_hwnd = 0

    self.screenshot_qimage = None
    self.dimmed_pixmap = None
    self.screenshot_pixmap = None

  def start(self) -> None:
    """Take a screenshot and show the selection overlay."""
    try:
      self._take_screenshot()
    except Exception as e:
      log.error("Failed to take screenshot: %s", e)
      if self.on_done:
        self.on_done(None, error=f"Screenshot failed: {e}")
      return

    self._prepare_dimmed()

    self.setWindowFlags(
      Qt.WindowType.FramelessWindowHint
      | Qt.WindowType.WindowStaysOnTopHint
      | Qt.WindowType.Tool
    )
    self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

    if self.mode == "window":
      self.setMouseTracking(True)

    self.setGeometry(
      self.screen_left, self.screen_top,
      self.screenshot_qimage.width(), self.screenshot_qimage.height(),
    )
    self.show()

    if self.mode == "window":
      self._overlay_hwnd = int(self.winId())

  def _take_screenshot(self) -> None:
    """Capture all monitors using mss, store as QImage."""
    with mss.mss() as sct:
      monitor = sct.monitors[0]
      raw = sct.grab(monitor)
      self.screenshot_qimage = QImage(
        bytes(raw.bgra), raw.width, raw.height, QImage.Format.Format_ARGB32,
      ).copy()
      self.screen_left = monitor["left"]
      self.screen_top = monitor["top"]

  def _prepare_dimmed(self) -> None:
    """Create a dimmed version of the screenshot for the overlay background."""
    self.screenshot_pixmap = QPixmap.fromImage(self.screenshot_qimage)
    self.dimmed_pixmap = self.screenshot_pixmap.copy()
    painter = QPainter(self.dimmed_pixmap)
    painter.fillRect(self.dimmed_pixmap.rect(), QColor(0, 0, 0, 120))
    painter.end()

  # -- Rendering --------------------------------------------------------

  def _draw_highlight(self, painter: QPainter, rect: QRect) -> None:
    """Draw a bright selection region with border and dimension label."""
    painter.drawPixmap(rect, self.screenshot_pixmap, rect)

    painter.setPen(QPen(QColor("#00aaff"), 2))
    painter.drawRect(rect)

    label = f"{rect.width()} x {rect.height()}"
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSize(11)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#00aaff"))
    label_y = rect.top() - 8 if rect.top() > 25 else rect.bottom() + 18
    painter.drawText(rect.left(), label_y, label)

  def paintEvent(self, event: QPaintEvent) -> None:
    painter = QPainter(self)
    painter.drawPixmap(0, 0, self.dimmed_pixmap)

    # Region mode: drag selection
    if self.is_selecting:
      rect = QRect(self.start_pos, self.current_pos).normalized()
      if rect.width() > 2 and rect.height() > 2:
        self._draw_highlight(painter, rect)

    # Window mode: hover highlight
    if self.mode == "window" and self.highlight_rect:
      self._draw_highlight(painter, self.highlight_rect)

    painter.end()

  # -- Mouse events -----------------------------------------------------

  def mousePressEvent(self, event: QMouseEvent) -> None:
    if event.button() == Qt.MouseButton.RightButton:
      self._cancel()
      return
    if event.button() == Qt.MouseButton.LeftButton:
      if self.mode == "window":
        self._capture_window()
      else:
        self.start_pos = event.position().toPoint()
        self.current_pos = self.start_pos
        self.is_selecting = True

  def mouseMoveEvent(self, event: QMouseEvent) -> None:
    if self.mode == "window":
      self._update_window_highlight(event.position().toPoint())
    elif self.is_selecting:
      self.current_pos = event.position().toPoint()
      self.update()

  def mouseReleaseEvent(self, event: QMouseEvent) -> None:
    if event.button() == Qt.MouseButton.LeftButton and self.is_selecting:
      self.is_selecting = False
      rect = QRect(self.start_pos, event.position().toPoint()).normalized()
      if rect.width() < 3 or rect.height() < 3:
        self._cancel()
        return
      cropped = self.screenshot_qimage.copy(rect)
      self._finish_capture(cropped)

  # -- Keyboard events --------------------------------------------------

  def keyPressEvent(self, event: QKeyEvent) -> None:
    if event.key() == Qt.Key.Key_Escape:
      self._cancel()
    elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
      self._capture_fullscreen()

  # -- Window detection -------------------------------------------------

  def _update_window_highlight(self, pos: QPoint) -> None:
    """Detect the window under the cursor and highlight it."""
    from window_utils import get_cursor_pos, get_window_rect_at

    # Use Win32 GetCursorPos for physical screen coordinates
    # (matches coordinate space of window rects from EnumWindows,
    # avoids logical vs physical pixel mismatch on high-DPI displays)
    screen_x, screen_y = get_cursor_pos()

    result = get_window_rect_at(screen_x, screen_y, self._overlay_hwnd)
    if result:
      left, top, right, bottom = result
      local_rect = QRect(
        left - self.screen_left,
        top - self.screen_top,
        right - left,
        bottom - top,
      )
      # Clip to overlay bounds
      local_rect = local_rect.intersected(
        QRect(0, 0, self.screenshot_qimage.width(), self.screenshot_qimage.height())
      )
      if local_rect != self.highlight_rect:
        self.highlight_rect = local_rect
        self.update()
    elif self.highlight_rect is not None:
      self.highlight_rect = None
      self.update()

  def _capture_window(self) -> None:
    """Capture the currently highlighted window."""
    if self.highlight_rect and self.highlight_rect.width() > 2 and self.highlight_rect.height() > 2:
      cropped = self.screenshot_qimage.copy(self.highlight_rect)
      self._finish_capture(cropped)
    else:
      self._cancel()

  # -- Capture logic ----------------------------------------------------

  def _finish_capture(self, qimage: QImage) -> None:
    """Copy to clipboard, optionally save, notify parent, close."""
    clipboard_ok = copy_image_to_clipboard(qimage)
    filepath = self._save(qimage) if self.save_to_disk else None
    self.close()

    if not clipboard_ok and not filepath:
      if self.save_to_disk:
        error = "Capture failed: could not copy to clipboard or save to disk"
      else:
        error = "Capture failed: could not copy to clipboard"
    elif not clipboard_ok:
      error = "Copied to disk but clipboard copy failed"
    else:
      error = None

    if self.on_done:
      self.on_done(filepath, error=error)

  def _capture_fullscreen(self) -> None:
    """Capture the entire screen from the overlay."""
    self._finish_capture(self.screenshot_qimage)

  def _save(self, qimage: QImage) -> str | None:
    try:
      folder = os.path.expanduser(self.save_folder)
      os.makedirs(folder, exist_ok=True)
    except OSError as e:
      log.error("Cannot create save folder '%s': %s", self.save_folder, e)
      return None

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")[:-3]  # milliseconds
    ext = self.fmt
    filepath = os.path.join(folder, f"{self.filename_prefix}_{timestamp}.{ext}")

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

  def _cancel(self) -> None:
    self.close()
    if self.on_done:
      self.on_done(None, error="cancelled")

  # -- Standalone (no overlay) ------------------------------------------

  def capture_fullscreen_direct(self) -> None:
    """Capture entire screen immediately, no overlay."""
    try:
      self._take_screenshot()
    except Exception as e:
      log.error("Failed to take fullscreen screenshot: %s", e)
      if self.on_done:
        self.on_done(None, error=f"Screenshot failed: {e}")
      return

    clipboard_ok = copy_image_to_clipboard(self.screenshot_qimage)
    filepath = self._save(self.screenshot_qimage) if self.save_to_disk else None

    if not clipboard_ok and not filepath:
      if self.save_to_disk:
        error = "Capture failed: could not copy to clipboard or save to disk"
      else:
        error = "Capture failed: could not copy to clipboard"
    elif not clipboard_ok:
      error = "Copied to disk but clipboard copy failed"
    else:
      error = None

    if self.on_done:
      self.on_done(filepath, error=error)
