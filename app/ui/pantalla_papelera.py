"""Papelera: lo que se sacó de la causa y todavía se puede recuperar.

Sacar una comunicación de una causa es deshacer una carga equivocada, pero el
error inverso —borrar la selección que no era— también existe, y en un
expediente no puede ser definitivo. Acá se ve qué se sacó, cuándo y quién, y se
devuelve entero: con su transcripción, su contexto, su nivel de interés y sus
marcas de audio.

Vaciar la papelera es el único punto del programa donde una comunicación deja
de existir, y por eso pide confirmación aparte.
"""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
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

from app.servicios import papelera

_COLUMNAS = ["Comunicación", "Enviada", "Por"]


class PantallaPapelera(QWidget):
    """Lista lo que está en la papelera, con restaurar y vaciar."""

    datos_cambiaron = Signal()

    def __init__(self, con: sqlite3.Connection) -> None:
        super().__init__()
        self._con = con
        self._caso_id: int | None = None
        self._filas: list[sqlite3.Row] = []
        self._construir()

    def set_caso(self, caso_id: int) -> None:
        self._caso_id = caso_id
        self.refrescar()

    def _construir(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 16, 22, 16)
        lay.setSpacing(10)

        cab = QHBoxLayout()
        titulos = QVBoxLayout()
        t = QLabel("Papelera")
        t.setObjectName("titulo")
        s = QLabel(
            "Comunicaciones sacadas de la causa. Vuelven enteras: con su "
            "transcripción, su contexto y sus marcas."
        )
        s.setObjectName("subtitulo")
        s.setWordWrap(True)
        titulos.addWidget(t)
        titulos.addWidget(s)
        cab.addLayout(titulos)
        cab.addStretch(1)

        self.btn_restaurar = QPushButton("Restaurar seleccionadas")
        self.btn_restaurar.setObjectName("primary")
        self.btn_restaurar.clicked.connect(self._restaurar)
        cab.addWidget(self.btn_restaurar)

        self.btn_vaciar = QPushButton("Vaciar papelera")
        self.btn_vaciar.setObjectName("danger")
        self.btn_vaciar.setToolTip(
            "Elimina definitivamente. Es lo único que no se puede deshacer."
        )
        self.btn_vaciar.clicked.connect(self._vaciar)
        cab.addWidget(self.btn_vaciar)
        lay.addLayout(cab)

        self.tabla = QTableWidget(0, len(_COLUMNAS))
        self.tabla.setHorizontalHeaderLabels(_COLUMNAS)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setSelectionMode(QTableWidget.ExtendedSelection)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setShowGrid(False)
        cabecera = self.tabla.horizontalHeader()
        cabecera.setSectionResizeMode(QHeaderView.ResizeToContents)
        cabecera.setSectionResizeMode(0, QHeaderView.Stretch)
        lay.addWidget(self.tabla, 1)

        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("subtitulo")
        lay.addWidget(self.lbl_status)

    # ------------------------------------------------------------------
    def refrescar(self) -> None:
        if self._caso_id is None:
            return
        self._filas = papelera.listar(self._con, self._caso_id)
        self.tabla.setRowCount(0)
        for f in self._filas:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            item = QTableWidgetItem(f["resumen"] or f"registro #{f['registro_id']}")
            item.setData(Qt.UserRole, f["id"])
            self.tabla.setItem(fila, 0, item)
            self.tabla.setItem(fila, 1, QTableWidgetItem(f["fecha"] or ""))
            self.tabla.setItem(fila, 2, QTableWidgetItem(f["usuario"] or ""))

        vacia = not self._filas
        self.btn_restaurar.setEnabled(not vacia)
        self.btn_vaciar.setEnabled(not vacia)
        self.lbl_status.setText(
            "La papelera está vacía." if vacia else
            f"{len(self._filas)} comunicaciones en la papelera."
        )

    def _seleccionadas(self) -> list[int]:
        return [
            self.tabla.item(i.row(), 0).data(Qt.UserRole)
            for i in self.tabla.selectionModel().selectedRows()
        ]

    def _restaurar(self) -> None:
        if self._caso_id is None:
            return
        ids = self._seleccionadas()
        if not ids:
            self.lbl_status.setText("Elegí qué comunicaciones querés restaurar.")
            return
        resultado = papelera.restaurar(self._con, self._caso_id, ids)
        self.refrescar()
        self.datos_cambiaron.emit()
        if resultado.ya_existentes:
            QMessageBox.information(
                self,
                "Papelera",
                f"{resultado.restauradas} restauradas.\n\n"
                f"{len(resultado.ya_existentes)} no se pudieron devolver porque "
                "la causa ya las tiene otra vez: se volvieron a importar "
                "mientras estaban acá. Quedan en la papelera.",
            )
        self.lbl_status.setText(f"{resultado.restauradas} comunicaciones restauradas.")

    def _vaciar(self) -> None:
        if self._caso_id is None or not self._filas:
            return
        ids = self._seleccionadas()
        cuantas = len(ids) if ids else len(self._filas)
        resp = QMessageBox.warning(
            self,
            "Vaciar papelera",
            f"Se van a eliminar definitivamente {cuantas} comunicaciones.\n\n"
            "Esto NO se puede deshacer. Los archivos de audio en disco no se "
            "tocan, así que el material se puede volver a importar; lo que se "
            "pierde es el trabajo hecho sobre él.\n\n¿Continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        n = papelera.vaciar(self._con, self._caso_id, ids or None)
        self.refrescar()
        self.lbl_status.setText(f"{n} comunicaciones eliminadas definitivamente.")
