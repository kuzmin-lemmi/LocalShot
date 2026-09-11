import logging
import math
import sys
from pathlib import Path

from PIL import Image, ImageOps
from PySide6.QtCore import (Qt, QRect, QRectF, QPointF, QTimer, QSettings, QUrl,
                           QLockFile, QStandardPaths)
from PySide6.QtGui import (QColor, QCursor, QDesktopServices, QIcon,
                           QImage, QKeySequence, QPainter, QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QPushButton, QLabel, QSystemTrayIcon, QMenu, QFileDialog, QCheckBox,
    QMessageBox, QScrollArea, QColorDialog, QSpinBox, QInputDialog, QToolBar)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from imaging import edit
from storage import save_png, save_png_as
from hotkeys import Hotkeys, LABELS
from dialogs import HotkeyDialog, CaptureDialog
from preferences import integer, restore_window
import startup


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
    HISTORY_BUDGET = 192 * 1024 * 1024
    HISTORY_LIMIT = 25

    def __init__(self, image, owner):
        super().__init__()
        self.image = image
        self.owner = owner
        self.history = []
        self.future = []
        self.start = None
        self.preview = None
        self.pan_start = None
        self.pixmap = to_pixmap(image)
        self.scale = 1.0
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.zoom(1.0)

    def zoom(self, scale):
        self.scale = scale = max(.05, min(4.0, scale))
        self.setFixedSize(max(1, round(self.image.width * scale)),
                          max(1, round(self.image.height * scale)))
        self.update()

    def point(self, event):
        p = event.position()
        return (max(0, min(self.image.width - 1, p.x() / self.scale)),
                max(0, min(self.image.height - 1, p.y() / self.scale)))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.pixmap)
        if self.start is not None and self.preview is not None:
            painter.scale(self.scale, self.scale)
            a, b = QPointF(*self.start), QPointF(*self.preview)
            painter.setPen(QPen(QColor(self.owner.color), self.owner.width.value()))
            tool = self.owner.tool
            if tool in ('line', 'arrow'):
                painter.drawLine(a, b)
                if tool == 'arrow' and math.dist(self.start, self.preview) > 2:
                    angle = math.atan2(b.y() - a.y(), b.x() - a.x())
                    length = max(16, self.owner.width.value() * 4)
                    points = [b] + [QPointF(b.x() - length * math.cos(angle + d),
                                          b.y() - length * math.sin(angle + d)) for d in (-.48, .48)]
                    painter.setBrush(QColor(self.owner.color))
                    painter.drawPolygon(QPolygonF(points))
            elif tool in ('hide', 'blur', 'rect'):
                # Outline only while dragging; modify full-resolution pixels once on release.
                painter.drawRect(QRectF(a, b).normalized())

    def result(self, end, text=''):
        return edit(self.image, self.owner.tool, self.start, end,
                    self.owner.color, self.owner.width.value(), text,
                    self.owner.font_size.value())

    def commit(self, result):
        self.history.append(self.snapshot())
        self.future.clear()
        self.trim_history()
        self.image = result
        self.refresh_image()

    def snapshot(self):
        # Packed RGB bytes have a measurable size, unlike Pillow's internal RGB storage.
        return self.image.size, self.image.tobytes()

    @property
    def history_bytes(self):
        return sum(sys.getsizeof(data) + sys.getsizeof(size) + sys.getsizeof(item)
                   for item in self.history + self.future for size, data in [item])

    def trim_history(self):
        while (len(self.history) + len(self.future) > self.HISTORY_LIMIT
               or self.history_bytes > self.HISTORY_BUDGET):
            if self.history:
                self.history.pop(0)
            elif self.future:
                self.future.pop(0)
            else:
                break

    def refresh_image(self):
        self.pixmap = to_pixmap(self.image)
        self.start = self.preview = None
        self.owner.dirty = True
        self.owner.update_history_actions()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.pan_start = event.globalPosition()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.start = self.point(event)
        if self.owner.tool == 'text':
            text, ok = QInputDialog.getText(self, 'Подпись', 'Текст:')
            if ok and text:
                self.commit(self.result(self.start, text))
            self.start = None

    def mouseMoveEvent(self, event):
        if self.pan_start is not None:
            delta = event.globalPosition() - self.pan_start
            self.pan_start = event.globalPosition()
            for bar, offset in [(self.owner.scroll.horizontalScrollBar(), delta.x()),
                                (self.owner.scroll.verticalScrollBar(), delta.y())]:
                bar.setValue(bar.value() - round(offset))
            return
        if self.start is not None:
            self.preview = self.point(event)
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.pan_start = None
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
        if event.button() == Qt.MouseButton.LeftButton and self.start is not None:
            self.commit(self.result(self.point(event)))
            self.start = self.preview = None
            self.update()

    def undo(self):
        if self.history:
            self.future.append(self.snapshot())
            size, data = self.history.pop()
            self.image = Image.frombytes('RGB', size, data)
            self.trim_history()
            self.refresh_image()

    def redo(self):
        if self.future:
            self.history.append(self.snapshot())
            size, data = self.future.pop()
            self.image = Image.frombytes('RGB', size, data)
            self.trim_history()
            self.refresh_image()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.owner.set_zoom(self.scale * (1.2 if event.angleDelta().y() > 0 else 1 / 1.2))
            event.accept()
        else:
            event.ignore()


class Editor(QMainWindow):
    def __init__(self, image, app, source_path=None):
        super().__init__()
        self.app = app
        self.tool = 'arrow'
        self.color = str(app.settings.value('editor/color', '#ef4444'))
        if not QColor(self.color).isValid():
            self.color = '#ef4444'
        self.source_path = source_path
        self.dirty = source_path is None
        self.setWindowTitle('Локальный снимок — редактор')
        self.setWindowIcon(app.windowIcon())
        self.resize(1120, 760)
        restore_window(self, app.settings, 'editor/geometry')
        self.canvas = Canvas(image, self)
        self.scroll = scroll = QScrollArea()
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
        self.color_button = QPushButton('Цвет')
        self.color_button.clicked.connect(self.pick_color)
        bar.addWidget(self.color_button)
        self.update_color_button()
        bar.setStyleSheet('QToolButton:checked { background: #bfdbfe; border: 2px solid #2563eb; }')
        self.width = QSpinBox()
        self.width.setRange(1, 30)
        self.width.setValue(integer(app.settings, 'editor/width', 5, 1, 30))
        self.width.valueChanged.connect(lambda value: app.settings.setValue('editor/width', value))
        self.width.setPrefix('Линия: ')
        bar.addWidget(self.width)
        self.font_size = QSpinBox()
        self.font_size.setRange(10, 160)
        self.font_size.setValue(integer(app.settings, 'editor/font_size', 28, 10, 160))
        self.font_size.valueChanged.connect(lambda value: app.settings.setValue('editor/font_size', value))
        self.font_size.setPrefix('Текст: ')
        bar.addWidget(self.font_size)
        self.addToolBarBreak()
        actions = QToolBar('Файл')
        actions.setMovable(False)
        self.addToolBar(actions)
        self.history_actions = {}
        for label, callback, shortcut in [
            ('Сохранить', self.save, 'Ctrl+S'), ('Копировать', self.copy, 'Ctrl+C'),
            ('Сохранить как…', self.save_as, 'Ctrl+Shift+S'),
            ('Открыть…', app.open_image, 'Ctrl+O'),
            ('Отменить правку', self.canvas.undo, 'Ctrl+Z'),
            ('Повторить правку', self.canvas.redo, 'Ctrl+Y'),
            ('Открыть папку', app.open_folder, 'Ctrl+Shift+O')]:
            action = actions.addAction(label, callback)
            action.setShortcut(QKeySequence(shortcut))
            if shortcut in ('Ctrl+Z', 'Ctrl+Y'):
                self.history_actions[shortcut] = action
        actions.addSeparator()
        actions.addAction('Вписать в окно', self.fit_to_window)
        for label, factor in [('50%', .5), ('100%', 1), ('150%', 1.5)]:
            actions.addAction(label, lambda checked=False, f=factor: self.set_zoom(f))
        self.zoom_label = QLabel('100%')
        self.statusBar().addPermanentWidget(self.zoom_label)
        self.fitting = False
        self.update_history_actions()
        self.choose('arrow')
        QTimer.singleShot(0, self.fit_to_window)

    def update_history_actions(self):
        self.history_actions['Ctrl+Z'].setEnabled(bool(self.canvas.history))
        self.history_actions['Ctrl+Y'].setEnabled(bool(self.canvas.future))

    def update_color_button(self):
        color = QColor(self.color)
        foreground = '#000000' if color.lightness() > 128 else '#ffffff'
        self.color_button.setText('Цвет ' + self.color.upper())
        self.color_button.setStyleSheet(f'background-color: {self.color}; color: {foreground}; padding: 5px;')

    def set_zoom(self, scale, fit=False):
        self.fitting = fit
        old = self.canvas.scale
        bars = [self.scroll.horizontalScrollBar(), self.scroll.verticalScrollBar()]
        centers = [(b.value() + b.pageStep() / 2) / old for b in bars]
        self.canvas.zoom(scale)
        for bar, center in zip(bars, centers):
            bar.setValue(round(center * self.canvas.scale - bar.pageStep() / 2))
        self.zoom_label.setText(f'{self.canvas.scale:.0%}')

    def fit_to_window(self):
        viewport = self.scroll.viewport().size()
        self.set_zoom(min(1.0, (viewport.width() - 4) / self.canvas.image.width,
                          (viewport.height() - 4) / self.canvas.image.height), fit=True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, 'fitting', False):
            QTimer.singleShot(0, self.fit_to_window)

    def choose(self, tool):
        self.canvas.start = self.canvas.preview = None
        self.canvas.update()
        self.tool = tool
        for key, action in self.actions.items():
            action.setChecked(key == tool)
        self.statusBar().showMessage('Скрыть: сплошная заливка выбранным цветом. Размытие может оставить ответ читаемым.'
                                     if tool in ('hide', 'blur') else 'Ctrl+Z / Ctrl+Y — отмена / повтор. Ctrl+колесо — масштаб. Средняя кнопка — перемещение.')

    def pick_color(self):
        color = QColorDialog.getColor(QColor(self.color), self)
        if color.isValid():
            self.color = color.name()
            self.app.settings.setValue('editor/color', self.color)
            self.update_color_button()

    def save(self):
        path = self.app.save_image(self.canvas.image, self)
        if path:
            self.dirty = False
            self.statusBar().showMessage(f'Сохранено: {path}')
        return path

    def save_as(self):
        initial = self.source_path or (self.app.folder / 'Снимок.png')
        filename, _ = QFileDialog.getSaveFileName(self, 'Сохранить как', str(initial), 'PNG (*.png)',
                                                options=QFileDialog.Option.DontConfirmOverwrite)
        if not filename:
            return None
        path = Path(filename)
        if path.suffix.lower() != '.png':
            path = path.with_suffix('.png')
        overwrite = path.exists()
        if overwrite and QMessageBox.question(self, 'Заменить файл?', f'Заменить файл «{path.name}»?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return None
        try:
            save_png_as(self.canvas.image, path, overwrite=overwrite)
        except Exception as error:
            logging.exception('Save as failed')
            QMessageBox.warning(self, 'Не удалось сохранить', str(error))
            return None
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
        self.app.settings.setValue('editor/geometry', self.saveGeometry())
        self.app.settings.sync()
        if self in self.app.editors:
            self.app.editors.remove(self)


class Overlay(QWidget):
    def __init__(self, screen, image, app):
        super().__init__()
        self.app, self.screen, self.image = app, screen, image
        self.setWindowTitle('Локальный снимок — выделение')
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


class MainPanel(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app

    def closeEvent(self, event):
        self.app.settings.setValue('panel/geometry', self.saveGeometry())
        self.app.settings.sync()
        if QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
        elif self.app.exit_app():
            event.accept()
        else:
            event.ignore()


class ShotApp(QApplication):
    def __init__(self, initialize=True, settings=None, enable_hotkeys=True):
        super().__init__(sys.argv)
        self.setApplicationName('LocalShot')
        self.setOrganizationName('LocalShot')
        self.setQuitOnLastWindowClosed(False)
        self.settings = settings if settings is not None else QSettings()
        self.enable_hotkeys = enable_hotkeys
        if initialize:
            self.initialize_ui()

    def initialize_ui(self):
        self.setWindowIcon(icon())
        self.folder = Path(self.settings.value('folder', str(Path.home() / 'Pictures' / 'LocalShot')))
        self.editors, self.overlays, self.hidden = [], [], []
        self.capturing = False
        self.capture_timer = QTimer(self)
        self.capture_timer.setSingleShot(True)
        self.capture_timer.timeout.connect(lambda: self.take_capture(self.capture_full))
        self.screenRemoved.connect(self.screen_changed)
        self.screenAdded.connect(self.watch_screen)
        for screen in self.screens():
            self.watch_screen(screen)
        self.panel = MainPanel(self)
        self.panel.setWindowTitle('Локальный снимок')
        self.panel.setWindowIcon(self.windowIcon())
        self.panel.resize(500, 340)
        restore_window(self.panel, self.settings, 'panel/geometry')
        layout = QVBoxLayout(self.panel)
        title = QLabel('Локальный снимок')
        title.setStyleSheet('font-size: 25px; font-weight: 700')
        layout.addWidget(title)
        layout.addWidget(QLabel('Снимки и пометки для уроков — на вашем компьютере.'))
        self.capture_buttons = []
        for label, fn in [('Выделить область', lambda: self.capture(False)),
                          ('Весь текущий экран', lambda: self.capture(True)),
                          ('Открыть папку снимков', self.open_folder),
                          ('Открыть изображение…', self.open_image),
                          ('Горячие клавиши…', self.configure_hotkeys),
                          ('Выбрать папку сохранения', self.choose_folder)]:
            button = QPushButton(label)
            button.setMinimumHeight(36)
            button.clicked.connect(fn)
            layout.addWidget(button)
            self.capture_buttons.append(button)
        self.folder_label = QLabel(str(self.folder))
        self.folder_label.setWordWrap(True)
        layout.addWidget(self.folder_label)
        self.tray_hint = QLabel()
        self.tray_hint.setWordWrap(True)
        layout.addWidget(self.tray_hint)
        self.startup_checkbox = QCheckBox('Запускать при входе в Windows')
        self.startup_checkbox.setChecked(self.settings.value('startup/enabled', True, type=bool))
        self.startup_checkbox.setEnabled(sys.platform == 'win32')
        self.startup_checkbox.toggled.connect(self.set_autostart)
        layout.addWidget(self.startup_checkbox)
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip('Локальный снимок — двойной щелчок открывает папку')
        menu = QMenu()
        menu.addAction('Выделить область', lambda: self.capture(False))
        menu.addAction('Весь текущий экран', lambda: self.capture(True))
        menu.addAction('Открыть папку', self.open_folder)
        menu.addAction('Открыть изображение…', self.open_image)
        menu.addAction('Горячие клавиши…', self.configure_hotkeys)
        menu.addAction('Главное окно', self.show_panel)
        menu.addSeparator()
        menu.addAction('Выход', self.exit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.open_folder() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.hotkeys = Hotkeys(self, backend=None if self.enable_hotkeys else False)
        self.installNativeEventFilter(self.hotkeys)
        self.aboutToQuit.connect(self.hotkeys.cleanup)
        self.hotkey_status = QLabel()
        self.hotkey_status.setWordWrap(True)
        layout.addWidget(self.hotkey_status)
        self.update_hotkey_labels()
        self.tray_timer = QTimer(self)
        self.tray_timer.timeout.connect(self.check_tray)
        self.tray_timer.start(2000)
        self.check_tray()
        if '--autostart' not in sys.argv or not QSystemTrayIcon.isSystemTrayAvailable():
            self.panel.show()

    def set_autostart(self, enabled):
        try:
            startup.set_enabled(enabled)
        except OSError as error:
            logging.exception('Startup setting failed')
            self.startup_checkbox.blockSignals(True)
            self.startup_checkbox.setChecked(not enabled)
            self.startup_checkbox.blockSignals(False)
            QMessageBox.warning(self.panel, 'Не удалось изменить автозапуск', str(error))
            return False
        self.settings.setValue('startup/enabled', enabled)
        self.settings.sync()
        self.startup_checkbox.blockSignals(True)
        self.startup_checkbox.setChecked(enabled)
        self.startup_checkbox.blockSignals(False)
        return True

    def initialize_autostart(self):
        if sys.platform == 'win32':
            self.set_autostart(self.settings.value('startup/enabled', True, type=bool))

    def update_hotkey_labels(self):
        for action, button in enumerate(self.capture_buttons[:3], 1):
            text = self.hotkeys.bindings[action]
            button.setText(LABELS[action] + ('    ' + text if text else ''))
        self.hotkey_status.setText('\n'.join(self.hotkeys.errors))
        self.hotkey_status.setVisible(bool(self.hotkeys.errors))

    def configure_hotkeys(self):
        dialog = HotkeyDialog(self)
        dialog.exec()
        dialog.deleteLater()

    def check_tray(self):
        available = QSystemTrayIcon.isSystemTrayAvailable()
        self.tray_hint.setText('Закрытие окна оставляет приложение возле часов.' if available else
                              'Трей недоступен. Закрытие окна завершит программу после проверки несохранённых снимков.')
        if available:
            if not self.tray.isVisible():
                self.tray.show()
        elif not self.capturing and not self.panel.isVisible():
            self.show_panel()

    def open_image(self):
        filename, _ = QFileDialog.getOpenFileName(self.activeWindow() or self.panel, 'Открыть изображение',
                                                  str(self.folder), 'Изображения (*.png *.jpg *.jpeg *.bmp *.webp)')
        if filename:
            return self.load_image(Path(filename))

    def load_image(self, path):
        try:
            with Image.open(path) as source:
                source = ImageOps.exif_transpose(source)
                if source.mode == 'RGBA' or 'transparency' in source.info:
                    rgba = source.convert('RGBA')
                    image = Image.new('RGBA', source.size, 'white')
                    image.alpha_composite(rgba)
                    image = image.convert('RGB')
                else:
                    image = source.convert('RGB')
            return self.open_editor(image, source_path=Path(path))
        except Exception as error:
            logging.exception('Could not open image')
            QMessageBox.warning(self.panel, 'Не удалось открыть изображение', str(error))
            return None

    def watch_screen(self, screen):
        screen.geometryChanged.connect(self.screen_changed)
        screen.logicalDotsPerInchChanged.connect(self.screen_changed)
        self.screen_changed()

    def screen_changed(self, *args):
        if self.capturing and (self.capture_timer.isActive() or self.overlays):
            self.cancel_capture()
            self.tray.showMessage('Захват отменён', 'Изменилась конфигурация мониторов. Повторите захват.')

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
            path = save_png(image, self.folder)
            self.tray.showMessage('Снимок сохранён', str(path), QSystemTrayIcon.MessageIcon.Information, 2500)
            return path
        except Exception as exc:
            logging.exception('Screenshot save failed')
            QMessageBox.warning(parent or self.panel, 'Не удалось сохранить', str(exc))
            return None

    def capture(self, full=False):
        if self.capturing or self.activeModalWidget() is not None:
            return
        self.capturing = True
        self.target_screen = self.screenAt(QCursor.pos()) or self.primaryScreen()
        self.hidden = [w for w in [self.panel, *self.editors] if w.isVisible()]
        for w in self.hidden:
            w.hide()
        self.capture_full = full
        self.capture_timer.start(250)

    def take_capture(self, full):
        if not self.capturing:
            return
        try:
            if self.target_screen not in self.screens():
                raise RuntimeError('Монитор отключён. Повторите захват.')
            screens = [self.target_screen] if full else self.screens()
            if not screens:
                raise RuntimeError('Нет доступных мониторов.')
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
            logging.exception('Screen capture failed')
            self.cancel_capture()
            QMessageBox.warning(self.panel, 'Ошибка захвата', str(exc))

    def cancel_capture(self):
        self.capture_timer.stop()
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
        dialog = CaptureDialog(image, to_pixmap(image), self.panel)
        try:
            dialog.exec()
            chosen = dialog.choice
        finally:
            self.capturing = False
            dialog.deleteLater()
        if chosen == 'save':
            if not self.save_image(image):
                self.open_editor(image)
        elif chosen == 'edit':
            self.open_editor(image)
        elif chosen == 'copy':
            self.clipboard().setPixmap(to_pixmap(image))

    def open_editor(self, image, source_path=None):
        editor = Editor(image, self, source_path=source_path)
        self.editors.append(editor)
        editor.show()
        editor.activateWindow()
        return editor

    def exit_app(self):
        for editor in list(self.editors):
            if not editor.close():
                return False
        self.settings.setValue('panel/geometry', self.panel.saveGeometry())
        self.settings.sync()
        self.quit()
        return True


def main():
    app = ShotApp(initialize=False)
    # Windows named pipes allow multiple listeners; use a per-user process lock too.
    folder = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    folder.mkdir(parents=True, exist_ok=True)
    app.instance_lock = QLockFile(str(folder / 'instance.lock'))
    app.instance_lock.setStaleLockTime(0)
    probe = QLocalSocket()
    if not app.instance_lock.tryLock(1500):
        probe.connectToServer('LocalShot.Desktop.v1')
        if probe.waitForConnected(1500):
            probe.disconnectFromServer()
            return 0
        raise RuntimeError('Программа уже запускается или не отвечает. Повторите запуск через несколько секунд.')
    app.aboutToQuit.connect(app.instance_lock.unlock)
    app.server = QLocalServer()
    if sys.platform != 'win32':
        QLocalServer.removeServer('LocalShot.Desktop.v1')
    if not app.server.listen('LocalShot.Desktop.v1'):
        raise RuntimeError('Не удалось запустить локальный сервер: ' + app.server.errorString())
    app.initialize_ui()
    app.initialize_autostart()
    if '--autostart' in sys.argv and QSystemTrayIcon.isSystemTrayAvailable():
        app.panel.hide()
    def activate():
        socket = app.server.nextPendingConnection()
        if socket:
            socket.close()
            socket.deleteLater()
        app.show_panel()
    app.server.newConnection.connect(activate)
    if app.server.hasPendingConnections():
        activate()
    return app.exec()


if __name__ == '__main__':
    from launcher import run
    sys.exit(run())
