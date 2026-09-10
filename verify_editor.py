"""Reproducible 4K editor smoke test; saves only a synthetic image."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from time import perf_counter
from PIL import Image, ImageDraw
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from app import ShotApp, Editor


def main():
    app = ShotApp()
    app.panel.hide()
    folder = Path(__file__).parent / 'verification-output'
    folder.mkdir(exist_ok=True)
    source = Image.new('RGB', (3840, 2160), '#f8fafc')
    draw = ImageDraw.Draw(source)
    for x in range(0, 3840, 160):
        draw.line((x, 0, x, 2159), fill='#cbd5e1', width=2)
    for y in range(0, 2160, 160):
        draw.line((0, y, 3839, y), fill='#cbd5e1', width=2)
    editor = Editor(source, app)
    editor.show()
    app.processEvents()
    editor.fit_to_window()
    canvas = editor.canvas
    editor.choose('arrow')
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(60, 60))
    times = []
    for i in range(60):
        event = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(100 + i * 5, 100 + i * 2),
                            QPointF(100 + i * 5, 100 + i * 2), Qt.MouseButton.NoButton,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        start = perf_counter()
        canvas.mouseMoveEvent(event)
        canvas.repaint()
        app.processEvents()
        times.append((perf_counter() - start) * 1000)
    start = perf_counter()
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(450, 250))
    commit_ms = (perf_counter() - start) * 1000
    expected = canvas.image.tobytes()
    canvas.undo()
    assert canvas.image.tobytes() == source.tobytes()
    canvas.redo()
    assert canvas.image.tobytes() == expected
    # Exercise fit, panning and wheel zoom handlers without changing OS settings.
    editor.set_zoom(1)
    app.processEvents()
    bar = editor.scroll.horizontalScrollBar()
    bar.setValue(300)
    before = bar.value()
    QTest.mousePress(canvas, Qt.MouseButton.MiddleButton, pos=QPoint(400, 200))
    event = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(450, 200),
                        canvas.pan_start + QPointF(50, 0), Qt.MouseButton.NoButton,
                        Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier)
    canvas.mouseMoveEvent(event)
    assert bar.value() == before - 50
    QTest.mouseRelease(canvas, Qt.MouseButton.MiddleButton, pos=QPoint(450, 200))
    editor.fit_to_window()
    app.processEvents()
    app.folder = folder
    path = editor.save()
    assert path and not editor.dirty
    with Image.open(path) as saved:
        assert saved.size == (3840, 2160)
        assert saved.tobytes() == expected
    assert editor.grab().save(str(folder / 'editor-4k.png'))
    result = {'image_size': [3840, 2160], 'preview_frames': len(times),
              'preview_median_ms': round(sorted(times)[len(times)//2], 2),
              'preview_max_ms': round(max(times), 2), 'commit_ms': round(commit_ms, 2),
              'history_bytes': canvas.history_bytes, 'zoom': canvas.scale,
              'undo_redo_save_pan': 'passed', 'platform': app.platformName(),
              'screens': [{'size': [s.size().width(), s.size().height()],
                           'dpr': s.devicePixelRatio()} for s in app.screens()]}
    (folder / 'editor-check.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    editor.close()
    app.tray.hide()
    app.hotkeys.cleanup()


if __name__ == '__main__':
    main()
