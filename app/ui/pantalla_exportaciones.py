"""Pantalla de lotes de exportación con opción de deshacer (pseudocódigo 6.10)."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app import repositorios as repo
from app.ui import tema

_TIPO_LABEL = {
    "word_informe": "Informe Word",
    "excel": "Excel",
    "imagen_mapa": "Imagen de mapa",
    "imagen_grafo": "Imagen de grafo",
}


class PantallaExportaciones(QWidget):
    """Lista de lotes de exportación con opción de deshacer."""

    lote_deshecho = Signal()

    def __init__(self, con: sqlite3.Connection) -> None:
        super().__init__()
        self._con = con
        self._caso_id: int | None = None
        self._construir()

    def set_caso(self, caso_id: int) -> None:
        self._caso_id = caso_id
        self.refrescar()

    def _construir(self) -> None:
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(22, 16, 22, 10)
        raiz.setSpacing(10)

        titulo = QLabel("Historial de exportaciones")
        titulo.setObjectName("titulo")
        raiz.addWidget(titulo)

        self.lbl_sub = QLabel("Lotes generados para el caso activo")
        self.lbl_sub.setObjectName("subtitulo")
        raiz.addWidget(self.lbl_sub)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        self._contenedor = QWidget()
        self._lay = QVBoxLayout(self._contenedor)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(8)
        self._lay.addStretch(1)
        scroll.setWidget(self._contenedor)
        raiz.addWidget(scroll, 1)

    def refrescar(self) -> None:
        if self._caso_id is None:
            return
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        lotes = repo.listar_lotes_exportacion(self._con, self._caso_id)
        if not lotes:
            vacio = QLabel("No hay exportaciones registradas.")
            vacio.setStyleSheet(f"color: {tema.TEXT_DIM}; padding: 20px;")
            self._lay.addWidget(vacio)
        else:
            for lote in lotes:
                self._lay.addWidget(self._tarjeta_lote(lote))
        self._lay.addStretch(1)
        self.lbl_sub.setText(f"{len(lotes)} lotes registrados")

    def _tarjeta_lote(self, lote: sqlite3.Row) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            f"background: {tema.PANEL_RAISED}; border-radius: 8px; padding: 12px;"
        )
        lay = QHBoxLayout(card)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(12)

        tipo = _TIPO_LABEL.get(lote["tipo"], lote["tipo"])
        info = QVBoxLayout()
        lbl_tipo = QLabel(tipo)
        lbl_tipo.setStyleSheet(f"font-weight: bold; color: {tema.TEXT_PRIMARY};")
        info.addWidget(lbl_tipo)

        lbl_fecha = QLabel(f"Fecha: {lote['fecha']}")
        lbl_fecha.setStyleSheet(f"color: {tema.TEXT_DIM}; font-size: 11px;")
        info.addWidget(lbl_fecha)

        if lote["usuario"]:
            lbl_user = QLabel(f"Usuario: {lote['usuario']}")
            lbl_user.setStyleSheet(f"color: {tema.TEXT_DIM}; font-size: 11px;")
            info.addWidget(lbl_user)

        lay.addLayout(info, 1)

        if lote["deshecho"]:
            badge = QLabel("DESHECHO")
            badge.setStyleSheet(
                f"color: {tema.DANGER}; font-weight: bold; font-size: 11px; "
                f"padding: 4px 8px; border: 1px solid {tema.DANGER}; border-radius: 4px;"
            )
            lay.addWidget(badge)
            if lote["fecha_deshecho"]:
                lbl_fd = QLabel(lote["fecha_deshecho"])
                lbl_fd.setStyleSheet(f"color: {tema.TEXT_DIM}; font-size: 10px;")
                lay.addWidget(lbl_fd)
        else:
            btn = QPushButton("Deshacer")
            btn.setStyleSheet(
                f"background: {tema.DANGER}; color: white; padding: 6px 16px; "
                f"border-radius: 4px; font-weight: bold;"
            )
            lote_id = lote["id"]
            btn.clicked.connect(lambda _=False, _id=lote_id: self._deshacer(_id))
            lay.addWidget(btn)

        return card

    def _deshacer(self, lote_id: int) -> None:
        resp = QMessageBox.question(
            self,
            "Deshacer exportación",
            f"¿Revertir los cambios del lote #{lote_id}? "
            "Los registros marcados como 'informada' volverán a su estado anterior.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        n = repo.deshacer_lote_exportacion(self._con, lote_id)
        QMessageBox.information(
            self, "Deshacer", f"Lote #{lote_id} deshecho. {n} cambio(s) revertido(s)."
        )
        self.refrescar()
        self.lote_deshecho.emit()
