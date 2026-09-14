"""Módulo de eventos clave (pseudocódigo 5.4).

Permite marcar momentos relevantes en la línea de tiempo del caso y resaltar
los registros cercanos a cada evento dentro de una ventana configurable.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta


def crear_evento(
    con: sqlite3.Connection,
    caso_id: int,
    descripcion: str,
    fecha_hora: str,
    ventana_minutos: int = 120,
) -> int:
    cur = con.execute(
        """
        INSERT INTO EventoClave (caso_id, descripcion, fecha_hora, ventana_minutos)
        VALUES (?, ?, ?, ?)
        """,
        (caso_id, descripcion, fecha_hora, ventana_minutos),
    )
    con.commit()
    return int(cur.lastrowid)


def listar_eventos(con: sqlite3.Connection, caso_id: int) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT * FROM EventoClave WHERE caso_id = ? ORDER BY fecha_hora",
        (caso_id,),
    ).fetchall()


def eliminar_evento(con: sqlite3.Connection, evento_id: int) -> None:
    con.execute("DELETE FROM EventoClave WHERE id = ?", (evento_id,))
    con.commit()


def registros_cerca_de_evento(
    con: sqlite3.Connection, caso_id: int, evento_id: int
) -> list[sqlite3.Row]:
    """Devuelve registros cuya fecha_inicio_dt cae dentro de la ventana del evento."""
    evento = con.execute(
        "SELECT * FROM EventoClave WHERE id = ?", (evento_id,)
    ).fetchone()
    if evento is None:
        return []

    fecha_str = evento["fecha_hora"]
    ventana = evento["ventana_minutos"]

    try:
        dt = datetime.fromisoformat(fecha_str)
    except (ValueError, TypeError):
        for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
            try:
                dt = datetime.strptime(fecha_str, fmt)
                break
            except ValueError:
                continue
        else:
            return []

    inicio = (dt - timedelta(minutes=ventana)).isoformat(sep=" ")
    fin = (dt + timedelta(minutes=ventana)).isoformat(sep=" ")

    return con.execute(
        """
        SELECT r.*, a.color_hex
        FROM Registro r
        LEFT JOIN Abonado a
               ON a.caso_id = r.caso_id
              AND a.numero_normalizado IN (r.origen, r.destino)
        WHERE r.caso_id = ?
          AND r.fecha_inicio_dt IS NOT NULL
          AND r.fecha_inicio_dt BETWEEN ? AND ?
        GROUP BY r.id
        ORDER BY r.fecha_inicio_dt
        """,
        (caso_id, inicio, fin),
    ).fetchall()
