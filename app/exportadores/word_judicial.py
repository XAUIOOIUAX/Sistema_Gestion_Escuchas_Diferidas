"""Informe Word con formato judicial — réplica exacta del Transcriptor Forense.

Este es el estándar de presentación de informes del organismo: encabezado del
CD suministrado por el Magistrado, un bloque por abonado y, por cada
comunicación: datos de la comunicación, DATOS DE LA CELDA, constancias
formales según el caso, la transcripción con interlocutores numerados y el
cierre "FIN DE LA COMUNICACIÓN." con línea separadora.

El formato replica 1:1 el generador_word.py del Transcriptor Forense
(fuente en SoftwareTranscriptor) y su salida real (informe_intervencion.docx).
Deja traza en LogAuditoria.
"""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from app import sesion
from app import repositorios as repo
from app.exportadores.errores import InformeVacio
from app.servicios.transcripcion import numerar_por_hablante

# Constancias formales (texto exacto del Transcriptor Forense).
_CONSTANCIA_AUDIO_SIN_TXT = (
    "Se deja constancia que el presente archivo de audio no posee "
    "archivo de metadatos asociado, por lo que la transcripción que sigue "
    "fue realizada únicamente sobre el contenido sonoro disponible."
)
_CONSTANCIA_TXT_SIN_AUDIO = (
    "Se deja constancia que se localizó archivo de metadatos asociado a una "
    "comunicación, sin hallarse el correspondiente archivo de audio, razón por "
    "la cual no fue posible efectuar transcripción del contenido sonoro."
)

_RE_LINEA_NUMERADA = re.compile(r"^\d+[\.\)]\s")

_FORMATOS_FECHA = (
    "%d/%m/%Y %H:%M:%S",
    "%d-%m-%Y %H:%M:%S",
    "%d/%m/%Y",
    "%d-%m-%Y",
)


# ---------------------------------------------------------------------------
# Primitivas de documento (mismas que el original)
# ---------------------------------------------------------------------------

def _configurar_estilo_base(doc: Document) -> None:
    estilo = doc.styles["Normal"]
    estilo.font.name = "Arial"
    estilo.font.size = Pt(12)
    pf = estilo.paragraph_format
    pf.line_spacing = 1.15
    pf.space_after = Pt(0)
    pf.space_before = Pt(0)


def _parrafo(doc: Document, texto: str = "", negrita: bool = False):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    run = p.add_run(texto)
    run.bold = negrita
    run.font.name = "Arial"
    run.font.size = Pt(12)
    return p


def _salto(doc: Document) -> None:
    doc.add_paragraph()


def _linea(doc: Document) -> None:
    p = doc.add_paragraph()
    p_pr = p._p.get_or_add_pPr()  # noqa: SLF001 — API de python-docx
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:color"), "000000")
    borders.append(bottom)
    p_pr.append(borders)


# ---------------------------------------------------------------------------
# Helpers de datos
# ---------------------------------------------------------------------------

def _direccion_texto(valor: str | None) -> str:
    """El original imprime la dirección como viene en el txt ('Entrante');
    la app la guarda normalizada en mayúsculas — se restituye el formato."""
    v = (valor or "").strip()
    if not v or v == "NO IDENTIFICADO":
        return v.capitalize() if v else ""
    return v.capitalize()


def _nombre_base(archivo: str | None) -> str:
    if not archivo:
        return ""
    nombre = archivo.replace(" (no encontrado)", "")
    return nombre.rsplit(".", 1)[0]


def _valor(v) -> str:
    v = ("" if v is None else str(v)).strip()
    return "" if v == "NO IDENTIFICADO" else v


# ---------------------------------------------------------------------------
# Bloques del informe (estructura exacta del original)
# ---------------------------------------------------------------------------

def _num_crudo(r: sqlite3.Row, campo: str) -> str:
    """Número tal como vino en el TXT (con prefijo 54, etc.); si no se guardó
    el crudo (importaciones viejas), usa el normalizado."""
    crudo = _valor(r[f"{campo}_crudo"])
    return crudo or _valor(r[campo])


def _datos_comunicacion(doc: Document, r: sqlite3.Row) -> None:
    # Estructura EXACTA del informe estándar (informe_intervencion.docx):
    # Dirección, Origen, Destino, Inicio, Fin. No lleva línea "Duración:".
    _parrafo(doc, f"Dirección: {_direccion_texto(r['direccion'])}")
    _parrafo(doc, f"Origen: {_num_crudo(r, 'origen')}")
    _parrafo(doc, f"Destino: {_num_crudo(r, 'destino')}")
    _parrafo(doc, f"Inicio: {_valor(r['fecha_inicio_texto'])}")
    _parrafo(doc, f"Fin: {_valor(r['fecha_fin_texto'])}")


def _datos_celda(doc: Document, r: sqlite3.Row) -> None:
    _parrafo(doc, "DATOS DE LA CELDA:", negrita=True)
    # Un renglón en blanco entre el rótulo y los datos. Son diez líneas
    # seguidas de "clave: valor"; pegadas al título se leen como un bloque
    # macizo y hay que buscar dónde empieza.
    _salto(doc)
    _parrafo(doc, f"Tecnología: {_valor(r['tecnologia'])}")
    # Datos importados antes de capturar calle/número por separado quedan en
    # 'antenas' (calle + número juntos): se usa como fallback.
    calle = _valor(r["calle"]) or _valor(r["antenas"])
    _parrafo(doc, f"Calle: {calle}")
    _parrafo(doc, f"Número: {_valor(r['numero_calle'])}")
    # La prestadora manda localidad y provincia en mayúsculas y el informe
    # estándar las reproduce así; la importación las pasa a Título para que la
    # grilla se lea mejor. Acá se restituye el original, que es el que tiene que
    # coincidir con el archivo de la prestadora si alguien lo coteja.
    _parrafo(doc, f"Localidad: {_valor(r['localidad']).upper()}")
    _parrafo(doc, f"Provincia: {_valor(r['provincia']).upper()}")
    _parrafo(doc, f"Latitud: {_valor(r['latitud'])}")
    _parrafo(doc, f"Longitud: {_valor(r['longitud'])}")
    _parrafo(doc, f"Azimuth: {_valor(r['azimuth'])}")
    _parrafo(doc, f"Radio Cobertura: {_valor(r['radio'])}")


def _transcripcion(doc: Document, r: sqlite3.Row) -> None:
    _parrafo(doc, "Transcripción:", negrita=True)
    _salto(doc)

    origen = _num_crudo(r, "origen")
    destino = _num_crudo(r, "destino")
    _parrafo(doc, f"1. Llama abonado {origen}" if origen else "1. Llama abonado")
    _parrafo(doc, f"2. Atiende abonado {destino}" if destino else "2. Atiende abonado")
    # Y otro antes del diálogo: las dos primeras líneas dicen QUIÉN es 1 y
    # quién 2, no lo que se dijo. Sin el corte se leen como si fueran las dos
    # primeras frases de la conversación.
    _salto(doc)

    # Con voces atribuidas el informe deja de adivinar: cada renglón lleva el
    # interlocutor que el analista marcó escuchando. Sin atribuir, se alterna
    # como se hacía antes, que es una convención y no un dato.
    segmentos = repo.segmentos_de_registro(r)
    if segmentos:
        for numero, linea in numerar_por_hablante(segmentos):
            texto_linea = (linea or "").strip()
            if texto_linea:
                _parrafo(doc, texto_linea if _RE_LINEA_NUMERADA.match(texto_linea)
                         else f"{numero}. {texto_linea}")
        return

    texto = (r["transcripcion"] or "").strip()
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
    for i, linea in enumerate(lineas):
        if _RE_LINEA_NUMERADA.match(linea):
            # La línea ya viene numerada por el analista: se respeta.
            _parrafo(doc, linea)
        else:
            num = 1 if i % 2 == 0 else 2
            _parrafo(doc, f"{num}. {linea}")


def _interpretacion(doc: Document, r: sqlite3.Row) -> None:
    """Lo que el analista concluyó de esta comunicación, si escribió algo.

    Va rotulada y separada de la transcripción a propósito: la transcripción
    dice QUÉ se dijo y esto dice QUÉ SIGNIFICA. Mezcladas, un lector no puede
    distinguir el registro de la inferencia; rotuladas, la opinión del analista
    se lee como lo que es y no contamina lo transcripto.

    Si no hay nada escrito no se imprime el rótulo. La mayoría de las
    comunicaciones no llevan interpretación, y doscientos "Interpretación:"
    vacíos arruinarían el documento.
    """
    try:
        texto = (r["interpretacion"] or "").strip()
    except (IndexError, KeyError):
        return          # base vieja, sin la columna
    if not texto:
        return
    _salto(doc)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    rotulo = p.add_run("Interpretación: ")
    rotulo.bold = True
    rotulo.underline = True
    rotulo.font.name = "Arial"
    rotulo.font.size = Pt(12)
    cuerpo = p.add_run(texto)
    cuerpo.font.name = "Arial"
    cuerpo.font.size = Pt(12)


def _mensaje_sms(doc: Document, r: sqlite3.Row) -> None:
    """Bloque de un SMS: datos de la comunicación, celda y contenido del mensaje."""
    _parrafo(doc, "Mensaje de texto (SMS):", negrita=True)
    _salto(doc)
    _parrafo(doc, f"Dirección: {_direccion_texto(r['direccion'])}")
    _parrafo(doc, f"Origen: {_num_crudo(r, 'origen')}")
    _parrafo(doc, f"Destino: {_num_crudo(r, 'destino')}")
    _parrafo(doc, f"Fecha: {_valor(r['fecha_inicio_texto'])}")
    _salto(doc)
    _datos_celda(doc, r)
    _salto(doc)
    _parrafo(doc, "Contenido del mensaje:", negrita=True)
    contenido = (r["transcripcion"] or "").strip()
    _parrafo(doc, contenido if contenido else "(sin contenido)")
    _salto(doc)
    _parrafo(doc, "FIN DE LA COMUNICACIÓN.", negrita=True)
    _interpretacion(doc, r)
    _linea(doc)
    _salto(doc)


def _comunicacion(doc: Document, r: sqlite3.Row) -> None:
    if r["tipo"] == "sms":
        _mensaje_sms(doc, r)
        return

    nombre = _nombre_base(r["archivo_audio"]) or _nombre_base(r["archivo_txt"]) \
        or f"registro {r['orden']}"
    _parrafo(doc, f"Archivo {nombre}:", negrita=True)
    _salto(doc)

    if r["estado"] == "audio_faltante":
        # txt_sin_audio: metadatos disponibles; no hay audio que transcribir.
        _datos_comunicacion(doc, r)
        _salto(doc)
        _datos_celda(doc, r)
        _salto(doc)
        _parrafo(doc, _CONSTANCIA_TXT_SIN_AUDIO)
        _salto(doc)
    elif r["estado"] == "transcripcion_faltante":
        # audio_sin_txt: solo audio; constancia y transcripción del sonido.
        _parrafo(doc, _CONSTANCIA_AUDIO_SIN_TXT)
        _salto(doc)
        _transcripcion(doc, r)
        _salto(doc)
    else:
        _datos_comunicacion(doc, r)
        _salto(doc)
        _datos_celda(doc, r)
        _salto(doc)
        _transcripcion(doc, r)
        _salto(doc)

    _parrafo(doc, "FIN DE LA COMUNICACIÓN.", negrita=True)
    _interpretacion(doc, r)
    _linea(doc)
    _salto(doc)


# ---------------------------------------------------------------------------
# Agrupación por abonado
# ---------------------------------------------------------------------------

def _numero_abonado(r: sqlite3.Row, numeros_caso: set[str]) -> str:
    """Determina a qué abonado del caso pertenece el registro.

    Primero lo que dijo la carpeta de origen: es el único dato que tiene un
    audio sin TXT, que no trae ni origen ni destino.
    """
    if "abonado_intervenido" in r.keys():
        propio = (r["abonado_intervenido"] or "").strip()
        if propio:
            return propio
    for num in (r["origen"], r["destino"]):
        if num and num in numeros_caso:
            return num
    interesado = (r["interesado"] or "").strip()
    if interesado and interesado != "NO IDENTIFICADO":
        return interesado
    return "NO IDENTIFICADO"


# ---------------------------------------------------------------------------
# API principal
# ---------------------------------------------------------------------------

def _fecha_mas_frecuente(registros: list[sqlite3.Row]) -> str:
    fechas = [
        (r["fecha_inicio_texto"] or "").split(" ")[0]
        for r in registros if r["fecha_inicio_texto"]
    ]
    return max(set(fechas), key=fechas.count) if fechas else ""


def _seccion_cd(
    doc: Document,
    numero_seccion: int,
    cd_numero: str,
    cd_identificador: str,
    fecha_recepcion: str,
    fecha_comunicaciones: str,
    abonados_declarados: list[str],
    registros: list[sqlite3.Row],
) -> None:
    """Una entrega completa: encabezado, presentación y bloques por abonado."""
    identificador = f"CD{cd_identificador}" if cd_identificador else ""
    guion = " - " if identificador else ""
    _parrafo(
        doc,
        f"{numero_seccion}. CD NRO. {cd_numero}{guion}{identificador}, "
        f"suministrado por el Magistrado interviniente el día "
        f"{fecha_recepcion}:",
        negrita=True,
    )
    _salto(doc)

    por_abonado: dict[str, list[sqlite3.Row]] = defaultdict(list)
    declarados = set(abonados_declarados)
    for r in registros:
        por_abonado[_numero_abonado(r, declarados)].append(r)

    abonados_txt = ", ".join(
        abonados_declarados
        or sorted(k for k in por_abonado if k != "NO IDENTIFICADO")
    )
    _parrafo(
        doc,
        f"El presente CD contiene las comunicaciones correspondientes al día "
        f"{fecha_comunicaciones}, registradas de los abonados {abonados_txt}. "
        "Para una mejor interpretación se realizó una transcripción "
        "mecanográfica de cada archivo considerado de interés.",
    )
    _salto(doc)

    # Primero las líneas intervenidas, en el orden en que las declara el CD;
    # después cualquier otro grupo que haya quedado.
    orden = [n for n in abonados_declarados if n in por_abonado]
    orden += sorted(k for k in por_abonado if k not in orden)

    for numero in orden:
        _parrafo(doc, f"Abonado {numero}:", negrita=True)
        _salto(doc)
        filas = sorted(
            por_abonado[numero],
            key=lambda x: (str(x["fecha_inicio_dt"] or ""), x["orden"] or 0),
        )
        for r in filas:
            _comunicacion(doc, r)


def _marcar_informadas(
    con: sqlite3.Connection,
    caso_id: int,
    registros: list[sqlite3.Row],
    usuario: str,
) -> None:
    """Deja constancia de que estas comunicaciones ya salieron en un informe.

    Es lo que permite que la grilla las distinga de un vistazo: sin la marca,
    el analista no tiene cómo saber cuál material ya se elevó y cuál no, y en
    una causa que se informa por entregas eso se pierde enseguida.

    Va atada a un lote de exportación para que se pueda deshacer: si el informe
    se descarta, la marca vuelve atrás con él desde la pantalla Exportaciones.
    """
    nuevas = [r for r in registros if not r["informada"]]
    if not nuevas:
        return
    lote_id = repo.crear_lote_exportacion(con, caso_id, "word_informe", usuario)
    for r in nuevas:
        repo.registrar_historial_cambio(
            con, r["id"], "informada", "0", "1", "automatico_export",
            usuario, lote_id,
        )
        con.execute(
            "UPDATE Registro SET informada = 1, lote_exportacion_id = ? WHERE id = ?",
            (lote_id, r["id"]),
        )


def exportar_informe_judicial(
    con: sqlite3.Connection,
    caso_id: int,
    ruta: str | Path,
    *,
    cds: list[int] | None = None,
    solo_interes: bool = False,
    solo_ids: Iterable[int] | None = None,
    fecha_recepcion: str = "",
    cd_numero: str = "",
    cd_id: str = "",
    fecha_comunicaciones: str = "",
    usuario: str | None = None,
) -> Path:
    """Genera el informe judicial, formato Transcriptor Forense.

    El documento se arma por entrega: una sección numerada por CD, con su
    encabezado ("3. CD NRO. 4 - CD700000002, suministrado por el Magistrado
    interviniente el día ..."), la presentación con la fecha y las líneas que
    ese CD declara, y adentro un bloque por abonado. Los datos salen de la
    tabla CD, que se completa sola al importar leyendo cada DatosCausa.txt.

    `cds` limita a ciertas entregas (por su id interno); sin él van todas.
    `solo_interes` deja únicamente las comunicaciones marcadas, que es lo que
    dice el propio texto del informe ("cada archivo considerado de interés").

    `solo_ids` recorta a comunicaciones puntuales: es lo que usa la entrega de
    una jornada desde Desgrabar, donde el analista ya sabe cuáles son y no
    quiere volver a elegirlas. Se combina con el resto de los filtros.

    `cd_numero`/`cd_id`/`fecha_comunicaciones` son la salida de emergencia para
    causas sin entregas registradas (importadas de Excel o de otra base): en ese
    caso se arma una sección única con lo que se pase a mano.
    """
    usuario = sesion.o_analista(usuario)
    registros = repo.listar_registros(con, caso_id)
    if solo_interes:
        registros = [r for r in registros if (r["nivel_interes"] or "ninguno") != "ninguno"]
    if solo_ids is not None:
        elegidas = set(solo_ids)
        registros = [r for r in registros if r["id"] in elegidas]
    if not registros:
        raise InformeVacio(
            "Ninguna de las comunicaciones elegidas quedó dentro del informe."
            if solo_ids is not None else
            "No hay comunicaciones marcadas de interés para incluir en el informe."
            if solo_interes else
            "El caso no tiene registros para incluir en el informe."
        )

    entregas = [
        cd for cd in repo.listar_cds(con, caso_id)
        if cds is None or cd["id"] in cds
    ]
    abonados_caso = [
        a["numero_normalizado"] for a in repo.listar_abonados_por_alta(con, caso_id)
    ]

    doc = Document()
    _configurar_estilo_base(doc)
    _parrafo(doc, "TRANSCRIPCIONES DEL ABONADO", negrita=True)
    _salto(doc)

    incluidos = 0
    incluidas: list[sqlite3.Row] = []
    if entregas:
        # "Suelto" es el registro que no pertenece a NINGUNA entrega de la causa,
        # no el que quedó fuera de la selección: si se pide solo el CD 4, los
        # del CD 3 no tienen por qué aparecer.
        numeros_registrados = {
            (cd["numero"] or "") for cd in repo.listar_cds(con, caso_id)
        }
        pendientes = {
            r["id"]: r for r in registros
            if (r["cd"] or "") not in numeros_registrados
        } if cds is None else {}

        for i, cd in enumerate(entregas, start=1):
            del_cd = [r for r in registros if (r["cd"] or "") == (cd["numero"] or "")]
            if not del_cd:
                continue
            recepcion = fecha_recepcion or (cd["fecha_recepcion"] or "")
            _seccion_cd(
                doc, i, cd["numero"] or "", cd["identificador"] or "",
                recepcion, cd["fecha"] or _fecha_mas_frecuente(del_cd),
                repo.abonados_declarados_de_cd(cd) or abonados_caso, del_cd,
            )
            incluidos += len(del_cd)
            incluidas.extend(del_cd)

        # Nada puede quedarse afuera del informe sin que se vea: lo que no cayó
        # en ninguna entrega va en una sección final, explícita.
        sueltos = list(pendientes.values())
        if sueltos:
            _seccion_cd(
                doc, len(entregas) + 1, "sin identificar", "",
                fecha_recepcion, _fecha_mas_frecuente(sueltos),
                abonados_caso, sueltos,
            )
            incluidos += len(sueltos)
            incluidas.extend(sueltos)
    else:
        _seccion_cd(
            doc, 1, cd_numero, cd_id, fecha_recepcion,
            fecha_comunicaciones or _fecha_mas_frecuente(registros),
            abonados_caso, registros,
        )
        incluidos = len(registros)
        incluidas = list(registros)

    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(ruta))

    _marcar_informadas(con, caso_id, incluidas, usuario)
    repo.log_auditoria(
        con, "exporto",
        f"Informe judicial ({incluidos} comunicaciones, "
        f"{len(entregas) or 1} CD) -> {ruta}",
        caso_id, usuario,
    )
    con.commit()
    return ruta
