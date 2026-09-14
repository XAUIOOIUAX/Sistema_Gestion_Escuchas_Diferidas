"""Lectura y parseo de archivos .txt de transcripción a diccionario clave->valor.

Replica el parser del .bas (robusto a UTF-8/ANSI y a variantes unicode de los
dos puntos) con las mejoras de normalización del pseudocódigo.
"""

from __future__ import annotations

from pathlib import Path

from app.config import ENCODINGS_TXT
from app.core.normalizers import normalizar_clave_campo

# Variantes unicode de ':' que pueden aparecer en datos copiados (full-width,
# ratio, etc.) y que se normalizan al ':' ASCII antes de partir la línea.
_COLONS_UNICODE = ("：", "∶", "﹕", "︓")


def leer_archivo_texto(path: str | Path) -> str:
    """Lee un archivo de texto probando varios encodings (UTF-8 BOM, UTF-8, latin-1).

    Devuelve el contenido como str, o '' si no se pudo leer.
    """
    datos: bytes
    try:
        datos = Path(path).read_bytes()
    except OSError:
        return ""
    for enc in ENCODINGS_TXT:
        try:
            return reparar_mojibake(datos.decode(enc))
        except (UnicodeDecodeError, LookupError):
            continue
    # Último recurso: decodificar ignorando bytes inválidos.
    return reparar_mojibake(datos.decode("utf-8", errors="ignore"))


def reparar_mojibake(texto: str) -> str:
    """Repara los acentos de un archivo con encodings mezclados.

    Los archivos de SMS de la prestadora vienen mixtos: el encabezado en cp1252
    (la "ó" de "información" es el byte ó, inválido en UTF-8) y el cuerpo de
    los mensajes en UTF-8. Al probar UTF-8 sobre el archivo entero falla en el
    encabezado y se cae a latin-1 para todo, así que el contenido —que sí era
    UTF-8— queda con "más" convertido en "mÃ¡s". En la causa de prueba eran 11
    de 46 mensajes, y el error llegaba tal cual al informe judicial.

    La reparación va renglón por renglón porque cada renglón viene de una sola
    fuente: se re-codifica a cp1252 y se decodifica como UTF-8, y solo se acepta
    si las dos operaciones salen bien. Un renglón sano no tiene los caracteres
    delatores y ni se toca; uno que no se pueda reparar queda como estaba.
    """
    if "Ã" not in texto and "Â" not in texto:
        return texto
    reparadas = []
    for linea in texto.splitlines(keepends=True):
        if "Ã" in linea or "Â" in linea:
            try:
                linea = linea.encode("cp1252").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
        reparadas.append(linea)
    return "".join(reparadas)


def _normalizar_colons(linea: str) -> str:
    for c in _COLONS_UNICODE:
        linea = linea.replace(c, ":")
    return linea


def parsear_txt_a_diccionario(path: str | Path) -> dict[str, str]:
    """Parsea un TXT 'clave: valor' a un diccionario normalizado.

    - normaliza saltos de línea (CRLF/CR -> LF)
    - normaliza variantes unicode de ':'
    - usa la primera aparición de ':' como separador
    - normaliza la clave (minúsculas, sin acentos, sin ruido)
    Devuelve {} si no se extrajo ninguna clave útil.
    """
    texto = leer_archivo_texto(path)
    if not texto:
        return {}

    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    resultado: dict[str, str] = {}

    for linea in texto.split("\n"):
        ln = linea.strip()
        if not ln:
            continue
        ln = _normalizar_colons(ln)
        pos = ln.find(":")
        if pos <= 0:
            continue
        clave = normalizar_clave_campo(ln[:pos])
        valor = ln[pos + 1:].strip()
        if clave:
            resultado[clave] = valor

    return resultado


def get_val(d: dict[str, str], clave: str) -> str:
    """Devuelve el valor recortado para la clave, o '' si no existe."""
    return (d.get(clave) or "").strip()


def get_val_multi(d: dict[str, str], *claves: str) -> str:
    """Devuelve el primer valor no vacío entre varias claves alternativas."""
    for clave in claves:
        v = (d.get(clave) or "").strip()
        if v:
            return v
    return ""
