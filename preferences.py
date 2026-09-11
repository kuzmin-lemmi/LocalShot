from PySide6.QtWidgets import QApplication


def integer(settings, key, default, minimum, maximum):
    try:
        return max(minimum, min(maximum, int(settings.value(key, default))))
    except (ValueError, TypeError):
        return default


def restore_window(window, settings, key):
    geometry = settings.value(key)
    if geometry is not None:
        try:
            window.restoreGeometry(geometry)
        except (TypeError, ValueError):
            pass
    # Keep the title bar reachable after disconnecting a monitor.
    if not any(s.availableGeometry().contains(window.frameGeometry().topLeft()) for s in QApplication.screens()):
        screen = QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            window.resize(min(window.width(), area.width()), min(window.height(), area.height()))
            window.move(area.center() - window.rect().center())
