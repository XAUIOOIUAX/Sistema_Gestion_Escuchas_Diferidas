"""Composición de la columna Interlocutor: la otra punta de la comunicación.

Interesado contesta "¿de quién es esta comunicación?" y señala a la línea
intervenida. Interlocutor contesta la otra mitad de la misma pregunta: "¿con
quién habló?". Es el dato por el que se recorre una causa —a la línea
intervenida ya se la conoce, lo que se investiga es con quién se comunica— y
hasta ahora había que leerlo a mano comparando Origen y Destino con la línea
pinchada, fila por fila.

Cuál de las dos puntas es el interlocutor se resuelve en este orden:

1. Si se sabe de qué línea intervenida salió el archivo (`abonado_intervenido`)
   y esa línea es una de las dos puntas, el interlocutor es la OTRA. Es el
   camino exacto y el que corre en todo lo importado desde esta versión.
2. Si no, manda la dirección, que ya está expresada desde la línea intervenida:
   en una ENTRANTE la llamó el origen, en una SALIENTE llamó al destino. Esto
   cubre lo importado de Excel, de otra base o antes de que se guardara la
   línea intervenida.
3. Si no hay ninguna de las dos cosas, no se puede saber cuál de los dos
   números es el de afuera, y decir cualquiera sería peor que no decir nada.

El NOMBRE sale del Índice de abonados, y si el Índice no lo tiene, de la
memoria «corresponde a» —que es la que se comparte entre causas—. Mientras no
haya nombre se muestra el NÚMERO, no un cartel de "sin identificar": el número
es el dato con el que el analista efectivamente trabaja, y la columna así sirve
desde la primera importación y va mejorando sola a medida que se nombran
abonados en el Índice.
"""

from __future__ import annotations

from app.config import VALOR_NO_IDENTIFICADO

SIN_INTERLOCUTOR = "SIN IDENTIFICAR"

_ENTRANTE = "ENTRANTE"
_SALIENTE = "SALIENTE"


def _limpio(valor: str) -> str:
    valor = (valor or "").strip()
    return "" if valor == VALOR_NO_IDENTIFICADO else valor


def numero_del_interlocutor(
    origen: str, destino: str, intervenido: str = "", direccion: str = ""
) -> str:
    """El número de la punta que NO es la línea intervenida, o '' si no se sabe."""
    origen, destino = _limpio(origen), _limpio(destino)
    linea = _limpio(intervenido)

    if linea:
        if linea == origen and destino:
            return destino
        if linea == destino and origen:
            return origen
        # La línea intervenida no es ninguna de las dos puntas: el dato no
        # cierra (número mal normalizado, registro editado a mano). Se cae a la
        # dirección en vez de inventar una punta.

    direccion = (direccion or "").strip().upper()
    if direccion == _ENTRANTE and origen:
        return origen
    if direccion == _SALIENTE and destino:
        return destino
    return ""


def componer_interlocutor(
    origen: str,
    destino: str,
    intervenido: str = "",
    direccion: str = "",
    nombres: dict[str, str] | None = None,
) -> str:
    """El texto de la columna: el nombre del interlocutor, o su número.

    `nombres` mapea número normalizado -> nombre, ya resuelto por quien llama
    (Índice primero, memoria «corresponde a» después).
    """
    numero = numero_del_interlocutor(origen, destino, intervenido, direccion)
    if not numero:
        return SIN_INTERLOCUTOR
    nombre = ((nombres or {}).get(numero) or "").strip()
    return nombre or numero


def nombres_de_las_puntas(
    origen: str, destino: str, del_indice=None, de_la_memoria=None
) -> dict[str, str]:
    """Arma el `nombres` de las dos puntas, con los resolvedores del importador.

    El Índice de la causa manda sobre la memoria compartida: si el analista
    nombró esa línea mirando este expediente, ese nombre es el que vale.
    """
    nombres: dict[str, str] = {}
    for numero in (origen, destino):
        if not numero:
            continue
        nombre = (del_indice(numero) if del_indice else "") or (
            de_la_memoria(numero) if de_la_memoria else ""
        )
        if nombre:
            nombres[numero] = nombre
    return nombres
