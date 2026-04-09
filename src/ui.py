"""
System tray UI для застосунку "Диктовка UA".
Іконка у треї змінює колір залежно від стану.
Без вікна — мінімальний візуальний слід.
"""

import logging
import threading
import tkinter as tk
from enum import Enum
from typing import Callable, Optional

import pystray
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)


class AppState(Enum):
    """Стани застосунку для відображення у GUI."""
    LOADING = "Завантаження моделі..."
    READY = "Готово"
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


def _create_dot_ring_icon(color: tuple, size: int = 64) -> Image.Image:
    """Створити іконку: точка з кільцем (macOS стиль)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx = size // 2
    cy = size // 2
    ring_w = max(3, size // 16)

    # Зовнішнє кільце
    ring_r = int(size * 0.375)
    draw.ellipse(
        [cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
        outline=color, width=ring_w,
    )

    # Внутрішня заповнена точка
    dot_r = int(size * 0.1875)
    draw.ellipse(
        [cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
        fill=color,
    )

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
        return _create_dot_ring_icon(color)
    return _create_circle_icon(color)


class TrayUI:
    """System tray іконка зі статусом диктовки."""

    def __init__(self, hotkey: str = "ctrl+shift+m"):
        self._state = AppState.LOADING
        self._text = ""
        self._hotkey = hotkey
        self._close_callback: Optional[Callable] = None
        self._hotkey_change_callback: Optional[Callable] = None
        self._icon: Optional[pystray.Icon] = None
        self._stopped = threading.Event()

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(
                lambda _: f"Status: {self._state.value}",
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda _: f"Hotkey: {self._hotkey.upper()}",
                self._on_change_hotkey,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._on_exit),
        )

    def set_hotkey_change_callback(self, callback: Callable) -> None:
        """Callback(new_hotkey: str) — викликається при зміні хоткея."""
        self._hotkey_change_callback = callback

    def _on_change_hotkey(self, icon, item) -> None:
        """Відкрити діалог для зміни хоткея."""
        threading.Thread(target=self._show_hotkey_dialog, daemon=True).start()

    def _show_hotkey_dialog(self) -> None:
        """Діалог захоплення хоткея — живе відстеження клавіш."""
        import keyboard as kb

        root = tk.Tk()
        root.title("Dictation UA")
        root.geometry("340x150")
        root.resizable(False, False)
        root.attributes("-topmost", True)
        root.configure(bg="#1e1e2e")

        MODIFIERS = {"ctrl", "alt", "shift", "right ctrl", "right alt",
                      "right shift", "left ctrl", "left alt", "left shift",
                      "left windows", "right windows"}

        state = {"pressed": set(), "best": "", "done": False}

        tk.Label(
            root, text="Press your hotkey combination",
            font=("Segoe UI", 13, "bold"), fg="#cdd6f4", bg="#1e1e2e",
        ).pack(pady=(18, 4))

        hotkey_label = tk.Label(
            root, text=self._hotkey.upper(),
            font=("Segoe UI", 18, "bold"), fg="#89b4fa", bg="#1e1e2e",
        )
        hotkey_label.pack(pady=8)

        hint_label = tk.Label(
            root, text="Hold modifiers + press a key",
            font=("Segoe UI", 9), fg="#6c7086", bg="#1e1e2e",
        )
        hint_label.pack()

        def _normalize(name):
            """Прибрати left/right префікси для фінального хоткея."""
            for prefix in ("left ", "right "):
                if name.startswith(prefix):
                    return name[len(prefix):]
            return name

        def _format_combo(keys):
            """Сформувати рядок хоткея зі стабільним порядком."""
            mods = []
            regular = []
            for k in keys:
                n = _normalize(k)
                if n in ("ctrl", "alt", "shift", "windows"):
                    if n not in mods:
                        mods.append(n)
                else:
                    regular.append(n)
            order = ["ctrl", "alt", "shift", "windows"]
            sorted_mods = [m for m in order if m in mods]
            return "+".join(sorted_mods + regular)

        def _apply(new_hotkey):
            if state["done"]:
                return
            state["done"] = True
            # Зняти тільки наш хук, не чіпати хоткеї диктовки
            if state.get("hook"):
                try:
                    kb.unhook(state["hook"])
                except Exception:
                    pass
            if new_hotkey and new_hotkey != self._hotkey:
                self._hotkey = new_hotkey
                if self._hotkey_change_callback:
                    self._hotkey_change_callback(new_hotkey)
            try:
                root.destroy()
            except Exception:
                pass

        def _on_key(event):
            if state["done"]:
                return
            name = event.name.lower() if event.name else ""
            if not name:
                return

            if event.event_type == "down":
                state["pressed"].add(name)

                # Показати поточні натиснуті клавіші
                combo = _format_combo(state["pressed"])
                has_mod = any(_normalize(k) in ("ctrl", "alt", "shift", "windows")
                             for k in state["pressed"])
                has_key = any(_normalize(k) not in ("ctrl", "alt", "shift", "windows")
                             for k in state["pressed"])

                if has_mod and has_key:
                    # Повна комбінація — зберегти
                    state["best"] = combo
                    root.after(0, lambda c=combo: hotkey_label.config(
                        text=c.upper(), fg="#a6e3a1"))
                    root.after(0, lambda: hint_label.config(
                        text="Saved! Closing...", fg="#a6e3a1"))
                    root.after(800, lambda c=combo: _apply(c))
                elif has_mod:
                    # Тільки модифікатори — показати жовтим
                    root.after(0, lambda c=combo: hotkey_label.config(
                        text=(c + "+...").upper(), fg="#f9e2af"))

            elif event.event_type == "up":
                state["pressed"].discard(name)

        state["hook"] = kb.hook(_on_key)

        def _on_close():
            state["done"] = True
            if state.get("hook"):
                try:
                    kb.unhook(state["hook"])
                except Exception:
                    pass
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", _on_close)
        root.focus_force()
        root.mainloop()

    def set_state(self, state: AppState, error_msg: str = "") -> None:
        """Оновити стан (іконка + tooltip)."""
        self._state = state

        tooltip = state.value
        if state == AppState.ERROR and error_msg:
            tooltip = f"Помилка: {error_msg}"

        if self._icon is not None:
            self._icon.icon = _icon_for_state(state)
            self._icon.title = f"Диктовка UA — {tooltip}"
            # Оновити меню щоб відобразити новий стан
            self._icon.menu = self._build_menu()

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
