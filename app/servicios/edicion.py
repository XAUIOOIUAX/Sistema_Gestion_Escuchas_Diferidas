"""Servicio de edición manual de registros con historial de cambios.

Cada edición valida el campo contra una lista blanca, registra el valor anterior
en HistorialCambio (origen_cambio='manual') y deja traza de auditoría. Permite
deshacer cambios puntuales.
"""

from __future__ import annotations

import sqlite3

from app import repositorios as repo
from app.core.colores import NIVELES_INTERES

# Campos editables inline desde la grilla y el panel de detalle (6.3 / 6.3.1).
CAMPOS_EDITABLES: frozenset[str] = frozenset(
    {"corresponde_a", "contexto", "nivel_interes", "transcripcion"}
)


class CampoNoEditable(ValueError):
    """Se intentó editar un campo fuera de la lista blanca."""


def editar_campo(
    con: sqlite3.Connection,
    registro_id: int,
    campo: str,
    valor_nuevo: object,
    usuario: str | None = None,
) -> bool:
    """Edita un campo de un registro y registra el cambio. Devuelve True si cambió.

    Lanza CampoNoEditable si el campo no está permitido o ValueError si el valor
    de nivel_interes no es válido.
    """
    if campo not in CAMPOS_EDITABLES:
        raise CampoNoEditable(f"Campo no editable: {campo}")

    if campo == "nivel_interes" and valor_nuevo not in NIVELES_INTERES:
        raise ValueError(f"Nivel de interés inválido: {valor_nuevo!r}")

    registro = repo.obtener_registro(con, registro_id)
    if registro is None:
        raise ValueError(f"Registro inexistente: {registro_id}")

    valor_anterior = registro[campo]
    if (valor_anterior or "") == (valor_nuevo or ""):
        return False  # sin cambios

    repo.actualizar_campo_registro(con, registro_id, campo, valor_nuevo)
    repo.registrar_historial_cambio(
        con, registro_id, campo, valor_anterior, valor_nuevo, "manual", usuario
    )
    repo.log_auditoria(
        con,
        "edito",
        f"Registro #{registro_id}: {campo} '{valor_anterior}' -> '{valor_nuevo}'",
        registro["caso_id"],
        usuario,
    )
    con.commit()
    return True


def deshacer_ultimo_cambio(
    con: sqlite3.Connection, registro_id: int, usuario: str | None = None
) -> bool:
    """Revierte el último cambio manual del registro a su valor anterior."""
    historial = repo.historial_de_registro(con, registro_id)
    ultimo = next((h for h in historial if h["origen_cambio"] == "manual"), None)
    if ultimo is None:
        return False
    campo = ultimo["campo"]
    if campo not in CAMPOS_EDITABLES:
        return False
    repo.actualizar_campo_registro(con, registro_id, campo, ultimo["valor_anterior"])
    repo.registrar_historial_cambio(
        con,
        registro_id,
        campo,
        ultimo["valor_nuevo"],
        ultimo["valor_anterior"],
        "manual",
        usuario,
    )
    con.commit()
    return True
