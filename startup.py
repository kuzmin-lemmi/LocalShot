"""Per-user Windows startup entry; never requires administrator privileges."""
from pathlib import Path
import subprocess
import sys

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME = 'LocalShot'


def command():
    executable = Path(sys.executable)
    if getattr(sys, 'frozen', False):
        arguments = [str(executable)]
    else:
        windowed = executable.with_name('pythonw.exe')
        arguments = [str(windowed if windowed.exists() else executable),
                     str(Path(__file__).resolve().with_name('launcher.py'))]
    return subprocess.list2cmdline([*arguments, '--autostart'])


def set_enabled(enabled):
    if sys.platform != 'win32':
        raise OSError('Автозапуск доступен только в Windows.')
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass


def is_enabled():
    if sys.platform != 'win32':
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
