"""Native full flow using a synthetic desktop window and isolated preferences."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from PySide6.QtCore import QPoint, QSettings, Qt, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QFileDialog, QDialogButtonBox, QLineEdit
from app import ShotApp
from dialogs import CaptureDialog, HotkeyDialog
from imaging import edit


def main():
    folder = Path(__file__).parent / 'verification-output'
    folder.mkdir(exist_ok=True)
    settings = QSettings(str(folder / 'flow-test.ini'), QSettings.Format.IniFormat)
    settings.clear()
    app = ShotApp(settings=settings, enable_hotkeys=False)
    app.file_dialog_options = QFileDialog.Option.DontUseNativeDialog
    app.folder = folder
    background = QWidget()
    background.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
    background.setStyleSheet('background: #e0f2fe; color: #0f172a')
    layout = QVBoxLayout(background)
    label = QLabel('LocalShot — проверка снимка\nОтвет: 12345')
    label.setStyleSheet('font-size: 32px')
    layout.addWidget(label)
    screen = app.primaryScreen()
    background.setGeometry(screen.geometry())
    background.show()
    app.panel.hide()
    try:
        QTest.qWait(300)
        with patch('app.QCursor.pos', return_value=screen.geometry().center()):
            app.capture(False)
            QTest.qWait(500)
            overlay = next(w for w in app.overlays if w.screen == screen)
            QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
            previews = []
            def edit_preview():
                dialog = app.activeModalWidget()
                if isinstance(dialog, CaptureDialog):
                    previews.append(not dialog.preview.pixmap().isNull())
                    dialog.grab().save(str(folder / 'capture-preview.png'))
                    dialog.buttons['edit'].click()
            QTimer.singleShot(0, edit_preview)
            QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(799, 499))
        assert previews == [True]
        assert len(app.editors) == 1
        editor = app.editors[0]
        background.hide()
        editor.set_zoom(1)
        editor.choose('hide')
        editor.color = '#000000'
        QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
        QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=QPoint(60, 60))
        assert editor.canvas.image.getpixel((10, 10)) == (0, 0, 0)
        changed = editor.canvas.image.tobytes()
        editor.history_actions['Ctrl+Z'].trigger()
        assert editor.canvas.image.tobytes() != changed
        editor.history_actions['Ctrl+Y'].trigger()
        assert editor.canvas.image.tobytes() == changed
        editor.width.setValue(9)
        editor.font_size.setValue(36)
        def complete_file_dialog(path, role):
            dialog = app.activeModalWidget()
            assert isinstance(dialog, QFileDialog)
            dialog.setDirectory(str(path.parent))
            field = dialog.findChild(QLineEdit, 'fileNameEdit')
            field.setFocus()
            field.selectAll()
            QTest.keyClicks(field, path.name)
            buttons = dialog.findChild(QDialogButtonBox)
            QTest.mouseClick(buttons.button(role), Qt.MouseButton.LeftButton)

        with tempfile.TemporaryDirectory(dir=folder) as temporary:
            destination = Path(temporary) / 'flow-saved.png'
            QTimer.singleShot(100, lambda: complete_file_dialog(destination, QDialogButtonBox.StandardButton.Save))
            saved_path = editor.save_as()
            assert saved_path == destination, (str(saved_path), str(destination))
            editor.canvas.commit(edit(editor.canvas.image, 'line', (100, 100), (150, 150), 'red'))
            changed = editor.canvas.image.tobytes()
            assert editor.save() == destination
            with Image.open(destination) as saved:
                assert saved.tobytes() == changed
            QTimer.singleShot(100, lambda: complete_file_dialog(destination, QDialogButtonBox.StandardButton.Open))
            reopened = app.open_image()
            assert reopened.canvas.image.tobytes() == changed
            assert not reopened.dirty
            assert reopened.width.value() == 9 and reopened.font_size.value() == 36
            reopened.close()
        editor.grab().save(str(folder / 'editor-flow.png'))
        editor.close()
        dialog = HotkeyDialog(app)
        dialog.fields[1].setKeySequence(QKeySequence('Ctrl+Shift+F8'))
        dialog.apply()
        assert app.hotkeys.bindings[1] == 'Ctrl+Shift+F8'
        dialog = HotkeyDialog(app)
        dialog.grab().save(str(folder / 'hotkey-settings.png'))
        dialog.close()
        app.panel.show()
        app.processEvents()
        app.panel.grab().save(str(folder / 'panel-03.png'))
        report = {'platform': app.platformName(), 'capture_preview_edit_save_reopen': True,
                  'image_size': list(editor.canvas.image.size), 'undo_redo': True,
                  'preferences_persisted': True, 'hotkey_dialog': True,
                  'real_file_dialogs': True, 'named_file_updated': True,
                  'settings_file': settings.fileName()}
        (folder / 'flow-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        background.close()
        for editor in list(app.editors):
            editor.dirty = False
            editor.close()
        app.panel.hide()
        app.tray.hide()
        app.hotkeys.cleanup()


if __name__ == '__main__':
    main()
