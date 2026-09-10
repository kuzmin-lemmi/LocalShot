import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageChops
from imaging import edit
from app import ShotApp, Editor, to_pil, to_pixmap


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


if __name__ == '__main__':
    unittest.main()
