# -*- mode: python ; coding: utf-8 -*-
"""Empaquetado del Sistema de Gestión de Escuchas Diferidas.

    py -m PyInstaller EscuchasDiferidas.spec

Se construye en modo CARPETA (onedir), no onefile, por dos razones:

  1. QtWebEngine (el Mapa) arranca un proceso aparte y en onefile hay que
     re-extraer todo el bundle en cada arranque: son varios segundos y cientos
     de MB de disco temporal cada vez.
  2. Los recursos pesados —el modelo de Whisper (483 MB) y ffmpeg— viven AL
     LADO del ejecutable, en `recursos/`, no adentro. Así se actualiza el
     programa sin volver a copiar el modelo, y se puede distribuir la
     aplicación sin él para equipos que ya lo tienen.

Lo que el analista escribe (base de datos, perfil, log) va a `datos/`, también
al lado del ejecutable: ver `app/config.py`.
"""

from PyInstaller.utils.hooks import collect_data_files

datos = [
    # El mapa se carga como archivo local desde QtWebEngine.
    ("app/ui/recursos", "app/ui/recursos"),
    # El worker de Whisper NO se importa: se ejecuta con otro intérprete, así
    # que viaja como archivo de datos y no como módulo.
    ("app/servicios/whisper_worker.py", "app/servicios"),
]

# tiktoken y whisper traen tablas de datos que se cargan en tiempo de ejecución.
ocultos = ["app.servicios.whisper_worker"]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datos,
    hiddenimports=ocultos,
    hookspath=[],
    runtime_hooks=[],
    # Torch y whisper pesan gigas y NO van adentro: el motor corre en un Python
    # aparte del equipo (ver app/servicios/transcripcion.py).
    excludes=[
        "torch", "whisper", "faster_whisper", "ctranslate2", "onnxruntime",
        "numpy.distutils", "tkinter", "matplotlib", "scipy", "pandas",
        "PySide6.QtQuick3D", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtBluetooth",
        "PySide6.QtNfc", "PySide6.QtSensors", "PySide6.QtSerialPort",
        "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EscuchasDiferidas",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX rompe las DLL de Qt
    console=False,      # sin ventana de consola detrás de la aplicación
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="icono.ico" if __import__("pathlib").Path("icono.ico").is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="EscuchasDiferidas",
)
