"""Saneo e inferencia de la dirección de la comunicación.

Dirección posible: ENTRANTE / SALIENTE / ENTRE ABONADOS / NO IDENTIFICADO.
"""

from __future__ import annotations

from app.config import VALOR_NO_IDENTIFICADO

ENTRANTE = "ENTRANTE"
SALIENTE = "SALIENTE"
ENTRE_ABONADOS = "ENTRE ABONADOS"


def sanear_direccion(texto: str | None) -> str:
    """Normaliza un texto de dirección a una de las etiquetas canónicas.

    Si el texto contiene 'ENTRANTE' o 'SALIENTE' (case-insensitive) devuelve la
    etiqueta correspondiente; en otro caso 'NO IDENTIFICADO'.
    """
    t = (texto or "").upper().strip()
    if "ENTRANTE" in t:
        return ENTRANTE
    if "SALIENTE" in t:
        return SALIENTE
    return VALOR_NO_IDENTIFICADO


def inferir_direccion_por_interesado(
    interesado_origen: str, interesado_destino: str
) -> str:
    """Infiere la dirección según qué extremos están identificados como interesados.

    - solo origen identificado  -> SALIENTE
    - solo destino identificado -> ENTRANTE
    - ambos identificados       -> ENTRE ABONADOS
    - ninguno                   -> NO IDENTIFICADO
    """
    ori = bool((interesado_origen or "").strip())
    des = bool((interesado_destino or "").strip())
    if ori and not des:
        return SALIENTE
    if des and not ori:
        return ENTRANTE
    if ori and des:
        return ENTRE_ABONADOS
    return VALOR_NO_IDENTIFICADO
