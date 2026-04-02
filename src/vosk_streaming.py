"""
Модуль streaming розпізнавання через Vosk.
Забезпечує real-time preview: текст з'являється слово за словом під час розмови.

Vosk модель для української: vosk-model-uk-v3 (~343 MB)
Завантажити: https://alphacephei.com/vosk/models/vosk-model-uk-v3.zip
Розпакувати в папку models/ проєкту.
"""

import json
import logging
import os
import zipfile
from pathlib import Path
from typing import Callable

from vosk import Model, KaldiRecognizer, SetLogLevel

logger = logging.getLogger(__name__)

# Vosk модель
MODEL_NAME = "vosk-model-uk-v3"
MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-uk-v3.zip"
SAMPLE_RATE = 16000


class VoskStreaming:
    """
    Streaming розпізнавач на базі Vosk.
    Приймає аудіо-чанки і повертає partial/final результати в реальному часі.
    """

    def __init__(self, models_dir: str = "models"):
        self._models_dir = Path(models_dir)
        self._model: Model | None = None
        self._recognizer: KaldiRecognizer | None = None
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def get_model_path(self) -> Path:
        """Повертає шлях до папки моделі."""
        return self._models_dir / MODEL_NAME

    def is_model_downloaded(self) -> bool:
        """Чи завантажена модель."""
        model_path = self.get_model_path()
        return model_path.exists() and (model_path / "conf").exists()

    def load(self) -> None:
        """Завантажити Vosk модель."""
        if self._loaded:
            return

        model_path = self.get_model_path()

        if not self.is_model_downloaded():
            raise FileNotFoundError(
                f"Vosk модель не знайдена: {model_path}\n\n"
                f"Завантажте модель:\n"
                f"1. Скачайте: {MODEL_URL}\n"
                f"2. Розпакуйте в папку: {self._models_dir}/\n"
                f"   (має бути {model_path}/conf/model.conf)"
            )

        # Придушити зайві логи Vosk
        SetLogLevel(-1)

        logger.info("Завантаження Vosk моделі з '%s'...", model_path)
        self._model = Model(str(model_path))
        self._loaded = True
        logger.info("Vosk модель завантажена")

    def create_recognizer(self) -> None:
        """Створити новий recognizer для нової сесії диктовки."""
        if not self._loaded or self._model is None:
            raise RuntimeError("Vosk модель не завантажена")
        self._recognizer = KaldiRecognizer(self._model, SAMPLE_RATE)
        self._recognizer.SetWords(False)  # Не потрібні timestamps слів

    def feed_audio(self, audio_bytes: bytes) -> tuple[str, bool]:
        """
        Подати аудіо-чанк на розпізнавання.

        Args:
            audio_bytes: PCM int16 аудіо дані.

        Returns:
            (text, is_final):
                text — розпізнаний текст (partial або final)
                is_final — True якщо Vosk визначив кінець фрази
        """
        if self._recognizer is None:
            return "", False

        if self._recognizer.AcceptWaveform(audio_bytes):
            # Кінець фрази — повний результат
            result = json.loads(self._recognizer.Result())
            text = result.get("text", "")
            return text, True
        else:
            # Проміжний результат
            partial = json.loads(self._recognizer.PartialResult())
            text = partial.get("partial", "")
            return text, False

    def get_final(self) -> str:
        """Отримати фінальний результат після закінчення аудіо."""
        if self._recognizer is None:
            return ""
        result = json.loads(self._recognizer.FinalResult())
        return result.get("text", "")
