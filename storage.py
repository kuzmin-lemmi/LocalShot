"""Exclusive PNG writes: never overwrite another file or leave a partial PNG."""
import logging
import os
from pathlib import Path
import tempfile
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


def save_png_as(image, path, overwrite=False):
    """Encode completely before replacing an explicitly approved destination."""
    path = Path(path)
    descriptor, name = tempfile.mkstemp(prefix='.localshot-', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            image.convert('RGB').save(stream, format='PNG')
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        elif os.name == 'nt':
            os.rename(temporary, path)  # Windows fails if destination already exists.
        else:
            os.link(temporary, path)  # Exclusive creation on POSIX as well.
        return path
    finally:
        temporary.unlink(missing_ok=True)
