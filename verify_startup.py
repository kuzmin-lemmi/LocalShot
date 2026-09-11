"""Concurrent native launch check; child apps exit automatically after 5 seconds."""
import json
from pathlib import Path
import subprocess
import sys


def child():
    import app
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QSystemTrayIcon
    original = app.ShotApp
    class TimedApp(original):
        def initialize_autostart(self):
            pass  # Verification must not change the user's startup settings.

        def initialize_ui(self):
            super().initialize_ui()
            print(json.dumps({'initialized': True, 'hotkeys': self.hotkeys.ids,
                              'hotkey_errors': self.hotkeys.errors, 'actions': sorted(self.hotkeys.id_actions.values()),
                              'tray_available': QSystemTrayIcon.isSystemTrayAvailable()}), flush=True)
            QTimer.singleShot(5000, self.quit)
    app.ShotApp = TimedApp
    return app.main()


def main():
    command = [sys.executable, str(Path(__file__).resolve()), '--child']
    one = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    two = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    a, ae = one.communicate(timeout=20)
    b, be = two.communicate(timeout=20)
    assert one.returncode == two.returncode == 0, (one.returncode, two.returncode, ae, be)
    initialized = [json.loads(line) for line in (a + b).splitlines() if line.strip()]
    assert len(initialized) == 1, initialized
    assert initialized[0]['actions'] == [1, 2, 3], initialized
    result = {'two_simultaneous_processes': 'passed', 'ui_initializations': len(initialized),
              'instance': initialized[0]}
    folder = Path(__file__).parent / 'verification-output'
    folder.mkdir(exist_ok=True)
    (folder / 'startup-check.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    sys.exit(child() if '--child' in sys.argv else main())
