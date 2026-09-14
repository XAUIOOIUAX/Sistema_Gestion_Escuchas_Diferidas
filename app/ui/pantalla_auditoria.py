"""Pantalla de log de auditoría transversal (Fase 5, ítem 17).

Acá vive además **qué base de datos está abierta**, y no es un dato decorativo.
El programa es portable —se copia la carpeta y anda—, así que es perfectamente
posible terminar con dos instalaciones, cada una con su propio
`datos/escuchas.db`. Cuando eso pasa, el trabajo hecho en una no aparece en la
otra y parece que se borró solo. Sin la ruta a la vista no hay forma de
darse cuenta: las dos pantallas se ven exactamente iguales.

Esta es la pantalla administrativa de la causa, así que es donde corresponde
mirar de dónde salen los datos y llevarse el historial para el expediente.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import config, repositorios as repo, sesion
from app.ui import tema
from app.ui.dialogos import abrir_carpeta

_ACCIONES = [
    ("", "— Todas —"),
    ("creo_caso", "Creó caso"),
    ("importo", "Importó"),
    ("exporto", "Exportó"),
    ("edito", "Editó"),
    ("deshizo_exportacion", "Deshizo exportación"),
]

_ENCABEZADOS = ["Fecha", "Acción", "Caso", "Detalle", "Usuario"]


def tamano_legible(bytes_: int) -> str:
    """1536 -> '1,5 KB'. Para que el tamaño de la base se lea de un vistazo."""
    valor = float(bytes_)
    for unidad in ("bytes", "KB", "MB", "GB"):
        if valor < 1024 or unidad == "GB":
            entero = unidad == "bytes"
            texto = f"{valor:.0f}" if entero else f"{valor:.1f}".replace(".", ",")
            return f"{texto} {unidad}"
        valor /= 1024
    return f"{valor:.1f} GB"


def texto_de_auditoria(
    filas, *, ruta_base: str = "", filtro: str = "", analista: str = "",
) -> str:
    """Arma el TXT del historial, con encabezado que dice de dónde salió.

    El encabezado no es adorno: un listado de auditoría suelto, sin decir de
    qué base ni con qué filtro se sacó, no prueba nada. Con dos instalaciones
    posibles del programa, «de qué base» es justamente la pregunta.
    """
    lineas = [
        "LOG DE AUDITORÍA",
        "=" * 78,
        f"Generado:      {datetime.now():%d/%m/%Y %H:%M:%S}",
        f"Analista:      {analista or '—'}",
        f"Base de datos: {ruta_base or '—'}",
        f"Filtro:        {filtro or 'sin filtro (todo el historial)'}",
        f"Entradas:      {len(filas)}",
        "=" * 78,
        "",
    ]
    for e in filas:
        caso = e["caso_nombre"] or (f"#{e['caso_id']}" if e["caso_id"] else "—")
        lineas.append(
            f"{e['fecha'] or '':19}  {e['accion'] or '':20}  {caso:24}  "
            f"{e['usuario'] or '—'}"
        )
        detalle = (e["detalle"] or "").strip()
        if detalle:
            lineas.append(f"{'':19}  {detalle}")
        lineas.append("")
    if not filas:
        lineas.append("(sin entradas para este filtro)")
    return "\n".join(lineas)


class PantallaAuditoria(QWidget):
    """Lista las entradas de LogAuditoria con filtro por acción."""

    def __init__(self, con: sqlite3.Connection) -> None:
        super().__init__()
        self._con = con
        self._caso_id: int | None = None
        self._construir()

    def set_caso(self, caso_id: int) -> None:
        self._caso_id = caso_id
        self.refrescar()

    def refrescar(self) -> None:
        self._poblar()

    def _construir(self) -> None:
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(22, 16, 22, 10)
        raiz.setSpacing(10)

        titulo = QLabel("Log de auditoría")
        titulo.setObjectName("titulo")
        raiz.addWidget(titulo)

        sub = QLabel("Historial de todas las acciones realizadas en el sistema")
        sub.setObjectName("subtitulo")
        raiz.addWidget(sub)

        raiz.addWidget(self._bloque_base())

        filtros = QHBoxLayout()
        filtros.setSpacing(10)
        filtros.addWidget(QLabel("Acción:"))
        self.cmb_accion = QComboBox()
        self.cmb_accion.setMinimumWidth(180)
        for valor, etiqueta in _ACCIONES:
            self.cmb_accion.addItem(etiqueta, valor)
        self.cmb_accion.currentIndexChanged.connect(lambda _: self._poblar())
        filtros.addWidget(self.cmb_accion)

        self.chk_caso_label = QLabel("Solo caso activo")
        filtros.addWidget(self.chk_caso_label)

        self.chk_caso = QCheckBox()
        self.chk_caso.setChecked(False)
        self.chk_caso.stateChanged.connect(lambda _: self._poblar())
        filtros.addWidget(self.chk_caso)

        filtros.addStretch(1)

        self.btn_exportar = QPushButton("Exportar a TXT")
        self.btn_exportar.setToolTip(
            "Guarda el historial que se está viendo en un archivo de texto, "
            "con el filtro aplicado y la base de la que salió."
        )
        self.btn_exportar.clicked.connect(self._exportar)
        filtros.addWidget(self.btn_exportar)

        self.btn_limpiar = QPushButton("Limpiar auditoría")
        self.btn_limpiar.setObjectName("danger")
        self.btn_limpiar.setToolTip(
            "Borra el historial de auditoría (todo, o solo el caso activo si el "
            "filtro está tildado)"
        )
        self.btn_limpiar.clicked.connect(self._limpiar)
        filtros.addWidget(self.btn_limpiar)
        raiz.addLayout(filtros)

        self.tabla = QTableWidget(0, len(_ENCABEZADOS))
        self.tabla.setHorizontalHeaderLabels(_ENCABEZADOS)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setAlternatingRowColors(True)
        hh = self.tabla.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        raiz.addWidget(self.tabla, 1)

        self.lbl_total = QLabel("")
        self.lbl_total.setObjectName("subtitulo")
        raiz.addWidget(self.lbl_total)

    # ------------------------- la base de datos --------------------------
    def _bloque_base(self) -> QWidget:
        """Qué archivo se está usando, dónde está y cuánto pesa."""
        marco = QFrame()
        marco.setStyleSheet(
            f"QFrame {{ background:{tema.PANEL}; border:1px solid {tema.LINE};"
            f" border-radius:6px; }}"
        )
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(6)

        rotulo = QLabel("BASE DE DATOS EN USO")
        rotulo.setObjectName("seccion")
        lay.addWidget(rotulo)

        self.lbl_ruta = QLabel("")
        self.lbl_ruta.setStyleSheet(
            "font-family:'IBM Plex Mono','Consolas',monospace; font-size:12px;"
        )
        # Seleccionable: la ruta se copia para pegarla en un correo o para
        # comparar dos instalaciones, que es justamente para lo que está.
        self.lbl_ruta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_ruta.setWordWrap(True)
        lay.addWidget(self.lbl_ruta)

        self.lbl_datos = QLabel("")
        self.lbl_datos.setObjectName("subtitulo")
        lay.addWidget(self.lbl_datos)

        fila = QHBoxLayout()
        fila.setSpacing(8)
        btn_carpeta = QPushButton("Abrir la carpeta")
        btn_carpeta.clicked.connect(self._abrir_carpeta_datos)
        fila.addWidget(btn_carpeta)
        btn_copiar = QPushButton("Copiar la ruta")
        btn_copiar.clicked.connect(self._copiar_ruta)
        fila.addWidget(btn_copiar)
        fila.addStretch(1)
        lay.addLayout(fila)
        return marco

    def ruta_base(self) -> Path:
        return Path(config.RUTA_BASE_DATOS)

    def _refrescar_base(self) -> None:
        ruta = self.ruta_base()
        self.lbl_ruta.setText(str(ruta))
        partes = []
        if ruta.exists():
            partes.append(tamano_legible(ruta.stat().st_size))
        else:
            partes.append("todavía no se creó")
        try:
            casos = self._con.execute("SELECT COUNT(*) FROM Caso").fetchone()[0]
            regs = self._con.execute("SELECT COUNT(*) FROM Registro").fetchone()[0]
            partes.append(f"{casos} causa(s)")
            partes.append(f"{regs} comunicación(es)")
        except sqlite3.Error:
            pass
        self.lbl_datos.setText("  ·  ".join(partes))

    def _abrir_carpeta_datos(self) -> None:
        ruta = self.ruta_base()
        destino = ruta if ruta.exists() else ruta.parent
        if not destino.exists():
            QMessageBox.information(
                self, "Base de datos",
                f"La carpeta todavía no existe:\n{ruta.parent}",
            )
            return
        abrir_carpeta(destino)

    def _copiar_ruta(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(str(self.ruta_base()))
        self.lbl_datos.setText("Ruta copiada al portapapeles.")

    # ------------------------------ el listado ----------------------------
    def _poblar(self) -> None:
        self._refrescar_base()
        accion = self.cmb_accion.currentData() or None
        caso_id = self._caso_id if self.chk_caso.isChecked() else None

        filas = repo.listar_log_auditoria(self._con, caso_id=caso_id, accion=accion)

        self.tabla.setRowCount(0)
        for entry in filas:
            row = self.tabla.rowCount()
            self.tabla.insertRow(row)
            self.tabla.setItem(row, 0, QTableWidgetItem(entry["fecha"] or ""))
            self.tabla.setItem(row, 1, QTableWidgetItem(entry["accion"] or ""))
            caso_txt = entry["caso_nombre"] or (f"#{entry['caso_id']}" if entry["caso_id"] else "—")
            self.tabla.setItem(row, 2, QTableWidgetItem(caso_txt))
            self.tabla.setItem(row, 3, QTableWidgetItem(entry["detalle"] or ""))
            self.tabla.setItem(row, 4, QTableWidgetItem(entry["usuario"] or ""))

        self.lbl_total.setText(f"{len(filas)} entradas")

    def _descripcion_del_filtro(self) -> str:
        partes = []
        if self.cmb_accion.currentData():
            partes.append(f"acción = {self.cmb_accion.currentText()}")
        if self.chk_caso.isChecked() and self._caso_id is not None:
            partes.append("solo el caso activo")
        return " · ".join(partes)

    def _exportar(self) -> None:
        """Saca a un TXT lo que se está viendo, con el filtro que se aplicó.

        Se exporta la vista y no todo el historial a propósito: lo que el
        analista quiere adjuntar es lo que acaba de mirar. El encabezado dice
        qué filtro había, así que el archivo no se puede leer como si fuera el
        historial completo.
        """
        filas = repo.listar_log_auditoria(
            self._con,
            caso_id=self._caso_id if self.chk_caso.isChecked() else None,
            accion=self.cmb_accion.currentData() or None,
        )
        sugerido = f"Auditoria_{datetime.now():%Y-%m-%d}.txt"
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Exportar auditoría", sugerido, "Texto (*.txt)"
        )
        if not ruta:
            return
        texto = texto_de_auditoria(
            filas,
            ruta_base=str(self.ruta_base()),
            filtro=self._descripcion_del_filtro(),
            analista=sesion.analista(),
        )
        try:
            destino = Path(ruta)
            destino.write_text(texto, encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(
                self, "Exportar auditoría", f"No se pudo escribir:\n{exc}"
            )
            return
        # Que la exportación quede en el propio historial: es una copia del
        # expediente saliendo del programa, igual que un informe.
        repo.log_auditoria(
            self._con, "exporto",
            f"Auditoría exportada ({len(filas)} entradas) -> {destino}",
            self._caso_id,
        )
        self._con.commit()
        self._poblar()
        QMessageBox.information(
            self, "Exportar auditoría",
            f"{len(filas)} entradas guardadas en:\n{destino}",
        )

    def _limpiar(self) -> None:
        solo_caso = self.chk_caso.isChecked() and self._caso_id is not None
        alcance = "del caso activo" if solo_caso else "COMPLETO (todos los casos)"
        resp = QMessageBox.warning(
            self,
            "Limpiar auditoría",
            f"Se va a borrar el historial de auditoría {alcance}.\n\n"
            "Esta acción no se puede deshacer. ¿Continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        n = repo.limpiar_log_auditoria(
            self._con, caso_id=self._caso_id if solo_caso else None
        )
        self._poblar()
        QMessageBox.information(
            self, "Limpiar auditoría", f"{n} entradas eliminadas."
        )
