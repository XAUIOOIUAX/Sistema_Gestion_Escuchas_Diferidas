"""Importador de registros desde otra base SQLite (Fase 5, ítem 18).

Abre la base externa en modo solo lectura, lee los registros del caso origen
y los inserta en el caso destino, verificando dedup por clave.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app import repositorios as repo
from app.config import VALOR_NO_IDENTIFICADO
from app.models import EstadoRegistro, RegistroParseado

_CAMPOS_REGISTRO = [
    "interesado", "cd", "direccion", "origen", "destino", "corresponde_a",
    "fecha_inicio_texto", "fecha_fin_texto", "fecha_inicio_dt",
    "antenas", "localidad", "provincia", "latitud", "longitud",
    "azimuth", "radio", "contexto", "archivo_audio", "archivo_txt",
    "estado", "clave_dedup",
]


@dataclass
class ResultadoDB:
    nuevos: int = 0
    existentes: int = 0
    error: int = 0
    casos_origen: int = 0

    def como_dict(self) -> dict[str, int]:
        return {"nuevos": self.nuevos, "existentes": self.existentes, "error": self.error}


def listar_casos_externos(path_db: str | Path) -> list[dict[str, object]]:
    """Lista los casos disponibles en la base externa (nombre + id + conteo)."""
    con_ext = sqlite3.connect(f"file:{path_db}?mode=ro", uri=True)
    con_ext.row_factory = sqlite3.Row
    try:
        filas = con_ext.execute(
            """
            SELECT c.id, c.nombre,
                   (SELECT COUNT(*) FROM Registro r WHERE r.caso_id = c.id) AS n_registros
            FROM Caso c
            ORDER BY c.id
            """
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        con_ext.close()


def _fila_a_registro(row: sqlite3.Row) -> RegistroParseado:
    def val(campo: str) -> str:
        v = row[campo]
        return str(v).strip() if v is not None else ""

    estado_txt = val("estado") or "completo"
    try:
        estado = EstadoRegistro(estado_txt)
    except ValueError:
        estado = EstadoRegistro.COMPLETO

    from datetime import datetime
    dt = None
    raw_dt = val("fecha_inicio_dt")
    if raw_dt:
        try:
            dt = datetime.fromisoformat(raw_dt)
        except ValueError:
            pass

    return RegistroParseado(
        estado=estado,
        cd=val("cd"),
        direccion=val("direccion") or VALOR_NO_IDENTIFICADO,
        origen=val("origen"),
        destino=val("destino"),
        interesado=val("interesado") or VALOR_NO_IDENTIFICADO,
        corresponde_a=val("corresponde_a") or VALOR_NO_IDENTIFICADO,
        fecha_inicio_texto=val("fecha_inicio_texto"),
        fecha_fin_texto=val("fecha_fin_texto"),
        fecha_inicio_dt=dt,
        antenas=val("antenas"),
        localidad=val("localidad"),
        provincia=val("provincia"),
        latitud=val("latitud"),
        longitud=val("longitud"),
        azimuth=val("azimuth"),
        radio=val("radio"),
        contexto=val("contexto"),
        archivo_audio=val("archivo_audio"),
        archivo_txt=val("archivo_txt") or None,
        clave_dedup=val("clave_dedup"),
    )


def fusionar_base_externa(
    con: sqlite3.Connection,
    caso_id_destino: int,
    path_db: str | Path,
    caso_id_origen: int | None = None,
    usuario: str | None = None,
) -> ResultadoDB:
    """Importa registros de una base SQLite externa al caso destino.

    Si `caso_id_origen` es None, importa de todos los casos.
    """
    path = Path(path_db)
    con_ext = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con_ext.row_factory = sqlite3.Row

    res = ResultadoDB()
    indice = repo.cargar_indice_abonados(con, caso_id_destino)

    try:
        if caso_id_origen is not None:
            registros = con_ext.execute(
                "SELECT * FROM Registro WHERE caso_id = ? ORDER BY orden",
                (caso_id_origen,),
            ).fetchall()
            res.casos_origen = 1
        else:
            registros = con_ext.execute("SELECT * FROM Registro ORDER BY caso_id, orden").fetchall()
            res.casos_origen = con_ext.execute("SELECT COUNT(DISTINCT caso_id) AS n FROM Registro").fetchone()["n"]

        for row in registros:
            try:
                reg = _fila_a_registro(row)
                if not reg.clave_dedup:
                    res.error += 1
                    continue
                orden = repo.siguiente_orden(con, caso_id_destino)
                reg_id = repo.insertar_registro(con, caso_id_destino, reg, orden)
                if reg_id == -1:
                    res.existentes += 1
                    continue
                res.nuevos += 1
                for numero in (reg.origen, reg.destino):
                    if numero and numero != VALOR_NO_IDENTIFICADO and numero not in indice:
                        repo.obtener_o_crear_abonado(con, caso_id_destino, numero)
                        indice[numero] = ""
            except Exception:
                res.error += 1
    finally:
        con_ext.close()

    imp_id = repo.registrar_importacion(con, caso_id_destino, str(path), res.como_dict(), tipo="db")
    repo.log_auditoria(
        con, "importo",
        f"DB desde {path.name}: {res.nuevos} nuevos, {res.existentes} existentes, "
        f"{res.error} con error, {res.casos_origen} caso(s) origen (imp #{imp_id})",
        caso_id_destino, usuario,
    )
    con.commit()
    return res
