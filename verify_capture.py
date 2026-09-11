"""Native Windows smoke checks. Uses synthetic windows; does not save desktop pixels."""
import json
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QPoint, Qt, QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from app import ShotApp


def main():
    folder = Path(__file__).parent / 'verification-output'
    folder.mkdir(exist_ok=True)
    settings = QSettings(str(folder / 'capture-test.ini'), QSettings.Format.IniFormat)
    settings.clear()
    app = ShotApp(settings=settings, enable_hotkeys=False)
    results = []
    captured = []
    def finish(image):
        captured.append(image)
        app.cancel_capture()
    app.finish_capture = finish
    try:
        for screen in app.screens():
            geometry = screen.geometry()
            background = QWidget()
            background.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
            background.setStyleSheet('background: #37b56d')
            background.setGeometry(geometry)
            background.show()
            background.raise_()
            app.panel.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            app.panel.move(geometry.center() - QPoint(250, 170))
            app.panel.show()
            app.panel.raise_()
            QTest.qWait(400)
            with patch('app.QCursor.pos', return_value=geometry.center()):
                app.capture(True)
                QTest.qWait(500)
                assert captured, 'full capture did not finish'
                full = captured.pop()
                center = full.getpixel((full.width // 2, full.height // 2))
                assert center == (55, 181, 109), f'own panel included or desktop obscured: {center}'
                app.capture(False)
                QTest.qWait(500)
                overlay = next(w for w in app.overlays if w.screen == screen)
                QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(40, 40))
                QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(239, 139))
                assert captured, 'region capture did not finish'
                region = captured.pop()
                sx, sy = full.width / geometry.width(), full.height / geometry.height()
                assert region.size == (round(240 * sx) - round(40 * sx), round(140 * sy) - round(40 * sy))
                app.capture(False)
                QTest.qWait(500)
                QTest.keyClick(app.overlays[0], Qt.Key.Key_Escape)
                assert not app.capturing and not app.overlays
                assert app.panel.isVisible()
                results.append({'geometry': [geometry.x(), geometry.y(), geometry.width(), geometry.height()],
                                'dpr': screen.devicePixelRatio(), 'full': list(full.size), 'region': list(region.size),
                                'own_windows_hidden': True, 'escape_and_repeat': True})
            background.close()
        folder = Path(__file__).parent / 'verification-output'
        folder.mkdir(exist_ok=True)
        (folder / 'capture-check.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(json.dumps(results, indent=2))
    finally:
        app.cancel_capture()
        app.panel.hide()
        app.tray.hide()
        app.hotkeys.cleanup()


if __name__ == '__main__':
    main()
