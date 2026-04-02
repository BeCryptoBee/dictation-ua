"""
Головний модуль застосунку "Диктовка UA".

Архітектура: Whisper large-v3-turbo на GPU, chunked live + system tray.
- Під час розмови кожні ~3-5 сек бере нове аудіо і транскрибує
- Результат одразу дописується в поле вводу
- При зупинці — текст вже є, нічого чекати не треба
- UI — іконка в system tray, без вікна
"""

import logging
import re
import signal
import sys
import threading
import queue

from recorder import AudioRecorder
from transcriber import Transcriber
from hotkey import HotkeyManager, DEFAULT_HOTKEY
from inserter import TextInserter
from ui import TrayUI, AppState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Мінімальна тривалість нового аудіо для транскрипції (сек)
# 5 сек — менше розрізів слів на межах чанків
MIN_NEW_AUDIO_SEC = 5.0
# Пауза між перевірками нового аудіо (сек)
CHECK_INTERVAL_SEC = 0.3

# Відомі галюцинації Whisper для української мови
HALLUCINATION_PATTERNS = [
    r"^дякуємо\.?$",
    r"^дякую\.?$",
    r"^дякую за увагу\.?$",
    r"^дякуємо за увагу\.?$",
    r"^до побачення\.?$",
    r"^субтитри.*$",
    r"^підписуйтес[ья].*$",
    r"^продовження.*$",
    r"^редактор субтитрів.*$",
    r"^ви дивили(сь|ся).*$",
    r"^не забудьте підписатися.*$",
    r"^музика$",
    r"^оплески$",
    r"^\.+$",
]
_HALLUCINATION_RE = re.compile(
    "|".join(HALLUCINATION_PATTERNS), re.IGNORECASE
)


def _is_hallucination(text: str) -> bool:
    """Перевірити чи текст є відомою галюцинацією Whisper."""
    cleaned = text.strip().rstrip(".")
    if len(cleaned) < 2:
        return True
    return bool(_HALLUCINATION_RE.match(cleaned))


class DictationApp:
    """Головний клас застосунку диктовки."""

    def __init__(self, model_size: str = "large-v3-turbo", hotkey: str = DEFAULT_HOTKEY):
        self._model_size = model_size
        self._hotkey = hotkey

        self._recorder = AudioRecorder()
        self._transcriber = Transcriber(model_size=model_size)
        self._hotkey_mgr = HotkeyManager()
        self._inserter = TextInserter()
        self._ui = TrayUI()

        self._is_dictating = False
        self._lock = threading.Lock()

        # Стан тексту
        self._confirmed_text = ""  # Вже вставлений текст
        self._full_audio = None    # Повне аудіо для фінальної транскрипції

        # Черга для append
        self._append_queue: queue.Queue[str] = queue.Queue()
        self._append_stop = threading.Event()
        self._transcribe_stop = threading.Event()
        self._transcribe_done = threading.Event()

    def start(self) -> None:
        logger.info("=" * 50)
        logger.info("Диктовка UA — запуск")
        logger.info("Хоткей: %s", self._hotkey)
        logger.info("Модель: %s", self._model_size)
        logger.info("=" * 50)

        self._ui.set_close_callback(self._on_shutdown)
        self._ui.set_state(AppState.LOADING)

        def _sigint_handler(*_):
            logger.info("Ctrl+C — завершення...")
            self._on_shutdown()
            self._ui.stop()

        signal.signal(signal.SIGINT, _sigint_handler)

        threading.Thread(target=self._load_model, daemon=True).start()
        self._ui.run()

    def _load_model(self) -> None:
        try:
            self._ui.set_text(f"Завантаження Whisper {self._model_size}...\n")
            self._transcriber.load()

            self._hotkey_mgr.register(self._hotkey, self._on_hotkey)
            self._ui.set_state(AppState.READY)
            self._ui.set_text(
                "Модель завантажена.\n"
                f"Натисніть {self._hotkey.title()} для диктовки.\n"
            )
            logger.info("Модель готова")

        except Exception as e:
            logger.error("Помилка завантаження: %s", e, exc_info=True)
            self._ui.set_state(AppState.ERROR, str(e))
            self._ui.set_text(f"Помилка:\n{e}\n")

    def _on_hotkey(self) -> None:
        with self._lock:
            if self._is_dictating:
                self._stop_dictation()
            else:
                self._start_dictation()

    def _start_dictation(self) -> None:
        try:
            self._confirmed_text = ""

            while not self._append_queue.empty():
                try:
                    self._append_queue.get_nowait()
                except queue.Empty:
                    break

            # Запустити потоки
            self._append_stop.clear()
            self._transcribe_stop.clear()
            self._transcribe_done.clear()
            self._full_audio = None
            threading.Thread(target=self._append_loop, daemon=True).start()

            # Почати запис (без Vosk callback)
            self._recorder.start()
            self._is_dictating = True
            self._ui.set_state(AppState.LISTENING)
            self._ui.set_text("")

            # Запустити потік транскрипції
            threading.Thread(target=self._transcribe_loop, daemon=True).start()

            logger.info("Диктовка розпочата")

        except Exception as e:
            logger.error("Помилка початку: %s", e, exc_info=True)
            self._ui.set_state(AppState.ERROR, str(e))

    def _transcribe_chunk(self, audio) -> str:
        """Транскрибувати один шматок аудіо з фільтром галюцинацій."""
        segments, _ = self._transcriber._model.transcribe(
            audio,
            language="uk",
            beam_size=1,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=300),
            condition_on_previous_text=False,
            no_speech_threshold=0.5,
            hallucination_silence_threshold=1.0,
        )
        parts = []
        for segment in segments:
            text = segment.text.strip()
            if not text or segment.no_speech_prob >= 0.7:
                continue
            if _is_hallucination(text):
                logger.debug("Відфільтровано галюцинацію: '%s'", text)
                continue
            parts.append(text)
        return " ".join(parts).strip()

    def _append_chunk_text(self, chunk_text: str, duration: float) -> None:
        """Додати транскрибований шматок до результату."""
        append_text = (" " + chunk_text) if self._confirmed_text else chunk_text
        self._confirmed_text += append_text
        self._ui.set_final_text(self._confirmed_text)
        self._append_queue.put(append_text)
        logger.info("Chunk [%.1fs]: '%s'", duration, chunk_text)

    def _transcribe_loop(self) -> None:
        """
        Головний цикл: чекає MIN_NEW_AUDIO_SEC секунд, бере нове аудіо,
        транскрибує Whisper medium, дописує в поле.
        """
        import numpy as np

        logger.info("Transcribe-потік запущено")
        sample_rate = 16000
        min_samples = int(MIN_NEW_AUDIO_SEC * sample_rate)
        accumulated = np.array([], dtype=np.float32)

        while not self._transcribe_stop.is_set():
            if self._transcribe_stop.wait(timeout=CHECK_INTERVAL_SEC):
                break

            if not self._is_dictating:
                break

            # Накопичити нове аудіо
            new_audio = self._recorder.get_new_audio()
            if len(new_audio) > 0:
                accumulated = np.concatenate([accumulated, new_audio])

            # Транскрибувати тільки коли достатньо накопичилось
            if len(accumulated) < min_samples:
                continue

            duration = len(accumulated) / sample_rate

            try:
                chunk_text = self._transcribe_chunk(accumulated)
                accumulated = np.array([], dtype=np.float32)  # Скинути

                if chunk_text:
                    self._append_chunk_text(chunk_text, duration)

            except Exception as e:
                logger.warning("Transcribe помилка: %s", e)

        # При зупинці — обробити залишок
        remaining = self._recorder.get_new_audio()
        if len(remaining) > 0:
            accumulated = np.concatenate([accumulated, remaining])

        if len(accumulated) > int(0.3 * sample_rate):
            try:
                duration = len(accumulated) / sample_rate
                chunk_text = self._transcribe_chunk(accumulated)
                if chunk_text:
                    self._append_chunk_text(chunk_text, duration)
            except Exception as e:
                logger.warning("Final chunk помилка: %s", e)

        self._transcribe_done.set()
        logger.info("Transcribe-потік завершено")

    def _append_loop(self) -> None:
        """Потік для дописування тексту в поле вводу."""
        logger.info("Append-потік запущено")
        while not self._append_stop.is_set():
            try:
                text = self._append_queue.get(timeout=0.2)

                # Взяти найсвіжіше
                latest = text
                while not self._append_queue.empty():
                    try:
                        latest = self._append_queue.get_nowait()
                    except queue.Empty:
                        break

                if latest:
                    self._inserter.append(latest)

            except queue.Empty:
                continue
            except Exception as e:
                logger.warning("Append помилка: %s", e)

        # Дочекатись залишків в черзі
        while not self._append_queue.empty():
            try:
                text = self._append_queue.get_nowait()
                self._inserter.append(text)
            except queue.Empty:
                break

        logger.info("Append-потік завершено")

    def _stop_dictation(self) -> None:
        try:
            self._is_dictating = False
            self._transcribe_stop.set()

            self._full_audio = self._recorder.stop()
            duration = len(self._full_audio) / 16000 if len(self._full_audio) > 0 else 0

            self._ui.set_state(AppState.TRANSCRIBING)
            logger.info("Зупинено (%.1f сек). Фінальна транскрипція...", duration)

            # Запустити фінальну транскрипцію в окремому потоці
            threading.Thread(target=self._final_transcribe, daemon=True).start()

        except Exception as e:
            logger.error("Помилка зупинки: %s", e, exc_info=True)
            self._ui.set_state(AppState.ERROR, str(e))
            self._is_dictating = False
            self._append_stop.set()

    def _final_transcribe(self) -> None:
        """Фінальна транскрипція повного аудіо для чистого результату."""
        # Дочекатись завершення transcribe_loop
        self._transcribe_done.wait(timeout=10.0)
        self._append_stop.set()

        if self._full_audio is None or len(self._full_audio) < int(0.3 * 16000):
            if not self._confirmed_text:
                self._ui.set_text("(Мову не розпізнано)\n")
            self._ui.set_state(AppState.READY)
            return

        try:
            full_text = self._transcribe_chunk(self._full_audio)
            if full_text:
                if self._confirmed_text and full_text != self._confirmed_text.strip():
                    # Замінити чанковий текст на чистий фінальний
                    self._inserter.replace_all(full_text)
                    logger.info("Фінальний текст (замінено): '%s'", full_text[:120])
                elif not self._confirmed_text:
                    self._inserter.append(full_text)
                    logger.info("Фінальний текст: '%s'", full_text[:120])
                else:
                    logger.info("Фінальний текст (без змін): '%s'", full_text[:120])
                self._confirmed_text = full_text
            else:
                if not self._confirmed_text:
                    self._ui.set_text("(Мову не розпізнано)\n")
        except Exception as e:
            logger.warning("Фінальна транскрипція помилка: %s", e)

        self._full_audio = None
        self._ui.set_state(AppState.READY)

    def _on_shutdown(self) -> None:
        logger.info("Завершення роботи...")
        self._is_dictating = False
        self._transcribe_stop.set()
        self._append_stop.set()
        self._hotkey_mgr.unregister_all()
        if self._recorder.is_recording:
            self._recorder.stop()
        logger.info("Застосунок завершено")


VALID_MODELS = {
    "tiny", "tiny.en", "base", "base.en", "small", "small.en",
    "medium", "medium.en", "large-v1", "large-v2", "large-v3",
    "large", "turbo", "large-v3-turbo",
}


def main():
    model_size = "large-v3-turbo"
    if len(sys.argv) > 1 and sys.argv[1] in VALID_MODELS:
        model_size = sys.argv[1]

    app = DictationApp(model_size=model_size)
    app.start()


if __name__ == "__main__":
    main()
