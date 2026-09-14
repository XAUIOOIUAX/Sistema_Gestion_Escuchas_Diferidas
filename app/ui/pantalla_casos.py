"""Pantalla de gestión de casos: listar, crear y abrir."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import repositorios as repo
from app.ui.dialogos import confirmar_borrado_caso


class PantallaCasos(QWidget):
    """Lista de casos con acciones para crear, abrir, vaciar y eliminar."""

    caso_abierto = Signal(int, str)  # (caso_id, nombre)
    caso_vaciado = Signal(int)  # caso_id
    caso_borrado = Signal(int)  # caso_id

    def __init__(self, con: sqlite3.Connection) -> None:
        super().__init__()
        self._con = con
        self._construir()
        self.refrescar()

    def _construir(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)

        cab = QHBoxLayout()
        titulos = QVBoxLayout()
        t = QLabel("Casos")
        t.setObjectName("titulo")
        s = QLabel("Causas registradas en el sistema")
        s.setObjectName("subtitulo")
        titulos.addWidget(t)
        titulos.addWidget(s)
        cab.addLayout(titulos)
        cab.addStretch(1)

        btn_nuevo = QPushButton("+ Crear caso nuevo")
        btn_nuevo.setObjectName("primary")
        btn_nuevo.clicked.connect(self._crear_caso)
        cab.addWidget(btn_nuevo)
        layout.addLayout(cab)

        self.tabla = QTableWidget(0, 6)
        self.tabla.setHorizontalHeaderLabels(
            ["Caso / Carátula", "Creado", "Registros", "", "", ""]
        )
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.verticalHeader().setDefaultSectionSize(42)
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setAlternatingRowColors(False)
        hh = self.tabla.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        # Columnas de botones: ancho fijo, ResizeToContents no mide cell widgets.
        hh.setSectionResizeMode(3, QHeaderView.Fixed)
        hh.setSectionResizeMode(4, QHeaderView.Fixed)
        hh.resizeSection(3, 96)
        hh.resizeSection(4, 96)
        self.tabla.doubleClicked.connect(lambda *_: self._abrir_seleccionado())
        layout.addWidget(self.tabla, 1)

    def refrescar(self) -> None:
        casos = repo.listar_casos(self._con)
        self.tabla.setRowCount(0)
        for caso in casos:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(caso["nombre"]))
            self.tabla.setItem(fila, 1, QTableWidgetItem(caso["fecha_creacion"] or ""))
            item_n = QTableWidgetItem(str(caso["n_registros"]))
            item_n.setTextAlignment(Qt.AlignCenter)
            self.tabla.setItem(fila, 2, item_n)

            btn = QPushButton("Abrir")
            btn.clicked.connect(
                lambda _=False, cid=caso["id"], nom=caso["nombre"]: self.caso_abierto.emit(
                    cid, nom
                )
            )
            self.tabla.setCellWidget(fila, 3, btn)

            btn_vaciar = QPushButton("Vaciar")
            btn_vaciar.setObjectName("danger")
            btn_vaciar.setToolTip(
                "Borra los registros importados del caso para cargar datos nuevos"
            )
            btn_vaciar.setEnabled(caso["n_registros"] > 0)
            btn_vaciar.clicked.connect(
                lambda _=False, cid=caso["id"], nom=caso["nombre"]: self._vaciar_caso(
                    cid, nom
                )
            )
            self.tabla.setCellWidget(fila, 4, btn_vaciar)

            btn_borrar = QPushButton("Eliminar")
            btn_borrar.setObjectName("danger")
            btn_borrar.setToolTip(
                "Saca la causa entera del sistema, con todo el trabajo hecho "
                "sobre ella. No se puede deshacer."
            )
            btn_borrar.clicked.connect(
                lambda _=False, cid=caso["id"], nom=caso["nombre"]: self._borrar_caso(
                    cid, nom
                )
            )
            self.tabla.setCellWidget(fila, 5, btn_borrar)
            # Guardar id en el item de la primera columna.
            self.tabla.item(fila, 0).setData(Qt.UserRole, caso["id"])
            self.tabla.item(fila, 0).setData(Qt.UserRole + 1, caso["nombre"])

    def _abrir_seleccionado(self) -> None:
        fila = self.tabla.currentRow()
        if fila < 0:
            return
        item = self.tabla.item(fila, 0)
        self.caso_abierto.emit(item.data(Qt.UserRole), item.data(Qt.UserRole + 1))

    def _crear_caso(self) -> None:
        nombre, ok = QInputDialog.getText(
            self, "Crear caso", "Nombre / carátula del caso:"
        )
        if not ok or not nombre.strip():
            return
        notas, _ = QInputDialog.getMultiLineText(
            self, "Crear caso", "Notas (opcional):"
        )
        try:
            caso_id = repo.crear_caso(self._con, nombre.strip(), notas.strip())
            repo.log_auditoria(self._con, "creo_caso", nombre.strip(), caso_id)
            self._con.commit()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"No se pudo crear el caso:\n{exc}")
            return
        self.refrescar()
        self.caso_abierto.emit(caso_id, nombre.strip())

    def _vaciar_caso(self, caso_id: int, nombre: str) -> None:
        caso = repo.obtener_caso(self._con, caso_id)
        n = repo.listar_casos(self._con)
        n_registros = next(
            (c["n_registros"] for c in n if c["id"] == caso_id), 0
        )
        if caso is None:
            return
        resp = QMessageBox.warning(
            self,
            "Vaciar caso",
            f"Se van a borrar los {n_registros} registros importados del caso "
            f"«{nombre}», junto con sus abonados, avisos e historial de "
            "importación.\n\nEl caso queda vacío, listo para una carga nueva. "
            "La memoria de «corresponde a» se conserva.\n\n"
            "Esta acción NO se puede deshacer. ¿Continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        try:
            borrados = repo.vaciar_caso(self._con, caso_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"No se pudo vaciar el caso:\n{exc}")
            return
        self.refrescar()
        self.caso_vaciado.emit(caso_id)
        QMessageBox.information(
            self,
            "Vaciar caso",
            f"Caso vaciado: {borrados['Registro']} registros y "
            f"{borrados['Abonado']} abonados eliminados.",
        )

    def _borrar_caso(self, caso_id: int, nombre: str) -> None:
        """Elimina la causa entera, previa confirmación escribiendo su nombre."""
        conteos = {
            tabla: self._con.execute(
                f"SELECT COUNT(*) FROM {tabla} WHERE caso_id = ?", (caso_id,)
            ).fetchone()[0]
            for tabla in ("Registro", "Abonado", "AvisoValidacion", "LoteExportacion")
        }
        if not confirmar_borrado_caso(self, nombre, conteos):
            return
        try:
            repo.borrar_caso(self._con, caso_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self, "Error", f"No se pudo eliminar la causa:\n{exc}"
            )
            return
        self.refrescar()
        # La ventana necesita enterarse: si la causa borrada era la abierta,
        # todas las pantallas están mostrando datos que ya no existen.
        self.caso_borrado.emit(caso_id)
