"""Servicio de importación de carpetas TXT/audio a un caso.

Orquesta el escaneo previo (txt_importador) y la escritura efectiva en la base
(repositorios), implementando importar_carpeta_confirmado() del pseudocódigo:
crea registros, asigna colores a abonados nuevos, genera avisos de validación
para los huérfanos y deja traza en HistorialImportacion + LogAuditoria.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app import repositorios as repo
from app.config import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN, VALOR_NO_IDENTIFICADO
from app.core.cd_extractor import extraer_cd_de_path
from app.importadores.datos_causa import IndiceCDs, duraciones_de_carpeta
from app.importadores.sms_importador import buscar_archivos_sms, parsear_sms
from app.importadores.txt_importador import (
    escanear_carpeta_preview,
    extraer_registro_de_txt,
    registro_audio_huerfano,
)
from app.importadores.txt_parser import parsear_txt_a_diccionario
from app.models import EstadoRegistro, ItemPreview, RegistroParseado, ResumenPreview


@dataclass
class ResultadoImportacion:
    nuevos: int = 0
    existentes: int = 0
    error: int = 0
    audio_faltante: int = 0
    txt_faltante: int = 0
    sms: int = 0
    # Segundas capturas de una comunicación ya importada: no son nuevas
    # comunicaciones, son otro audio de la misma.
    audio_alternativo: int = 0

    def como_dict(self) -> dict[str, int]:
        return {
            "nuevos": self.nuevos,
            "existentes": self.existentes,
            "error": self.error,
            "audio_faltante": self.audio_faltante,
            "txt_faltante": self.txt_faltante,
            "audio_alternativo": self.audio_alternativo,
            "sms": self.sms,
        }


def preview_importacion(
    con: sqlite3.Connection, caso_id: int, ruta_raiz: str | Path
) -> ResumenPreview:
    """Escaneo previo que clasifica contra los registros ya existentes del caso."""
    existentes = repo.claves_dedup_existentes(con, caso_id)
    resumen = escanear_carpeta_preview(ruta_raiz, claves_existentes=existentes)
    resumen.sms = sum(
        len(parsear_sms(p)) for p in buscar_archivos_sms(ruta_raiz)
    )
    return resumen


def _coordenadas_sospechosas(reg: RegistroParseado) -> bool:
    """True si lat/lon caen fuera del bounding box laxo de Argentina."""
    try:
        lat = float(str(reg.latitud).replace(",", "."))
        lon = float(str(reg.longitud).replace(",", "."))
    except (TypeError, ValueError):
        return False
    return not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX)


def importar_carpeta_confirmado(
    con: sqlite3.Connection,
    caso_id: int,
    ruta_raiz: str | Path,
    preview: ResumenPreview,
    *,
    progreso: Callable[[int, int], None] | None = None,
) -> ResultadoImportacion:
    """Escribe en la base los ítems nuevos de un preview confirmado.

    `progreso(actual, total)` es un callback opcional para la barra de progreso
    de la UI.
    """
    res = ResultadoImportacion(existentes=len(preview.existentes))
    indice = repo.cargar_indice_abonados(con, caso_id)

    # Cada entrega trae su propio DatosCausa.txt: de ahí salen el número de CD
    # y las líneas intervenidas de ESA entrega. Los declarados son la unión de
    # todas (el juzgado va levantando líneas, así que la última entrega declara
    # menos que la primera y quedarse con una sola perdería abonados).
    indice_cds = IndiceCDs(ruta_raiz)
    declarados = indice_cds.declarados()

    # Las entregas quedan guardadas: el informe judicial las necesita para
    # encabezar cada sección ("CD NRO. 4 - CD700000002") sin que el analista
    # tenga que acordarse del identificador ni tipearlo.
    for carpeta, datos in indice_cds.por_carpeta.items():
        repo.guardar_cd(
            con, caso_id, datos.cd_numero, datos.cd_id, datos.fecha,
            datos.abonados_declarados, str(carpeta),
        )

    def resolver_cd(path) -> str:
        # Lo que declara el archivo manda; la ruta es el plan B, acotada a la
        # carpeta importada para no salir a buscar números fuera de la causa.
        return indice_cds.cd_para(path) or extraer_cd_de_path(path, ruta_raiz)

    for numero in sorted(declarados):
        repo.obtener_o_crear_abonado(con, caso_id, numero, intervenido=True)
        indice.setdefault(numero, "")

    # Duración exacta de cada audio según los Datos.txt de la prestadora.
    duraciones = duraciones_de_carpeta(ruta_raiz)

    def resolver_interesado(numero: str) -> str:
        return indice.get(numero, "")

    def resolver_corresponde_a(numero: str) -> str:
        return repo.buscar_corresponde_a(con, caso_id, numero)

    total = len(preview.nuevos)
    for idx, item in enumerate(preview.nuevos, start=1):
        try:
            reg = _materializar(
                item, resolver_interesado, resolver_corresponde_a, resolver_cd
            )
            if reg is None:
                res.error += 1
                continue

            orden = repo.siguiente_orden(con, caso_id)
            reg_id = repo.insertar_registro(con, caso_id, reg, orden)
            if reg_id == -1:
                res.existentes += 1
                # La comunicación ya estaba, pero este archivo puede ser la
                # otra captura (la misma llamada grabada desde la otra línea
                # intervenida): se anota en vez de tirarla.
                if item.path_audio and repo.guardar_audio_alternativo(
                    con, caso_id, reg.clave_dedup, Path(item.path_audio).name
                ):
                    res.audio_alternativo += 1
                continue

            res.nuevos += 1
            if item.abonado_intervenido:
                con.execute(
                    "UPDATE Registro SET abonado_intervenido = ? WHERE id = ?",
                    (item.abonado_intervenido, reg_id),
                )
            _aplicar_duracion(con, reg_id, reg, duraciones)
            _registrar_abonados_nuevos(
                con, caso_id, reg, indice, item.abonado_intervenido, declarados
            )
            _generar_avisos(con, caso_id, reg_id, reg, res)
        except Exception as exc:  # noqa: BLE001 - aislar fallo por ítem
            res.error += 1
            repo.crear_aviso(
                con,
                caso_id,
                "fecha_invalida",
                f"No se pudo importar '{item.nombre_base}': {exc}",
                "Revisar el archivo de origen.",
            )
        finally:
            if progreso:
                progreso(idx, total)

    _importar_sms(
        con, caso_id, ruta_raiz, indice, declarados, res, resolver_cd,
        resolver_interesado, resolver_corresponde_a,
    )

    imp_id = repo.registrar_importacion(con, caso_id, str(ruta_raiz), res.como_dict())
    repo.log_auditoria(
        con,
        "importo",
        f"TXT desde {ruta_raiz}: {res.nuevos} nuevos, {res.existentes} existentes, "
        f"{res.error} con error (imp #{imp_id})",
        caso_id,
    )
    con.commit()
    return res


def _aplicar_duracion(
    con: sqlite3.Connection,
    reg_id: int,
    reg: RegistroParseado,
    duraciones: dict[str, float],
) -> None:
    """Completa duracion_seg con el valor exacto del Datos.txt de la prestadora."""
    nombre = (reg.archivo_audio or "").replace(" (no encontrado)", "").strip().lower()
    seg = duraciones.get(nombre)
    if seg:
        repo.guardar_duracion(con, reg_id, seg)


def _importar_sms(
    con: sqlite3.Connection,
    caso_id: int,
    ruta_raiz,
    indice: dict[str, str],
    declarados: set[str],
    res: ResultadoImportacion,
    resolver_cd=None,
    resolver_interesado=None,
    resolver_corresponde_a=None,
) -> None:
    """Importa los mensajes de las carpetas SMS/ como registros tipo 'sms'."""
    for path_sms in buscar_archivos_sms(ruta_raiz):
        intervenido = _intervenido_de_ruta(path_sms, declarados)
        # Los SMS vienen de la misma entrega que las llamadas y hasta ahora
        # entraban sin CD: quedaban fuera del filtro y del informe por CD.
        cd = resolver_cd(path_sms) if resolver_cd else ""
        for reg in parsear_sms(
            path_sms, resolver_interesado, resolver_corresponde_a, intervenido
        ):
            if cd and not reg.cd:
                reg.cd = cd
            try:
                orden = repo.siguiente_orden(con, caso_id)
                reg_id = repo.insertar_registro(con, caso_id, reg, orden)
                if reg_id == -1:
                    res.existentes += 1
                    continue
                res.sms += 1
                if intervenido:
                    con.execute(
                        "UPDATE Registro SET abonado_intervenido = ? WHERE id = ?",
                        (intervenido, reg_id),
                    )
                _registrar_abonados_nuevos(
                    con, caso_id, reg, indice, intervenido, declarados
                )
            except Exception as exc:  # noqa: BLE001
                res.error += 1
                repo.crear_aviso(
                    con, caso_id, "fecha_invalida",
                    f"No se pudo importar un SMS de '{path_sms.name}': {exc}",
                    "Revisar el archivo SMS de origen.",
                )


def _intervenido_de_ruta(path, declarados: set[str]) -> str:
    """Abonado intervenido según la carpeta del archivo (reutiliza el detector)."""
    from app.importadores.txt_importador import detectar_abonado_intervenido
    detectado = detectar_abonado_intervenido(path)
    return detectado if detectado in declarados or not declarados else detectado


def _materializar(
    item: ItemPreview,
    resolver_interesado,
    resolver_corresponde_a,
    resolver_cd=None,
) -> RegistroParseado | None:
    """Convierte un ItemPreview en un RegistroParseado listo para insertar."""
    if item.estado is EstadoRegistro.TRANSCRIPCION_FALTANTE:
        return registro_audio_huerfano(
            item.path_audio,  # type: ignore[arg-type]
            resolver_cd,
            item.abonado_intervenido,
            resolver_interesado(item.abonado_intervenido)
            if (resolver_interesado and item.abonado_intervenido) else "",
        )

    # completo o audio_faltante -> hay TXT
    d = parsear_txt_a_diccionario(item.path_txt)  # type: ignore[arg-type]
    if not d:
        return None
    nombre_audio = Path(item.path_audio).name if item.path_audio else None
    return extraer_registro_de_txt(
        item.path_txt,
        d,
        item.estado,
        resolver_interesado=resolver_interesado,
        resolver_corresponde_a=resolver_corresponde_a,
        resolver_cd=resolver_cd,
        abonado_intervenido=item.abonado_intervenido,
        nombre_audio=nombre_audio,
    )


def _registrar_abonados_nuevos(
    con: sqlite3.Connection,
    caso_id: int,
    reg: RegistroParseado,
    indice: dict[str, str],
    abonado_intervenido: str,
    declarados: set[str],
) -> None:
    """Crea (con color) los abonados origen/destino y marca el intervenido.

    El abonado intervenido de este registro es el que indica la carpeta
    (`abonado_intervenido`); si por algún motivo no se detectó, se usa el que
    esté entre los declarados en DatosCausa.
    """
    intervenido = abonado_intervenido
    if not intervenido:
        for numero in (reg.origen, reg.destino):
            if numero in declarados:
                intervenido = numero
                break

    for numero in (reg.origen, reg.destino):
        if numero and numero != VALOR_NO_IDENTIFICADO:
            es_interv = numero == intervenido
            if numero not in indice or es_interv:
                repo.obtener_o_crear_abonado(
                    con, caso_id, numero, intervenido=es_interv
                )
                indice[numero] = ""


def _generar_avisos(
    con: sqlite3.Connection,
    caso_id: int,
    reg_id: int,
    reg: RegistroParseado,
    res: ResultadoImportacion,
) -> None:
    """Genera los AvisoValidacion correspondientes al estado/calidad del registro."""
    if reg.estado is EstadoRegistro.AUDIO_FALTANTE:
        res.audio_faltante += 1
        repo.crear_aviso(
            con,
            caso_id,
            "audio_faltante",
            "Se encontró la transcripción pero no el archivo de audio en la carpeta.",
            "Verificar si el audio fue movido, renombrado o no fue descargado aún.",
            registro_id=reg_id,
        )
    elif reg.estado is EstadoRegistro.TRANSCRIPCION_FALTANTE:
        res.txt_faltante += 1
        repo.crear_aviso(
            con,
            caso_id,
            "transcripcion_faltante",
            "Se encontró el archivo de audio pero no su transcripción .txt asociada. "
            "Los metadatos (origen, destino, fechas, antena) no pudieron completarse.",
            "Verificar si la transcripción está pendiente o si el .txt tiene otro nombre/ubicación.",
            registro_id=reg_id,
        )

    if reg.cd and reg.cd.startswith("SIN CD"):
        repo.crear_aviso(
            con,
            caso_id,
            "cd_no_detectado",
            "No se pudo inferir el CD a partir de la ruta del archivo.",
            "Completar el CD manualmente en el registro.",
            registro_id=reg_id,
        )

    if reg.estado is not EstadoRegistro.TRANSCRIPCION_FALTANTE and _coordenadas_sospechosas(reg):
        repo.crear_aviso(
            con,
            caso_id,
            "coordenadas_sospechosas",
            f"Coordenadas fuera del rango esperado (lat={reg.latitud}, lon={reg.longitud}).",
            "Verificar latitud/longitud en el TXT original.",
            registro_id=reg_id,
        )
