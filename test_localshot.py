import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock
from PySide6.QtCore import QPointF, QPoint, Qt, QSettings, QTimer
from PySide6.QtGui import QMouseEvent, QColor
from PySide6.QtWidgets import QMessageBox, QDialog
from PySide6.QtTest import QTest
from PIL import Image, ImageChops
from imaging import edit
from app import ShotApp, Editor, Overlay, to_pil, to_pixmap
from storage import save_png, save_png_as
from hotkeys import Hotkeys, parse_shortcut, DEFAULTS
from dialogs import CaptureDialog, HotkeyDialog
import startup


class LocalShotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.app = ShotApp(settings=QSettings(str(Path(cls.temporary.name) / 'settings.ini'), QSettings.Format.IniFormat),
                          enable_hotkeys=False)
        cls.app.tray_timer.stop()
        cls.app.panel.hide()

    def setUp(self):
        self.app.settings.clear()

    @classmethod
    def tearDownClass(cls):
        cls.app.tray.hide()
        cls.app.hotkeys.cleanup()
        cls.temporary.cleanup()

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

    def test_blur_includes_edge_and_does_not_modify_source(self):
        from PIL import ImageFilter
        source = Image.effect_noise((40, 30), 70).convert('RGB')
        before = source.tobytes()
        result = edit(source, 'blur', (39, 29), (0, 0))
        self.assertEqual(result.tobytes(), source.filter(ImageFilter.GaussianBlur(14)).tobytes())
        self.assertEqual(source.tobytes(), before)

    def test_rectangle_line_and_text_render(self):
        source = Image.new('RGB', (200, 100), 'white')
        rectangle = edit(source, 'rect', (199, 99), (0, 0), 'black', width=2)
        self.assertEqual(rectangle.getpixel((199, 99)), (0, 0, 0))
        self.assertEqual(rectangle.getpixel((50, 50)), (255, 255, 255))
        line = edit(source, 'line', (0, 0), (199, 99), 'black', width=2)
        self.assertEqual(line.getpixel((199, 99)), (0, 0, 0))
        text = edit(source, 'text', (5, 5), (5, 5), 'black', text='Текст', font_size=20)
        self.assertIsNotNone(ImageChops.difference(source, text).getbbox())

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

    def test_save_as_preserves_existing_file_on_encode_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'existing.png'
            Image.new('RGB', (5, 5), 'red').save(path)
            previous = path.read_bytes()
            with patch.object(Image.Image, 'save', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    save_png_as(Image.new('RGB', (5, 5)), path, overwrite=True)
            self.assertEqual(path.read_bytes(), previous)
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ['existing.png'])

    def test_save_as_requires_overwrite_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'existing.png'
            original = Image.new('RGB', (5, 5), 'red')
            original.save(path)
            with self.assertRaises(FileExistsError):
                save_png_as(Image.new('RGB', (5, 5)), path)
            with Image.open(path) as image:
                self.assertEqual(image.tobytes(), original.tobytes())

    def test_save_as_rename_failure_preserves_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'original.png'
            path.write_bytes(b'original')
            with patch('storage.os.replace', side_effect=PermissionError('locked')):
                with self.assertRaises(PermissionError):
                    save_png_as(Image.new('RGB', (5, 5)), path, overwrite=True)
            self.assertEqual(path.read_bytes(), b'original')
            self.assertEqual(len(list(Path(tmp).iterdir())), 1)

    def test_save_as_normalizes_extension_and_cancellation(self):
        editor = self.make_editor()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'chosen.jpg'
            with patch('app.QFileDialog.getSaveFileName', return_value=(str(path), 'PNG')):
                saved = editor.save_as()
            self.assertEqual(saved, path.with_suffix('.png'))
            self.assertFalse(path.exists())
            original = saved.read_bytes()
            with patch('app.QFileDialog.getSaveFileName', return_value=(str(saved), 'PNG')), \
                    patch('app.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
                self.assertIsNone(editor.save_as())
            self.assertEqual(saved.read_bytes(), original)
        with patch('app.QFileDialog.getSaveFileName', return_value=('', '')):
            self.assertIsNone(editor.save_as())

    def test_ctrl_s_updates_named_file(self):
        editor = self.make_editor()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'named.png'
            with patch('app.QFileDialog.getSaveFileName', return_value=(str(path), 'PNG')):
                self.assertEqual(editor.save_as(), path)
            editor.canvas.commit(edit(editor.canvas.image, 'hide', (0, 0), (99, 79), 'black'))
            with patch.object(self.app, 'save_image', side_effect=AssertionError('must use named file')):
                self.assertEqual(editor.save(), path)
            self.assertEqual(len(list(Path(tmp).iterdir())), 1)
            with Image.open(path) as saved:
                self.assertEqual(saved.getextrema(), ((0, 0),) * 3)
            self.assertFalse(editor.dirty)
            self.assertIn('named.png', editor.windowTitle())

    def test_undo_to_saved_revision_and_branch(self):
        editor = self.make_editor()
        canvas = editor.canvas
        canvas.commit(edit(canvas.image, 'hide', (0, 0), (5, 5), 'black'))
        editor.mark_saved(Path('saved.png'))
        canvas.commit(edit(canvas.image, 'hide', (10, 10), (20, 20), 'red'))
        self.assertTrue(editor.dirty)
        canvas.undo()
        self.assertFalse(editor.dirty)
        canvas.redo()
        self.assertTrue(editor.dirty)
        canvas.undo()
        canvas.undo()
        self.assertTrue(editor.dirty)
        canvas.commit(edit(canvas.image, 'hide', (10, 10), (20, 20), 'blue'))
        self.assertTrue(editor.dirty)
        self.assertFalse(canvas.future)

    def test_clean_saved_revision_closes_without_prompt(self):
        editor = self.make_editor()
        editor.mark_saved(Path('saved.png'))
        editor.canvas.commit(edit(editor.canvas.image, 'line', (0, 0), (40, 40)))
        editor.canvas.undo()
        with patch('app.QMessageBox.question', side_effect=AssertionError('no unsaved changes')):
            self.assertTrue(editor.close())

    def test_named_save_failure_blocks_close(self):
        editor = self.make_editor()
        editor.save_target = Path('named.png')
        with patch('app.save_png_as', side_effect=PermissionError('locked')), \
                patch('app.QMessageBox.warning'), self.assertLogs(level='ERROR'), \
                patch('app.QMessageBox.question', return_value=QMessageBox.StandardButton.Save):
            self.assertFalse(editor.close())
        self.assertTrue(editor.dirty)

    def test_grayscale_alpha_opens_on_white(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'gray.png'
            Image.new('LA', (5, 5), (0, 0)).save(path)
            editor = self.app.load_image(path)
            self.assertEqual(editor.canvas.image.getpixel((0, 0)), (255, 255, 255))
            self.assertEqual(self.app.settings.value('files/open_directory'), str(path.parent))
            editor.close()

    def test_save_directory_remembered(self):
        editor = self.make_editor()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'named.png'
            self.assertEqual(editor.write_named_file(path, False), path)
            other = self.make_editor()
            with patch('app.QFileDialog.getSaveFileName', return_value=('', '')) as choose:
                other.save_as()
                self.assertEqual(Path(choose.call_args.args[2]).parent, path.parent)

    def test_folder_creation_denied(self):
        with patch.object(Path, 'mkdir', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                save_png(Image.new('RGB', (1, 1)), Path('unused'))

    def test_editor_preferences_persist(self):
        editor = self.make_editor()
        editor.width.setValue(12)
        editor.font_size.setValue(48)
        with patch('app.QColorDialog.getColor', return_value=QColor('#00ff00')):
            editor.pick_color()
        editor.resize(700, 500)
        editor.dirty = False
        editor.close()
        settings = QSettings(self.app.settings.fileName(), QSettings.Format.IniFormat)
        self.assertEqual(int(settings.value('editor/width')), 12)
        self.assertEqual(settings.value('editor/color'), '#00ff00')
        other = self.make_editor()
        self.assertEqual(other.width.value(), 12)
        self.assertEqual(other.font_size.value(), 48)
        self.assertEqual(other.color, '#00ff00')
        self.assertEqual(other.size().width(), 700)

    def test_preferences_readable_in_new_process(self):
        editor = self.make_editor()
        editor.width.setValue(17)
        editor.font_size.setValue(54)
        editor.dirty = False
        editor.close()
        code = ('import json,sys; from PySide6.QtCore import QSettings; '
                's=QSettings(sys.argv[1], QSettings.Format.IniFormat); '
                'print(json.dumps([int(s.value("editor/width")),int(s.value("editor/font_size"))]))')
        values = subprocess.check_output([sys.executable, '-c', code, self.app.settings.fileName()], text=True)
        self.assertEqual(json.loads(values), [17, 54])

    def test_bad_preferences_fall_back(self):
        self.app.settings.setValue('editor/width', 'broken')
        self.app.settings.setValue('editor/font_size', 9999)
        self.app.settings.setValue('editor/color', 'not a color')
        editor = self.make_editor()
        self.assertEqual(editor.width.value(), 5)
        self.assertEqual(editor.font_size.value(), 160)
        self.assertEqual(editor.color, '#ef4444')

    def test_open_image_keeps_original_and_handles_transparency(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.png'
            Image.new('RGBA', (10, 10), (255, 0, 0, 0)).save(path)
            previous = path.read_bytes()
            editor = self.app.load_image(path)
            self.assertIsNotNone(editor)
            self.assertFalse(editor.dirty)
            self.assertEqual(editor.canvas.image.getpixel((0, 0)), (255, 255, 255))
            editor.canvas.commit(edit(editor.canvas.image, 'hide', (0, 0), (9, 9), 'black'))
            self.assertTrue(editor.dirty)
            editor.dirty = False
            editor.close()
            self.assertEqual(path.read_bytes(), previous)

    def test_open_invalid_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.png'
            path.write_bytes(b'not an image')
            with patch('app.QMessageBox.warning'), self.assertLogs(level='ERROR'):
                self.assertIsNone(self.app.load_image(path))

    def test_capture_preview_and_save_error_fallback(self):
        source = Image.new('RGB', (1200, 800), 'blue')
        def select_save():
            dialog = self.app.activeModalWidget()
            self.assertIsInstance(dialog, CaptureDialog)
            self.assertLessEqual(dialog.preview.pixmap().width(), 640)
            dialog.buttons['save'].click()
        QTimer.singleShot(0, select_save)
        with patch.object(self.app, 'save_image', return_value=None), patch.object(self.app, 'open_editor') as opened:
            self.app.finish_capture(source)
            opened.assert_called_once_with(source)
        self.assertFalse(self.app.capturing)

    def test_capture_preview_cancel(self):
        QTimer.singleShot(0, lambda: self.app.activeModalWidget().reject())
        with patch.object(self.app, 'open_editor') as opened, patch.object(self.app, 'save_image') as saved:
            self.app.finish_capture(Image.new('RGB', (10, 10)))
            opened.assert_not_called()
            saved.assert_not_called()
        self.assertFalse(self.app.capturing)

    def test_exit_multiple_editors_cancel_then_save(self):
        first, second = self.make_editor(), self.make_editor()
        self.app.editors.extend([first, second])
        with patch('app.QMessageBox.question', side_effect=[QMessageBox.StandardButton.Discard, QMessageBox.StandardButton.Cancel]), \
                patch.object(self.app, 'quit') as quit_app:
            self.assertFalse(self.app.exit_app())
            quit_app.assert_not_called()
        self.assertEqual(self.app.editors, [second])
        with patch('app.QMessageBox.question', return_value=QMessageBox.StandardButton.Save), \
                patch.object(self.app, 'save_image', return_value=Path('saved.png')), patch.object(self.app, 'quit') as quit_app:
            self.assertTrue(self.app.exit_app())
            quit_app.assert_called_once()
        self.assertEqual(self.app.editors, [])

    def test_no_tray_close_can_cancel(self):
        self.app.panel.show()
        with patch('app.QSystemTrayIcon.isSystemTrayAvailable', return_value=False), \
                patch.object(self.app, 'exit_app', return_value=False):
            self.assertFalse(self.app.panel.close())
            self.assertTrue(self.app.panel.isVisible())
        self.app.panel.hide()

    def test_tray_disappears_restores_panel(self):
        self.app.panel.hide()
        with patch('app.QSystemTrayIcon.isSystemTrayAvailable', return_value=False):
            self.app.check_tray()
            self.assertTrue(self.app.panel.isVisible())
        self.app.panel.hide()

    def test_autostart_preference_and_disable(self):
        with patch('app.startup.set_enabled') as configure:
            self.app.initialize_autostart()
            configure.assert_called_with(True)
            self.app.set_autostart(False)
            configure.assert_called_with(False)
            self.app.initialize_autostart()
            configure.assert_called_with(False)

    def test_autostart_error_keeps_preference(self):
        self.app.settings.setValue('startup/enabled', False)
        with patch('app.startup.set_enabled', side_effect=PermissionError('denied')), \
                patch('app.QMessageBox.warning'), self.assertLogs(level='ERROR'):
            self.assertFalse(self.app.set_autostart(True))
        self.assertFalse(self.app.settings.value('startup/enabled', type=bool))


class FakeHotkeyBackend:
    def __init__(self):
        self.registered = {}
        self.blocked = set()

    def RegisterHotKey(self, window, ident, mods, key):
        combo = mods, key
        if combo in self.blocked or combo in self.registered.values():
            return 0
        self.registered[ident] = combo
        return 1

    def UnregisterHotKey(self, window, ident):
        self.registered.pop(ident, None)
        return 1


class HotkeyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = Mock()
        self.app.settings = QSettings(str(Path(self.tmp.name) / 'settings.ini'), QSettings.Format.IniFormat)
        self.backend = FakeHotkeyBackend()
        self.hotkeys = Hotkeys(self.app, backend=self.backend)
        self.addCleanup(self.hotkeys.cleanup)

    def test_conflict_rolls_back_new_registrations(self):
        old = self.backend.registered.copy()
        self.backend.blocked.add(parse_shortcut('Ctrl+Alt+Y')[1])
        with self.assertRaises(ValueError):
            self.hotkeys.configure({1: 'Ctrl+Alt+X', 2: 'Ctrl+Alt+Y', 3: ''})
        self.assertEqual(self.backend.registered, old)
        self.assertEqual(self.hotkeys.bindings, DEFAULTS)

    def test_swap_and_disable(self):
        self.hotkeys.configure({1: DEFAULTS[2], 2: DEFAULTS[1], 3: ''})
        self.assertEqual(len(self.backend.registered), 2)
        self.assertEqual(self.hotkeys.id_actions[self.hotkeys.registrations[parse_shortcut(DEFAULTS[2])[1]]], 1)
        self.assertEqual(self.app.settings.value('hotkeys/3'), '')

    def test_custom_bindings_reload(self):
        requested = {1: 'Ctrl+Shift+F9', 2: 'Alt+F10', 3: ''}
        self.hotkeys.configure(requested)
        self.hotkeys.cleanup()
        other = Hotkeys(self.app, backend=self.backend)
        try:
            self.assertEqual(other.bindings, requested)
            self.assertEqual(len(other.ids), 2)
        finally:
            other.cleanup()

    def test_duplicate_shortcuts_rejected(self):
        with self.assertRaises(ValueError):
            self.hotkeys.configure({1: 'Ctrl+Alt+X', 2: 'Ctrl+Alt+X', 3: ''})
        self.assertEqual(len(self.backend.registered), 3)

    def test_invalid_and_reserved_shortcuts(self):
        for text in ('A', 'Shift+A', 'Meta+A', 'F12', 'Ctrl+K, Ctrl+C', 'Ctrl+Я'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_shortcut(text)
        self.assertEqual(parse_shortcut('Ctrl+Shift+F9')[1], (0x4006, 0x78))

    def test_editor_shortcuts_cannot_be_registered_globally(self):
        for text in ('Ctrl+S', 'Ctrl+Shift+S', 'Ctrl+O', 'Ctrl+C', 'Ctrl+Z', 'Ctrl+Y'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_shortcut(text)

    def test_autostart_frozen_command_is_quoted(self):
        with patch('startup.sys.executable', 'C:\\Apps With Spaces\\LocalShot.exe'), patch('startup.sys.frozen', True, create=True):
            self.assertEqual(startup.command(), '"C:\\Apps With Spaces\\LocalShot.exe" --autostart')


if __name__ == '__main__':
    unittest.main()
