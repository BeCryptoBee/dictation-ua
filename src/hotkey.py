"""
Модуль глобальних хоткеїв.

Реєстрація через scan-коди (фізичні позиції клавіш) — незалежно від
розкладки клавіатури (укр/англ/тощо). Це дозволяє використовувати клавіші
типу `,` `.` `/` навіть коли активна розкладка перебиває їх на `б` `ю` `.`.
"""

import logging
import threading
from typing import Callable

import keyboard

logger = logging.getLogger(__name__)

DEFAULT_HOTKEY = "ctrl+shift+m"

# Мапа Windows scan-кодів → стандартні (англійські) імена клавіш.
# Scan-код = фізична позиція клавіші, не залежить від розкладки.
SCAN_CODE_TO_KEY: dict[int, str] = {
    2: "1", 3: "2", 4: "3", 5: "4", 6: "5", 7: "6", 8: "7", 9: "8", 10: "9", 11: "0",
    12: "-", 13: "=",
    16: "q", 17: "w", 18: "e", 19: "r", 20: "t", 21: "y", 22: "u", 23: "i", 24: "o", 25: "p",
    26: "[", 27: "]",
    30: "a", 31: "s", 32: "d", 33: "f", 34: "g", 35: "h", 36: "j", 37: "k", 38: "l",
    39: ";", 40: "'", 41: "`", 43: "\\",
    44: "z", 45: "x", 46: "c", 47: "v", 48: "b", 49: "n", 50: "m",
    51: ",", 52: ".", 53: "/",
    57: "space", 28: "enter", 15: "tab", 14: "backspace", 1: "esc",
    59: "f1", 60: "f2", 61: "f3", 62: "f4", 63: "f5", 64: "f6",
    65: "f7", 66: "f8", 67: "f9", 68: "f10", 87: "f11", 88: "f12",
}

# Зворотна мапа + аліаси (для парсингу з config.json та діалогу).
KEY_TO_SCAN_CODE: dict[str, int] = {v: k for k, v in SCAN_CODE_TO_KEY.items()}
KEY_TO_SCAN_CODE.update({
    "comma": 51, "period": 52, "dot": 52, "slash": 53,
    "minus": 12, "equal": 13, "semicolon": 39, "apostrophe": 40,
    "backquote": 41, "backslash": 43,
    "leftbracket": 26, "rightbracket": 27,
    "win": 91,
})

_MODIFIERS = {"ctrl", "shift", "alt", "windows"}


def _normalize_modifier(name: str) -> str | None:
    """Повернути канонічну назву модифікатора або None якщо це не модифікатор."""
    n = name.lower().strip()
    for prefix in ("left ", "right "):
        if n.startswith(prefix):
            n = n[len(prefix):]
    if n == "win":
        n = "windows"
    return n if n in _MODIFIERS else None


def _parse_hotkey(hotkey: str) -> tuple[set[str], int]:
    """
    Розпарсити рядок хоткея (напр. "ctrl+shift+,") у (модифікатори, scan-код).
    """
    parts = [p.strip().lower() for p in hotkey.split("+")]
    modifiers: set[str] = set()
    main_sc: int | None = None
    for p in parts:
        if not p:
            continue
        mod = _normalize_modifier(p)
        if mod is not None:
            modifiers.add(mod)
            continue
        sc = KEY_TO_SCAN_CODE.get(p)
        if sc is None:
            raise ValueError(f"Невідома клавіша в хоткеї: '{p}'")
        if main_sc is not None:
            raise ValueError(f"Кілька основних клавіш у хоткеї: '{hotkey}'")
        main_sc = sc
    if main_sc is None:
        raise ValueError(f"Хоткей без основної клавіші: '{hotkey}'")
    if not modifiers:
        logger.warning(
            "Хоткей '%s' без модифікаторів — може ловити звичайні натискання",
            hotkey,
        )
    return modifiers, main_sc


class _ScanHotkey:
    """Слухач одного хоткея через keyboard.hook + matching по scan-кодах."""

    def __init__(
        self,
        modifiers: set[str],
        main_scan_code: int,
        callback: Callable,
        display: str,
    ):
        self._modifiers = modifiers
        self._main_sc = main_scan_code
        self._callback = callback
        self._display = display
        self._pressed_mods: set[str] = set()
        self._fired = False
        self._hook = None

    def install(self) -> None:
        self._hook = keyboard.hook(self._on_event)

    def uninstall(self) -> None:
        if self._hook is not None:
            try:
                keyboard.unhook(self._hook)
            except (KeyError, ValueError) as e:
                logger.debug("unhook повернув помилку (ігнорую): %s", e)
            self._hook = None

    def _on_event(self, e) -> None:
        try:
            self._handle(e)
        except Exception as ex:
            logger.exception("Помилка в hotkey hook: %s", ex)

    def _handle(self, e) -> None:
        name = e.name if e.name else ""
        mod = _normalize_modifier(name)

        if e.event_type == "down":
            if mod is not None:
                self._pressed_mods.add(mod)
                return
            if e.scan_code == self._main_sc:
                if self._modifiers.issubset(self._pressed_mods) and not self._fired:
                    self._fired = True
                    logger.debug("Хоткей '%s' спрацював", self._display)
                    threading.Thread(target=self._callback, daemon=True).start()
        elif e.event_type == "up":
            if mod is not None:
                self._pressed_mods.discard(mod)
                return
            if e.scan_code == self._main_sc:
                self._fired = False


class HotkeyManager:
    """Менеджер глобальних хоткеїв через scan-коди."""

    def __init__(self):
        self._active: _ScanHotkey | None = None
        self._active_str: str | None = None

    def register(self, hotkey: str, callback: Callable) -> None:
        """Зареєструвати глобальний хоткей. Замінює попередній якщо є."""
        modifiers, main_sc = _parse_hotkey(hotkey)
        if self._active is not None:
            self._active.uninstall()
        h = _ScanHotkey(modifiers, main_sc, callback, hotkey)
        h.install()
        self._active = h
        self._active_str = hotkey
        logger.info(
            "Хоткей '%s' зареєстровано (mods=%s, scan_code=%d)",
            hotkey, sorted(modifiers), main_sc,
        )

    def unregister(self) -> None:
        """Зняти активний хоткей."""
        if self._active is not None:
            self._active.uninstall()
            logger.info("Хоткей '%s' знято", self._active_str)
            self._active = None
            self._active_str = None

    def unregister_all(self) -> None:
        self.unregister()
