"""Bootstrap logging before importing Qt, including missing-dependency failures."""
import ctypes
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys


def configure_logging():
    folder = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'LocalShot' / 'logs'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'localshot.log'
    handler = RotatingFileHandler(path, maxBytes=2 * 1024 * 1024, backupCount=2, encoding='utf-8')
    logging.basicConfig(handlers=[handler], level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    return path


def run():
    if len(sys.argv) == 3 and sys.argv[1] == '--self-check':
        from selfcheck import run as self_check
        return self_check(sys.argv[2])
    try:
        log_path = configure_logging()
    except OSError:
        log_path = None
        logging.basicConfig(level=logging.INFO)

    def report(kind, value, traceback):
        logging.critical('Unhandled error', exc_info=(kind, value, traceback))
        message = ('Произошла ошибка. Если редактор открыт, попробуйте сохранить снимок.\n'
                   + (f'Журнал: {log_path}' if log_path else 'Не удалось создать журнал ошибок.'))
        if sys.platform == 'win32':
            ctypes.windll.user32.MessageBoxW(None, message, 'Локальный снимок — ошибка', 0x10)
        elif sys.stderr:
            print(message, file=sys.stderr)

    sys.excepthook = report
    try:
        from app import main
        return main()
    except Exception:
        report(*sys.exc_info())
        return 1


if __name__ == '__main__':
    sys.exit(run())
