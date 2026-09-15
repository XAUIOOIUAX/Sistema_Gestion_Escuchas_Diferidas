"""Configuración central de la aplicación.

Todas las constantes ajustables del sistema viven aquí, no hardcodeadas en
las funciones (ver BUG-01 del pseudocódigo: el patrón de archivo debe ser
configurable y calibrado con datos reales).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Versión del programa. Va en el encabezado de cada error registrado: cuando el
# programa esté instalado en varias máquinas, un reporte sin versión no se
# puede ubicar en el tiempo ni descartar contra algo ya arreglado.
VERSION = "1.0"

# --------------------------------------------------------------------------
# Rutas de la aplicación
# --------------------------------------------------------------------------
# Hay que distinguir dos cosas que corriendo desde el código fuente son la
# misma carpeta y empaquetado NO:
#
#   RAIZ_APP  -> de dónde se LEE lo que viene con el programa (mapa.html, el
#                worker de Whisper). Empaquetado es la carpeta temporal que
#                PyInstaller extrae.
#   DIR_DATOS -> dónde se ESCRIBE lo del analista: la base de la causa, su
#                perfil y el log de errores.
#
# Confundirlas es fatal: en un ejecutable "onefile" la carpeta de extracción se
# borra al cerrar, así que la base de datos —el trabajo de la jornada— se iría
# con ella sin que nadie se entere hasta el día siguiente.
EMPAQUETADO: bool = getattr(sys, "frozen", False)

if EMPAQUETADO:
    RAIZ_APP: Path = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    # Junto al .exe: la aplicación queda portable, que es lo que se espera de
    # una herramienta que va y viene entre equipos de la fiscalía.
    _JUNTO_AL_EXE = Path(sys.executable).resolve().parent
    DIR_DATOS: Path = _JUNTO_AL_EXE / "datos"
    try:
        DIR_DATOS.mkdir(parents=True, exist_ok=True)
        _prueba = DIR_DATOS / ".escritura"
        _prueba.write_bytes(b"")
        _prueba.unlink()
    except OSError:
        # Instalado en Program Files o en una unidad de red sin permiso: se cae
        # al perfil del usuario, que siempre se puede escribir.
        DIR_DATOS = (
            Path(os.environ.get("LOCALAPPDATA", Path.home())) / "EscuchasDiferidas"
        )
        DIR_DATOS.mkdir(parents=True, exist_ok=True)
else:
    RAIZ_APP: Path = Path(__file__).resolve().parent.parent
    DIR_DATOS: Path = RAIZ_APP / "datos"

RUTA_BASE_DATOS: Path = DIR_DATOS / "escuchas.db"

# --------------------------------------------------------------------------
# Importación
# --------------------------------------------------------------------------

# Extensiones reconocidas como archivo de audio (en minúsculas, sin punto).
AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {"wav", "mp3", "amr", "ogg", "opus", "m4a", "wma", "aac", "flac"}
)

# Patrón de archivo de audio transcripto (BUG-01).
#
# Patrón real observado en datos: B-#####-####-##-##-######-#######
#   B-  + 5 dígitos + año(4) + mes(2) + día(2) + hora-compacta(6) + 7 dígitos
# El .bas original aceptaba cualquier "B-*" como fallback laxo; aquí lo
# ajustamos. SOLO_AUDIO_PATTERN controla si se filtra por patrón o se acepta
# cualquier nombre base.
SOLO_AUDIO_PATTERN: bool = True

# Patrón estricto calibrado. Se mantiene flexible en la cantidad de dígitos
# de cada bloque porque los datos reales varían; debe re-calibrarse contra un
# set grande de archivos reales antes de fijarlo definitivamente.
PATRON_AUDIO: re.Pattern[str] = re.compile(
    r"^b-\d{4,6}-\d{4}-\d{2}-\d{2}-\d{4,6}-\d{5,8}",
    re.IGNORECASE,
)

# Fallback permisivo: si SOLO_AUDIO_PATTERN está activo pero el nombre no
# matchea el patrón estricto, aceptar igual los que empiezan con "b-".
# (Replica el comportamiento tolerante del .bas; desactivar si genera ruido.)
PATRON_AUDIO_FALLBACK_PERMISIVO: bool = True

# --------------------------------------------------------------------------
# Normalización / parseo
# --------------------------------------------------------------------------

# Offset horario aplicado SOLO al datetime derivado (no al texto original).
# Si los TXT vinieran en UTC y se quisiera ART: -3.
OFFSET_HORAS: int = 0

# Encodings a intentar al leer un TXT, en orden.
ENCODINGS_TXT: tuple[str, ...] = ("utf-8-sig", "utf-8", "latin-1")

# Evitar duplicados al importar (índice UNIQUE sobre clave_dedup).
EVITAR_DUPLICADOS: bool = True

# --------------------------------------------------------------------------
# Valores por defecto / etiquetas
# --------------------------------------------------------------------------
VALOR_NO_IDENTIFICADO: str = "NO IDENTIFICADO"
CD_NO_DETECTADO: str = "SIN CD DETECTADO"
CONTEXTO_DEFAULT: str = "SIN CONTEXTO ASIGNADO"

# Catálogo inicial de contextos (etiquetas sugeridas).
CONTEXTOS_INICIALES: tuple[str, ...] = (
    "INTENTO DE COMUNICACION",
    "COMUNICACION SIN INTERES",
    "SIN CONTEXTO ASIGNADO",
)

# --------------------------------------------------------------------------
# Transcripción automática (Whisper)
# --------------------------------------------------------------------------
# El motor corre en un proceso separado con un Python que tenga instalado
# openai-whisper + torch (el venv de la app no los necesita). Si estas rutas
# son None, el servicio las autodetecta (ver servicios/transcripcion.py).
RUTA_MODELO_WHISPER: Path | None = None   # .pt local (p.ej. small.pt)
RUTA_FFMPEG: Path | None = None           # carpeta que contiene ffmpeg.exe
PYTHON_WHISPER: Path | None = None        # python.exe con whisper instalado
# Motor empaquetado. Si está presente no hace falta ningún Python en el equipo:
# el .exe trae whisper y torch adentro. Se autodetecta en
# `recursos/motor/whisper_worker.exe`.
MOTOR_WHISPER_EXE: Path | None = None
WHISPER_IDIOMA: str = "es"

# Motor de transcripción:
#   "openai" -> openai-whisper, modelos .pt en recursos/modelos/whisper/
#   "faster" -> faster-whisper (CTranslate2), carpetas en
#               recursos/modelos/faster-whisper/<nombre>/
#
# Medido en este equipo (4 CPU lógicas, sin GPU) sobre una comunicación de 2:48:
#   openai + small : 124 s  (0,73x tiempo real)
#   faster + small : 172 s  (1,02x)
#   faster + large-v3: 407 s (2,42x), claramente más preciso
#
# O sea: faster NO es más rápido acá —eso pasa en equipos con más núcleos—,
# pero es la única vía práctica a large-v3, porque el mismo modelo con el motor
# openai sería varias veces más lento todavía. Por eso el default sigue siendo
# openai+small (una causa de 27 min de audio se transcribe en 20 min) y faster
# queda para cuando la causa justifique la hora de large-v3.
WHISPER_MOTOR: str = "openai"

# Modelo a usar con el motor 'faster' cuando no hay una carpeta local: el
# nombre alcanza para que faster-whisper lo tome de su caché.
WHISPER_MODELO_FASTER: str = "small"

# Contexto opcional para Whisper (initial_prompt). Texto calibrado y listo para
# usar: orienta el vocabulario hacia el español rioplatense y el registro
# coloquial de una comunicación telefónica.
WHISPER_PROMPT_TELEFONICA: str = (
    "Grabación de una comunicación telefónica en español rioplatense de "
    "Argentina. Registro coloquial, con muletillas, interrupciones y "
    "repeticiones. Se transcribe textualmente lo que se escucha."
)

# initial_prompt que se usa realmente. Vacío = ninguno, y ese es el default a
# propósito.
#
# Medido sobre una comunicación real de 2:48 (modelo small, CPU):
#   - sin prompt      : 44 segmentos, arranca en "Hola." — fiel al audio.
#   - con este prompt : 34 segmentos, mejor segmentado, pero AGREGA un
#                       "¿Qué pasa?" en el segundo 0 que no está en la
#                       grabación.
# En un informe judicial inventar una línea es peor que segmentar de más, así
# que el prompt queda apagado. Para activarlo:
#     WHISPER_PROMPT_BASE = WHISPER_PROMPT_TELEFONICA
WHISPER_PROMPT_BASE: str = ""

# Sumar al prompt los nombres y lugares de la causa (los del Índice de abonados
# y las antenas). La idea es tentadora —son las palabras que el modelo no puede
# adivinar— pero medida en el mismo audio EMPEORA: con un nombre y una
# localidad del Índice en el prompt, el modelo abrió la transcripción con una
# deformación de ese mismo apellido y metió un "J viewed" en el medio. Sesga
# la salida hacia esas palabras aunque no suenen.
# Queda como opción para probar por causa, apagada por defecto.
WHISPER_PROMPT_VOCABULARIO: bool = False

# Carpetas donde autodetectar los recursos del Transcriptor Forense.
# El modelo (483 MB) y ffmpeg NO van adentro del ejecutable: se buscan al lado
# de él, que es donde los deja el instalador, y en las carpetas del Transcriptor
# Forense por si ya están en el equipo.
DIRS_RECURSOS_WHISPER: tuple[Path, ...] = (
    (Path(sys.executable).resolve().parent / "recursos") if EMPAQUETADO
    else RAIZ_APP / "recursos",
    RAIZ_APP / "recursos",
    RAIZ_APP / "SoftwareTranscriptor" / "Transcripcion_de_Audios"
    / "TranscriptorForenseGUI" / "_internal" / "recursos",
)

# --------------------------------------------------------------------------
# Validación de coordenadas (Argentina, aprox.)
# --------------------------------------------------------------------------
# Bounding box laxo de Argentina continental para detectar coordenadas
# sospechosas (no bloqueante, solo genera aviso).
LAT_MIN, LAT_MAX = -55.5, -21.5
LON_MIN, LON_MAX = -74.0, -53.0
