import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock
from PySide6.QtCore import QPointF, QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PIL import Image, ImageChops
from imaging import edit
from app import ShotApp, Editor, Overlay, to_pil, to_pixmap
from storage import save_png


class LocalShotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ShotApp()
        cls.app.panel.hide()

    @classmethod
    def tearDownClass(cls):
        cls.app.tray.hide()
        cls.app.hotkeys.cleanup()

    def test_redaction_is_flattened_and_preserves_outside(self):
        source = Image.effect_noise((100, 80), 70).convert('RGB')
        result = edit(source, 'hide', (70, 60), (20, 10), '#ffffff')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'redacted.png'
            result.save(path)
            reopened = Image.open(path).convert('RGB')
            self.assertEqual(reopened.crop((20, 10, 70, 60)).getextrema(), ((255, 255),) * 3)
            self.assertIsNone(ImageChops.difference(source.crop((0, 0, 20, 80)), reopened.crop((0, 0, 20, 80))).getbbox())
        self.assertIsNotNone(ImageChops.difference(source, result).getbbox())

    def test_qt_roundtrip(self):
        original = Image.new('RGB', (123, 45), '#3b82f6')
        self.assertIsNone(ImageChops.difference(original, to_pil(to_pixmap(original))).getbbox())

    def test_editor_undo_and_render(self):
        source = Image.new('RGB', (640, 360), 'white')
        editor = Editor(source, self.app)
        editor.canvas.commit(edit(source, 'arrow', (30, 40), (400, 200)))
        self.assertIsNotNone(ImageChops.difference(source, editor.canvas.image).getbbox())
        editor.canvas.undo()
        self.assertIsNone(ImageChops.difference(source, editor.canvas.image).getbbox())
        editor.show()
        self.app.processEvents()
        self.assertFalse(editor.grab().isNull())
        editor.dirty = False
        editor.close()

    def test_save_distinct_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = self.app.folder
            self.app.folder = Path(tmp)
            try:
                image = Image.new('RGB', (20, 10), 'white')
                one = self.app.save_image(image)
                two = self.app.save_image(image)
                self.assertNotEqual(one, two)
                with Image.open(one) as saved:
                    self.assertEqual(saved.size, (20, 10))
            finally:
                self.app.folder = previous

    def make_editor(self, size=(100, 80)):
        editor = Editor(Image.new('RGB', size, 'white'), self.app)
        def cleanup():
            editor.dirty = False
            editor.close()
        self.addCleanup(cleanup)
        return editor

    def test_hide_includes_last_row_and_column(self):
        source = Image.new('RGB', (10, 8), 'black')
        for a, b in [((0, 0), (9, 7)), ((9, 7), (0, 0))]:
            self.assertEqual(edit(source, 'hide', a, b, 'white').getextrema(), ((255, 255),) * 3)
        result = edit(source, 'hide', (9, 7), (9, 7), 'white')
        self.assertEqual(result.getpixel((9, 7)), (255, 255, 255))
        self.assertEqual(result.getpixel((8, 7)), (0, 0, 0))

    def test_failed_save_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            def fail(image, stream, **kwargs):
                stream.write(b'partial')
                raise OSError('disk full')
            with patch.object(Image.Image, 'save', fail):
                with self.assertRaises(OSError):
                    save_png(Image.new('RGB', (10, 10)), Path(tmp))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_collision_keeps_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp, patch('storage.datetime') as clock:
            clock.now.return_value.strftime.return_value = 'same'
            one = save_png(Image.new('RGB', (10, 10), 'red'), Path(tmp))
            two = save_png(Image.new('RGB', (10, 10), 'blue'), Path(tmp))
            self.assertNotEqual(one, two)
            with Image.open(one) as image:
                self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))

    def test_failed_editor_save_keeps_dirty_image(self):
        editor = self.make_editor()
        with patch('app.save_png', side_effect=PermissionError('denied')), patch('app.QMessageBox.warning'), self.assertLogs(level='ERROR'):
            self.assertIsNone(editor.save())
        self.assertTrue(editor.dirty)
        self.assertEqual(editor.canvas.image.size, (100, 80))

    def test_redo_and_branch(self):
        editor = self.make_editor()
        canvas = editor.canvas
        canvas.commit(edit(canvas.image, 'hide', (0, 0), (20, 20), 'red'))
        canvas.undo()
        canvas.redo()
        self.assertEqual(canvas.image.getpixel((0, 0)), (255, 0, 0))
        canvas.undo()
        canvas.commit(edit(canvas.image, 'hide', (0, 0), (20, 20), 'blue'))
        self.assertFalse(canvas.future)

    def test_history_budget_shared_with_redo(self):
        canvas = self.make_editor().canvas
        canvas.HISTORY_BUDGET = 50000
        for i in range(5):
            canvas.commit(Image.new('RGB', (100, 80), (i, 0, 0)))
        self.assertLessEqual(canvas.history_bytes, canvas.HISTORY_BUDGET)
        self.assertEqual(len(canvas.history), 2)
        canvas.undo()
        self.assertLessEqual(canvas.history_bytes, canvas.HISTORY_BUDGET)
        self.assertEqual(len(canvas.history) + len(canvas.future), 2)

    def test_drag_preview_does_not_edit_pixels(self):
        canvas = self.make_editor((3840, 2160)).canvas
        canvas.start = (0, 0)
        event = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(100, 100), QPointF(100, 100),
                            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        original = canvas.image
        with patch('app.edit', side_effect=AssertionError('preview must not edit')):
            canvas.mouseMoveEvent(event)
        self.assertIs(canvas.image, original)
        self.assertEqual(canvas.preview, (100, 100))

    def test_cancel_stops_pending_capture(self):
        self.app.capture()
        self.assertTrue(self.app.capture_timer.isActive())
        self.app.cancel_capture()
        self.assertFalse(self.app.capture_timer.isActive())
        self.assertFalse(self.app.capturing)
        with patch.object(self.app, 'finish_capture') as finish:
            self.app.take_capture(True)
            finish.assert_not_called()

    def test_screen_change_cancels_capture(self):
        self.app.capture()
        self.app.screen_changed()
        self.assertFalse(self.app.capturing)
        self.assertEqual(self.app.hidden, [])

    def test_capture_failure_restores_window(self):
        self.app.panel.show()
        self.app.capture()
        self.app.target_screen = None
        with patch('app.QMessageBox.warning'), self.assertLogs(level='ERROR'):
            self.app.take_capture(True)
        self.assertTrue(self.app.panel.isVisible())
        self.assertFalse(self.app.capturing)
        self.app.panel.hide()

    def test_overlay_crop_at_different_scales(self):
        from PySide6.QtCore import QRect
        for scale in (1, 1.25, 1.5, 2):
            with self.subTest(scale=scale):
                screen = Mock()
                screen.geometry.return_value = QRect(-400, 0, 400, 300)
                owner = Mock()
                pixmap = to_pixmap(Image.new('RGB', (round(400 * scale), round(300 * scale)), 'red'))
                overlay = Overlay(screen, pixmap, owner)
                overlay.start = QPoint(0, 0)
                event = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(399, 299), QPointF(399, 299),
                                    Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
                overlay.mouseReleaseEvent(event)
                result = owner.finish_capture.call_args.args[0]
                self.assertEqual(result.size, (round(400 * scale), round(300 * scale)))
                self.assertEqual(result.getextrema(), ((255, 255), (0, 0), (0, 0)))
                overlay.close()


if __name__ == '__main__':
    unittest.main()
