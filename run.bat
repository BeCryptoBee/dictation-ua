@echo off
chcp 65001 >nul 2>nul
cd /d "%~dp0"

for /f "tokens=*" %%i in ('py -c "import nvidia.cublas; print(nvidia.cublas.__path__[0])" 2^>nul') do set "CUBLAS_PATH=%%i\bin"
for /f "tokens=*" %%i in ('py -c "import nvidia.cudnn; print(nvidia.cudnn.__path__[0])" 2^>nul') do set "CUDNN_PATH=%%i\bin"
if defined CUBLAS_PATH set "PATH=%CUBLAS_PATH%;%PATH%"
if defined CUDNN_PATH set "PATH=%CUDNN_PATH%;%PATH%"

py src/main.py %*
pause
