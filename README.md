# Dictation UA

Local offline speech-to-text for Ukrainian language. Runs entirely on your machine — no cloud APIs, no data leaves your PC.

Uses **Whisper large-v3-turbo** on GPU (CUDA) for fast, accurate transcription. Press a hotkey, dictate, press again — text appears in any active input field.

## How it works

1. App starts and loads the Whisper model into GPU memory
2. A microphone icon appears in the system tray (blue = ready)
3. Press `Ctrl+Shift+M` — icon turns red, recording starts
4. While you speak, text is transcribed in real-time chunks and pasted into the active window
5. Press `Ctrl+Shift+M` again — recording stops, full audio is re-transcribed for clean results and replaces the chunked text via `Ctrl+A → Ctrl+V`
6. Icon goes back to blue — ready for the next round

### Architecture

```
Hotkey (keyboard) → AudioRecorder (sounddevice, 16kHz mono)
                        ↓
                  Transcribe loop (every ~5s chunk)
                        ↓
                  faster-whisper (GPU/CUDA, large-v3-turbo)
                        ↓
                  TextInserter (pyperclip + pyautogui → Ctrl+V)
                        ↓
                  On stop: final full-audio transcription → replace_all
```

- **System tray UI** — pystray with colored microphone icon (no window)
- **Hallucination filter** — removes known Whisper artifacts ("Дякуємо", "Субтитри", etc.)
- **VAD filter** — skips silence segments for speed and accuracy

## Requirements

- **Windows 10/11**
- **Python 3.10+**
- **NVIDIA GPU with CUDA** (tested on RTX 4070). CPU fallback available but slower
- Microphone

## Installation

```bash
# Clone
git clone https://github.com/BeCryptoBee/dictation-ua.git
cd dictation-ua

# Install dependencies
pip install -r requirements.txt

# For GPU (recommended) — install CUDA support
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```

The Whisper model (~3 GB) downloads automatically on first launch from HuggingFace.

## Usage

### Normal mode (with console for logs)

```bash
run.bat
```

### Background mode (no console window)

Double-click `run_background.pyw` or run:
```bash
pythonw run_background.pyw
```

### Autostart with Windows

Create a shortcut in the Startup folder:
```powershell
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut((Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\Dictation_UA.lnk')); $s.TargetPath = 'pythonw.exe'; $s.Arguments = 'D:\Scripts\5_Text_to_speech\run_background.pyw'; $s.WorkingDirectory = 'D:\Scripts\5_Text_to_speech'; $s.Description = 'Dictation UA'; $s.Save()"
```
Adjust the path to match your installation directory.

### Choose a different model

```bash
run.bat medium          # lighter, ~1 GB VRAM
run.bat large-v3-turbo  # default, best speed/quality
run.bat large-v3        # highest quality, slower
```

## Tray icon states

| Icon | Color | State |
|------|-------|-------|
| Microphone | Blue | Ready — waiting for hotkey |
| Microphone | Red | Listening — recording audio |
| Circle | Orange | Loading model |
| Circle | Blue | Processing final transcription |
| Circle | Red | Error |

## Resource usage (idle)

| Resource | Usage |
|----------|-------|
| CPU | ~0% |
| GPU VRAM | ~1.5-2 GB (model in memory) |
| RAM | ~300-500 MB |

During active transcription, GPU utilization spikes briefly per chunk.

## Hotkey

Default: `Ctrl+Shift+M` (toggle recording on/off)

## Project structure

```
src/
  main.py          — app logic, chunked + final transcription, hallucination filter
  ui.py            — system tray UI (pystray, microphone icons)
  recorder.py      — audio capture (sounddevice)
  transcriber.py   — Whisper model wrapper (faster-whisper)
  inserter.py      — text insertion via clipboard (pyperclip + pyautogui)
  hotkey.py        — global hotkey registration (keyboard)
  vosk_streaming.py — optional Vosk streaming (not used in current architecture)
run.bat            — launcher with CUDA path setup
run_background.pyw — silent background launcher (pythonw)
```

## License

MIT
