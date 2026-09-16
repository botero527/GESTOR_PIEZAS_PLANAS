@echo off
chcp 65001 > nul
title Build EXE - Piezas Planas

echo.
echo  ================================================
echo    Build EXE - Piezas Planas AGP
echo  ================================================
echo.

py -m pip install -r requirements.txt --quiet
py -m pip install pyinstaller --quiet

echo  Compilando ejecutable...
py -m PyInstaller PiezasPlanas.spec

echo.
echo  ================================================
echo    EXE generado en: dist\PiezasPlanas_AGP.exe
echo  ================================================
pause
