from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QFormLayout, QKeySequenceEdit, QDialogButtonBox)
from hotkeys import DEFAULTS, LABELS


class HotkeyDialog(QDialog):
    def __init__(self, app):
        super().__init__(app.panel)
        self.app = app
        self.setWindowTitle('Горячие клавиши')
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        help_text = QLabel('Нажмите новое сочетание в поле. Ctrl/Alt + латинская буква или цифра;\n'
                           'также доступны F1–F24, кроме F12. Очистите поле для отключения.')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        form = QFormLayout()
        layout.addLayout(form)
        self.fields = {}
        for action, title in LABELS.items():
            field = QKeySequenceEdit(QKeySequence(app.hotkeys.bindings[action]))
            field.setMaximumSequenceLength(1)
            field.setClearButtonEnabled(True)
            form.addRow(title, field)
            self.fields[action] = field
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet('color: #dc2626')
        layout.addWidget(self.error)
        reset = QPushButton('По умолчанию')
        reset.clicked.connect(self.reset)
        layout.addWidget(reset)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('Сохранить')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Отмена')
        buttons.accepted.connect(self.apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def reset(self):
        for action, field in self.fields.items():
            field.setKeySequence(QKeySequence(DEFAULTS[action]))

    def apply(self):
        try:
            self.app.hotkeys.configure({action: field.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
                                        for action, field in self.fields.items()})
        except ValueError as error:
            self.error.setText(str(error))
            return
        self.app.update_hotkey_labels()
        self.accept()


class CaptureDialog(QDialog):
    def __init__(self, image, pixmap, parent=None):
        super().__init__(parent)
        self.choice = None
        self.setWindowTitle('Снимок готов')
        layout = QVBoxLayout(self)
        title = QLabel(f'Снимок {image.width} × {image.height}')
        layout.addWidget(title)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setPixmap(pixmap.scaled(640, 340, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(self.preview)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.buttons = {}
        for action, title in [('save', 'Сохранить'), ('edit', 'Редактировать'), ('copy', 'Копировать'), ('cancel', 'Отмена')]:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, action=action: self.select(action))
            row.addWidget(button)
            self.buttons[action] = button
        self.buttons['edit'].setDefault(True)

    def select(self, action):
        self.choice = action
        self.accept()
