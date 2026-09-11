"""Check background launch UI without modifying the startup entry."""
import json
from pathlib import Path
import sys
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QSystemTrayIcon
from app import ShotApp
import startup


def main():
    folder = Path(__file__).parent / 'verification-output'
    folder.mkdir(exist_ok=True)
    sys.argv.append('--autostart')
    app = ShotApp(settings=QSettings(str(folder / 'autostart-test.ini'), QSettings.Format.IniFormat),
                  enable_hotkeys=False)
    try:
        app.processEvents()
        tray = QSystemTrayIcon.isSystemTrayAvailable()
        assert app.panel.isVisible() == (not tray)
        result = {'tray_available': tray, 'panel_visible': app.panel.isVisible(),
                  'startup_entry_present': startup.is_enabled(), 'background_launch': True}
        (folder / 'autostart-check.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))
    finally:
        app.hotkeys.cleanup()
        app.tray.hide()
        app.panel.hide()


if __name__ == '__main__':
    main()
