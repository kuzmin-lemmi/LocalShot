"""Exclusive PNG writes: never overwrite another file or leave a partial PNG."""
import logging
from datetime import datetime
from uuid import uuid4


def save_png(image, folder):
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f')
    for attempt in range(10):
        suffix = '' if attempt == 0 else '_' + uuid4().hex[:8]
        path = folder / f'Снимок_{stamp}{suffix}.png'
        try:
            stream = path.open('xb')
        except FileExistsError:
            continue
        try:
            with stream:
                image.convert('RGB').save(stream, format='PNG')
        except Exception:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logging.exception('Could not remove incomplete screenshot: %s', path)
            raise
        return path
    raise OSError('Не удалось подобрать свободное имя снимка.')
