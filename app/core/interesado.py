"""Composición de la columna Interesado.

Interesado contesta "¿de quién es esta comunicación?", y es la guía con la que
el analista recorre la Tabla TOTAL. Hasta ahora salía únicamente de los nombres
que el analista hubiera cargado en el Índice de abonados, así que en una causa
recién importada decía NO IDENTIFICADO en todas las filas: la columna no servía
de nada justo cuando más falta hace, que es al empezar.

Pero el dato existe desde el momento de importar: cada archivo viene de la
carpeta de una línea intervenida. Con eso la columna arranca mostrando el
número de esa línea y va mejorando sola a medida que se le ponen nombres.

Vive en `core` porque la usan los tres lados: el importador de llamadas, el de
SMS y el recálculo que corre al nombrar un abonado en el Índice.
"""

from __future__ import annotations

from app.config import VALOR_NO_IDENTIFICADO


def componer_interesado(
    nombre_origen: str,
    nombre_destino: str,
    intervenido: str = "",
    nombre_intervenido: str = "",
) -> str:
    """Arma el texto de la columna a partir de lo que se sepa de cada punta.

    En orden de preferencia:

    1. Los dos extremos nombrados y distintos -> se nombran los dos.
    2. Los dos nombrados e iguales, o uno solo -> ese nombre.
    3. Ninguno nombrado, pero se sabe de qué línea intervenida salió el
       archivo -> el nombre de esa línea si lo tiene, y si no su número.
    4. Nada -> NO IDENTIFICADO.

    El paso 3 es el que hace que la columna sirva desde la primera importación.
    """
    origen = (nombre_origen or "").strip()
    destino = (nombre_destino or "").strip()
    if origen and destino:
        return origen if origen == destino else f"ORIGEN: {origen} / DESTINO: {destino}"
    if origen or destino:
        return origen or destino

    propio = (nombre_intervenido or "").strip()
    if propio:
        return propio
    linea = (intervenido or "").strip()
    if linea and linea != VALOR_NO_IDENTIFICADO:
        return linea
    return VALOR_NO_IDENTIFICADO
