"""Pantalla de importación: elegir carpeta, previsualizar y confirmar.

La ruta se pide SIEMPRE y no se persiste (pseudocódigo 6.2). El preview muestra
el desglose por estado antes de escribir nada en la base.
"""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.importadores.db_importador import fusionar_base_externa, listar_casos_externos
from app.importadores.excel_importador import importar_desde_excel
from app.models import ResumenPreview
from app.servicios.importacion import (
    importar_carpeta_confirmado,
    preview_importacion,
)

_ETIQUETA_ESTADO = {
    "completo": "Completo",
    "audio_faltante": "⚠ Audio faltante",
    "transcripcion_faltante": "⚠ Transcripción faltante",
}


class PantallaImportar(QWidget):
    """Flujo de importación de una carpeta de TXT/audio al caso activo."""

    importacion_finalizada = Signal()

    def __init__(self, con: sqlite3.Connection) -> None:
        super().__init__()
        self._con = con
        self._caso_id: int | None = None
        self._ruta: str | None = None
        self._preview: ResumenPreview | None = None
        self._construir()

    def set_caso(self, caso_id: int) -> None:
        self._caso_id = caso_id
        self._preview = None
        self._ruta = None
        self.lbl_resumen.setText("Elegí una carpeta para escanear.")
        self.tabla.setRowCount(0)
        self.btn_confirmar.setEnabled(False)
        self.barra.setValue(0)

    def _construir(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)

        t = QLabel("Importar transcripciones")
        t.setObjectName("titulo")
        layout.addWidget(t)
        sub = QLabel(
            "Escaneo recursivo: empareja .txt con su audio por nombre base y "
            "detecta huérfanos (audio sin txt / txt sin audio)."
        )
        sub.setObjectName("subtitulo")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        fila = QHBoxLayout()
        self.btn_elegir = QPushButton("📁 Elegir carpeta…")
        self.btn_elegir.clicked.connect(self._elegir_carpeta)
        fila.addWidget(self.btn_elegir)

        self.btn_excel = QPushButton("📊 Importar Excel…")
        self.btn_excel.clicked.connect(self._importar_excel)
        fila.addWidget(self.btn_excel)

        self.btn_db = QPushButton("🗄 Importar Base…")
        self.btn_db.clicked.connect(self._importar_db)
        fila.addWidget(self.btn_db)

        self.lbl_ruta = QLabel("")
        self.lbl_ruta.setObjectName("subtitulo")
        fila.addWidget(self.lbl_ruta, 1)
        layout.addLayout(fila)

        self.lbl_resumen = QLabel("Elegí una carpeta para escanear.")
        self.lbl_resumen.setObjectName("subtitulo")
        layout.addWidget(self.lbl_resumen)

        self.tabla = QTableWidget(0, 5)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setHorizontalHeaderLabels(
            ["Estado", "Nombre base", "Origen", "Destino", "Inicio"]
        )
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        hh = self.tabla.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        for c in (2, 3, 4):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        layout.addWidget(self.tabla, 1)

        self.barra = QProgressBar()
        self.barra.setValue(0)
        layout.addWidget(self.barra)

        acciones = QHBoxLayout()
        acciones.addStretch(1)
        self.btn_confirmar = QPushButton("Confirmar importación")
        self.btn_confirmar.setObjectName("primary")
        self.btn_confirmar.setEnabled(False)
        self.btn_confirmar.clicked.connect(self._confirmar)
        acciones.addWidget(self.btn_confirmar)
        layout.addLayout(acciones)

    def _elegir_carpeta(self) -> None:
        if self._caso_id is None:
            QMessageBox.information(self, "Importar", "Primero abrí un caso.")
            return
        ruta = QFileDialog.getExistingDirectory(self, "Elegí la carpeta RAÍZ")
        if not ruta:
            return
        self._ruta = ruta
        self.lbl_ruta.setText(ruta)
        self._escanear()

    def _escanear(self) -> None:
        try:
            self._preview = preview_importacion(self._con, self._caso_id, self._ruta)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"Falló el escaneo:\n{exc}")
            return
        self.lbl_resumen.setText(self._preview.resumen_texto())
        self._poblar_tabla(self._preview)
        self.btn_confirmar.setEnabled(len(self._preview.nuevos) > 0)
        self.barra.setValue(0)

    def _poblar_tabla(self, preview: ResumenPreview) -> None:
        self.tabla.setRowCount(0)
        for item in preview.nuevos:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            est = _ETIQUETA_ESTADO.get(item.estado.value, item.estado.value)
            self.tabla.setItem(fila, 0, QTableWidgetItem(est))
            self.tabla.setItem(fila, 1, QTableWidgetItem(item.nombre_base))
            self.tabla.setItem(fila, 2, QTableWidgetItem(item.origen or "—"))
            self.tabla.setItem(fila, 3, QTableWidgetItem(item.destino or "—"))
            self.tabla.setItem(fila, 4, QTableWidgetItem(item.fecha_inicio_texto or "—"))

    def _confirmar(self) -> None:
        if not self._preview or self._caso_id is None:
            return
        self.btn_confirmar.setEnabled(False)
        self.barra.setMaximum(max(1, len(self._preview.nuevos)))

        def progreso(actual: int, total: int) -> None:
            self.barra.setMaximum(max(1, total))
            self.barra.setValue(actual)

        try:
            res = importar_carpeta_confirmado(
                self._con, self._caso_id, self._ruta, self._preview, progreso=progreso
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"Falló la importación:\n{exc}")
            self.btn_confirmar.setEnabled(True)
            return

        QMessageBox.information(
            self,
            "Importación finalizada",
            f"Nuevos: {res.nuevos}\n"
            f"Existentes (omitidos): {res.existentes}\n"
            f"Con error: {res.error}\n\n"
            f"⚠ Con audio faltante: {res.audio_faltante}\n"
            f"⚠ Con transcripción faltante: {res.txt_faltante}",
        )
        self.importacion_finalizada.emit()
        # Re-escanear para reflejar que ahora son "existentes".
        self._escanear()

    # ----------------------- Importar desde Excel ----------------------------
    def _importar_excel(self) -> None:
        if self._caso_id is None:
            QMessageBox.information(self, "Importar", "Primero abrí un caso.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Elegí un archivo Excel", "", "Excel (*.xlsx *.xls)"
        )
        if not path:
            return
        try:
            res = importar_desde_excel(self._con, self._caso_id, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"Falló la importación Excel:\n{exc}")
            return
        QMessageBox.information(
            self,
            "Importación Excel finalizada",
            f"Nuevos: {res.nuevos}\n"
            f"Existentes (omitidos): {res.existentes}\n"
            f"Con error: {res.error}",
        )
        self.importacion_finalizada.emit()

    # ----------------------- Importar desde Base SQLite -----------------------
    def _importar_db(self) -> None:
        if self._caso_id is None:
            QMessageBox.information(self, "Importar", "Primero abrí un caso.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Elegí una base de datos", "", "SQLite (*.db *.sqlite *.sqlite3)"
        )
        if not path:
            return
        try:
            casos = listar_casos_externos(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"No se pudo leer la base:\n{exc}")
            return

        if not casos:
            QMessageBox.information(self, "Importar", "La base no tiene casos.")
            return

        from PySide6.QtWidgets import QInputDialog

        items = [f"{c['nombre']} (#{c['id']}, {c['n_registros']} registros)" for c in casos]
        items.insert(0, "— Todos los casos —")
        elegido, ok = QInputDialog.getItem(
            self, "Seleccionar caso", "Caso a importar:", items, 0, False
        )
        if not ok:
            return

        caso_origen = None
        idx = items.index(elegido)
        if idx > 0:
            caso_origen = casos[idx - 1]["id"]

        try:
            res = fusionar_base_externa(
                self._con, self._caso_id, path, caso_id_origen=caso_origen
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"Falló la fusión:\n{exc}")
            return
        QMessageBox.information(
            self,
            "Importación DB finalizada",
            f"Nuevos: {res.nuevos}\n"
            f"Existentes (omitidos): {res.existentes}\n"
            f"Con error: {res.error}\n"
            f"Casos origen: {res.casos_origen}",
        )
        self.importacion_finalizada.emit()
