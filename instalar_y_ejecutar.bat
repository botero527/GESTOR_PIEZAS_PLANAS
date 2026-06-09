@echo off
chcp 65001 > nul
title Piezas Planas - AGP GROUP

echo.
echo  ╔══════════════════════════════════════╗
echo  ║      Piezas Planas · AGP GROUP       ║
echo  ╚══════════════════════════════════════╝
echo.

:: Verificar Python
py --version > nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python no esta instalado.
    echo  Descarga Python desde https://python.org
    pause
    exit /b 1
)

echo  Instalando dependencias...
py -m pip install -r requirements.txt --quiet

echo  Iniciando aplicacion...
echo.
py main.py
pause
