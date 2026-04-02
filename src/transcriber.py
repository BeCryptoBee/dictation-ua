"""
Модуль транскрипції аудіо в текст.
Використовує faster-whisper для локального офлайн розпізнавання української мови.

Підтримує chunked транскрипцію: аудіо розбивається на шматки ~8 сек,
кожен транскрибується окремо і результат віддається через callback.
"""

import logging
from typing import Callable

import numpy as np
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

DEFAULT_MODEL_SIZE = "medium"
LANGUAGE = "uk"
CHUNK_DURATION_SEC = 8  # Розмір шматка для chunked транскрипції
SAMPLE_RATE = 16000

# Глобальний кеш device
_detected_device: str | None = None


class Transcriber:
    """Обгортка над faster-whisper для розпізнавання української мови."""

    def __init__(self, model_size: str = DEFAULT_MODEL_SIZE, device: str = "auto"):
        self._model_size = model_size
        self._model: WhisperModel | None = None
        self._device = device
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Завантажити модель Whisper."""
        global _detected_device

        if self._loaded:
            return

        logger.info("Завантаження моделі Whisper '%s'...", self._model_size)

        if self._device == "auto" and _detected_device is not None:
            self._device = _detected_device
            logger.info("Device: %s (з кешу)", self._device)

        if self._device == "auto":
            if self._try_load_cuda():
                _detected_device = "cuda"
                logger.info("Використовується GPU (CUDA)")
            else:
                _detected_device = "cpu"
                logger.info("GPU недоступний, використовується CPU")
                self._load_cpu()
        else:
            if self._device == "cuda":
                self._model = WhisperModel(
                    self._model_size, device="cuda", compute_type="float16",
                )
            else:
                self._load_cpu()

        self._loaded = True
        logger.info("Модель '%s' завантажена (%s)", self._model_size, self._device)

    def _load_cpu(self) -> None:
        self._device = "cpu"
        try:
            self._model = WhisperModel(
                self._model_size, device="cpu", compute_type="int8",
                local_files_only=True,
            )
        except Exception:
            logger.info("Кеш не знайдено, завантаження з інтернету...")
            self._model = WhisperModel(
                self._model_size, device="cpu", compute_type="int8",
            )

    def _try_load_cuda(self) -> bool:
        try:
            model = WhisperModel(self._model_size, device="cuda", compute_type="float16")
            _silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
            segments, _ = model.transcribe(_silence, language=LANGUAGE)
            for _ in segments:
                pass
            self._model = model
            self._device = "cuda"
            return True
        except Exception as e:
            logger.debug("CUDA не пройшов: %s", e)
            return False

    def transcribe_chunked(self, audio: np.ndarray,
                           on_chunk: Callable[[str, int, int], None]) -> str:
        """
        Транскрибувати аудіо по шматках, викликаючи callback після кожного.

        Args:
            audio: Весь записаний аудіо масив.
            on_chunk: Callback(chunk_text, chunk_index, total_chunks).
                     Викликається після кожного шматка з його текстом.

        Returns:
            Повний зібраний текст.
        """
        if not self._loaded or self._model is None:
            raise RuntimeError("Модель не завантажена.")

        if len(audio) == 0:
            return ""

        total_duration = len(audio) / SAMPLE_RATE
        chunk_size = CHUNK_DURATION_SEC * SAMPLE_RATE

        # Розбити на шматки
        chunks = []
        for start in range(0, len(audio), chunk_size):
            chunk = audio[start:start + chunk_size]
            if len(chunk) > SAMPLE_RATE * 0.3:  # Мінімум 0.3 сек
                chunks.append(chunk)

        total_chunks = len(chunks)
        logger.info("Транскрипція %.1f сек аудіо (%d шматків по ~%dс)",
                     total_duration, total_chunks, CHUNK_DURATION_SEC)

        all_text_parts = []

        for i, chunk in enumerate(chunks):
            segments, _ = self._model.transcribe(
                chunk,
                language=LANGUAGE,
                beam_size=3,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=300),
                condition_on_previous_text=False,
            )

            chunk_parts = []
            for segment in segments:
                chunk_parts.append(segment.text.strip())

            chunk_text = " ".join(chunk_parts).strip()

            if chunk_text:
                all_text_parts.append(chunk_text)
                logger.info("Chunk %d/%d: '%s'", i + 1, total_chunks, chunk_text)
                on_chunk(chunk_text, i, total_chunks)

        result = " ".join(all_text_parts).strip()
        logger.info("Повний результат: '%s'", result[:120])
        return result
