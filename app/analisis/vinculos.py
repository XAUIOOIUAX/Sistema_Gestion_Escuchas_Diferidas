"""Detección de vínculos entre casos (pseudocódigo 5.1).

Identifica abonados compartidos y registros con misma antena+cercanía horaria
entre dos casos. Los vínculos se crean como candidatos no confirmados para
revisión manual del analista.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta


def detectar_vinculos_entre_casos(
    con: sqlite3.Connection,
    caso_id_a: int,
    caso_id_b: int,
    ventana_minutos: int = 120,
) -> list[int]:
    """Detecta vínculos potenciales y los inserta. Devuelve lista de ids creados."""
    ids_creados = []

    abonados_a = {
        r["numero_normalizado"]
        for r in con.execute(
            "SELECT numero_normalizado FROM Abonado WHERE caso_id = ?", (caso_id_a,)
        )
    }
    abonados_b = {
        r["numero_normalizado"]
        for r in con.execute(
            "SELECT numero_normalizado FROM Abonado WHERE caso_id = ?", (caso_id_b,)
        )
    }
    comunes = abonados_a & abonados_b
    for numero in comunes:
        cur = con.execute(
            """
            INSERT INTO VinculoDetectado (caso_id_a, caso_id_b, tipo, detalle_json)
            VALUES (?, ?, 'mismo_abonado', ?)
            """,
            (caso_id_a, caso_id_b, json.dumps({"numero": numero})),
        )
        ids_creados.append(int(cur.lastrowid))

    regs_a = con.execute(
        """
        SELECT id, antenas, fecha_inicio_dt FROM Registro
        WHERE caso_id = ? AND antenas IS NOT NULL AND antenas != ''
          AND fecha_inicio_dt IS NOT NULL
        """,
        (caso_id_a,),
    ).fetchall()

    regs_b = con.execute(
        """
        SELECT id, antenas, fecha_inicio_dt FROM Registro
        WHERE caso_id = ? AND antenas IS NOT NULL AND antenas != ''
          AND fecha_inicio_dt IS NOT NULL
        """,
        (caso_id_b,),
    ).fetchall()

    ventana = timedelta(minutes=ventana_minutos)
    ya_vinculados: set[tuple[int, int]] = set()

    for ra in regs_a:
        try:
            dt_a = datetime.fromisoformat(ra["fecha_inicio_dt"])
        except (ValueError, TypeError):
            continue
        for rb in regs_b:
            if (ra["id"], rb["id"]) in ya_vinculados:
                continue
            if ra["antenas"] != rb["antenas"]:
                continue
            try:
                dt_b = datetime.fromisoformat(rb["fecha_inicio_dt"])
            except (ValueError, TypeError):
                continue
            if abs(dt_a - dt_b) <= ventana:
                ya_vinculados.add((ra["id"], rb["id"]))
                cur = con.execute(
                    """
                    INSERT INTO VinculoDetectado (caso_id_a, caso_id_b, tipo, detalle_json)
                    VALUES (?, ?, 'misma_antena_cercania_horaria', ?)
                    """,
                    (
                        caso_id_a, caso_id_b,
                        json.dumps({
                            "antena": ra["antenas"],
                            "registro_a": ra["id"],
                            "registro_b": rb["id"],
                            "diferencia_minutos": int(abs(dt_a - dt_b).total_seconds() / 60),
                        }),
                    ),
                )
                ids_creados.append(int(cur.lastrowid))

    con.commit()
    return ids_creados


def confirmar_vinculo(con: sqlite3.Connection, vinculo_id: int) -> None:
    con.execute(
        """
        UPDATE VinculoDetectado
        SET confirmado = 1, fecha_confirmacion = datetime('now','localtime')
        WHERE id = ?
        """,
        (vinculo_id,),
    )
    con.commit()


def descartar_vinculo(con: sqlite3.Connection, vinculo_id: int) -> None:
    con.execute("DELETE FROM VinculoDetectado WHERE id = ?", (vinculo_id,))
    con.commit()


def listar_vinculos(
    con: sqlite3.Connection, caso_id: int
) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT * FROM VinculoDetectado
        WHERE caso_id_a = ? OR caso_id_b = ?
        ORDER BY confirmado DESC, fecha_deteccion DESC
        """,
        (caso_id, caso_id),
    ).fetchall()
