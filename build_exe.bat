@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Building BKCurveTool.exe from: %CD%

findstr /C:"tray-popup-taskbarcreated-20260429f" main.py >nul
if errorlevel 1 (
  echo ERROR: main.py 中缺少本版托盘标记 ^(tray-popup-taskbarcreated-20260429f^)。
  exit /b 1
)

echo Using BKCurveTool.spec ^(bundles src\index.html — do not use bare pyinstaller main.py^) ...
python -m PyInstaller --clean --noconfirm BKCurveTool.spec
if errorlevel 1 (
  echo Build FAILED.
  exit /b 1
)

echo.
echo OK: dist\BKCurveTool.exe
echo 运行后请打开 %USERPROFILE%\BKCurveTool_debug.log，开头应含 Tray build: tray-popup-taskbarcreated-20260429f
exit /b 0
