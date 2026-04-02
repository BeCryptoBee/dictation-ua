"""
Фоновий запуск Диктовка UA — без консольного вікна.
Python автоматично запускає .pyw файли через pythonw.exe.
"""

import os
import sys

# Встановити CUDA шляхи (як у run.bat)
try:
    import nvidia.cublas
    os.environ["PATH"] = os.path.join(nvidia.cublas.__path__[0], "bin") + os.pathsep + os.environ.get("PATH", "")
except ImportError:
    pass

try:
    import nvidia.cudnn
    os.environ["PATH"] = os.path.join(nvidia.cudnn.__path__[0], "bin") + os.pathsep + os.environ.get("PATH", "")
except ImportError:
    pass

# Робоча директорія — корінь проєкту
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
sys.path.insert(0, os.path.join(script_dir, "src"))

from main import main

main()
