"""
System tray UI для застосунку "Диктовка UA".
Іконка-мікрофон у треї змінює колір залежно від стану.
Без вікна — мінімальний візуальний слід.
"""

import logging
import threading
from enum import Enum
from typing import Callable, Optional

import pystray
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)


class AppState(Enum):
    """Стани застосунку для відображення у GUI."""
    LOADING = "Завантаження моделі..."
    READY = "Готово (Ctrl+Shift+M)"
    LISTENING = "Слухаю..."
    TRANSCRIBING = "Обробка..."
    ERROR = "Помилка"


# RGB кольори для кожного стану
STATE_COLORS = {
    AppState.LOADING: (255, 165, 0),       # Помаранчевий
    AppState.READY: (100, 180, 255),        # Спокійний блакитний
    AppState.LISTENING: (220, 50, 50),      # Червоний (запис)
    AppState.TRANSCRIBING: (33, 150, 243),  # Синій
    AppState.ERROR: (255, 87, 34),          # Темно-червоний
}


def _create_mic_icon(bg_color: tuple, size: int = 64) -> Image.Image:
    """Створити іконку мікрофона на кольоровому фоні."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Фон — коло
    p = size // 32 or 1
    draw.ellipse([p, p, size - p, size - p], fill=bg_color)

    white = (255, 255, 255)
    lw = max(2, size // 18)
    cx = size // 2

    # Тіло мікрофона (овал)
    mw = int(size * 0.17)
    mt = int(size * 0.20)
    mb = int(size * 0.52)
    draw.ellipse([cx - mw, mt, cx + mw, mb], fill=white)

    # U-тримач (дуга під мікрофоном)
    uw = int(size * 0.25)
    ut = int(size * 0.36)
    ub = int(size * 0.66)
    draw.arc([cx - uw, ut, cx + uw, ub], start=0, end=180, fill=white, width=lw)

    # Вертикальна ніжка
    st = int(size * 0.66)
    sb = int(size * 0.74)
    draw.line([cx, st, cx, sb], fill=white, width=lw)

    # Горизонтальна основа
    bw = int(size * 0.13)
    draw.line([cx - bw, sb, cx + bw, sb], fill=white, width=lw)

    return img


def _create_circle_icon(color: tuple, size: int = 64) -> Image.Image:
    """Створити просту кольорову круглу іконку (для службових станів)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, size - 4, size - 4], fill=color)
    return img


def _icon_for_state(state: AppState) -> Image.Image:
    """Повернути відповідну іконку для стану."""
    color = STATE_COLORS.get(state, (255, 255, 255))
    if state in (AppState.READY, AppState.LISTENING):
        return _create_mic_icon(color)
    return _create_circle_icon(color)


class TrayUI:
    """System tray іконка зі статусом диктовки."""

    def __init__(self):
        self._state = AppState.LOADING
        self._text = ""
        self._close_callback: Optional[Callable] = None
        self._icon: Optional[pystray.Icon] = None
        self._stopped = threading.Event()

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(
                lambda _: f"Диктовка UA — {self._state.value}",
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Вихід", self._on_exit),
        )

    def set_state(self, state: AppState, error_msg: str = "") -> None:
        """Оновити стан (іконка + tooltip)."""
        self._state = state

        tooltip = state.value
        if state == AppState.ERROR and error_msg:
            tooltip = f"Помилка: {error_msg}"

        if self._icon is not None:
            self._icon.icon = _icon_for_state(state)
            self._icon.title = f"Диктовка UA — {tooltip}"

        logger.debug("UI стан: %s", tooltip)

    def set_text(self, text: str) -> None:
        self._text = text

    def set_final_text(self, text: str) -> None:
        self._text = text

    def append_text(self, text: str) -> None:
        self._text += text

    def set_preview_text(self, text: str) -> None:
        self._text = text

    def set_close_callback(self, callback: Callable) -> None:
        self._close_callback = callback

    def stop(self) -> None:
        """Зупинити tray іконку (можна викликати з будь-якого потоку)."""
        self._stopped.set()
        if self._icon is not None:
            self._icon.stop()

    def _on_exit(self, icon, item) -> None:
        if self._close_callback:
            self._close_callback()
        self._stopped.set()
        icon.stop()

    def run(self) -> None:
        """Запустити tray іконку (блокуючий виклик, реагує на Ctrl+C)."""
        self._icon = pystray.Icon(
            "dictation_ua",
            _icon_for_state(AppState.LOADING),
            "Диктовка UA — Завантаження...",
            menu=self._build_menu(),
        )
        threading.Thread(target=self._icon.run, daemon=True).start()
        try:
            while not self._stopped.is_set():
                self._stopped.wait(timeout=1.0)
        except KeyboardInterrupt:
            if self._close_callback:
                self._close_callback()
            self._icon.stop()

    @property
    def root(self):
        return None
