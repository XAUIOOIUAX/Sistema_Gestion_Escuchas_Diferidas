"""Emparejamiento de archivos TXT y audio por nombre base.

Funciones de clasificación de archivos usadas por el importador para detectar
pares completos y huérfanos (BUG-06).
"""

from __future__ import annotations

from app.config import (
    AUDIO_EXTENSIONS,
    PATRON_AUDIO,
    PATRON_AUDIO_FALLBACK_PERMISIVO,
    SOLO_AUDIO_PATTERN,
)


def nombre_base_archivo(nombre_archivo: str) -> str:
    """Devuelve el nombre sin su extensión (todo lo previo al último punto).

    Si no hay punto, devuelve el nombre completo.
    """
    if not nombre_archivo:
        return ""
    pos = nombre_archivo.rfind(".")
    if pos <= 0:  # sin punto, o punto inicial (archivo oculto) -> sin extensión
        return nombre_archivo
    return nombre_archivo[:pos]


def extension_de(nombre_archivo: str) -> str:
    """Devuelve la extensión en minúsculas, sin punto ('audio.WAV' -> 'wav')."""
    if not nombre_archivo:
        return ""
    pos = nombre_archivo.rfind(".")
    if pos == -1 or pos == len(nombre_archivo) - 1:
        return ""
    return nombre_archivo[pos + 1:].lower()


def es_extension_audio(extension: str) -> bool:
    """True si la extensión (sin punto) corresponde a un formato de audio reconocido."""
    return (extension or "").lower().lstrip(".") in AUDIO_EXTENSIONS


def cumple_patron_audio(nombre_base: str) -> bool:
    """True si el nombre base cumple el patrón de archivo de audio transcripto.

    Si SOLO_AUDIO_PATTERN está desactivado, acepta cualquier nombre base.
    Si está activo, exige el patrón estricto (config.PATRON_AUDIO); con
    fallback permisivo opcional para nombres que solo empiezan con 'b-'.
    """
    if not SOLO_AUDIO_PATTERN:
        return True
    nb = (nombre_base or "").strip()
    if PATRON_AUDIO.match(nb):
        return True
    if PATRON_AUDIO_FALLBACK_PERMISIVO and nb.lower().startswith("b-"):
        return True
    return False
