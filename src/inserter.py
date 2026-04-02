"""
Модуль вставки тексту в активний додаток.

Режими:
- append() — дописати нові слова в кінець поля (без select-all)
- replace_all() — Ctrl+A → paste (для фінальної заміни Whisper)
"""

import logging
import time

import pyperclip
import pyautogui

logger = logging.getLogger(__name__)

PASTE_DELAY_SEC = 0.05


class TextInserter:
    """Вставляє текст в активне вікно."""

    def __init__(self):
        self._old_clipboard = ""

    def _save_clipboard(self) -> None:
        """Зберегти clipboard перед операцією."""
        try:
            self._old_clipboard = pyperclip.paste()
        except Exception:
            self._old_clipboard = ""

    def _restore_clipboard(self) -> None:
        """Відновити clipboard після операції."""
        time.sleep(0.05)
        try:
            pyperclip.copy(self._old_clipboard)
        except Exception:
            pass

    def append(self, new_text: str) -> bool:
        """
        Дописати текст в кінець поля вводу.
        Просто paste без select-all — курсор залишається в кінці.

        Args:
            new_text: Нові слова для додавання.
        """
        if not new_text:
            return False

        try:
            self._save_clipboard()
            pyperclip.copy(new_text)
            time.sleep(PASTE_DELAY_SEC)
            pyautogui.hotkey("ctrl", "v")
            self._restore_clipboard()
            logger.info("Дописано: '%s'", new_text)
            return True
        except Exception as e:
            logger.warning("Append помилка: %s", e)
            return False

    def replace_all(self, text: str) -> bool:
        """
        Замінити весь текст у полі вводу (Ctrl+A → paste).
        Використовується для фінальної Whisper заміни.
        """
        if not text or not text.strip():
            return False

        try:
            self._save_clipboard()
            pyperclip.copy(text)
            time.sleep(PASTE_DELAY_SEC)
            pyautogui.hotkey("ctrl", "a")
            time.sleep(PASTE_DELAY_SEC)
            pyautogui.hotkey("ctrl", "v")
            self._restore_clipboard()
            logger.info("Замінено весь текст (%d символів)", len(text))
            return True
        except Exception as e:
            logger.error("Replace помилка: %s", e)
            return False

    def copy_only(self, text: str) -> bool:
        """Тільки скопіювати текст в clipboard."""
        try:
            pyperclip.copy(text)
            logger.info("Скопійовано в clipboard (%d символів)", len(text))
            return True
        except Exception as e:
            logger.error("Помилка копіювання: %s", e)
            return False
