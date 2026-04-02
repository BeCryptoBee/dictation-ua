"""Скрипт для завантаження Vosk моделі української мови."""

import os
import sys
import urllib.request
import zipfile

MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-uk-v3.zip"
MODEL_NAME = "vosk-model-uk-v3"
MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
ZIP_PATH = os.path.join(MODELS_DIR, f"{MODEL_NAME}.zip")


def download():
    os.makedirs(MODELS_DIR, exist_ok=True)

    model_path = os.path.join(MODELS_DIR, MODEL_NAME)
    if os.path.exists(os.path.join(model_path, "conf")):
        print(f"Модель вже завантажена: {model_path}")
        return

    print(f"Завантаження {MODEL_URL}")
    print("Розмір: ~343 MB, зачекайте...")

    def progress(block_num, block_size, total_size):
        downloaded = block_num * block_size
        if total_size > 0:
            pct = min(100, downloaded * 100 // total_size)
            mb = downloaded / (1024 * 1024)
            total_mb = total_size / (1024 * 1024)
            sys.stdout.write(f"\r  {mb:.0f}/{total_mb:.0f} MB ({pct}%)")
            sys.stdout.flush()

    urllib.request.urlretrieve(MODEL_URL, ZIP_PATH, reporthook=progress)
    print("\n\nРозпаковка...")

    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        zf.extractall(MODELS_DIR)

    os.remove(ZIP_PATH)
    print(f"Готово! Модель: {model_path}")


if __name__ == "__main__":
    download()
