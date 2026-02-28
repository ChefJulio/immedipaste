"""Tests for the annotation editor module."""

import math
from unittest.mock import patch, MagicMock

import pytest
from PySide6.QtCore import QPointF, QRectF, QPoint, QRect, Qt
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from annotation_editor import (
  FreehandAnnotation, ArrowAnnotation, OvalAnnotation, RectAnnotation,
  TextAnnotation, AnnotationEditor, ARROW_STYLES, DEFAULT_COLOR,
  DEFAULT_STROKE_WIDTH, DEFAULT_FONT_SIZE,
)


def make_test_image(w=200, h=150):
  """Create a small solid-color QImage for testing."""
  img = QImage(w, h, QImage.Format.Format_ARGB32)
  img.fill(QColor(255, 255, 255))
  return img


# -- Data model ---------------------------------------------------------------

class TestDataModel:
  def test_freehand_annotation(self):
    ann = FreehandAnnotation(
      points=[QPointF(0, 0), QPointF(10, 10)],
      color=QColor(255, 0, 0),
      width=3.0,
    )
    assert len(ann.points) == 2
    assert ann.color == QColor(255, 0, 0)
    assert ann.width == 3.0

  def test_arrow_annotation(self):
    ann = ArrowAnnotation(
      start=QPointF(0, 0), end=QPointF(100, 50),
      color=QColor(255, 0, 0), width=3.0,
      style="standard", drag_mode="line", rect=None,
    )
    assert ann.style == "standard"
    assert ann.drag_mode == "line"
    assert ann.rect is None

  def test_arrow_box_mode(self):
    r = QRectF(10, 10, 80, 40)
    ann = ArrowAnnotation(
      start=QPointF(10, 30), end=QPointF(90, 30),
      color=QColor(255, 0, 0), width=3.0,
      style="standard", drag_mode="box", rect=r,
    )
    assert ann.drag_mode == "box"
    assert ann.rect == r

  def test_oval_annotation(self):
    ann = OvalAnnotation(
      rect=QRectF(10, 10, 80, 60),
      color=QColor(0, 255, 0), width=2.0,
    )
    assert ann.rect.width() == 80

  def test_rect_annotation(self):
    ann = RectAnnotation(
      rect=QRectF(5, 5, 50, 30),
      color=QColor(0, 0, 255), width=4.0,
    )
    assert ann.rect.height() == 30

  def test_text_annotation(self):
    ann = TextAnnotation(
      position=QPointF(50, 50),
      text="Hello",
      color=QColor(255, 0, 0),
      font_size=16,
    )
    assert ann.text == "Hello"
    assert ann.font_size == 16

  def test_arrow_styles_defined(self):
    assert len(ARROW_STYLES) == 4
    assert "standard" in ARROW_STYLES
    assert "open" in ARROW_STYLES
    assert "double" in ARROW_STYLES
    assert "thick" in ARROW_STYLES


# -- Compositing --------------------------------------------------------------

class TestCompositing:
  def _make_editor(self, tmp_path):
    img = make_test_image()
    editor = AnnotationEditor(
      qimage=img,
      save_folder=str(tmp_path),
      fmt="png",
      save_to_disk=True,
      on_done=MagicMock(),
    )
    return editor

  def test_composite_without_annotations_matches_original(self, tmp_path):
    editor = self._make_editor(tmp_path)
    composited = editor._composite()
    # Without annotations, the composited image should match the original
    assert composited.size() == editor._qimage.size()
    # Spot-check a pixel
    assert composited.pixelColor(50, 50) == editor._qimage.pixelColor(50, 50)
    editor.close()

  def test_composite_with_rect_differs_from_original(self, tmp_path):
    editor = self._make_editor(tmp_path)
    # Add a red rectangle annotation
    ann = RectAnnotation(
      rect=QRectF(10, 10, 80, 60),
      color=QColor(255, 0, 0), width=3.0,
    )
    editor._undo_stack.append(ann)
    composited = editor._composite()
    # The pixel at the edge of the rectangle should differ from pure white
    # (the rect border is drawn at 10,10 with width 3)
    border_pixel = composited.pixelColor(10, 10)
    original_pixel = editor._qimage.pixelColor(10, 10)
    assert border_pixel != original_pixel
    editor.close()

  def test_composite_with_freehand_differs(self, tmp_path):
    editor = self._make_editor(tmp_path)
    ann = FreehandAnnotation(
      points=[QPointF(0, 0), QPointF(100, 100)],
      color=QColor(0, 0, 255), width=5.0,
    )
    editor._undo_stack.append(ann)
    composited = editor._composite()
    # A pixel along the diagonal should be blue-ish
    px = composited.pixelColor(50, 50)
    assert px != QColor(255, 255, 255)
    editor.close()


# -- Undo / Redo --------------------------------------------------------------

class TestUndoRedo:
  def _make_editor(self, tmp_path):
    img = make_test_image()
    editor = AnnotationEditor(
      qimage=img,
      save_folder=str(tmp_path),
      on_done=MagicMock(),
    )
    return editor

  def test_undo_pops_from_stack(self, tmp_path):
    editor = self._make_editor(tmp_path)
    ann = RectAnnotation(QRectF(0, 0, 10, 10), QColor(255, 0, 0), 2.0)
    editor._undo_stack.append(ann)
    editor._update_undo_redo_buttons()

    editor._undo()
    assert len(editor._undo_stack) == 0
    assert len(editor._redo_stack) == 1
    assert editor._redo_stack[0] is ann
    editor.close()

  def test_redo_pushes_back(self, tmp_path):
    editor = self._make_editor(tmp_path)
    ann = RectAnnotation(QRectF(0, 0, 10, 10), QColor(255, 0, 0), 2.0)
    editor._undo_stack.append(ann)
    editor._undo()
    editor._redo()

    assert len(editor._undo_stack) == 1
    assert len(editor._redo_stack) == 0
    assert editor._undo_stack[0] is ann
    editor.close()

  def test_new_annotation_clears_redo(self, tmp_path):
    editor = self._make_editor(tmp_path)
    ann1 = RectAnnotation(QRectF(0, 0, 10, 10), QColor(255, 0, 0), 2.0)
    ann2 = OvalAnnotation(QRectF(20, 20, 30, 30), QColor(0, 255, 0), 2.0)
    editor._undo_stack.append(ann1)
    editor._undo()
    # Redo stack should have ann1
    assert len(editor._redo_stack) == 1

    # Adding a new annotation should clear redo stack
    editor._undo_stack.append(ann2)
    editor._redo_stack.clear()
    assert len(editor._redo_stack) == 0
    editor.close()

  def test_undo_does_nothing_when_empty(self, tmp_path):
    editor = self._make_editor(tmp_path)
    editor._undo()  # Should not crash
    assert len(editor._undo_stack) == 0
    assert len(editor._redo_stack) == 0
    editor.close()

  def test_redo_does_nothing_when_empty(self, tmp_path):
    editor = self._make_editor(tmp_path)
    editor._redo()  # Should not crash
    assert len(editor._undo_stack) == 0
    assert len(editor._redo_stack) == 0
    editor.close()

  def test_undo_blocked_during_drawing(self, tmp_path):
    editor = self._make_editor(tmp_path)
    ann = RectAnnotation(QRectF(0, 0, 10, 10), QColor(255, 0, 0), 2.0)
    editor._undo_stack.append(ann)
    editor._drawing = True  # Simulate active drag
    editor._undo()
    # Should not have undone because drawing is in progress
    assert len(editor._undo_stack) == 1
    editor._drawing = False
    editor.close()


# -- Coordinate conversion ---------------------------------------------------

class TestCoordinateConversion:
  def _make_editor(self, tmp_path, img_w=200, img_h=150):
    img = make_test_image(img_w, img_h)
    editor = AnnotationEditor(
      qimage=img,
      save_folder=str(tmp_path),
      on_done=MagicMock(),
    )
    return editor

  def test_image_coords_within_bounds(self, tmp_path):
    editor = self._make_editor(tmp_path)
    # The image is centered on screen; compute expected position
    ir = editor._image_rect
    # Click in the center of the image
    center = QPoint(ir.x() + ir.width() // 2, ir.y() + ir.height() // 2)
    result = editor._to_image_coords(center)
    assert result is not None
    # Should be approximately center of image in image-space
    assert 50 < result.x() < 150
    assert 30 < result.y() < 120
    editor.close()

  def test_image_coords_outside_returns_none(self, tmp_path):
    editor = self._make_editor(tmp_path)
    # Click way outside the image area
    result = editor._to_image_coords(QPoint(-100, -100))
    assert result is None
    editor.close()

  def test_clamp_stays_in_bounds(self, tmp_path):
    editor = self._make_editor(tmp_path)
    # Clamp a point far outside bounds
    result = editor._clamp_to_image(QPoint(-9999, -9999))
    assert result.x() == 0.0
    assert result.y() == 0.0

    result2 = editor._clamp_to_image(QPoint(99999, 99999))
    assert result2.x() == editor._qimage.width() - 1.0
    assert result2.y() == editor._qimage.height() - 1.0
    editor.close()

  def test_scale_computed_for_small_image(self, tmp_path):
    # An image smaller than the screen should have scale <= 1.0
    editor = self._make_editor(tmp_path, 100, 100)
    assert editor._scale <= 1.0
    editor.close()


# -- Save and cancel ----------------------------------------------------------

class TestSaveCancel:
  def test_save_calls_done_with_filepath(self, tmp_path):
    done_mock = MagicMock()
    img = make_test_image()
    editor = AnnotationEditor(
      qimage=img, save_folder=str(tmp_path), fmt="png",
      save_to_disk=True, on_done=done_mock,
    )
    editor._save_and_close()
    done_mock.assert_called_once()
    filepath, = done_mock.call_args[0]
    assert filepath is not None
    assert filepath.endswith(".png")
    assert done_mock.call_args[1]["error"] is None

  def test_save_clipboard_only(self, tmp_path):
    done_mock = MagicMock()
    img = make_test_image()
    editor = AnnotationEditor(
      qimage=img, save_folder=str(tmp_path),
      save_to_disk=False, on_done=done_mock,
    )
    with patch("annotation_editor.copy_image_to_clipboard", return_value=True):
      editor._save_and_close()
    done_mock.assert_called_once()
    filepath, = done_mock.call_args[0]
    assert filepath is None
    assert done_mock.call_args[1]["error"] is None

  def test_cancel_calls_done_with_cancelled(self, tmp_path):
    done_mock = MagicMock()
    img = make_test_image()
    editor = AnnotationEditor(
      qimage=img, save_folder=str(tmp_path), on_done=done_mock,
    )
    editor._cancel_and_close()
    done_mock.assert_called_once_with(None, error="cancelled")


# -- Tool from modifiers ------------------------------------------------------

class TestToolFromModifiers:
  def _make_editor(self, tmp_path):
    img = make_test_image()
    editor = AnnotationEditor(
      qimage=img, save_folder=str(tmp_path), on_done=MagicMock(),
    )
    return editor

  def test_shift_gives_arrow(self, tmp_path):
    editor = self._make_editor(tmp_path)
    tool = editor._tool_from_modifiers(Qt.KeyboardModifier.ShiftModifier)
    assert tool == "arrow"
    editor.close()

  def test_ctrl_gives_oval(self, tmp_path):
    editor = self._make_editor(tmp_path)
    tool = editor._tool_from_modifiers(Qt.KeyboardModifier.ControlModifier)
    assert tool == "oval"
    editor.close()

  def test_alt_gives_rect(self, tmp_path):
    editor = self._make_editor(tmp_path)
    tool = editor._tool_from_modifiers(Qt.KeyboardModifier.AltModifier)
    assert tool == "rect"
    editor.close()

  def test_no_modifier_gives_toolbar_default(self, tmp_path):
    editor = self._make_editor(tmp_path)
    tool = editor._tool_from_modifiers(Qt.KeyboardModifier(0))
    assert tool == "freehand"  # default toolbar selection
    editor.close()

  def test_shift_takes_priority_over_ctrl(self, tmp_path):
    editor = self._make_editor(tmp_path)
    mods = Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier
    tool = editor._tool_from_modifiers(mods)
    assert tool == "arrow"
    editor.close()
