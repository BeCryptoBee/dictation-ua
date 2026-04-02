"""
Модуль глобальних хоткеїв.
Використовує бібліотеку keyboard для реєстрації системних гарячих клавіш.
"""

import logging
from typing import Callable

import keyboard

logger = logging.getLogger(__name__)

DEFAULT_HOTKEY = "ctrl+shift+m"


class HotkeyManager:
    """Менеджер глобальних хоткеїв Windows."""

    def __init__(self):
        self._registered: dict[str, Callable] = {}

    def register(self, hotkey: str, callback: Callable) -> None:
        """
        Зареєструвати глобальний хоткей.

        Args:
            hotkey: Комбінація клавіш (напр. "ctrl+shift+space").
            callback: Функція, яка викликається при натисканні.
        """
        if hotkey in self._registered:
            logger.warning("Хоткей '%s' вже зареєстрований, перезаписую", hotkey)
            keyboard.remove_hotkey(hotkey)

        keyboard.add_hotkey(hotkey, callback, suppress=False)
        self._registered[hotkey] = callback
        logger.info("Хоткей '%s' зареєстровано", hotkey)

    def unregister(self, hotkey: str | None = None) -> None:
        """
        Зняти реєстрацію хоткея або всіх хоткеїв.

        Args:
            hotkey: Конкретний хоткей або None для зняття всіх.
        """
        if hotkey is not None:
            if hotkey in self._registered:
                keyboard.remove_hotkey(hotkey)
                del self._registered[hotkey]
                logger.info("Хоткей '%s' знято", hotkey)
        else:
            for hk in list(self._registered.keys()):
                keyboard.remove_hotkey(hk)
            self._registered.clear()
            logger.info("Всі хоткеї знято")

    def unregister_all(self) -> None:
        """Зняти всі зареєстровані хоткеї."""
        self.unregister(None)
