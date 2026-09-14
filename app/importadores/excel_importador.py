"""Importador de registros desde archivos Excel (.xlsx).

Lee las filas de la hoja TOTAL (o la primera hoja) y las mapea a
RegistroParseado, aplicando la misma normalización/dedup que el importador TXT.
Si hay columna ESTADO en el Excel, se respeta; si no, se asume 'completo'.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook

from app import repositorios as repo
from app.config import VALOR_NO_IDENTIFICADO
from app.core.fechas import parsear_fecha_hora_ar
from app.core.normalizers import generar_clave_dedup, normalizar_numero, titulo_case, valor_seguro
from app.models import EstadoRegistro, RegistroParseado

_MAPEO_COLUMNAS: dict[str, str] = {
    "ORDEN": "_orden",
    "INTERESADO": "interesado",
    "CD": "cd",
    "DIRECCION": "direccion",
    "ORIGEN": "origen",
    "DESTINO": "destino",
    "CORRESPONDE A": "corresponde_a",
    "FECHA INICIO": "fecha_inicio_texto",
    "FECHA FIN": "fecha_fin_texto",
    "ANTENAS": "antenas",
    "LOCALIDAD": "localidad",
    "PROVINCIA": "provincia",
    "LATITUD": "latitud",
    "LONGITUD": "longitud",
    "AZIMUTH": "azimuth",
    "RADIO": "radio",
    "CONTEXTO": "contexto",
    "ARCHIVO AUDIO": "archivo_audio",
    "ESTADO": "estado",
}


@dataclass
class ResultadoExcel:
    nuevos: int = 0
    existentes: int = 0
    error: int = 0

    def como_dict(self) -> dict[str, int]:
        return {"nuevos": self.nuevos, "existentes": self.existentes, "error": self.error}


def _normalizar_encabezado(texto: str) -> str:
    return str(texto).strip().upper().replace("_", " ")


def _leer_filas(path: Path) -> list[dict[str, str]]:
    wb = load_workbook(str(path), read_only=True, data_only=True)
    ws = wb["TOTAL"] if "TOTAL" in wb.sheetnames else wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if len(rows) < 2:
        return []

    encabezados_raw = [_normalizar_encabezado(h or "") for h in rows[0]]
    mapeo_idx: dict[int, str] = {}
    for idx, enc in enumerate(encabezados_raw):
        if enc in _MAPEO_COLUMNAS:
            mapeo_idx[idx] = _MAPEO_COLUMNAS[enc]

    filas: list[dict[str, str]] = []
    for fila in rows[1:]:
        d: dict[str, str] = {}
        for idx, campo in mapeo_idx.items():
            val = fila[idx] if idx < len(fila) else None
            d[campo] = str(val).strip() if val is not None else ""
        filas.append(d)
    return filas


def _fila_a_registro(d: dict[str, str]) -> RegistroParseado:
    origen = normalizar_numero(d.get("origen", ""))
    destino = normalizar_numero(d.get("destino", ""))
    fecha_texto = d.get("fecha_inicio_texto", "")

    estado_txt = d.get("estado", "completo").strip().lower()
    try:
        estado = EstadoRegistro(estado_txt)
    except ValueError:
        estado = EstadoRegistro.COMPLETO

    return RegistroParseado(
        estado=estado,
        cd=d.get("cd", ""),
        direccion=(d.get("direccion", "") or VALOR_NO_IDENTIFICADO).upper(),
        origen=origen,
        destino=destino,
        interesado=d.get("interesado", "") or VALOR_NO_IDENTIFICADO,
        corresponde_a=d.get("corresponde_a", "") or VALOR_NO_IDENTIFICADO,
        fecha_inicio_texto=fecha_texto,
        fecha_fin_texto=d.get("fecha_fin_texto", ""),
        fecha_inicio_dt=parsear_fecha_hora_ar(fecha_texto),
        antenas=valor_seguro(d.get("antenas", "")),
        localidad=titulo_case(d.get("localidad", "")),
        provincia=titulo_case(d.get("provincia", "")),
        latitud=valor_seguro(d.get("latitud", "")),
        longitud=valor_seguro(d.get("longitud", "")),
        azimuth=valor_seguro(d.get("azimuth", "")),
        radio=valor_seguro(d.get("radio", "")),
        contexto=d.get("contexto", ""),
        archivo_audio=d.get("archivo_audio", ""),
        clave_dedup=generar_clave_dedup(origen, destino, fecha_texto),
    )


def importar_desde_excel(
    con: sqlite3.Connection,
    caso_id: int,
    path_excel: str | Path,
    usuario: str | None = None,
) -> ResultadoExcel:
    """Importa registros desde un .xlsx al caso. Devuelve resumen."""
    path = Path(path_excel)
    filas = _leer_filas(path)
    res = ResultadoExcel()
    indice = repo.cargar_indice_abonados(con, caso_id)

    for d in filas:
        try:
            reg = _fila_a_registro(d)
            orden = repo.siguiente_orden(con, caso_id)
            reg_id = repo.insertar_registro(con, caso_id, reg, orden)
            if reg_id == -1:
                res.existentes += 1
                continue
            res.nuevos += 1
            for numero in (reg.origen, reg.destino):
                if numero and numero != VALOR_NO_IDENTIFICADO and numero not in indice:
                    repo.obtener_o_crear_abonado(con, caso_id, numero)
                    indice[numero] = ""
        except Exception:
            res.error += 1

    imp_id = repo.registrar_importacion(con, caso_id, str(path), res.como_dict(), tipo="xlsx")
    repo.log_auditoria(
        con, "importo",
        f"Excel desde {path.name}: {res.nuevos} nuevos, {res.existentes} existentes, "
        f"{res.error} con error (imp #{imp_id})",
        caso_id, usuario,
    )
    con.commit()
    return res
