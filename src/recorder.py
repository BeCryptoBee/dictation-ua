"""
Модуль запису аудіо з мікрофона.
Використовує sounddevice для захоплення аудіо.
Підтримує два формати: float32 для Whisper і int16 для Vosk streaming.
"""

import logging
import threading
from typing import Callable

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000  # Whisper і Vosk потребують 16kHz
CHANNELS = 1         # Mono


class AudioRecorder:
    """Записує аудіо з мікрофона. Підтримує streaming callback для Vosk."""

    def __init__(self, device: int | None = None):
        self._device = device
        self._chunks: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._recording = False
        self._lock = threading.Lock()
        self._stream_callback: Callable[[bytes], None] | None = None
        self._read_index = 0  # Індекс для get_new_audio

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self, stream_callback: Callable[[bytes], None] | None = None) -> None:
        """
        Почати запис.

        Args:
            stream_callback: якщо вказано, кожен аудіо-чанк буде передано
                            в цю функцію як bytes (int16 PCM) для streaming розпізнавання.
        """
        with self._lock:
            if self._recording:
                logger.warning("Запис вже активний")
                return

            self._chunks.clear()
            self._read_index = 0
            self._stream_callback = stream_callback
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                device=self._device,
                callback=self._audio_callback,
                blocksize=4096,
            )
            self._stream.start()
            self._recording = True
            logger.info("Запис розпочато (device=%s, rate=%d, streaming=%s)",
                        self._device, SAMPLE_RATE, stream_callback is not None)

    def stop(self) -> np.ndarray:
        """Зупинити запис і повернути все записане аудіо (float32 для Whisper)."""
        with self._lock:
            if not self._recording:
                logger.warning("Запис не був активний")
                return np.array([], dtype=np.float32)

            self._recording = False
            self._stream_callback = None
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
                self._stream = None

        if not self._chunks:
            logger.warning("Немає записаних даних")
            return np.array([], dtype=np.float32)

        audio = np.concatenate(self._chunks, axis=0).flatten()
        duration = len(audio) / SAMPLE_RATE
        logger.info("Запис зупинено: %.1f сек, %d семплів", duration, len(audio))
        return audio

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        """Callback від sounddevice — зберігає чанки і передає в streaming."""
        if status:
            logger.warning("Audio callback status: %s", status)
        if not self._recording:
            return

        # Зберігати float32 для фінальної Whisper транскрипції
        self._chunks.append(indata.copy())

        # Передати int16 bytes в streaming callback (Vosk)
        if self._stream_callback is not None:
            try:
                # Конвертація float32 [-1.0, 1.0] → int16
                int16_data = (indata * 32767).astype(np.int16)
                self._stream_callback(int16_data.tobytes())
            except Exception as e:
                logger.warning("Stream callback помилка: %s", e)

    def get_new_audio(self) -> np.ndarray:
        """
        Отримати НОВЕ аудіо з моменту останнього виклику.
        Використовується для chunked Whisper streaming.
        """
        with self._lock:
            if self._read_index >= len(self._chunks):
                return np.array([], dtype=np.float32)
            new_chunks = self._chunks[self._read_index:]
            self._read_index = len(self._chunks)
        return np.concatenate(new_chunks, axis=0).flatten()

    def get_all_audio(self) -> np.ndarray:
        """Отримати все накопичене аудіо без зупинки запису."""
        with self._lock:
            if not self._chunks:
                return np.array([], dtype=np.float32)
            return np.concatenate(self._chunks, axis=0).flatten()

    def get_devices(self) -> list[dict]:
        """Повертає список доступних аудіопристроїв для вводу."""
        devices = sd.query_devices()
        input_devices = []
        for i, dev in enumerate(devices):
            if dev["max_input_channels"] > 0:
                input_devices.append({
                    "id": i,
                    "name": dev["name"],
                    "channels": dev["max_input_channels"],
                    "sample_rate": dev["default_samplerate"],
                })
        return input_devices
