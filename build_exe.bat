@echo off
chcp 65001 > nul
title Build EXE - Piezas Planas

echo.
echo  ╔══════════════════════════════════════╗
echo  ║   Build EXE · Piezas Planas AGP      ║
echo  ╚══════════════════════════════════════╝
echo.

py -m pip install pyinstaller --quiet

echo  Compilando ejecutable...
py -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "PiezasPlanas_AGP" ^
    --add-data "dxf_processor.py;." ^
    main.py

echo.
echo  ╔══════════════════════════════════════╗
echo  ║  EXE generado en: dist\PiezasPlanas_AGP.exe  ║
echo  ╚══════════════════════════════════════╝
pause
