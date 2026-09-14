"""Extracción del número de CD a partir de la ruta de un archivo.

Corrige BUG-04 del .bas: si no se puede inferir el CD del path, se devuelve
explícitamente 'SIN CD DETECTADO' (no string vacío), para que el panel de
validaciones lo liste y el analista lo complete a mano.
"""

from __future__ import annotations

import re
from pathlib import PurePath

from app.config import CD_NO_DETECTADO

# Número al inicio de un segmento, seguido de un punto: "4. CD700000011" -> "4".
_NUM_INICIAL = re.compile(r"^(\d+)\.")


def _numero_inicial(segmento: str) -> str | None:
    """Devuelve el número al inicio del segmento si está seguido de '.', si no None."""
    m = _NUM_INICIAL.match(segmento.strip())
    return m.group(1) if m else None


def extraer_cd_de_path(
    path_completo: str | PurePath, raiz: str | PurePath | None = None
) -> str:
    """Extrae el número de CD priorizando el segmento de carpeta que contiene 'CD'.

    Estrategia (replica y endurece la del .bas):
      1. Buscar de derecha a izquierda el primer segmento que contenga 'CD'.
      2. Si lo hay, intentar el número inicial en ESE segmento; si no está,
         buscar hacia la izquierda (carpetas anteriores).
      3. Fallback: último segmento del path que empiece con 'número.'.
      4. Si nada matchea -> 'SIN CD DETECTADO'.

    `raiz` acota la búsqueda a la carpeta que el analista eligió al importar.
    Sin ese límite el paso 3 sigue subiendo por el árbol y termina agarrando la
    numeración de las carpetas de trabajo del usuario: una causa guardada en
    "1. Paredes / 10. Escuchas / INTERVENCION-700000001 / ..." daba CD "10"
    para TODOS los registros, colapsando cuatro entregas distintas en un CD que
    no existe. Con `raiz` no se mira nunca por encima de lo que se importó.
    """
    if not path_completo:
        return CD_NO_DETECTADO

    partes = [p for p in PurePath(str(path_completo)).parts if p not in ("\\", "/")]
    if raiz is not None:
        base = [p for p in PurePath(str(raiz)).parts if p not in ("\\", "/")]
        if partes[: len(base)] == base:
            partes = partes[len(base):]
    if not partes:
        return CD_NO_DETECTADO

    idx_cd = -1
    for i in range(len(partes) - 1, -1, -1):
        if "cd" in partes[i].lower():
            idx_cd = i
            break

    if idx_cd != -1:
        num = _numero_inicial(partes[idx_cd])
        if num is not None:
            return num
        for i in range(idx_cd - 1, -1, -1):
            num = _numero_inicial(partes[i])
            if num is not None:
                return num

    # Fallback: cualquier segmento (de derecha a izquierda) con 'número.'
    for i in range(len(partes) - 1, -1, -1):
        num = _numero_inicial(partes[i])
        if num is not None:
            return num

    return CD_NO_DETECTADO
