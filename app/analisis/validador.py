"""Validaciones de calidad de datos (pseudocódigo 5.3).

Funciones que detectan problemas en los registros y devuelven avisos legibles
para el panel de validaciones. Las que operan sobre un único registro son puras;
la detección de duplicados parciales consulta la base.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.config import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN
from app.core.fechas import parsear_fecha_hora_ar


@dataclass
class Aviso:
    """Aviso de validación desacoplado de la base (tipo, descripción, sugerencia)."""

    tipo: str
    descripcion: str
    sugerencia: str


def _a_float(valor: object) -> float | None:
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return None


def coordenadas_sospechosas(latitud: object, longitud: object) -> bool:
    """True si lat/lon caen fuera del bounding box laxo de Argentina."""
    lat, lon = _a_float(latitud), _a_float(longitud)
    if lat is None or lon is None:
        return False
    return not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX)


def validar_datos_parseados(
    origen: str,
    destino: str,
    fecha_inicio_texto: str,
    latitud: object = "",
    longitud: object = "",
) -> list[Aviso]:
    """Valida los datos crudos de un registro y devuelve la lista de avisos."""
    avisos: list[Aviso] = []

    if not (origen or "").strip() and not (destino or "").strip():
        avisos.append(
            Aviso(
                "sin_abonados",
                "El registro no tiene origen ni destino.",
                "Revisar el TXT original; podría ser un archivo descartable.",
            )
        )

    if (fecha_inicio_texto or "").strip() and parsear_fecha_hora_ar(
        fecha_inicio_texto
    ) is None:
        avisos.append(
            Aviso(
                "fecha_invalida",
                f"La fecha de inicio '{fecha_inicio_texto}' no pudo interpretarse.",
                "Verificar el formato de fecha en el TXT original.",
            )
        )

    if coordenadas_sospechosas(latitud, longitud):
        avisos.append(
            Aviso(
                "coordenadas_sospechosas",
                f"Coordenadas fuera del rango esperado (lat={latitud}, lon={longitud}).",
                "Verificar latitud/longitud; podrían estar corruptas.",
            )
        )

    return avisos


def detectar_duplicados_parciales(
    con: sqlite3.Connection,
    caso_id: int,
    origen: str,
    destino: str,
    fecha_inicio_texto: str,
    tolerancia_segundos: int = 120,
) -> list[sqlite3.Row]:
    """Busca registros con mismo origen/destino y fecha cercana (no idéntica).

    Devuelve candidatos a duplicado parcial para revisión manual del analista.
    """
    objetivo = parsear_fecha_hora_ar(fecha_inicio_texto)
    if objetivo is None:
        return []
    candidatos: list[sqlite3.Row] = []
    filas = con.execute(
        """
        SELECT id, orden, fecha_inicio_texto
        FROM Registro
        WHERE caso_id = ? AND origen = ? AND destino = ?
        """,
        (caso_id, origen, destino),
    )
    for r in filas:
        otra = parsear_fecha_hora_ar(r["fecha_inicio_texto"] or "")
        if otra is None:
            continue
        delta = abs((otra - objetivo).total_seconds())
        if 0 < delta <= tolerancia_segundos:
            candidatos.append(r)
    return candidatos
