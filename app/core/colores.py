"""Paleta automática de colores por abonado.

La asignación a un abonado concreto vive en la capa de datos (necesita contar
los abonados del caso); aquí están las piezas puras: la paleta base, la
selección por índice con generación de variantes, y el realce por nivel de
interés.
"""

from __future__ import annotations

import colorsys
import re

# Paleta categórica bien diferenciable (alineada con los acentos del mockup
# v2). Se evita rojo puro + verde puro juntos por daltonismo.
PALETA_BASE: tuple[str, ...] = (
    "#C97B84",  # rose
    "#5FA8A0",  # teal
    "#9085C9",  # violet
    "#8FAE6B",  # sage
    "#C9A36A",  # sand
    "#6E8CB0",  # slate-blue
    "#D7A53D",  # accent (ámbar)
    "#B5836B",  # terracota
    "#7FA3C4",  # azul claro
    "#A88BBd",  # lila
    "#88B0A6",  # verde agua
    "#C58F9C",  # malva
)

# Niveles de interés válidos (orden ascendente).
# El interés es binario: una comunicación sirve para el expediente o no sirve.
# Antes había bajo/medio/alto, y en la práctica el analista no distingue tres
# grados mientras escucha: decide si la transcribe y si va al informe. Tres
# opciones obligaban a una decisión que después nadie usaba para nada.
NIVELES_INTERES: tuple[str, ...] = ("ninguno", "interes")

_RE_COLOR_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def normalizar_color_hex(valor: str) -> str:
    """Valida un color y lo devuelve como ``#RRGGBB`` en mayúsculas.

    Se normaliza al guardar porque los consumidores comparan y transforman el
    valor crudo (el exportador a Excel hace ``lstrip('#').upper()``), así que
    conviene que todos reciban siempre la misma forma. Lanza ValueError si el
    formato no es el esperado.
    """
    v = (valor or "").strip()
    if v and not v.startswith("#"):
        v = "#" + v
    if not _RE_COLOR_HEX.match(v):
        raise ValueError(f"Color inválido: {valor!r} (se espera #RRGGBB)")
    return v.upper()


def _hex_a_rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _rgb_a_hex(r: float, g: float, b: float) -> str:
    return "#{:02X}{:02X}{:02X}".format(
        max(0, min(255, round(r * 255))),
        max(0, min(255, round(g * 255))),
        max(0, min(255, round(b * 255))),
    )


def ajustar_luminosidad(hex_color: str, factor: float) -> str:
    """Devuelve una variante del color con la luminosidad escalada por `factor`.

    factor < 1 oscurece, factor > 1 aclara. Útil para generar variantes cuando
    se agotan los colores de la paleta base.
    """
    r, g, b = _hex_a_rgb(hex_color)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = max(0.0, min(1.0, l * factor))
    return _rgb_a_hex(*colorsys.hls_to_rgb(h, l, s))


def color_por_indice(indice: int) -> str:
    """Devuelve el color para el N-ésimo abonado del caso (0-based).

    Mientras hay colores base sin usar, los devuelve directamente. Al agotarlos,
    genera variantes ajustando la luminosidad para no repetir colores idénticos
    en casos con muchos abonados.
    """
    n = len(PALETA_BASE)
    base = PALETA_BASE[indice % n]
    vuelta = indice // n
    if vuelta == 0:
        return base
    # Alternar oscurecer / aclarar en vueltas sucesivas.
    factor = 0.78 if vuelta % 2 == 1 else 1.22
    factor = factor ** ((vuelta + 1) // 2)
    return ajustar_luminosidad(base, factor)


def estilo_por_interes(hex_color: str, nivel_interes: str) -> dict[str, object]:
    """Calcula al vuelo el estilo de realce según el nivel de interés.

    NO se persiste un color distinto: el color base del abonado se mantiene y
    esto se recalcula para la visualización (relleno + grosor de borde).
    """
    # Se aceptan los valores viejos (bajo/medio/alto) porque pueden llegar de
    # una base sin migrar o de una importación desde otra causa.
    nivel = (nivel_interes or "ninguno").lower()
    if nivel in ("interes", "alto", "medio", "bajo"):
        return {"color": ajustar_luminosidad(hex_color, 0.82), "borde": 3}
    return {"color": hex_color, "borde": 0}
