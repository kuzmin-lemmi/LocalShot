import ctypes
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt, QRect, QPoint, QTimer, QSettings, QUrl, QAbstractNativeEventFilter
from PySide6.QtGui import (QAction, QColor, QCursor, QDesktopServices, QIcon,
                           QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut)
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QLabel, QSystemTrayIcon, QMenu, QFileDialog,
    QMessageBox, QScrollArea, QColorDialog, QSpinBox, QInputDialog, QToolBar)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from imaging import edit


def to_pil(pixmap):
    q = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombytes('RGBA', (q.width(), q.height()), bytes(q.bits()),
                           'raw', 'RGBA', q.bytesPerLine()).convert('RGB')


def to_pixmap(img):
    data = img.convert('RGBA').tobytes()
    return QPixmap.fromImage(QImage(data, img.width, img.height, img.width * 4,
                                    QImage.Format.Format_RGBA8888).copy())


def icon():
    p = QPixmap(64, 64)
    p.fill(Qt.GlobalColor.transparent)
    painter = QPainter(p)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor('#2563eb'))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, 60, 60, 16, 16)
    painter.setPen(QPen(Qt.GlobalColor.white, 4))
    painter.drawRoundedRect(13, 20, 38, 28, 5, 5)
    painter.drawEllipse(25, 26, 14, 14)
    painter.end()
    return QIcon(p)


class Canvas(QWidget):
    def __init__(self, image, owner):
        super().__init__()
        self.image = image
        self.owner = owner
        self.history = []
        self.start = None
        self.preview = None
        self.scale = 1.0
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.zoom(1.0)

    def zoom(self, scale):
        self.scale = scale
        self.setFixedSize(max(1, round(self.image.width * scale)),
                          max(1, round(self.image.height * scale)))
        self.update()

    def point(self, event):
        p = event.position()
        return (max(0, min(self.image.width - 1, p.x() / self.scale)),
                max(0, min(self.image.height - 1, p.y() / self.scale)))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), to_pixmap(self.preview or self.image))

    def result(self, end, text=''):
        return edit(self.image, self.owner.tool, self.start, end,
                    self.owner.color, self.owner.width.value(), text,
                    self.owner.font_size.value())

    def commit(self, result):
        self.history.append(self.image)
        # Bound undo memory to roughly 192 MiB (at least one undo).
        limit = max(1, min(25, 192 * 1024 * 1024 // (self.image.width * self.image.height * 3)))
        self.history = self.history[-limit:]
        self.image = result
        self.owner.dirty = True
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.start = self.point(event)
        if self.owner.tool == 'text':
            text, ok = QInputDialog.getText(self, 'Подпись', 'Текст:')
            if ok and text:
                self.commit(self.result(self.start, text))
            self.start = None

    def mouseMoveEvent(self, event):
        if self.start is not None:
            self.preview = self.result(self.point(event))
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.start is not None:
            self.commit(self.result(self.point(event)))
            self.start = self.preview = None
            self.update()

    def undo(self):
        if self.history:
            self.image = self.history.pop()
            self.preview = None
            self.owner.dirty = True
            self.update()


class Editor(QMainWindow):
    def __init__(self, image, app):
        super().__init__()
        self.app = app
        self.tool = 'arrow'
        self.color = '#ef4444'
        self.dirty = True
        self.setWindowTitle('Локальный снимок — редактор')
        self.setWindowIcon(app.windowIcon())
        self.resize(1120, 760)
        self.canvas = Canvas(image, self)
        scroll = QScrollArea()
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidget(self.canvas)
        self.setCentralWidget(scroll)
        bar = QToolBar('Инструменты')
        bar.setMovable(False)
        self.addToolBar(bar)
        self.actions = {}
        for key, label in [('arrow', 'Стрелка'), ('line', 'Линия'), ('rect', 'Рамка'),
                           ('hide', 'Скрыть'), ('blur', 'Размыть'), ('text', 'Текст')]:
            action = bar.addAction(label)
            action.setCheckable(True)
            action.triggered.connect(lambda checked=False, k=key: self.choose(k))
            self.actions[key] = action
        bar.addSeparator()
        bar.addAction('Цвет', self.pick_color)
        self.width = QSpinBox()
        self.width.setRange(1, 30)
        self.width.setValue(5)
        self.width.setPrefix('Линия: ')
        bar.addWidget(self.width)
        self.font_size = QSpinBox()
        self.font_size.setRange(10, 160)
        self.font_size.setValue(28)
        self.font_size.setPrefix('Текст: ')
        bar.addWidget(self.font_size)
        self.addToolBarBreak()
        actions = QToolBar('Файл')
        actions.setMovable(False)
        self.addToolBar(actions)
        for label, callback, shortcut in [
            ('Сохранить', self.save, 'Ctrl+S'), ('Копировать', self.copy, 'Ctrl+C'),
            ('Отменить правку', self.canvas.undo, 'Ctrl+Z'),
            ('Открыть папку', app.open_folder, 'Ctrl+O')]:
            action = actions.addAction(label, callback)
            action.setShortcut(QKeySequence(shortcut))
        actions.addSeparator()
        for label, factor in [('50%', .5), ('100%', 1), ('150%', 1.5)]:
            actions.addAction(label, lambda checked=False, f=factor: self.canvas.zoom(f))
        self.choose('arrow')

    def choose(self, tool):
        self.tool = tool
        for key, action in self.actions.items():
            action.setChecked(key == tool)
        self.statusBar().showMessage('Скрыть: сплошная заливка выбранным цветом. Размытие может оставить ответ читаемым.'
                                     if tool in ('hide', 'blur') else 'Проведите мышью по снимку. Ctrl+Z — отменить правку.')

    def pick_color(self):
        color = QColorDialog.getColor(QColor(self.color), self)
        if color.isValid():
            self.color = color.name()

    def save(self):
        path = self.app.save_image(self.canvas.image, self)
        if path:
            self.dirty = False
            self.statusBar().showMessage(f'Сохранено: {path}')
        return path

    def copy(self):
        self.app.clipboard().setPixmap(to_pixmap(self.canvas.image))
        self.statusBar().showMessage('Скопировано. Можно вставить через Ctrl+V.')

    def closeEvent(self, event):
        if self.dirty:
            answer = QMessageBox.question(self, 'Сохранить снимок?',
                'Сохранить текущий снимок перед закрытием?',
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Cancel or (answer == QMessageBox.StandardButton.Save and not self.save()):
                event.ignore()
                return
        event.accept()
        if self in self.app.editors:
            self.app.editors.remove(self)


class Overlay(QWidget):
    def __init__(self, screen, image, app):
        super().__init__()
        self.app, self.screen, self.image = app, screen, image
        self.start = self.end = None
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.image)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 115))
        if self.start is not None:
            box = QRect(self.start, self.end).normalized().intersected(self.rect())
            painter.save()
            painter.setClipRect(box)
            painter.drawPixmap(self.rect(), self.image)
            painter.restore()
            painter.setPen(QPen(QColor('#60a5fa'), 2))
            painter.drawRect(box)
        else:
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(24, 40, 'Выделите область мышью • Esc — отмена')

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start = self.end = event.position().toPoint()

    def mouseMoveEvent(self, event):
        if self.start is not None:
            self.end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.start is None:
            return
        self.end = event.position().toPoint()
        box = QRect(self.start, self.end).normalized().intersected(self.rect())
        if box.width() < 3 or box.height() < 3:
            self.start = self.end = None
            self.update()
            return
        # Qt widget coordinates are logical, screenshot pixels are physical.
        sx, sy = self.image.width() / self.width(), self.image.height() / self.height()
        crop = to_pil(self.image).crop((round(box.left() * sx), round(box.top() * sy),
            round((box.right() + 1) * sx), round((box.bottom() + 1) * sy)))
        self.app.finish_capture(crop)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.app.cancel_capture()


class Hotkeys(QAbstractNativeEventFilter):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.ids = []
        self.errors = []
        if sys.platform == 'win32':
            for ident, key, label in [(1, 0x41, 'Ctrl+Alt+A'), (2, 0x53, 'Ctrl+Alt+S'), (3, 0x4F, 'Ctrl+Alt+O')]:
                if ctypes.windll.user32.RegisterHotKey(None, ident, 0x4003, key):
                    self.ids.append(ident)
                else:
                    self.errors.append(label)

    def nativeEventFilter(self, event_type, message):
        if sys.platform == 'win32':
            from ctypes.wintypes import MSG
            msg = MSG.from_address(int(message))
            if msg.message == 0x0312:
                ident = int(msg.wParam)
                if ident == 3:
                    self.app.open_folder()
                else:
                    self.app.capture(ident == 2)
                return True, 0
        return False, 0

    def cleanup(self):
        if sys.platform == 'win32':
            for ident in self.ids:
                ctypes.windll.user32.UnregisterHotKey(None, ident)


class ShotApp(QApplication):
    def __init__(self):
        super().__init__(sys.argv)
        self.setApplicationName('LocalShot')
        self.setOrganizationName('LocalShot')
        self.setQuitOnLastWindowClosed(False)
        self.setWindowIcon(icon())
        self.settings = QSettings()
        self.folder = Path(self.settings.value('folder', str(Path.home() / 'Pictures' / 'LocalShot')))
        self.editors, self.overlays, self.hidden = [], [], []
        self.capturing = False
        self.panel = QWidget()
        self.panel.setWindowTitle('Локальный снимок')
        self.panel.setWindowIcon(self.windowIcon())
        self.panel.resize(500, 340)
        layout = QVBoxLayout(self.panel)
        title = QLabel('Локальный снимок')
        title.setStyleSheet('font-size: 25px; font-weight: 700')
        layout.addWidget(title)
        layout.addWidget(QLabel('Снимки и пометки для уроков — на вашем компьютере.'))
        for label, fn in [('Выделить область    Ctrl+Alt+A', lambda: self.capture(False)),
                          ('Весь текущий экран    Ctrl+Alt+S', lambda: self.capture(True)),
                          ('Открыть папку    Ctrl+Alt+O', self.open_folder),
                          ('Выбрать папку сохранения', self.choose_folder)]:
            button = QPushButton(label)
            button.setMinimumHeight(36)
            button.clicked.connect(fn)
            layout.addWidget(button)
        self.folder_label = QLabel(str(self.folder))
        self.folder_label.setWordWrap(True)
        layout.addWidget(self.folder_label)
        layout.addWidget(QLabel('Закрытие окна оставляет приложение возле часов.'))
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip('Локальный снимок — двойной щелчок открывает папку')
        menu = QMenu()
        menu.addAction('Выделить область', lambda: self.capture(False))
        menu.addAction('Весь текущий экран', lambda: self.capture(True))
        menu.addAction('Открыть папку', self.open_folder)
        menu.addAction('Главное окно', self.show_panel)
        menu.addSeparator()
        menu.addAction('Выход', self.exit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.open_folder() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show()
        self.hotkeys = Hotkeys(self)
        self.installNativeEventFilter(self.hotkeys)
        self.aboutToQuit.connect(self.hotkeys.cleanup)
        if self.hotkeys.errors:
            layout.addWidget(QLabel('Клавиши заняты другой программой: ' + ', '.join(self.hotkeys.errors) + '. Используйте кнопки или меню возле часов.'))
        self.panel.show()

    def show_panel(self):
        self.panel.showNormal()
        self.panel.raise_()
        self.panel.activateWindow()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self.panel, 'Папка снимков', str(self.folder))
        if folder:
            self.folder = Path(folder)
            self.settings.setValue('folder', folder)
            self.folder_label.setText(folder)

    def open_folder(self):
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.folder))):
                raise OSError('Не удалось открыть проводник.')
        except OSError as exc:
            QMessageBox.warning(self.panel, 'Ошибка папки', str(exc))

    def save_image(self, image, parent=None):
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            path = self.folder / ('Снимок_' + datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f') + '.png')
            # Exclusive create prevents silent overwriting.
            with path.open('xb') as stream:
                image.convert('RGB').save(stream, format='PNG')
            self.tray.showMessage('Снимок сохранён', str(path), QSystemTrayIcon.MessageIcon.Information, 2500)
            return path
        except OSError as exc:
            QMessageBox.warning(parent or self.panel, 'Не удалось сохранить', str(exc))
            return None

    def capture(self, full=False):
        if self.capturing:
            return
        self.capturing = True
        self.target_screen = self.screenAt(QCursor.pos()) or self.primaryScreen()
        self.hidden = [w for w in [self.panel, *self.editors] if w.isVisible()]
        for w in self.hidden:
            w.hide()
        QTimer.singleShot(250, lambda: self.take_capture(full))

    def take_capture(self, full):
        try:
            screens = [self.target_screen] if full else self.screens()
            # Capture every screen BEFORE showing any overlays.
            captures = [(s, s.grabWindow(0)) for s in screens]
            if any(p.isNull() for s, p in captures):
                raise RuntimeError('Система не предоставила изображение экрана.')
            if full:
                self.finish_capture(to_pil(captures[0][1]))
                return
            for screen, pix in captures:
                overlay = Overlay(screen, pix, self)
                self.overlays.append(overlay)
                overlay.show()
            current = next((w for w in self.overlays if w.screen == self.target_screen), self.overlays[0])
            current.activateWindow()
            current.setFocus()
        except Exception as exc:
            self.cancel_capture()
            QMessageBox.warning(self.panel, 'Ошибка захвата', str(exc))

    def cancel_capture(self):
        for overlay in self.overlays:
            overlay.close()
            overlay.deleteLater()
        self.overlays = []
        for w in self.hidden:
            w.show()
        self.hidden = []
        self.capturing = False

    def finish_capture(self, image):
        self.cancel_capture()
        self.capturing = True
        dialog = QMessageBox(self.panel)
        dialog.setWindowTitle('Область готова')
        dialog.setText(f'Снимок {image.width} × {image.height}. Что сделать?')
        save = dialog.addButton('Сохранить', QMessageBox.ButtonRole.AcceptRole)
        editor = dialog.addButton('Редактировать', QMessageBox.ButtonRole.ActionRole)
        copy = dialog.addButton('Копировать', QMessageBox.ButtonRole.ActionRole)
        dialog.addButton('Отмена', QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        chosen = dialog.clickedButton()
        self.capturing = False
        if chosen == save:
            if not self.save_image(image):
                self.open_editor(image)
        elif chosen == editor:
            self.open_editor(image)
        elif chosen == copy:
            self.clipboard().setPixmap(to_pixmap(image))

    def open_editor(self, image):
        editor = Editor(image, self)
        self.editors.append(editor)
        editor.show()
        editor.activateWindow()

    def exit_app(self):
        for editor in list(self.editors):
            if not editor.close():
                return
        self.quit()


def main():
    app = ShotApp()
    # Prevent two background copies from competing for global hotkeys.
    probe = QLocalSocket()
    probe.connectToServer('LocalShot.Desktop.v1')
    if probe.waitForConnected(300):
        probe.write(b'show')
        probe.waitForBytesWritten(300)
        app.hotkeys.cleanup()
        return
    QLocalServer.removeServer('LocalShot.Desktop.v1')
    app.server = QLocalServer()
    app.server.listen('LocalShot.Desktop.v1')
    def activate():
        socket = app.server.nextPendingConnection()
        if socket:
            socket.close()
            socket.deleteLater()
        app.show_panel()
    app.server.newConnection.connect(activate)
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
