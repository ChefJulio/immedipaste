"""Annotation editor for captured screenshots."""

from __future__ import annotations

import dataclasses
import math
from typing import Callable, Union, TYPE_CHECKING

from PySide6.QtCore import Qt, QPoint, QPointF, QRect, QRectF, Signal
from PySide6.QtGui import (
  QImage, QPixmap, QPainter, QColor, QPen, QBrush, QFont,
  QFontDatabase, QFontMetricsF, QPainterPath, QCursor, QPolygonF, QIcon,
)
from PySide6.QtWidgets import (
  QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QSpinBox,
  QButtonGroup, QToolButton, QMenu, QColorDialog, QLineEdit, QLabel,
  QApplication,
)

from log import get_logger
from platform_utils import copy_image_to_clipboard, save_qimage

if TYPE_CHECKING:
  from PySide6.QtGui import QPaintEvent, QMouseEvent, QKeyEvent, QCloseEvent

log = get_logger("annotate")


# -- Data model ---------------------------------------------------------------

@dataclasses.dataclass
class FreehandAnnotation:
  points: list
  color: QColor
  width: float


@dataclasses.dataclass
class ArrowAnnotation:
  start: QPointF
  end: QPointF
  color: QColor
  width: float
  style: str  # "open", "standard", "double"


@dataclasses.dataclass
class OvalAnnotation:
  rect: QRectF
  color: QColor
  width: float


@dataclasses.dataclass
class RectAnnotation:
  rect: QRectF
  color: QColor
  width: float


@dataclasses.dataclass
class TextAnnotation:
  position: QPointF
  text: str
  color: QColor
  font_size: int


Annotation = Union[
  FreehandAnnotation, ArrowAnnotation, OvalAnnotation,
  RectAnnotation, TextAnnotation,
]

ARROW_STYLES = ("open", "standard", "double")
ARROW_STYLE_LABELS = {
  "open": "Hollow",
  "standard": "Filled",
  "double": "Double",
}

DEFAULT_COLOR = QColor(255, 0, 0)
DEFAULT_STROKE_WIDTH = 3
DEFAULT_FONT_SIZE = 16
MIN_DRAG_SIZE = 3
ICON_SIZE = 24


# -- Icon drawing helpers -----------------------------------------------------

def _make_icon(draw_fn) -> QIcon:
  """Create a QIcon by painting onto a 24x24 pixmap."""
  pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
  pixmap.fill(QColor(0, 0, 0, 0))
  painter = QPainter(pixmap)
  painter.setRenderHint(QPainter.RenderHint.Antialiasing)
  draw_fn(painter, ICON_SIZE)
  painter.end()
  return QIcon(pixmap)


def _draw_freehand_icon(painter: QPainter, size: int) -> None:
  pen = QPen(QColor(200, 200, 200), 2)
  painter.setPen(pen)
  path = QPainterPath()
  path.moveTo(3, size * 0.7)
  path.cubicTo(size * 0.25, size * 0.2, size * 0.5, size * 0.8, size - 3, size * 0.3)
  painter.drawPath(path)


def _draw_arrow_icon(painter: QPainter, size: int) -> None:
  pen = QPen(QColor(200, 200, 200), 2)
  painter.setPen(pen)
  painter.drawLine(4, size - 4, size - 6, 6)
  # Arrowhead
  painter.setBrush(QColor(200, 200, 200))
  head = QPolygonF([
    QPointF(size - 4, 4),
    QPointF(size - 10, 6),
    QPointF(size - 6, 12),
  ])
  painter.drawPolygon(head)


def _draw_oval_icon(painter: QPainter, size: int) -> None:
  pen = QPen(QColor(200, 200, 200), 2)
  painter.setPen(pen)
  painter.setBrush(Qt.BrushStyle.NoBrush)
  painter.drawEllipse(3, 5, size - 6, size - 10)


def _draw_rect_icon(painter: QPainter, size: int) -> None:
  pen = QPen(QColor(200, 200, 200), 2)
  painter.setPen(pen)
  painter.setBrush(Qt.BrushStyle.NoBrush)
  painter.drawRect(3, 5, size - 6, size - 10)


def _draw_text_icon(painter: QPainter, size: int) -> None:
  font = painter.font()
  font.setPointSize(14)
  font.setBold(True)
  painter.setFont(font)
  painter.setPen(QColor(200, 200, 200))
  painter.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "A")


# -- Color button -------------------------------------------------------------

class ColorButton(QPushButton):
  """Color swatch button that opens a QColorDialog on click."""
  color_changed = Signal(QColor)

  def __init__(self, color: QColor = DEFAULT_COLOR, parent: QWidget | None = None):
    super().__init__(parent)
    self._color = QColor(color)
    self.setFixedSize(28, 28)
    self.setToolTip("Annotation color")
    self._update_style()
    self.clicked.connect(self._pick_color)

  def color(self) -> QColor:
    return QColor(self._color)

  def _update_style(self) -> None:
    self.setStyleSheet(
      "QPushButton { background-color: %s; border: 2px solid #555; border-radius: 4px; }"
      "QPushButton:hover { border-color: #aaa; }"
      % self._color.name()
    )

  def _pick_color(self) -> None:
    c = QColorDialog.getColor(self._color, self.parentWidget(), "Annotation Color")
    if c.isValid():
      self._color = c
      self._update_style()
      self.color_changed.emit(c)


# -- Draggable toolbar --------------------------------------------------------

_DEFAULT_MODIFIER_TOOLS = {"shift": "arrow", "ctrl": "oval", "alt": "text"}
_MODIFIER_LABELS = {"shift": "Shift", "ctrl": "Ctrl", "alt": "Alt"}


class AnnotationToolbar(QWidget):
  """Floating draggable toolbar for annotation tools."""

  tool_changed = Signal(str)
  undo_requested = Signal()
  redo_requested = Signal()
  save_requested = Signal()
  cancel_requested = Signal()

  def __init__(self, parent: QWidget | None = None,
               modifier_tools: dict[str, str] | None = None):
    super().__init__(parent)
    self.setWindowFlags(Qt.WindowType.SubWindow)
    self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    self.setStyleSheet(
      "AnnotationToolbar { background: rgba(40, 40, 40, 220); border-radius: 8px; padding: 4px; }"
    )
    self.setCursor(Qt.CursorShape.ArrowCursor)

    self._drag_pos = None

    layout = QHBoxLayout(self)
    layout.setContentsMargins(8, 4, 8, 4)
    layout.setSpacing(4)

    # Drag handle label
    handle = QLabel(":::")
    handle.setStyleSheet("QLabel { color: #888; font-weight: bold; font-size: 14px; }")
    handle.setToolTip("Drag to move toolbar")
    layout.addWidget(handle)

    # Tool buttons
    self._tool_group = QButtonGroup(self)
    self._tool_group.setExclusive(True)

    btn_style = (
      "QPushButton { background: transparent; border: 1px solid #555; border-radius: 4px; padding: 2px; }"
      "QPushButton:checked { background: rgba(255, 255, 255, 40); border-color: #aaa; }"
      "QPushButton:hover { background: rgba(255, 255, 255, 20); }"
    )

    self._freehand_btn = QPushButton()
    self._freehand_btn.setIcon(_make_icon(_draw_freehand_icon))
    self._freehand_btn.setFixedSize(32, 32)
    self._freehand_btn.setCheckable(True)
    self._freehand_btn.setChecked(True)
    self._freehand_btn.setToolTip("Freehand (default drag)")
    self._freehand_btn.setStyleSheet(btn_style)
    self._tool_group.addButton(self._freehand_btn)
    layout.addWidget(self._freehand_btn)

    self._arrow_btn = QPushButton()
    self._arrow_btn.setIcon(_make_icon(_draw_arrow_icon))
    self._arrow_btn.setFixedSize(32, 32)
    self._arrow_btn.setCheckable(True)
    self._arrow_btn.setToolTip("Arrow (Shift + drag)")
    self._arrow_btn.setStyleSheet(btn_style)
    self._tool_group.addButton(self._arrow_btn)
    layout.addWidget(self._arrow_btn)

    self._oval_btn = QPushButton()
    self._oval_btn.setIcon(_make_icon(_draw_oval_icon))
    self._oval_btn.setFixedSize(32, 32)
    self._oval_btn.setCheckable(True)
    self._oval_btn.setToolTip("Oval (Ctrl + drag)")
    self._oval_btn.setStyleSheet(btn_style)
    self._tool_group.addButton(self._oval_btn)
    layout.addWidget(self._oval_btn)

    self._rect_btn = QPushButton()
    self._rect_btn.setIcon(_make_icon(_draw_rect_icon))
    self._rect_btn.setFixedSize(32, 32)
    self._rect_btn.setCheckable(True)
    self._rect_btn.setToolTip("Rectangle (Alt + drag)")
    self._rect_btn.setStyleSheet(btn_style)
    self._tool_group.addButton(self._rect_btn)
    layout.addWidget(self._rect_btn)

    self._text_btn = QPushButton()
    self._text_btn.setIcon(_make_icon(_draw_text_icon))
    self._text_btn.setFixedSize(32, 32)
    self._text_btn.setCheckable(True)
    self._text_btn.setToolTip("Text (click to place)")
    self._text_btn.setStyleSheet(btn_style)
    self._tool_group.addButton(self._text_btn)
    layout.addWidget(self._text_btn)

    # Separator
    sep1 = QLabel("|")
    sep1.setStyleSheet("QLabel { color: #555; }")
    layout.addWidget(sep1)

    # Arrow style selector
    self._arrow_style = "standard"
    self._arrow_style_btn = QToolButton()
    self._arrow_style_btn.setText("Filled")
    self._arrow_style_btn.setToolTip("Arrow style")
    self._arrow_style_btn.setFixedSize(48, 28)
    self._arrow_style_btn.setStyleSheet(
      "QToolButton { color: #ccc; background: transparent; border: 1px solid #555; border-radius: 4px; font-size: 11px; }"
      "QToolButton:hover { background: rgba(255, 255, 255, 20); }"
      "QToolButton::menu-indicator { image: none; }"
    )
    arrow_menu = QMenu(self)
    arrow_menu.setStyleSheet(
      "QMenu { background: #333; color: #ccc; border: 1px solid #555; }"
      "QMenu::item:selected { background: #555; }"
    )
    for style_key, style_label in ARROW_STYLE_LABELS.items():
      action = arrow_menu.addAction(style_label)
      action.setData(style_key)
      action.triggered.connect(lambda checked, s=style_key: self._set_arrow_style(s))
    self._arrow_style_btn.setMenu(arrow_menu)
    self._arrow_style_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    layout.addWidget(self._arrow_style_btn)

    # Separator
    sep2 = QLabel("|")
    sep2.setStyleSheet("QLabel { color: #555; }")
    layout.addWidget(sep2)

    # Color picker
    self.color_btn = ColorButton(DEFAULT_COLOR, self)
    layout.addWidget(self.color_btn)

    # Stroke width
    width_label = QLabel("W:")
    width_label.setStyleSheet("QLabel { color: #ccc; font-size: 11px; }")
    layout.addWidget(width_label)
    spin_style = (
      "QSpinBox { background: #333; color: #ccc; border: 1px solid #555;"
      " border-radius: 4px; padding-right: 18px; }"
      "QSpinBox::up-button { width: 16px; }"
      "QSpinBox::down-button { width: 16px; }"
    )
    self.width_spin = QSpinBox()
    self.width_spin.setRange(1, 20)
    self.width_spin.setValue(DEFAULT_STROKE_WIDTH)
    self.width_spin.setFixedWidth(58)
    self.width_spin.setToolTip("Stroke width")
    self.width_spin.setStyleSheet(spin_style)
    layout.addWidget(self.width_spin)

    # Font size (for text tool)
    font_label = QLabel("Pt:")
    font_label.setStyleSheet("QLabel { color: #ccc; font-size: 11px; }")
    layout.addWidget(font_label)
    self.font_spin = QSpinBox()
    self.font_spin.setRange(8, 72)
    self.font_spin.setValue(DEFAULT_FONT_SIZE)
    self.font_spin.setFixedWidth(58)
    self.font_spin.setToolTip("Text font size")
    self.font_spin.setStyleSheet(spin_style)
    layout.addWidget(self.font_spin)

    # Separator
    sep3 = QLabel("|")
    sep3.setStyleSheet("QLabel { color: #555; }")
    layout.addWidget(sep3)

    # Undo / Redo
    undo_style = (
      "QPushButton { color: #ccc; background: transparent; border: 1px solid #555; border-radius: 4px; font-size: 11px; }"
      "QPushButton:hover { background: rgba(255, 255, 255, 20); }"
      "QPushButton:disabled { color: #555; border-color: #444; }"
    )
    self._undo_btn = QPushButton("Undo")
    self._undo_btn.setFixedSize(44, 28)
    self._undo_btn.setToolTip("Undo (Ctrl+Z)")
    self._undo_btn.setStyleSheet(undo_style)
    self._undo_btn.setEnabled(False)
    self._undo_btn.clicked.connect(self.undo_requested.emit)
    layout.addWidget(self._undo_btn)

    self._redo_btn = QPushButton("Redo")
    self._redo_btn.setFixedSize(44, 28)
    self._redo_btn.setToolTip("Redo (Ctrl+Shift+Z)")
    self._redo_btn.setStyleSheet(undo_style)
    self._redo_btn.setEnabled(False)
    self._redo_btn.clicked.connect(self.redo_requested.emit)
    layout.addWidget(self._redo_btn)

    # Separator
    sep4 = QLabel("|")
    sep4.setStyleSheet("QLabel { color: #555; }")
    layout.addWidget(sep4)

    # Save / Cancel buttons
    action_style = (
      "QPushButton { color: #fff; border: 1px solid #555; border-radius: 4px; font-size: 11px; padding: 2px 8px; }"
      "QPushButton:hover { border-color: #aaa; }"
    )
    self._save_btn = QPushButton("Save")
    self._save_btn.setFixedHeight(28)
    self._save_btn.setToolTip("Save annotated image (Enter)")
    self._save_btn.setStyleSheet(
      action_style.replace("color: #fff", "color: #8f8")
    )
    self._save_btn.clicked.connect(self.save_requested.emit)
    layout.addWidget(self._save_btn)

    self._cancel_btn = QPushButton("Cancel")
    self._cancel_btn.setFixedHeight(28)
    self._cancel_btn.setToolTip("Discard and cancel (Esc)")
    self._cancel_btn.setStyleSheet(
      action_style.replace("color: #fff", "color: #f88")
    )
    self._cancel_btn.clicked.connect(self.cancel_requested.emit)
    layout.addWidget(self._cancel_btn)

    self._tool_group.buttonClicked.connect(self._on_tool_clicked)

    # Set tooltips dynamically based on modifier-to-tool mapping
    self._update_tool_tooltips(modifier_tools or _DEFAULT_MODIFIER_TOOLS)

  def _on_tool_clicked(self, btn: QPushButton) -> None:
    tool = self._button_to_tool(btn)
    self.tool_changed.emit(tool)

  def _update_tool_tooltips(self, modifier_tools: dict[str, str]) -> None:
    """Set tool button tooltips based on the current modifier-to-tool mapping."""
    # Build reverse map: tool -> modifier display name
    tool_to_shortcut: dict[str, str] = {}
    for mod_key, tool in modifier_tools.items():
      if tool != "none":
        tool_to_shortcut[tool] = _MODIFIER_LABELS.get(mod_key, mod_key)

    btn_map = {
      "freehand": self._freehand_btn,
      "arrow": self._arrow_btn,
      "oval": self._oval_btn,
      "rect": self._rect_btn,
      "text": self._text_btn,
    }
    base_names = {
      "freehand": "Freehand",
      "arrow": "Arrow",
      "oval": "Oval",
      "rect": "Rectangle",
      "text": "Text",
    }
    for tool_key, btn in btn_map.items():
      shortcut = tool_to_shortcut.get(tool_key)
      name = base_names[tool_key]
      if shortcut:
        if tool_key == "text":
          btn.setToolTip("%s (%s + click)" % (name, shortcut))
        else:
          btn.setToolTip("%s (%s + drag)" % (name, shortcut))
      elif tool_key == "freehand":
        btn.setToolTip("Freehand (default drag)")
      elif tool_key == "text":
        btn.setToolTip("Text (click to place)")
      else:
        btn.setToolTip(name)

  def _button_to_tool(self, btn: QPushButton) -> str:
    if btn is self._freehand_btn:
      return "freehand"
    elif btn is self._arrow_btn:
      return "arrow"
    elif btn is self._oval_btn:
      return "oval"
    elif btn is self._rect_btn:
      return "rect"
    elif btn is self._text_btn:
      return "text"
    return "freehand"

  def current_tool(self) -> str:
    checked = self._tool_group.checkedButton()
    if checked:
      return self._button_to_tool(checked)
    return "freehand"

  def current_color(self) -> QColor:
    return self.color_btn.color()

  def current_width(self) -> int:
    return self.width_spin.value()

  def current_font_size(self) -> int:
    return self.font_spin.value()

  def current_arrow_style(self) -> str:
    return self._arrow_style

  def set_undo_enabled(self, enabled: bool) -> None:
    self._undo_btn.setEnabled(enabled)

  def set_redo_enabled(self, enabled: bool) -> None:
    self._redo_btn.setEnabled(enabled)

  def set_active_tool_button(self, tool: str) -> None:
    """Visually check the button for the given tool."""
    mapping = {
      "freehand": self._freehand_btn,
      "arrow": self._arrow_btn,
      "oval": self._oval_btn,
      "rect": self._rect_btn,
      "text": self._text_btn,
    }
    btn = mapping.get(tool)
    if btn:
      btn.setChecked(True)

  def _set_arrow_style(self, style: str) -> None:
    self._arrow_style = style
    short = {"open": "Hollow", "standard": "Filled", "double": "Double"}
    self._arrow_style_btn.setText(short.get(style, style))

  # -- Dragging ---------------------------------------------------------------

  def mousePressEvent(self, event: QMouseEvent) -> None:
    if event.button() == Qt.MouseButton.LeftButton:
      self._drag_pos = event.globalPosition().toPoint() - self.pos()
      event.accept()
    else:
      super().mousePressEvent(event)

  def mouseMoveEvent(self, event: QMouseEvent) -> None:
    if self._drag_pos is not None:
      new_pos = event.globalPosition().toPoint() - self._drag_pos
      # Constrain to parent bounds
      if self.parentWidget():
        pw = self.parentWidget().width()
        ph = self.parentWidget().height()
        x = max(0, min(new_pos.x(), pw - self.width()))
        y = max(0, min(new_pos.y(), ph - self.height()))
        self.move(x, y)
      else:
        self.move(new_pos)
      event.accept()
    else:
      super().mouseMoveEvent(event)

  def mouseReleaseEvent(self, event: QMouseEvent) -> None:
    self._drag_pos = None
    super().mouseReleaseEvent(event)


# -- Text input widget --------------------------------------------------------

class AnnotationTextInput(QLineEdit):
  """Transient text input for placing text annotations."""
  confirmed = Signal(str, QPointF)
  cancelled = Signal()

  def __init__(self, image_pos: QPointF, color: QColor, font_size: int,
               parent: QWidget | None = None):
    super().__init__(parent)
    self._image_pos = image_pos
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    font.setPointSize(font_size)
    self.setFont(font)
    self.setStyleSheet(
      "QLineEdit { background: rgba(0,0,0,120); color: %s; border: 1px solid %s;"
      " border-radius: 3px; padding: 2px 4px; }"
      % (color.name(), color.name())
    )
    self.setMinimumWidth(100)
    self.setMaximumWidth(400)
    self.setFocus()

  def _on_confirm(self) -> None:
    text = self.text().strip()
    if text:
      self.confirmed.emit(text, self._image_pos)
    else:
      self.cancelled.emit()

  def keyPressEvent(self, event) -> None:
    if event.key() == Qt.Key.Key_Escape:
      self.cancelled.emit()
      event.accept()
      return
    if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
      # Handle Enter ourselves and accept the event so it does NOT
      # propagate to the parent editor (which would trigger save).
      self._on_confirm()
      event.accept()
      return
    super().keyPressEvent(event)


# -- Main editor --------------------------------------------------------------

class AnnotationEditor(QWidget):
  """Fullscreen annotation editor for captured screenshots."""

  def __init__(self, qimage: QImage, save_folder: str, fmt: str = "jpg",
               save_to_disk: bool = True, filename_prefix: str = "screenshot",
               filename_suffix: str = "%Y-%m-%d_%H-%M-%S",
               on_done: Callable[..., None] | None = None,
               modifier_tools: dict[str, str] | None = None,
               default_tool: str = "freehand"):
    super().__init__()
    self._qimage = qimage
    self._save_folder = save_folder
    self._fmt = fmt
    self._save_to_disk = save_to_disk
    self._filename_prefix = filename_prefix
    self._filename_suffix = filename_suffix
    self.on_done = on_done
    self._modifier_tools = modifier_tools or dict(_DEFAULT_MODIFIER_TOOLS)
    self._default_tool = default_tool

    self._saved = False
    self._drawing = False
    self._current_ann = None  # in-progress annotation
    self._drag_start = None  # original drag start in image-space (for oval/rect)
    self._text_input = None  # active text input widget
    self._dragging_text_idx = None  # index into _undo_stack of text being dragged
    self._text_drag_offset = QPointF(0, 0)  # offset from click to text position

    # Undo/redo stacks
    self._undo_stack: list[Annotation] = []
    self._redo_stack: list[Annotation] = []

    # Window setup
    self.setWindowFlags(
      Qt.WindowType.FramelessWindowHint
      | Qt.WindowType.WindowStaysOnTopHint
      | Qt.WindowType.Tool
    )
    self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # Fullscreen geometry
    screen = QApplication.primaryScreen().geometry()
    self.setGeometry(screen)

    # Compute image layout
    self._image_rect = QRect()
    self._scale = 1.0
    self._compute_layout()

    # Pre-render dimmed background
    self._bg_pixmap = QPixmap(self.width(), self.height())
    self._bg_pixmap.fill(QColor(0, 0, 0, 180))
    painter = QPainter(self._bg_pixmap)
    scaled_img = self._qimage.scaled(
      self._image_rect.width(), self._image_rect.height(),
      Qt.AspectRatioMode.KeepAspectRatio,
      Qt.TransformationMode.SmoothTransformation,
    )
    painter.drawImage(self._image_rect.topLeft(), scaled_img)
    painter.end()

    # Toolbar
    self._toolbar = AnnotationToolbar(self, modifier_tools=self._modifier_tools)
    self._toolbar.set_active_tool_button(self._default_tool)
    self._toolbar.undo_requested.connect(self._undo)
    self._toolbar.redo_requested.connect(self._redo)
    self._toolbar.save_requested.connect(self._save_and_close)
    self._toolbar.cancel_requested.connect(self._cancel_and_close)
    self._toolbar.adjustSize()
    # Position toolbar at top-center
    tx = (self.width() - self._toolbar.width()) // 2
    self._toolbar.move(tx, 8)
    self._toolbar.show()
    self._toolbar.raise_()

  def _compute_layout(self) -> None:
    """Compute image position and scale for display."""
    sw, sh = self.width(), self.height()
    iw, ih = self._qimage.width(), self._qimage.height()
    if iw <= 0 or ih <= 0:
      self._image_rect = QRect(0, 0, sw, sh)
      self._scale = 1.0
      return
    scale = min(sw / iw, sh / ih, 1.0)
    dw = int(iw * scale)
    dh = int(ih * scale)
    x = (sw - dw) // 2
    y = (sh - dh) // 2
    self._image_rect = QRect(x, y, dw, dh)
    self._scale = scale

  def _to_image_coords(self, screen_pos: QPoint) -> QPointF | None:
    """Convert screen position to image-space coordinates."""
    if self._scale <= 0:
      return None
    x = (screen_pos.x() - self._image_rect.x()) / self._scale
    y = (screen_pos.y() - self._image_rect.y()) / self._scale
    if x < 0 or y < 0 or x >= self._qimage.width() or y >= self._qimage.height():
      return None
    return QPointF(x, y)

  def _clamp_to_image(self, screen_pos: QPoint) -> QPointF:
    """Convert screen position to image-space, clamping to image bounds."""
    if self._scale <= 0:
      return QPointF(0, 0)
    x = (screen_pos.x() - self._image_rect.x()) / self._scale
    y = (screen_pos.y() - self._image_rect.y()) / self._scale
    x = max(0.0, min(x, self._qimage.width() - 1.0))
    y = max(0.0, min(y, self._qimage.height() - 1.0))
    return QPointF(x, y)

  # -- Text hit-testing -------------------------------------------------------

  def _text_bounding_rect(self, ann: TextAnnotation) -> QRectF:
    """Compute bounding rect of a text annotation in image-space."""
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    font.setPointSize(ann.font_size)
    fm = QFontMetricsF(font)
    br = fm.boundingRect(ann.text)
    # drawText(position, text) draws baseline at position.y()
    return QRectF(
      ann.position.x() + br.x(),
      ann.position.y() + br.y(),
      br.width(),
      br.height(),
    )

  def _hit_test_text(self, image_pos: QPointF) -> int | None:
    """Return index of topmost text annotation at image_pos, or None."""
    # Search in reverse (topmost annotation first)
    for i in range(len(self._undo_stack) - 1, -1, -1):
      ann = self._undo_stack[i]
      if isinstance(ann, TextAnnotation):
        rect = self._text_bounding_rect(ann)
        # Add a small margin for easier clicking
        rect.adjust(-4, -4, 4, 4)
        if rect.contains(image_pos):
          return i
    return None

  # -- Determine tool from modifiers ------------------------------------------

  def _tool_from_modifiers(self, mods) -> str:
    """Determine drawing tool based on held modifier keys and config."""
    if mods & Qt.KeyboardModifier.ShiftModifier:
      tool = self._modifier_tools.get("shift", "arrow")
    elif mods & Qt.KeyboardModifier.ControlModifier:
      tool = self._modifier_tools.get("ctrl", "oval")
    elif mods & Qt.KeyboardModifier.AltModifier:
      tool = self._modifier_tools.get("alt", "text")
    else:
      return self._toolbar.current_tool()
    if tool == "none":
      return self._toolbar.current_tool()
    return tool

  # -- Paint ------------------------------------------------------------------

  def paintEvent(self, event: QPaintEvent) -> None:
    painter = QPainter(self)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Draw background with image
    painter.drawPixmap(0, 0, self._bg_pixmap)

    # Set up transform for annotations (image-space)
    painter.save()
    painter.translate(self._image_rect.x(), self._image_rect.y())
    painter.scale(self._scale, self._scale)

    # Draw completed annotations
    for ann in self._undo_stack:
      self._paint_annotation(painter, ann)

    # Draw in-progress annotation
    if self._drawing and self._current_ann is not None:
      self._paint_annotation(painter, self._current_ann)

    painter.restore()
    painter.end()

  def _paint_annotation(self, painter: QPainter, ann: Annotation) -> None:
    if isinstance(ann, FreehandAnnotation):
      self._paint_freehand(painter, ann)
    elif isinstance(ann, ArrowAnnotation):
      self._paint_arrow(painter, ann)
    elif isinstance(ann, OvalAnnotation):
      self._paint_oval(painter, ann)
    elif isinstance(ann, RectAnnotation):
      self._paint_rect(painter, ann)
    elif isinstance(ann, TextAnnotation):
      self._paint_text(painter, ann)

  def _paint_freehand(self, painter: QPainter, ann: FreehandAnnotation) -> None:
    if len(ann.points) < 2:
      return
    pen = QPen(ann.color, ann.width, Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(ann.points[0])
    for pt in ann.points[1:]:
      path.lineTo(pt)
    painter.drawPath(path)

  def _arrow_dimensions(self, ann: ArrowAnnotation, length: float):
    """Compute shaft_width and head_size for an arrow annotation."""
    shaft_width = ann.width
    head_size = ann.width * 4.0
    # Cap head size to 45% of arrow length so short arrows don't get absurd heads
    head_size = min(head_size, length * 0.45)
    # Ensure a minimum visible head
    head_size = max(head_size, 6.0)
    return shaft_width, head_size

  def _paint_arrow(self, painter: QPainter, ann: ArrowAnnotation) -> None:
    dx = ann.end.x() - ann.start.x()
    dy = ann.end.y() - ann.start.y()
    length = math.hypot(dx, dy)
    if length < 1:
      return

    angle = math.atan2(dy, dx)
    shaft_width, head_size = self._arrow_dimensions(ann, length)

    if ann.style == "open":
      # Hollow arrow: entire shape drawn as an outlined polygon
      self._paint_arrow_hollow(painter, ann, angle, shaft_width, head_size)
    else:
      # Filled arrow: solid shaft + filled triangle head
      self._paint_arrow_filled(painter, ann, angle, shaft_width, head_size)

  def _paint_arrow_filled(self, painter: QPainter, ann: ArrowAnnotation,
                          angle: float, shaft_width: float, head_size: float) -> None:
    """Draw a filled arrow (standard, double styles)."""
    pen = QPen(ann.color, shaft_width, Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.MiterJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    # Shaft start/end -- pull back from tips so shaft doesn't overlap arrowheads
    shaft_start = ann.start
    shaft_end_x = ann.end.x() - math.cos(angle) * head_size * 0.7
    shaft_end_y = ann.end.y() - math.sin(angle) * head_size * 0.7
    if ann.style == "double":
      # Pull shaft start forward past the back arrowhead
      shaft_start = QPointF(
        ann.start.x() + math.cos(angle) * head_size * 0.7,
        ann.start.y() + math.sin(angle) * head_size * 0.7,
      )
    painter.drawLine(shaft_start, QPointF(shaft_end_x, shaft_end_y))

    # Draw arrowhead(s)
    spread = math.radians(25)
    if ann.style == "double":
      self._draw_filled_head(painter, ann.start, angle + math.pi, head_size, spread, ann.color)
    self._draw_filled_head(painter, ann.end, angle, head_size, spread, ann.color)

  def _draw_filled_head(self, painter: QPainter, tip: QPointF, angle: float,
                        size: float, spread: float, color: QColor) -> None:
    """Draw a filled triangular arrowhead."""
    p1 = QPointF(
      tip.x() - size * math.cos(angle - spread),
      tip.y() - size * math.sin(angle - spread),
    )
    p2 = QPointF(
      tip.x() - size * math.cos(angle + spread),
      tip.y() - size * math.sin(angle + spread),
    )
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(color))
    painter.drawPolygon(QPolygonF([tip, p1, p2]))

  def _paint_arrow_hollow(self, painter: QPainter, ann: ArrowAnnotation,
                          angle: float, shaft_width: float, head_size: float) -> None:
    """Draw a fully hollow (outlined) arrow shape."""
    spread = math.radians(30)
    # Perpendicular direction for shaft edges
    perp_x = -math.sin(angle)
    perp_y = math.cos(angle)
    half_shaft = shaft_width * 0.5
    # Head wing width (wider than shaft)
    head_wing = head_size * math.sin(spread)

    # Shaft corners at start
    s_top = QPointF(ann.start.x() + perp_x * half_shaft,
                    ann.start.y() + perp_y * half_shaft)
    s_bot = QPointF(ann.start.x() - perp_x * half_shaft,
                    ann.start.y() - perp_y * half_shaft)

    # Where the head begins (shaft meets head base)
    hx = ann.end.x() - math.cos(angle) * head_size
    hy = ann.end.y() - math.sin(angle) * head_size
    h_top = QPointF(hx + perp_x * half_shaft, hy + perp_y * half_shaft)
    h_bot = QPointF(hx - perp_x * half_shaft, hy - perp_y * half_shaft)

    # Head wing tips (wider than shaft)
    wing_top = QPointF(hx + perp_x * head_wing, hy + perp_y * head_wing)
    wing_bot = QPointF(hx - perp_x * head_wing, hy - perp_y * head_wing)

    # Build polygon: start_top -> head_junction_top -> wing_top -> tip -> wing_bot -> head_junction_bot -> start_bot
    outline = QPolygonF([
      s_top, h_top, wing_top, ann.end, wing_bot, h_bot, s_bot,
    ])

    outline_pen = QPen(ann.color, max(1.5, ann.width * 0.4), Qt.PenStyle.SolidLine,
                       Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.MiterJoin)
    painter.setPen(outline_pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPolygon(outline)

  def _paint_oval(self, painter: QPainter, ann: OvalAnnotation) -> None:
    pen = QPen(ann.color, ann.width, Qt.PenStyle.SolidLine)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(ann.rect)

  def _paint_rect(self, painter: QPainter, ann: RectAnnotation) -> None:
    pen = QPen(ann.color, ann.width, Qt.PenStyle.SolidLine)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(ann.rect)

  def _paint_text(self, painter: QPainter, ann: TextAnnotation) -> None:
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    font.setPointSize(ann.font_size)
    painter.setFont(font)
    painter.setPen(ann.color)
    painter.drawText(ann.position, ann.text)

  # -- Mouse events -----------------------------------------------------------

  def mousePressEvent(self, event: QMouseEvent) -> None:
    if event.button() == Qt.MouseButton.RightButton:
      self._cancel_and_close()
      return

    if event.button() != Qt.MouseButton.LeftButton:
      return

    # Check if click is on toolbar area -- let toolbar handle it
    toolbar_geom = self._toolbar.geometry()
    if toolbar_geom.contains(event.position().toPoint()):
      return

    pos = self._to_image_coords(event.position().toPoint())
    if pos is None:
      return

    tool = self._tool_from_modifiers(event.modifiers())

    # Text mode: drag existing text or place new text input
    if tool == "text":
      # Check if clicking on existing text to drag it
      hit_idx = self._hit_test_text(pos)
      if hit_idx is not None:
        ann = self._undo_stack[hit_idx]
        self._dragging_text_idx = hit_idx
        self._text_drag_offset = QPointF(
          ann.position.x() - pos.x(),
          ann.position.y() - pos.y(),
        )
        self._drawing = True
        return
      self._place_text_input(event.position().toPoint(), pos)
      return

    color = self._toolbar.current_color()
    width = self._toolbar.current_width()

    self._drag_start = pos

    if tool == "freehand":
      self._current_ann = FreehandAnnotation(
        points=[pos], color=QColor(color), width=width,
      )
    elif tool == "arrow":
      self._current_ann = ArrowAnnotation(
        start=pos, end=pos, color=QColor(color), width=width,
        style=self._toolbar.current_arrow_style(),
      )
    elif tool == "oval":
      self._current_ann = OvalAnnotation(
        rect=QRectF(pos, pos), color=QColor(color), width=width,
      )
    elif tool == "rect":
      self._current_ann = RectAnnotation(
        rect=QRectF(pos, pos), color=QColor(color), width=width,
      )

    self._drawing = True
    self.update()

  def mouseMoveEvent(self, event: QMouseEvent) -> None:
    # Text dragging
    if self._dragging_text_idx is not None:
      pos = self._clamp_to_image(event.position().toPoint())
      ann = self._undo_stack[self._dragging_text_idx]
      ann.position = QPointF(
        pos.x() + self._text_drag_offset.x(),
        pos.y() + self._text_drag_offset.y(),
      )
      self.update()
      return

    if not self._drawing or self._current_ann is None:
      return

    pos = self._clamp_to_image(event.position().toPoint())

    if isinstance(self._current_ann, FreehandAnnotation):
      self._current_ann.points.append(pos)
    elif isinstance(self._current_ann, ArrowAnnotation):
      self._current_ann.end = pos
    elif isinstance(self._current_ann, (OvalAnnotation, RectAnnotation)):
      self._current_ann.rect = QRectF(self._drag_start, pos).normalized()

    self.update()

  def mouseReleaseEvent(self, event: QMouseEvent) -> None:
    if event.button() != Qt.MouseButton.LeftButton:
      return

    # Finish text drag
    if self._dragging_text_idx is not None:
      self._dragging_text_idx = None
      self._drawing = False
      self.update()
      return

    if not self._drawing:
      return

    self._drawing = False
    if self._current_ann is None:
      return

    # Check minimum size
    discard = False
    if isinstance(self._current_ann, FreehandAnnotation):
      if len(self._current_ann.points) < 2:
        discard = True
    elif isinstance(self._current_ann, ArrowAnnotation):
      dx = self._current_ann.end.x() - self._current_ann.start.x()
      dy = self._current_ann.end.y() - self._current_ann.start.y()
      if math.hypot(dx, dy) < MIN_DRAG_SIZE:
        discard = True
    elif isinstance(self._current_ann, (OvalAnnotation, RectAnnotation)):
      r = self._current_ann.rect
      if r.width() < MIN_DRAG_SIZE and r.height() < MIN_DRAG_SIZE:
        discard = True

    if not discard:
      self._undo_stack.append(self._current_ann)
      self._redo_stack.clear()
      self._update_undo_redo_buttons()

    self._current_ann = None
    self.update()

  # -- Text tool --------------------------------------------------------------

  def _place_text_input(self, screen_pos: QPoint, image_pos: QPointF) -> None:
    """Show a text input at the given screen position."""
    if self._text_input is not None:
      self._cancel_text_input()

    color = self._toolbar.current_color()
    font_size = self._toolbar.current_font_size()
    self._text_input = AnnotationTextInput(image_pos, color, font_size, self)
    self._text_input.confirmed.connect(self._confirm_text_input)
    self._text_input.cancelled.connect(self._cancel_text_input)
    self._text_input.move(screen_pos)
    self._text_input.show()
    self._text_input.setFocus()

  def _confirm_text_input(self, text: str, image_pos: QPointF) -> None:
    """Create a text annotation from confirmed input."""
    color = self._toolbar.current_color()
    font_size = self._toolbar.current_font_size()
    ann = TextAnnotation(
      position=image_pos, text=text, color=QColor(color), font_size=font_size,
    )
    self._undo_stack.append(ann)
    self._redo_stack.clear()
    self._update_undo_redo_buttons()
    self._remove_text_input()
    self.update()

  def _cancel_text_input(self) -> None:
    self._remove_text_input()

  def _remove_text_input(self) -> None:
    if self._text_input is not None:
      self._text_input.hide()
      self._text_input.deleteLater()
      self._text_input = None

  # -- Undo / Redo ------------------------------------------------------------

  def _undo(self) -> None:
    if self._drawing or not self._undo_stack:
      return
    ann = self._undo_stack.pop()
    self._redo_stack.append(ann)
    self._update_undo_redo_buttons()
    self.update()

  def _redo(self) -> None:
    if self._drawing or not self._redo_stack:
      return
    ann = self._redo_stack.pop()
    self._undo_stack.append(ann)
    self._update_undo_redo_buttons()
    self.update()

  def _update_undo_redo_buttons(self) -> None:
    self._toolbar.set_undo_enabled(len(self._undo_stack) > 0)
    self._toolbar.set_redo_enabled(len(self._redo_stack) > 0)

  # -- Keyboard ---------------------------------------------------------------

  def keyPressEvent(self, event: QKeyEvent) -> None:
    # If text input is active, intercept Enter and Escape here
    if self._text_input is not None and self._text_input.isVisible():
      if event.key() == Qt.Key.Key_Escape:
        self._cancel_text_input()
        return
      if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
        # Confirm text -- do NOT fall through to save
        self._text_input._on_confirm()
        return
      super().keyPressEvent(event)
      return

    key = event.key()
    # Mask out non-essential modifiers (NumLock, etc.)
    mods = event.modifiers() & (
      Qt.KeyboardModifier.ControlModifier
      | Qt.KeyboardModifier.ShiftModifier
      | Qt.KeyboardModifier.AltModifier
    )

    if key == Qt.Key.Key_Escape:
      self._cancel_and_close()
    elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
      self._save_and_close()
    elif key == Qt.Key.Key_Z and mods == Qt.KeyboardModifier.ControlModifier:
      if not self._drawing:
        self._undo()
    elif (key == Qt.Key.Key_Z
          and mods == (Qt.KeyboardModifier.ControlModifier
                       | Qt.KeyboardModifier.ShiftModifier)):
      if not self._drawing:
        self._redo()

  # -- Save / Cancel ----------------------------------------------------------

  def _composite(self) -> QImage:
    """Draw all annotations onto a copy of the captured image."""
    result = self._qimage.copy()
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    for ann in self._undo_stack:
      self._paint_annotation(painter, ann)
    painter.end()
    return result

  def _save_and_close(self) -> None:
    """Composite annotations onto image, clipboard + save, close."""
    composited = self._composite()

    clipboard_ok = copy_image_to_clipboard(composited)
    filepath = save_qimage(
      composited, self._save_folder, self._fmt, self._filename_prefix,
      self._filename_suffix,
    ) if self._save_to_disk else None

    if not clipboard_ok and not filepath:
      if self._save_to_disk:
        error = "Capture failed: could not copy to clipboard or save to disk"
      else:
        error = "Capture failed: could not copy to clipboard"
    elif not clipboard_ok:
      error = "Copied to disk but clipboard copy failed"
    else:
      error = None

    self._saved = True
    self.close()
    if self.on_done:
      self.on_done(filepath, error=error)

  def _cancel_and_close(self) -> None:
    """Discard annotations and close."""
    self._saved = True  # prevent closeEvent from double-firing
    self.close()
    if self.on_done:
      self.on_done(None, error="cancelled")

  def showEvent(self, event) -> None:
    """Grab keyboard focus when the editor becomes visible."""
    super().showEvent(event)
    self.raise_()
    self.activateWindow()
    self.setFocus()

  def closeEvent(self, event: QCloseEvent) -> None:
    if not self._saved:
      # Window closed by manager (Alt+F4 etc.) -- treat as cancel
      self._saved = True
      if self.on_done:
        self.on_done(None, error="cancelled")
    super().closeEvent(event)
