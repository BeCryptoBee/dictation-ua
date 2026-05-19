"""
Модуль вставки тексту в активний додаток.

Режими:
- append() — дописати нові слова в кінець поля (без select-all)
- replace_all() — Ctrl+A → paste (для фінальної заміни Whisper)
"""

import ctypes
import logging
import time
from ctypes import wintypes

import pyperclip

logger = logging.getLogger(__name__)


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]

# Затримка між copy в clipboard і натисканням Ctrl+V — час щоб OS оновила буфер.
PASTE_DELAY_SEC = 0.10
# Затримка ПІСЛЯ Ctrl+V перед відновленням clipboard — час щоб цільовий
# додаток (особливо Telegram Desktop/Qt) встиг прочитати буфер.
PASTE_HOLD_SEC = 0.25


def _window_title(hwnd: int) -> str:
    if not hwnd:
        return "(none)"
    try:
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception:
        return "(error)"


def _window_class(hwnd: int) -> str:
    if not hwnd:
        return "(none)"
    try:
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
        return buf.value
    except Exception:
        return "(error)"


def _get_active_window_info() -> tuple[int, str]:
    """Повернути (HWND, title) активного (foreground) вікна."""
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return 0, "(none)"
        return int(hwnd), _window_title(hwnd)
    except Exception as e:
        return 0, f"(error: {e})"


def _get_focused_control_info() -> tuple[int, str]:
    """
    HWND і class name контролу, що має клавіатурний фокус всередині foreground-вікна.
    Це важливо: Ctrl+V іде у цей focused control, а не у foreground window.
    Якщо фокус = 0 — клавіатура «нікуди не націлена», вставка не спрацює.
    """
    try:
        fore = ctypes.windll.user32.GetForegroundWindow()
        if not fore:
            return 0, "(no fg)"
        tid = ctypes.windll.user32.GetWindowThreadProcessId(fore, None)
        info = _GUITHREADINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetGUIThreadInfo(tid, ctypes.byref(info)):
            return 0, "(no info)"
        focus_hwnd = info.hwndFocus or 0
        if not focus_hwnd:
            return 0, "(no focus)"
        return int(focus_hwnd), _window_class(focus_hwnd)
    except Exception as e:
        return 0, f"(error: {e})"


def _wait_clipboard(expected: str, timeout: float = 0.5) -> bool:
    """Чекати поки clipboard буде відповідати expected. True якщо встигли."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if pyperclip.paste() == expected:
                return True
        except Exception:
            pass
        time.sleep(0.02)
    return False


# Windows message для команди «paste» — Qt edit-віджети обробляють її напряму.
_WM_PASTE = 0x0302


def _send_wm_paste(hwnd: int) -> int:
    """SendMessage(WM_PASTE) до HWND. Повертає return code (для діагностики)."""
    if not hwnd:
        return -1
    try:
        return int(ctypes.windll.user32.SendMessageW(hwnd, _WM_PASTE, 0, 0))
    except Exception as e:
        logger.warning("WM_PASTE помилка: %s", e)
        return -2


def _set_foreground(hwnd: int) -> bool:
    """Спробувати повернути фокус на HWND (на випадок якщо його зірвали)."""
    if not hwnd:
        return False
    try:
        return bool(ctypes.windll.user32.SetForegroundWindow(hwnd))
    except Exception:
        return False


# Низькорівнева емуляція клавіш через scan-коди — обходить активну розкладку.
# pyautogui.hotkey передає scan_code=0, і Windows підставляє код за поточною
# розкладкою. На UA розкладці VK_V → scan-код 'м'. Qt/Chromium-додатки
# (Telegram, Chrome) дивляться на scan-code і отримують Ctrl+М замість Ctrl+V.
# З KEYEVENTF_SCANCODE ми посилаємо фізичний код клавіші — розкладка ігнорується.
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_SCANCODE = 0x0008
_SC_CTRL = 0x1D  # 29
_SC_A = 0x1E     # 30
_SC_V = 0x2F     # 47


def _kbd_down(scan: int) -> None:
    ctypes.windll.user32.keybd_event(0, scan, _KEYEVENTF_SCANCODE, 0)


def _kbd_up(scan: int) -> None:
    ctypes.windll.user32.keybd_event(0, scan, _KEYEVENTF_SCANCODE | _KEYEVENTF_KEYUP, 0)


def _send_ctrl_combo(letter_scan: int) -> None:
    """Натиснути Ctrl+<scan-код> на фізичних позиціях клавіш (layout-independent)."""
    _kbd_down(_SC_CTRL)
    time.sleep(0.005)
    _kbd_down(letter_scan)
    time.sleep(0.015)
    _kbd_up(letter_scan)
    time.sleep(0.005)
    _kbd_up(_SC_CTRL)


def _do_paste(focus_hwnd: int, foreground_hwnd: int) -> str:
    """
    Вставити з clipboard у відповідний таргет. Повертає шлях, який вибрано
    (для логу): 'wm_paste' або 'ctrl_v'.

    Логіка:
    - Якщо focus_hwnd це дочірній HWND (≠ foreground) — це нативний edit-control
      (RichEdit, Edit і т.д.). Для них WM_PASTE — найнадійніше.
    - Інакше (Qt/Chromium — Telegram, Chrome, Discord) — клавіатурна емуляція
      Ctrl+V. Перед цим повертаємо фокус на foreground через SetForegroundWindow,
      щоб виключити втрату фокусу через звукове сповіщення/tray-update.
    """
    if focus_hwnd and focus_hwnd != foreground_hwnd:
        ret = _send_wm_paste(focus_hwnd)
        logger.info("Paste via WM_PASTE → focus=%s ret=%s", focus_hwnd, ret)
        return "wm_paste"
    _send_ctrl_combo(_SC_V)
    logger.info("Paste via Ctrl+V scancode → foreground=%s", foreground_hwnd)
    return "ctrl_v_sc"


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
        """Відновити clipboard після того як цільовий додаток встиг прочитати буфер."""
        time.sleep(PASTE_HOLD_SEC)
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

        hwnd, title = _get_active_window_info()
        focus_hwnd, focus_cls = _get_focused_control_info()
        logger.info(
            "Append target: foreground=%s '%s' | focus=%s class='%s'",
            hwnd, title, focus_hwnd, focus_cls,
        )

        try:
            self._save_clipboard()
            pyperclip.copy(new_text)
            if not _wait_clipboard(new_text, timeout=0.5):
                logger.warning("Clipboard не оновився очікуваним текстом")
            time.sleep(PASTE_DELAY_SEC)
            method = _do_paste(focus_hwnd, hwnd)
            self._restore_clipboard()
            logger.info("Дописано (%s): '%s'", method, new_text)
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

        hwnd, title = _get_active_window_info()
        focus_hwnd, focus_cls = _get_focused_control_info()
        logger.info(
            "Replace target: foreground=%s '%s' | focus=%s class='%s'",
            hwnd, title, focus_hwnd, focus_cls,
        )

        try:
            self._save_clipboard()
            pyperclip.copy(text)
            if not _wait_clipboard(text, timeout=0.5):
                logger.warning("Clipboard не оновився очікуваним текстом")
            time.sleep(PASTE_DELAY_SEC)
            # Ctrl+A через scan-код (як і Ctrl+V) — інакше на UA розкладці
            # йде як Ctrl+Ф, і виділення не спрацьовує.
            _send_ctrl_combo(_SC_A)
            time.sleep(PASTE_DELAY_SEC)
            method = _do_paste(focus_hwnd, hwnd)
            self._restore_clipboard()
            logger.info("Замінено весь текст (%s, %d символів)", method, len(text))
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
