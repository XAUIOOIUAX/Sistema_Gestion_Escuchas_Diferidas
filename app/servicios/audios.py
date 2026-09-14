"""Dónde está el archivo de audio de una comunicación.

La base guarda el NOMBRE del archivo, no su ruta: el material se entrega en CD
y se copia a donde cada analista quiera, así que la ruta de hoy no sirve
mañana. Para encontrarlo se recorren las carpetas desde las que se importó esa
causa, que quedan anotadas en `HistorialImportacion`.

Ese recorrido se hacía con un `rglob` por cada audio que se abría. Con una
carpeta de entregas de cientos de archivos eso es medio segundo cada vez que se
cambia de comunicación, y en la pantalla Corregir se cambia todo el tiempo. Acá
se arma el índice de la carpeta una sola vez y se reutiliza.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# {(caso_id, ruta_raiz): {nombre_de_archivo: ruta_completa}}
_INDICE: dict[tuple[int, str], dict[str, Path]] = {}


def olvidar(caso_id: int | None = None) -> None:
    """Tira el índice. Hay que llamarlo después de importar material nuevo."""
    if caso_id is None:
        _INDICE.clear()
        return
    for clave in [c for c in _INDICE if c[0] == caso_id]:
        del _INDICE[clave]


def _indice_de(caso_id: int, raiz: Path) -> dict[str, Path]:
    clave = (caso_id, str(raiz))
    cacheado = _INDICE.get(clave)
    if cacheado is None:
        cacheado = {}
        try:
            for hallado in raiz.rglob("*"):
                if hallado.is_file():
                    # El primero gana: las carpetas se recorren en orden y la
                    # entrega más vieja es la original.
                    cacheado.setdefault(hallado.name, hallado)
        except OSError:
            # Carpeta en un disco que no está conectado: no es un error, es
            # material que hoy no está a mano.
            cacheado = {}
        _INDICE[clave] = cacheado
    return cacheado


def localizar(
    con: sqlite3.Connection, caso_id: int | None, nombre: str
) -> Path | None:
    """La ruta del audio, o None si no está en ninguna carpeta importada."""
    if not nombre or caso_id is None:
        return None
    for fila in con.execute(
        "SELECT DISTINCT ruta_usada FROM HistorialImportacion "
        "WHERE caso_id = ? ORDER BY id DESC",
        (caso_id,),
    ):
        raiz = Path(fila["ruta_usada"] or "")
        if not raiz.is_dir():
            continue
        directo = raiz / nombre
        if directo.is_file():
            return directo
        hallado = _indice_de(caso_id, raiz).get(nombre)
        if hallado is not None and hallado.is_file():
            return hallado
    return None
