# -*- mode: python ; coding: utf-8 -*-
"""Empaquetado del MOTOR de transcripción como ejecutable propio.

    py -m PyInstaller WhisperWorker.spec

Por qué existe este segundo ejecutable, separado del programa:

Whisper y torch pesan más de un giga y no entran en el ejecutable de la
aplicación —de hecho están en `excludes` del otro .spec—. Hasta ahora eso
obligaba a instalar Python y hacer `pip install openai-whisper` en cada equipo
que fuera a transcribir, que es justamente lo que no se puede pedirle a un
puesto de trabajo de una fiscalía.

Empaquetando el worker aparte, el motor viaja como un `.exe` más y **no hace
falta ningún Python instalado**. La aplicación lo busca en
`recursos/motor/whisper_worker.exe` y, si está, ni siquiera se molesta en
buscar intérpretes en el equipo.

El worker habla por stdin/stdout con JSON: recibe rutas de audio y devuelve las
transcripciones. No tiene interfaz, así que va con consola apagada.

El MODELO no va adentro: sigue en `recursos/modelos/`, al lado. Son 461 MB que
cambian una vez cada nunca, y meterlos acá obligaría a recompilar el motor para
cambiar de modelo.
"""

from PyInstaller.utils.hooks import collect_data_files

# whisper trae archivos de DATOS que carga al transcribir —los filtros mel y
# los vocabularios del tokenizador— y PyInstaller no los recoge solo: el
# ejecutable compila, importa todo bien, carga el modelo y recién falla al
# primer audio con "No such file or directory: mel_filters.npz".
datos = collect_data_files("whisper") + collect_data_files("tiktoken_ext")

a = Analysis(
    ["app/servicios/whisper_worker.py"],
    pathex=[],
    binaries=[],
    datas=datos,
    # whisper carga sus tablas y assets en tiempo de ejecución, y numba compila
    # al vuelo: sin esto el ejecutable arranca y falla al primer audio.
    hiddenimports=[
        "whisper",
        "whisper.audio",
        "whisper.decoding",
        "whisper.tokenizer",
        "tiktoken_ext",
        "tiktoken_ext.openai_public",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Nada de interfaz: este ejecutable no dibuja una sola ventana.
        "PySide6", "shiboken6", "tkinter", "matplotlib",
        # NO se excluyen submódulos de torch. `torch.distributed` parecía
        # prescindible —acá no hay entrenamiento distribuido— pero
        # `torch.utils.data.dataloader` lo importa sin condición y el paquete
        # queda inservible. Los megas que ahorra no valen el riesgo.
        # faster-whisper y su dependencia `av` quedan afuera. `av` trae seis
        # extensiones compiladas con el MISMO nombre de archivo en carpetas
        # distintas (format.pyd en av/, av/audio/, av/video/) y empaquetadas
        # hacen fallar el import con "cannot load module more than once per
        # process", que se lleva puesto también a whisper.
        #
        # No se pierde nada: el motor por defecto es `openai`, y faster-whisper
        # necesita modelos CTranslate2 que este paquete no distribuye.
        "faster_whisper", "av", "onnxruntime",
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
    name="whisper_worker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,      # sin ventana propia; la app lo lanza y lee su salida
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="whisper_worker",
)
