# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'PIL', 'Pillow', 'pystray',
        'PySide6.QtNetwork', 'PySide6.QtQml', 'PySide6.QtQuick',
        'PySide6.QtSvg', 'PySide6.QtSvgWidgets', 'PySide6.QtXml',
        'PySide6.QtDBus', 'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets',
        'PySide6.QtPrintSupport', 'PySide6.QtMultimedia',
        'PySide6.QtBluetooth', 'PySide6.QtPositioning',
        'PySide6.QtSensors', 'PySide6.QtSerialPort',
        'PySide6.QtWebChannel', 'PySide6.QtWebSockets',
        'PySide6.QtTest', 'PySide6.QtHelp', 'PySide6.QtPdf',
        'PySide6.QtCharts', 'PySide6.QtDataVisualization',
    ],
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
    name='ImmediPaste',
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
)
