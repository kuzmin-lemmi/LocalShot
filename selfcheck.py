"""Offline check of a copied/frozen distribution; never captures the desktop."""
import json
from pathlib import Path
import sys
import tempfile


def run(report_path):
    report_path = Path(report_path)
    try:
        from PIL import Image
        from app import ShotApp, Editor, to_pil, to_pixmap
        from imaging import edit
        from storage import save_png
        from PySide6.QtCore import QSettings
        with tempfile.TemporaryDirectory() as temporary:
            app = ShotApp(initialize=False, settings=QSettings(str(Path(temporary) / 'settings.ini'), QSettings.Format.IniFormat))
            app.editors = []
            app.folder = Path(temporary)
            app.open_folder = lambda: None
            app.save_image = lambda image, parent=None: save_png(image, Path(temporary))
            source = Image.new('RGB', (640, 360), 'white')
            assert to_pil(to_pixmap(source)).tobytes() == source.tobytes()
            editor = Editor(source, app)
            editor.canvas.commit(edit(source, 'hide', (0, 0), (639, 359), 'black'))
            assert editor.canvas.image.getextrema() == ((0, 0),) * 3
            editor.canvas.undo()
            assert editor.canvas.image.tobytes() == source.tobytes()
            editor.canvas.redo()
            saved = editor.save()
            with Image.open(saved) as image:
                assert image.getextrema() == ((0, 0),) * 3
            assert not editor.grab().isNull()
            editor.close()
        report = {'ok': True, 'frozen': bool(getattr(sys, 'frozen', False)),
                  'executable': sys.executable, 'qt_platform': app.platformName(),
                  'checks': ['Qt window render', 'Qt/Pillow conversion', 'redaction',
                             'undo/redo', 'PNG save and reopen']}
        code = 0
    except Exception as error:
        report = {'ok': False, 'error': repr(error)}
        code = 1
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return code
