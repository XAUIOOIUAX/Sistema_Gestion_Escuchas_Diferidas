"""Parseo de fecha/hora en formato argentino.

IMPORTANTE (pseudocódigo sección 2): el texto original de la fecha se guarda
SIEMPRE tal cual viene del TXT, sin reformatear. El datetime derivado es solo
una copia interna usada para ordenar/filtrar; nunca se muestra en lugar del
original.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.config import OFFSET_HORAS


# Hasta acá un año de dos dígitos es de este siglo; de ahí para arriba, del
# anterior. Es la convención de POSIX y deja lugar a causas de los noventa sin
# fechar en el futuro lo que evidentemente es de ahora.
_CORTE_SIGLO = 68


def _siglo_de(anio: int) -> int:
    """'26' -> 2026, '99' -> 1999.

    Sin esto `datetime(26, 5, 5)` es un año 26 válido: la fecha derivada salía
    casi dos mil años atrás, ordenaba primero en el Timeline y dejaba afuera de
    todo filtro por rango a esa comunicación. Y era invisible, porque lo que se
    muestra es el texto original, que se ve perfecto.
    """
    return anio + (2000 if anio <= _CORTE_SIGLO else 1900)


def parsear_fecha_hora_ar(texto: str) -> datetime | None:
    """Interpreta una fecha/hora argentina y devuelve un datetime, o None.

    Acepta:
      - dd/mm/yyyy [hh:mm[:ss]] [AM/PM]   (formato principal)
      - yyyy/mm/dd [hh:mm[:ss]]           (fallback ISO-ish)
      - separadores '-' o '/' en la fecha

    Aplica OFFSET_HORAS (config) SOLO al datetime derivado. Devuelve None si no
    se puede interpretar (el llamador conserva igual el texto original).
    """
    if texto is None:
        return None
    t = str(texto).strip()
    if not t:
        return None

    t = t.replace("-", "/")
    while "  " in t:
        t = t.replace("  ", " ")

    if " " in t:
        f, _, h = t.partition(" ")
        tiene_hora = True
    else:
        f, h, tiene_hora = t, "", False

    partes_f = f.split("/")
    if len(partes_f) != 3:
        return None

    try:
        if len(partes_f[0]) == 4:  # YYYY/MM/DD
            anio, mes, dia = (int(partes_f[0]), int(partes_f[1]), int(partes_f[2]))
        else:  # DD/MM/YYYY
            dia, mes, anio = (int(partes_f[0]), int(partes_f[1]), int(partes_f[2]))
            if len(partes_f[2]) <= 2:
                anio = _siglo_de(anio)
    except ValueError:
        return None

    hh = mm = ss = 0
    if tiene_hora and h:
        h_up = h.upper()
        ampm = ""
        if "AM" in h_up:
            ampm = "AM"
        elif "PM" in h_up:
            ampm = "PM"
        h_limpia = h_up.replace("AM", "").replace("PM", "").strip()
        partes_h = h_limpia.split(":")
        try:
            if len(partes_h) >= 1 and partes_h[0]:
                hh = int(partes_h[0])
            if len(partes_h) >= 2 and partes_h[1]:
                mm = int(partes_h[1])
            if len(partes_h) >= 3 and partes_h[2]:
                ss = int(partes_h[2])
        except ValueError:
            return None
        if ampm == "PM" and hh < 12:
            hh += 12
        if ampm == "AM" and hh == 12:
            hh = 0

    try:
        dt = datetime(anio, mes, dia, hh, mm, ss)
    except ValueError:
        return None

    if OFFSET_HORAS:
        dt = dt + timedelta(hours=OFFSET_HORAS)

    return dt


def formatear_fecha_ar(dt: datetime | None) -> str:
    """Formatea un datetime a 'dd/mm/yyyy hh:mm:ss', o '' si es None.

    Se usa para presentación derivada, no para reemplazar el texto original.
    """
    if dt is None:
        return ""
    return dt.strftime("%d/%m/%Y %H:%M:%S")
