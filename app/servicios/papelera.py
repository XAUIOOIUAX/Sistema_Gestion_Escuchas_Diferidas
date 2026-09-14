"""Papelera de comunicaciones: borrar sin perder.

Eliminar una comunicación de una causa es deshacer una carga equivocada —el
mismo día importado dos veces desde carpetas distintas, una entrega que no era
de esta causa—, no depurar material. Pero el error inverso también existe: se
borra la selección equivocada, y en un expediente eso no puede ser definitivo.

La fila SALE de `Registro` y se guarda entera en `Papelera`, con sus hijos:
historial de cambios, marcas de audio y avisos de validación. Restaurar la
devuelve tal cual estaba. El borrado lógico —una columna "eliminado" y un
filtro en cada consulta— se descartó a propósito: hay 29 consultas distintas
sobre Registro y olvidarse de filtrar en una sola haría reaparecer una
comunicación borrada en un informe judicial.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field

from app import repositorios as repo
from app import sesion

# Hijos que se llevan y se traen junto con la comunicación. La clave es el
# nombre de la tabla; el valor, la columna que apunta al registro.
_HIJOS = {
    "HistorialCambio": "registro_id",
    "MarcaAudio": "registro_id",
    "AvisoValidacion": "registro_id",
}


@dataclass
class ResultadoRestauracion:
    restauradas: int = 0
    # Comunicaciones que no se pudieron devolver porque volvieron a importarse
    # mientras estaban en la papelera: la causa ya tiene esa comunicación.
    ya_existentes: list[str] = field(default_factory=list)


def _fila_a_dict(fila: sqlite3.Row) -> dict:
    return {clave: fila[clave] for clave in fila.keys()}


def _resumen(fila: sqlite3.Row) -> str:
    """Una línea legible, para no tener que abrir el JSON al mirar la papelera."""
    partes = [
        f"Nº {fila['orden']}" if fila["orden"] else "",
        f"{fila['origen'] or '?'} → {fila['destino'] or '?'}",
        fila["fecha_inicio_texto"] or "",
    ]
    return "   ".join(p for p in partes if p)


def enviar(
    con: sqlite3.Connection,
    caso_id: int,
    registro_ids: list[int],
    usuario: str | None = None,
) -> str:
    """Manda las comunicaciones a la papelera. Devuelve el identificador del lote.

    El lote agrupa lo borrado en una misma acción, que es lo que permite
    deshacer "lo último que hice" de un saque.
    """
    usuario = sesion.o_analista(usuario)
    ids = [int(i) for i in registro_ids]
    if not ids:
        return ""

    marcadores = ",".join("?" for _ in ids)
    filas = con.execute(
        f"SELECT * FROM Registro WHERE caso_id = ? AND id IN ({marcadores})",
        (caso_id, *ids),
    ).fetchall()
    if not filas:
        return ""

    lote = uuid.uuid4().hex[:12]
    for fila in filas:
        datos = {"registro": _fila_a_dict(fila), "hijos": {}}
        for tabla, columna in _HIJOS.items():
            datos["hijos"][tabla] = [
                _fila_a_dict(h)
                for h in con.execute(
                    f"SELECT * FROM {tabla} WHERE {columna} = ?", (fila["id"],)
                )
            ]
        con.execute(
            """
            INSERT INTO Papelera
                (caso_id, registro_id, orden, resumen, datos_json, lote, usuario)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                caso_id, fila["id"], fila["orden"], _resumen(fila),
                json.dumps(datos, ensure_ascii=False), lote, usuario,
            ),
        )

    con.execute(
        f"DELETE FROM Registro WHERE caso_id = ? AND id IN ({marcadores})",
        (caso_id, *ids),
    )
    repo.log_auditoria(
        con,
        "papelera_enviar",
        f"{len(filas)} comunicaciones a la papelera (lote {lote}): "
        + "; ".join(_resumen(f) for f in filas),
        caso_id,
        usuario,
    )
    con.commit()
    return lote


def listar(con: sqlite3.Connection, caso_id: int) -> list[sqlite3.Row]:
    """Contenido de la papelera de la causa, lo último primero."""
    return con.execute(
        "SELECT * FROM Papelera WHERE caso_id = ? ORDER BY fecha DESC, id DESC",
        (caso_id,),
    ).fetchall()


def contar(con: sqlite3.Connection, caso_id: int) -> int:
    return con.execute(
        "SELECT COUNT(*) AS n FROM Papelera WHERE caso_id = ?", (caso_id,)
    ).fetchone()["n"]


def ultimo_lote(con: sqlite3.Connection, caso_id: int) -> str:
    """Identificador de lo último que se mandó a la papelera, o ''."""
    fila = con.execute(
        "SELECT lote FROM Papelera WHERE caso_id = ? ORDER BY id DESC LIMIT 1",
        (caso_id,),
    ).fetchone()
    return (fila["lote"] or "") if fila else ""


def _insertar_de_vuelta(con: sqlite3.Connection, datos: dict) -> int:
    """Reinserta la comunicación y sus hijos. Devuelve el id nuevo, o -1."""
    registro = dict(datos.get("registro") or {})
    registro.pop("id", None)
    columnas = ", ".join(registro)
    marcadores = ", ".join("?" for _ in registro)
    try:
        cur = con.execute(
            f"INSERT INTO Registro ({columnas}) VALUES ({marcadores})",
            tuple(registro.values()),
        )
    except sqlite3.IntegrityError:
        # La comunicación volvió a importarse mientras estaba en la papelera:
        # la causa ya la tiene y meterla de nuevo la duplicaría.
        return -1

    nuevo_id = int(cur.lastrowid)
    for tabla, columna in _HIJOS.items():
        for hijo in datos.get("hijos", {}).get(tabla, []):
            hijo = dict(hijo)
            hijo.pop("id", None)
            hijo[columna] = nuevo_id
            cols = ", ".join(hijo)
            marks = ", ".join("?" for _ in hijo)
            try:
                con.execute(
                    f"INSERT INTO {tabla} ({cols}) VALUES ({marks})",
                    tuple(hijo.values()),
                )
            except sqlite3.IntegrityError:
                continue  # un hijo perdido no puede impedir la restauración
    return nuevo_id


def restaurar(
    con: sqlite3.Connection,
    caso_id: int,
    papelera_ids: list[int],
    usuario: str | None = None,
) -> ResultadoRestauracion:
    """Devuelve a la causa las comunicaciones elegidas de la papelera."""
    usuario = sesion.o_analista(usuario)
    resultado = ResultadoRestauracion()
    ids = [int(i) for i in papelera_ids]
    if not ids:
        return resultado

    marcadores = ",".join("?" for _ in ids)
    filas = con.execute(
        f"SELECT * FROM Papelera WHERE caso_id = ? AND id IN ({marcadores})",
        (caso_id, *ids),
    ).fetchall()

    devueltos: list[int] = []
    for fila in filas:
        try:
            datos = json.loads(fila["datos_json"])
        except (ValueError, TypeError):
            resultado.ya_existentes.append(fila["resumen"] or f"#{fila['id']}")
            continue
        if _insertar_de_vuelta(con, datos) == -1:
            resultado.ya_existentes.append(fila["resumen"] or f"#{fila['id']}")
            continue
        devueltos.append(fila["id"])
        resultado.restauradas += 1

    if devueltos:
        vaciar_marcadores = ",".join("?" for _ in devueltos)
        con.execute(
            f"DELETE FROM Papelera WHERE id IN ({vaciar_marcadores})",
            tuple(devueltos),
        )
        repo.log_auditoria(
            con,
            "papelera_restaurar",
            f"{resultado.restauradas} comunicaciones restauradas desde la papelera",
            caso_id,
            usuario,
        )
    con.commit()
    return resultado


def restaurar_lote(
    con: sqlite3.Connection, caso_id: int, lote: str, usuario: str | None = None
) -> ResultadoRestauracion:
    """Deshace de un saque todo lo borrado en una misma acción."""
    if not lote:
        return ResultadoRestauracion()
    ids = [
        f["id"]
        for f in con.execute(
            "SELECT id FROM Papelera WHERE caso_id = ? AND lote = ?", (caso_id, lote)
        )
    ]
    return restaurar(con, caso_id, ids, usuario)


def vaciar(
    con: sqlite3.Connection,
    caso_id: int,
    papelera_ids: list[int] | None = None,
    usuario: str | None = None,
) -> int:
    """Borra definitivamente. Sin `papelera_ids`, vacía la papelera entera.

    Es el único punto del programa donde una comunicación deja de existir. El
    log de auditoría conserva la constancia de qué se sacó.
    """
    usuario = sesion.o_analista(usuario)
    if papelera_ids is None:
        filas = con.execute(
            "SELECT id, resumen FROM Papelera WHERE caso_id = ?", (caso_id,)
        ).fetchall()
    else:
        ids = [int(i) for i in papelera_ids]
        if not ids:
            return 0
        marcadores = ",".join("?" for _ in ids)
        filas = con.execute(
            f"SELECT id, resumen FROM Papelera WHERE caso_id = ? "
            f"AND id IN ({marcadores})",
            (caso_id, *ids),
        ).fetchall()
    if not filas:
        return 0

    marcadores = ",".join("?" for _ in filas)
    con.execute(
        f"DELETE FROM Papelera WHERE id IN ({marcadores})",
        tuple(f["id"] for f in filas),
    )
    repo.log_auditoria(
        con,
        "papelera_vaciar",
        f"{len(filas)} comunicaciones eliminadas definitivamente: "
        + "; ".join(f["resumen"] or "" for f in filas),
        caso_id,
        usuario,
    )
    con.commit()
    return len(filas)
