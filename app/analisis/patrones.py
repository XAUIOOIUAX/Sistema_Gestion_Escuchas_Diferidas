"""Módulo de análisis de patrones (pseudocódigo 5.2).

Detecta ráfagas de comunicaciones, horarios atípicos, abonados descartables
y ranking de pares frecuentes.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class Rafaga:
    """Grupo de comunicaciones concentradas en una ventana de tiempo."""
    abonado: str
    inicio: datetime
    fin: datetime
    cantidad: int
    registros_ids: list[int]


@dataclass
class ParFrecuente:
    """Par de abonados con alta frecuencia de comunicación."""
    origen: str
    destino: str
    cantidad: int
    horarios: list[int]


def _registros_abonado(
    con: sqlite3.Connection, caso_id: int, numero: str
) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT * FROM Registro
        WHERE caso_id = ? AND (origen = ? OR destino = ?)
          AND fecha_inicio_dt IS NOT NULL
        ORDER BY fecha_inicio_dt
        """,
        (caso_id, numero, numero),
    ).fetchall()


def detectar_rafagas(
    con: sqlite3.Connection,
    caso_id: int,
    numero: str,
    ventana_minutos: int = 30,
    minimo_comunicaciones: int = 5,
) -> list[Rafaga]:
    """Detecta ráfagas: grupos de N+ comunicaciones en ventana deslizante."""
    registros = _registros_abonado(con, caso_id, numero)
    if len(registros) < minimo_comunicaciones:
        return []

    dts = []
    for r in registros:
        try:
            dts.append((datetime.fromisoformat(r["fecha_inicio_dt"]), r["id"]))
        except (ValueError, TypeError):
            continue

    dts.sort(key=lambda x: x[0])
    rafagas = []
    ventana = timedelta(minutes=ventana_minutos)

    i = 0
    while i < len(dts):
        grupo = [(dts[i][0], dts[i][1])]
        j = i + 1
        while j < len(dts) and (dts[j][0] - dts[i][0]) <= ventana:
            grupo.append((dts[j][0], dts[j][1]))
            j += 1
        if len(grupo) >= minimo_comunicaciones:
            rafagas.append(Rafaga(
                abonado=numero,
                inicio=grupo[0][0],
                fin=grupo[-1][0],
                cantidad=len(grupo),
                registros_ids=[rid for _, rid in grupo],
            ))
            i = j
        else:
            i += 1

    return rafagas


def detectar_horarios_atipicos(
    con: sqlite3.Connection,
    caso_id: int,
    numero: str,
    hora_inicio_normal: int = 7,
    hora_fin_normal: int = 23,
) -> list[sqlite3.Row]:
    """Registros fuera del rango horario normal."""
    registros = _registros_abonado(con, caso_id, numero)
    atipicos = []
    for r in registros:
        try:
            dt = datetime.fromisoformat(r["fecha_inicio_dt"])
        except (ValueError, TypeError):
            continue
        if dt.hour < hora_inicio_normal or dt.hour >= hora_fin_normal:
            atipicos.append(r)
    return atipicos


def detectar_abonado_descartable(
    con: sqlite3.Connection,
    caso_id: int,
    numero: str,
    dias_actividad_max: int = 3,
    umbral_comunicaciones: int = 10,
) -> bool:
    """True si el abonado parece descartable (alta actividad en pocos días)."""
    registros = _registros_abonado(con, caso_id, numero)
    if len(registros) < umbral_comunicaciones:
        return False

    fechas = []
    for r in registros:
        try:
            fechas.append(datetime.fromisoformat(r["fecha_inicio_dt"]))
        except (ValueError, TypeError):
            continue

    if not fechas:
        return False

    rango = (max(fechas) - min(fechas)).days
    return rango <= dias_actividad_max


def ranking_pares_frecuentes(
    con: sqlite3.Connection,
    caso_id: int,
    top_n: int = 10,
) -> list[ParFrecuente]:
    """Top N pares de abonados con más comunicaciones, con horarios habituales."""
    registros = con.execute(
        """
        SELECT origen, destino, fecha_inicio_dt FROM Registro
        WHERE caso_id = ? AND origen != '' AND destino != ''
          AND fecha_inicio_dt IS NOT NULL
        """,
        (caso_id,),
    ).fetchall()

    pares: dict[tuple[str, str], list[int]] = defaultdict(list)
    for r in registros:
        key = tuple(sorted([r["origen"], r["destino"]]))
        try:
            dt = datetime.fromisoformat(r["fecha_inicio_dt"])
            pares[key].append(dt.hour)
        except (ValueError, TypeError):
            pares[key].append(-1)

    resultado = []
    for (o, d), horas in sorted(pares.items(), key=lambda x: len(x[1]), reverse=True)[:top_n]:
        resultado.append(ParFrecuente(
            origen=o, destino=d,
            cantidad=len(horas),
            horarios=sorted(h for h in horas if h >= 0),
        ))

    return resultado
