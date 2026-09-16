# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — Piezas Planas
# Uso: pyinstaller PiezasPlanas.spec
#
# datas bundlea la carpeta ui/ (HTML/CSS/JS/logo) dentro del .exe, igual
# que macro_stivencito/PipeMirror.spec. hiddenimports trae el bloque
# pywin32 que PyInstaller no detecta solo (mismo patrón reusado en todos
# los proyectos AGP con AutoCAD COM).

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('ui', 'ui')],
    hiddenimports=[
        'win32com.client',
        'win32com.server',
        'pythoncom',
        'pywintypes',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PiezasPlanas_AGP',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='ui/assets/logo.ico',
)
