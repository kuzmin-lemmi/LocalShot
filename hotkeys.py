"""Global shortcuts with transactional replacement: conflicts preserve old bindings."""
import ctypes
import sys
from PySide6.QtCore import QAbstractNativeEventFilter, Qt
from PySide6.QtGui import QKeySequence

DEFAULTS = {1: 'Ctrl+Alt+A', 2: 'Ctrl+Alt+S', 3: 'Ctrl+Alt+O'}
LABELS = {1: 'Выделить область', 2: 'Весь текущий экран', 3: 'Открыть папку снимков'}


def parse_shortcut(text):
    if not text.strip():
        return '', None
    sequence = QKeySequence.fromString(text, QKeySequence.SequenceFormat.PortableText)
    if sequence.count() != 1:
        raise ValueError('Нужно одно сочетание клавиш, не последовательность.')
    combination = sequence[0]
    key = int(combination.key())
    mods = combination.keyboardModifiers()
    allowed = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier
    if mods & ~allowed:
        raise ValueError('Используйте Ctrl, Alt или Shift без клавиши Windows.')
    native_mods = (2 if mods & Qt.KeyboardModifier.ControlModifier else 0) | (1 if mods & Qt.KeyboardModifier.AltModifier else 0) | (4 if mods & Qt.KeyboardModifier.ShiftModifier else 0)
    if 65 <= key <= 90 or 48 <= key <= 57:
        if not native_mods & 3:
            raise ValueError('Для буквы или цифры добавьте Ctrl или Alt.')
        vk = key
    elif int(Qt.Key.Key_F1) <= key <= int(Qt.Key.Key_F24):
        vk = 0x70 + key - int(Qt.Key.Key_F1)
        if vk == 0x7B:
            raise ValueError('F12 зарезервирована Windows. Выберите другую клавишу.')
    else:
        raise ValueError('Выберите латинскую букву A–Z, цифру или F1–F24 (кроме F12).')
    return sequence.toString(QKeySequence.SequenceFormat.PortableText), (native_mods | 0x4000, vk)


class Hotkeys(QAbstractNativeEventFilter):
    def __init__(self, app, backend=None):
        super().__init__()
        self.app = app
        self.backend = backend if backend is not None else (ctypes.windll.user32 if sys.platform == 'win32' else False)
        self.registrations = {}
        self.id_actions = {}
        self.next_id = 100
        self.errors = []
        self.bindings = {}
        seen = set()
        for action, default in DEFAULTS.items():
            raw = app.settings.value(f'hotkeys/{action}', default)
            try:
                text, combo = parse_shortcut(str(raw))
                if combo and combo in seen:
                    raise ValueError('Сочетание повторяется в настройках.')
            except ValueError as error:
                text, combo = '', None
                self.errors.append(f'{LABELS[action]}: {error}')
            self.bindings[action] = text
            if combo:
                seen.add(combo)
                native_id = self.register(combo)
                if native_id is not None:
                    self.registrations[combo] = native_id
                    self.id_actions[native_id] = action
                else:
                    self.errors.append(f'{text} — занято другой программой')

    @property
    def ids(self):
        return list(self.id_actions)

    def register(self, combo):
        native_id = self.next_id
        self.next_id += 1
        if self.backend is False or self.backend.RegisterHotKey(None, native_id, *combo):
            return native_id
        return None

    def unregister(self, native_id):
        if self.backend is not False:
            self.backend.UnregisterHotKey(None, native_id)

    def configure(self, requested):
        parsed = {action: parse_shortcut(requested.get(action, '')) for action in DEFAULTS}
        combos = [combo for text, combo in parsed.values() if combo]
        if len(combos) != len(set(combos)):
            raise ValueError('Для разных действий нужны разные сочетания.')
        added = {}
        for combo in combos:
            if combo in self.registrations:
                continue
            native_id = self.register(combo)
            if native_id is None:
                for ident in added.values():
                    self.unregister(ident)
                label = next(text for text, value in parsed.values() if value == combo)
                raise ValueError(f'{label} занято другой программой. Старые сочетания сохранены.')
            added[combo] = native_id
        for combo, ident in self.registrations.items():
            if combo not in combos:
                self.unregister(ident)
        self.registrations = {combo: {**self.registrations, **added}[combo] for combo in combos}
        self.id_actions = {self.registrations[combo]: action for action, (text, combo) in parsed.items() if combo}
        self.bindings = {action: text for action, (text, combo) in parsed.items()}
        self.errors = []
        for action, text in self.bindings.items():
            self.app.settings.setValue(f'hotkeys/{action}', text)
        self.app.settings.sync()

    def nativeEventFilter(self, event_type, message):
        if sys.platform == 'win32' and self.backend is not False:
            from ctypes.wintypes import MSG
            msg = MSG.from_address(int(message))
            if msg.message == 0x0312 and int(msg.wParam) in self.id_actions:
                if self.app.activeModalWidget() is None:
                    action = self.id_actions[int(msg.wParam)]
                    if action == 3:
                        self.app.open_folder()
                    else:
                        self.app.capture(action == 2)
                return True, 0
        return False, 0

    def cleanup(self):
        for ident in self.registrations.values():
            self.unregister(ident)
        self.registrations.clear()
        self.id_actions.clear()
