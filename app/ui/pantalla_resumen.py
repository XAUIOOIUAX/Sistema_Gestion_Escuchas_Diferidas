"""Resumen del caso: la pantalla que contesta «¿en qué estaba?».

Hasta ahora abrir una causa dejaba al analista frente a la Tabla TOTAL: cientos
de filas sin contexto, y para saber cuánto faltaba escuchar o cuántos avisos
había quedado abiertos había que ir combinando filtros. Esta pantalla junta esa
foto en un vistazo y ofrece los tres caminos que se toman después: seguir
escuchando, resolver los avisos o importar más material.

Es también el registro que se pide para las escuchas diferidas: qué material
entró, hasta qué fecha llega, cuánto se trabajó y qué salió informado.
"""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHeaderView,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import repositorios as repo
from app.ui import tema


def _formato_duracion(segundos: float) -> str:
    """Duración total en horas y minutos, que es como se la piensa."""
    segundos = int(segundos or 0)
    horas, resto = divmod(segundos, 3600)
    minutos = resto // 60
    if horas:
        return f"{horas} h {minutos:02d} min"
    return f"{minutos} min"


def _formato_fecha(valor: str | None) -> str:
    """De '2025-02-20 18:03:42' (como guarda SQLite) a '20/02/2025'."""
    if not valor:
        return "—"
    fecha = str(valor)[:10]
    partes = fecha.split("-")
    if len(partes) == 3:
        return f"{partes[2]}/{partes[1]}/{partes[0]}"
    return fecha


class _Tarjeta(QFrame):
    """Un número grande con su rótulo y, si hace falta, una aclaración."""

    def __init__(self, rotulo: str, color: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tarjeta")
        self.setStyleSheet(
            f"QFrame#tarjeta {{ background:{tema.PANEL}; border:1px solid {tema.LINE};"
            " border-radius:8px; }"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(2)

        self.lbl_valor = QLabel("—")
        self.lbl_valor.setStyleSheet(
            f"color:{color or tema.TEXT_PRIMARY}; font-size:24px; font-weight:600;"
        )
        lay.addWidget(self.lbl_valor)

        lbl_rotulo = QLabel(rotulo)
        lbl_rotulo.setStyleSheet(f"color:{tema.TEXT_MUTED}; font-size:11px;")
        lay.addWidget(lbl_rotulo)

        self.lbl_pie = QLabel("")
        self.lbl_pie.setStyleSheet(f"color:{tema.TEXT_DIM}; font-size:10px;")
        self.lbl_pie.setWordWrap(True)
        lay.addWidget(self.lbl_pie)

    def set_valor(self, valor: object, pie: str = "") -> None:
        self.lbl_valor.setText(str(valor))
        self.lbl_pie.setText(pie)


class PantallaResumen(QWidget):
    """Estado general de la causa activa."""

    ir_a_pantalla = Signal(str)   # etiqueta del sidebar a la que saltar
    seguir_escuchando = Signal()  # Tabla TOTAL, filtrada a lo que falta oír
    ver_cd = Signal(str)          # Tabla TOTAL, filtrada a una entrega

    def __init__(self, con: sqlite3.Connection) -> None:
        super().__init__()
        self._con = con
        self._caso_id: int | None = None
        self._construir()

    # ------------------------------------------------------------------
    def set_caso(self, caso_id: int) -> None:
        self._caso_id = caso_id
        self.refrescar()

    def _construir(self) -> None:
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(22, 16, 22, 16)
        raiz.setSpacing(12)

        cab = QHBoxLayout()
        titulos = QVBoxLayout()
        self.lbl_titulo = QLabel("Resumen")
        self.lbl_titulo.setObjectName("titulo")
        self.lbl_sub = QLabel("Estado de la causa")
        self.lbl_sub.setObjectName("subtitulo")
        titulos.addWidget(self.lbl_titulo)
        titulos.addWidget(self.lbl_sub)
        cab.addLayout(titulos)
        cab.addStretch(1)

        self.btn_escuchar = QPushButton("▶  Seguir escuchando")
        self.btn_escuchar.setObjectName("primary")
        self.btn_escuchar.setToolTip(
            "Abre la Tabla TOTAL filtrada a los registros que todavía no escuchaste"
        )
        self.btn_escuchar.clicked.connect(self.seguir_escuchando)
        cab.addWidget(self.btn_escuchar)

        self.btn_avisos = QPushButton("Revisar validaciones")
        self.btn_avisos.clicked.connect(
            lambda: self.ir_a_pantalla.emit("Validaciones")
        )
        cab.addWidget(self.btn_avisos)

        btn_importar = QPushButton("Importar material")
        btn_importar.clicked.connect(lambda: self.ir_a_pantalla.emit("Importar"))
        cab.addWidget(btn_importar)
        raiz.addLayout(cab)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        cuerpo = QWidget()
        lay = QVBoxLayout(cuerpo)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(14)

        # Fila de titulares.
        fila = QHBoxLayout()
        fila.setSpacing(10)
        self.t_registros = _Tarjeta("Comunicaciones registradas")
        self.t_escuchadas = _Tarjeta("Escuchadas", tema.TEAL)
        self.t_interes = _Tarjeta("Marcadas de interés", tema.ACCENT)
        self.t_avisos = _Tarjeta("Avisos sin resolver", tema.DANGER)
        for t in (self.t_registros, self.t_escuchadas, self.t_interes, self.t_avisos):
            fila.addWidget(t, 1)
        lay.addLayout(fila)

        # Progreso de escucha.
        self.barra = QProgressBar()
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(8)
        lay.addWidget(self.barra)
        self.lbl_progreso = QLabel("")
        self.lbl_progreso.setObjectName("subtitulo")
        lay.addWidget(self.lbl_progreso)

        lay.addWidget(self._bloque_entregas())
        lay.addWidget(self._bloque_material())
        lay.addWidget(self._bloque_trabajo())
        lay.addStretch(1)

        scroll.setWidget(cuerpo)
        raiz.addWidget(scroll, 1)

    def _bloque_entregas(self) -> QWidget:
        """Una fila por CD recibido: es la unidad en que llega y se informa.

        El CD no es una categoría inventada: es una entrega del juzgado, con su
        fecha, su identificador y las líneas que estaban intervenidas ESE día
        —que se van achicando cuando el juzgado levanta alguna—. Verlas juntas
        contesta de un vistazo qué material entró y cuánto se trabajó de cada
        entrega, y es también control de calidad: cuatro entregas colapsadas en
        un renglón se ven al toque.
        """
        caja = QFrame()
        caja.setObjectName("caja")
        caja.setStyleSheet(
            f"QFrame#caja {{ background:{tema.PANEL}; border:1px solid {tema.LINE};"
            " border-radius:8px; }"
        )
        lay = QVBoxLayout(caja)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        lbl = QLabel("ENTREGAS RECIBIDAS")
        lbl.setObjectName("seccion")
        lbl.setStyleSheet(f"color:{tema.TEXT_DIM};")
        lay.addWidget(lbl)

        self.tabla_cds = QTableWidget(0, 6)
        self.tabla_cds.setHorizontalHeaderLabels(
            ["CD", "Identificador", "Fecha", "Líneas", "Comunicaciones", "Trabajado"]
        )
        self.tabla_cds.verticalHeader().setVisible(False)
        self.tabla_cds.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla_cds.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla_cds.setSelectionMode(QTableWidget.SingleSelection)
        self.tabla_cds.setAlternatingRowColors(True)
        self.tabla_cds.setShowGrid(False)
        cabecera = self.tabla_cds.horizontalHeader()
        cabecera.setSectionResizeMode(QHeaderView.ResizeToContents)
        cabecera.setSectionResizeMode(4, QHeaderView.Stretch)
        cabecera.setSectionResizeMode(5, QHeaderView.Stretch)
        self.tabla_cds.setCursor(Qt.PointingHandCursor)
        self.tabla_cds.cellClicked.connect(self._al_elegir_cd)
        lay.addWidget(self.tabla_cds)

        pie = QLabel("Clic en una entrega para ver sus comunicaciones.")
        pie.setStyleSheet(f"color:{tema.TEXT_DIM}; font-size:10px;")
        lay.addWidget(pie)
        return caja

    def _al_elegir_cd(self, fila: int, _columna: int) -> None:
        item = self.tabla_cds.item(fila, 0)
        if item is not None and item.data(Qt.UserRole):
            self.ver_cd.emit(item.data(Qt.UserRole))

    def _poblar_entregas(self) -> None:
        entregas = repo.resumen_por_cd(self._con, self._caso_id)
        self.tabla_cds.setRowCount(0)
        for e in entregas:
            fila = self.tabla_cds.rowCount()
            self.tabla_cds.insertRow(fila)
            numero = e["numero"]
            item_cd = QTableWidgetItem(f"Nº {numero}" if numero else "sin CD")
            item_cd.setData(Qt.UserRole, numero)
            self.tabla_cds.setItem(fila, 0, item_cd)
            self.tabla_cds.setItem(
                fila, 1,
                QTableWidgetItem(f"CD{e['identificador']}" if e["identificador"] else "—"),
            )
            self.tabla_cds.setItem(fila, 2, QTableWidgetItem(e["fecha"] or "—"))
            declaradas = len(e["declarados"])
            item_lineas = QTableWidgetItem(str(declaradas) if declaradas else "—")
            item_lineas.setToolTip(
                "Líneas intervenidas que declara esta entrega:  "
                + ", ".join(e["declarados"]) if declaradas else
                "Esta entrega no declara líneas (no trae DatosCausa.txt)"
            )
            self.tabla_cds.setItem(fila, 3, item_lineas)

            detalle = str(e["registros"])
            if e["incompletos"]:
                detalle += f"  ({e['incompletos']} con archivos faltantes)"
            self.tabla_cds.setItem(fila, 4, QTableWidgetItem(detalle))

            trabajado = f"{e['escuchadas']} escuchadas"
            if e["interes"]:
                trabajado += f"  ·  {e['interes']} de interés"
            item_trab = QTableWidgetItem(trabajado)
            if e["registros"] and e["escuchadas"] == e["registros"]:
                item_trab.setForeground(QColor(tema.TEAL))
            self.tabla_cds.setItem(fila, 5, item_trab)

        alto_fila = self.tabla_cds.verticalHeader().defaultSectionSize()
        self.tabla_cds.setFixedHeight(
            min(220, alto_fila * (len(entregas) + 1) + 8)
        )

    def _bloque_material(self) -> QWidget:
        caja, grilla = self._caja("MATERIAL INCORPORADO")
        self._campos_material = {}
        for i, (clave, rotulo) in enumerate((
            ("cds", "CDs distintos"),
            ("periodo", "Período cubierto"),
            ("abonados", "Abonados"),
            ("intervenidos", "Líneas intervenidas"),
            ("ultima", "Última importación"),
        )):
            grilla.addWidget(self._rotulo(rotulo), i, 0)
            valor = QLabel("—")
            valor.setWordWrap(True)
            self._campos_material[clave] = valor
            grilla.addWidget(valor, i, 1)
        return caja

    def _bloque_trabajo(self) -> QWidget:
        caja, grilla = self._caja("ESTADO DEL TRABAJO")
        self._campos_trabajo = {}
        for i, (clave, rotulo) in enumerate((
            ("archivos", "Archivos"),
            ("transcripciones", "Transcripciones"),
            ("interes", "De interés"),
            ("informadas", "Ya informadas"),
        )):
            grilla.addWidget(self._rotulo(rotulo), i, 0)
            valor = QLabel("—")
            valor.setWordWrap(True)
            self._campos_trabajo[clave] = valor
            grilla.addWidget(valor, i, 1)
        return caja

    def _caja(self, titulo: str) -> tuple[QWidget, QGridLayout]:
        caja = QFrame()
        # La regla va anclada al objectName: QLabel hereda de QFrame, así que
        # un selector "QFrame" suelto le pone borde y fondo a cada rótulo de
        # adentro y la caja termina pareciendo una planilla de formularios.
        caja.setObjectName("caja")
        caja.setStyleSheet(
            f"QFrame#caja {{ background:{tema.PANEL}; border:1px solid {tema.LINE};"
            " border-radius:8px; }"
        )
        lay = QVBoxLayout(caja)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        lbl = QLabel(titulo)
        lbl.setObjectName("seccion")
        lbl.setStyleSheet(f"color:{tema.TEXT_DIM};")
        lay.addWidget(lbl)

        grilla = QGridLayout()
        grilla.setHorizontalSpacing(18)
        grilla.setVerticalSpacing(6)
        grilla.setColumnStretch(1, 1)
        lay.addLayout(grilla)
        return caja, grilla

    def _rotulo(self, texto: str) -> QLabel:
        lbl = QLabel(texto)
        lbl.setStyleSheet(f"color:{tema.TEXT_DIM}; font-size:12px;")
        lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        lbl.setFixedWidth(150)
        return lbl

    # ------------------------------------------------------------------
    def refrescar(self) -> None:
        if self._caso_id is None:
            return
        caso = repo.obtener_caso(self._con, self._caso_id)
        if caso is None:
            return
        d = repo.resumen_caso(self._con, self._caso_id)
        self._poblar_entregas()

        self.lbl_titulo.setText(caso["nombre"])
        self.lbl_sub.setText(
            f"Causa abierta el {_formato_fecha(caso['fecha_creacion'])}"
        )

        sms = f"{d['sms']} son SMS" if d["sms"] else ""
        self.t_registros.set_valor(d["registros"], sms)

        con_audio = d["con_audio"]
        escuchados = d["escuchados"]
        porcentaje = round(100 * escuchados / con_audio) if con_audio else 0
        self.t_escuchadas.set_valor(
            f"{escuchados} / {con_audio}",
            f"{porcentaje}% de lo que tiene audio",
        )
        interes = d["de_interes"]
        self.t_interes.set_valor(
            interes,
            "listas para transcribir y para el informe" if interes
            else "todavía ninguna",
        )
        self.t_avisos.set_valor(
            d["avisos_pendientes"],
            "" if d["avisos_pendientes"] else "nada pendiente",
        )

        self.barra.setMaximum(max(con_audio, 1))
        self.barra.setValue(escuchados)
        faltan = con_audio - escuchados
        if not faltan:
            texto_progreso = "Todo el material con audio está escuchado."
        else:
            texto_progreso = f"Faltan escuchar {faltan} comunicaciones"
            if d["segundos"]:
                texto_progreso += (
                    f"  ·  {_formato_duracion(d['segundos'])} de audio medido"
                )
        self.lbl_progreso.setText(texto_progreso)
        self.btn_escuchar.setEnabled(faltan > 0)

        ultima = d["ultima_importacion"]
        self._campos_material["cds"].setText(str(d["cds"]) if d["cds"] else "—")
        self._campos_material["periodo"].setText(
            f"{_formato_fecha(d['desde'])}  a  {_formato_fecha(d['hasta'])}"
            if d["desde"] else "—"
        )
        self._campos_material["abonados"].setText(str(d["abonados"]))
        self._campos_material["intervenidos"].setText(
            str(d["intervenidos"]) if d["intervenidos"]
            else "ninguna marcada (se marcan en el Índice)"
        )
        self._campos_material["ultima"].setText(
            f"{_formato_fecha(ultima['fecha'])} · {ultima['archivos_nuevos']} "
            f"nuevos · {ultima['ruta_usada'] or ''}"
            if ultima else "sin importaciones registradas"
        )

        self._campos_trabajo["archivos"].setText(
            f"{d['completos']} completos · {d['audio_faltante']} sin audio · "
            f"{d['transcripcion_faltante']} sin transcripción"
        )
        self._campos_trabajo["transcripciones"].setText(
            f"{d['con_transcripcion']} con texto · {d['sin_revisar']} sin revisar"
        )
        self._campos_trabajo["interes"].setText(
            f"{interes} de interés · {d['registros'] - interes} sin marcar"
        )
        self._campos_trabajo["informadas"].setText(
            f"{d['informadas']} incluidas en algún informe"
        )
