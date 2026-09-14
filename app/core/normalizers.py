"""Normalización de números de abonado, claves de campo y texto.

Corrige BUG-02 del .bas: la eliminación de acentos ya NO usa un mapeo manual
posicional de caracteres (que ante corrupción de encoding podía colapsar todas
las vocales a "a"), sino unicodedata.normalize('NFKD') + filtrado de marcas
diacríticas combinantes.
"""

from __future__ import annotations

import hashlib
import unicodedata

from app.config import VALOR_NO_IDENTIFICADO


def quitar_acentos(texto: str) -> str:
    """Quita tildes y diéresis preservando la letra base (BUG-02).

    Usa descomposición canónica NFKD y descarta las marcas combinantes (Mn),
    de modo que 'á' -> 'a', 'ñ' -> 'n', sin mapeos manuales frágiles.
    """
    if not texto:
        return ""
    descompuesto = unicodedata.normalize("NFKD", texto)
    sin_marcas = "".join(
        c for c in descompuesto if not unicodedata.combining(c)
    )
    # 'ñ' descompone a 'n' + tilde combinante; queda cubierto arriba.
    return sin_marcas


def normalizar_numero(texto: str) -> str:
    """Normaliza un número de abonado argentino a su forma canónica.

    - elimina espacios, guiones y paréntesis
    - quita prefijo internacional '+54' o '54' al inicio
    - quita '9' inicial (indicador de móvil) tras lo anterior
    - quita '0' inicial (característica) tras lo anterior

    La prestadora entrega los números ya en la forma canónica —'3875550023',
    sin prefijo, sin el '15' del formato local y sin separadores—, así que
    sobre lo importado esta función no hace nada. Lo que limpia es lo que se
    teclea a mano en el Índice o en «corresponde a», que es de donde salen las
    variantes. No hay que agregarle manejo del '15': no aparece en los datos, y
    para ubicarlo haría falta saber dónde termina la característica, que sin
    una tabla de códigos de área es adivinar comiéndose dígitos buenos.

    Los separadores se sacan PRIMERO, y el orden importa: pelando los prefijos
    antes, '+54 9 3875550023' quedaba en ' 9 3875550023', que no empieza con
    '9' sino con un espacio, así que el indicador de móvil sobrevivía y el
    mismo número daba '93875550023' escrito con espacios y '3875550023'
    escrito sin ellos. Dos identidades para una línea rompen la deduplicación,
    el cruce con el Índice, la memoria «corresponde a» y los nodos del Grafo.
    """
    if texto is None:
        return ""
    t = str(texto).strip()
    if not t:
        return ""

    for ch in (" ", "-", "(", ")", ".", "\t"):
        t = t.replace(ch, "")

    if t.startswith("+54"):
        t = t[3:]
    elif t.startswith("54"):
        t = t[2:]

    if t.startswith("9"):
        t = t[1:]
    if t.startswith("0"):
        t = t[1:]

    return t


def normalizar_clave_campo(texto: str) -> str:
    """Normaliza la clave (parte izquierda) de una línea 'clave: valor' del TXT.

    - recorta espacios y tabs
    - elimina el ruido 'DATOS DE LA CELDA' (case-insensitive)
    - pasa a minúsculas
    - quita acentos (NFKD)
    """
    if texto is None:
        return ""
    t = str(texto).strip().replace("\t", " ")
    # Eliminar substring de ruido, case-insensitive.
    bajo = t.lower()
    ruido = "datos de la celda"
    idx = bajo.find(ruido)
    while idx != -1:
        t = t[:idx] + t[idx + len(ruido):]
        bajo = t.lower()
        idx = bajo.find(ruido)
    t = quitar_acentos(t.lower())
    return t.strip()


def titulo_case(texto: str) -> str:
    """Capitaliza la primera letra de cada palabra ('salta capital' -> 'Salta Capital')."""
    if not texto:
        return ""
    palabras = texto.strip().lower().split(" ")
    return " ".join(p[:1].upper() + p[1:] if p else p for p in palabras)


def valor_seguro(texto: str | None) -> str:
    """Devuelve 'NO IDENTIFICADO' si el valor está vacío o solo espacios."""
    if texto is None or not str(texto).strip():
        return VALOR_NO_IDENTIFICADO
    return str(texto)


def generar_clave_dedup(origen: str, destino: str, fecha_inicio_texto: str) -> str:
    """Genera una clave de deduplicación estable a partir de los campos clave.

    Usa los números normalizados + el texto de fecha tal cual viene del TXT.
    Devuelve un hash sha256 truncado (legible y de longitud fija).
    """
    base = "|".join(
        (
            normalizar_numero(origen or ""),
            normalizar_numero(destino or ""),
            (fecha_inicio_texto or "").strip(),
        )
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]
