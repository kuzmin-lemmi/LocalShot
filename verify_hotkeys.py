"""Check Windows registration changes and conflicts without generating keystrokes."""
import ctypes
import json
from pathlib import Path
from PySide6.QtCore import QSettings
from app import ShotApp
from hotkeys import parse_shortcut


def main():
    folder = Path(__file__).parent / 'verification-output'
    folder.mkdir(exist_ok=True)
    settings = QSettings(str(folder / 'hotkeys-test.ini'), QSettings.Format.IniFormat)
    settings.clear()
    for action in (1, 2, 3):
        settings.setValue(f'hotkeys/{action}', '')
    app = ShotApp(settings=settings)
    app.panel.hide()
    backend = ctypes.windll.user32
    reserved_id = 20000
    reserved = False
    try:
        app.hotkeys.configure({1: 'Ctrl+Shift+F9', 2: 'Ctrl+Shift+F10', 3: 'Ctrl+Shift+F11'})
        assert len(app.hotkeys.ids) == 3
        previous = app.hotkeys.bindings.copy()
        reserved = bool(backend.RegisterHotKey(None, reserved_id, *parse_shortcut('Ctrl+Alt+Shift+F8')[1]))
        assert reserved, 'test combination is occupied'
        try:
            app.hotkeys.configure({1: 'Ctrl+Alt+Shift+F8', 2: previous[2], 3: previous[3]})
            raise AssertionError('OS conflict was not detected')
        except ValueError:
            pass
        assert app.hotkeys.bindings == previous
        app.hotkeys.configure({1: previous[2], 2: previous[1], 3: ''})
        assert len(app.hotkeys.ids) == 2
        result = {'windows_registration': True, 'os_conflict_preserves_previous': True,
                  'swap_and_disable': True}
        (folder / 'hotkey-check.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))
    finally:
        if reserved:
            backend.UnregisterHotKey(None, reserved_id)
        app.hotkeys.cleanup()
        app.tray.hide()
        app.panel.hide()


if __name__ == '__main__':
    main()
