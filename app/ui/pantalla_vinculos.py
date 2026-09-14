"""Pantalla de detección de vínculos entre casos (pseudocódigo 6.8).

Selector de 2 casos a comparar, botón buscar vínculos, lista de candidatos
con botón confirmar/descartar.
"""

from __future__ import annotations

import json
import sqlite3

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app import repositorios as repo
from app.analisis import vinculos
from app.ui import tema

_TIPO_LABEL = {
    "mismo_abonado": "Mismo abonado",
    "misma_antena_cercania_horaria": "Misma antena + cercanía horaria",
}


class PantallaVinculos(QWidget):
    """Pantalla de vínculos entre casos."""

    def __init__(self, con: sqlite3.Connection) -> None:
        super().__init__()
        self._con = con
        self._caso_id: int | None = None
        self._construir()

    def set_caso(self, caso_id: int) -> None:
        self._caso_id = caso_id
        self._actualizar_combos()
        self._refrescar_lista()

    def refrescar(self) -> None:
        if self._caso_id is None:
            return
        self._actualizar_combos()
        self._refrescar_lista()

    def _construir(self) -> None:
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(22, 16, 22, 10)
        raiz.setSpacing(10)

        titulo = QLabel("Vínculos entre casos")
        titulo.setObjectName("titulo")
        raiz.addWidget(titulo)

        sub = QLabel("Detecta abonados y antenas compartidas entre dos causas")
        sub.setObjectName("subtitulo")
        raiz.addWidget(sub)

        sel = QHBoxLayout()
        sel.setSpacing(10)

        sel.addWidget(QLabel("Caso actual vs:"))
        self.cmb_otro = QComboBox()
        self.cmb_otro.setMinimumWidth(200)
        sel.addWidget(self.cmb_otro)

        self.btn_buscar = QPushButton("Buscar vínculos")
        self.btn_buscar.setObjectName("primary")
        self.btn_buscar.clicked.connect(self._buscar)
        sel.addWidget(self.btn_buscar)
        sel.addStretch(1)
        raiz.addLayout(sel)

        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("subtitulo")
        raiz.addWidget(self.lbl_status)

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

    def _actualizar_combos(self) -> None:
        self.cmb_otro.clear()
        casos = repo.listar_casos(self._con)
        for c in casos:
            if c["id"] != self._caso_id:
                self.cmb_otro.addItem(f"{c['nombre']} (#{c['id']})", c["id"])

    def _buscar(self) -> None:
        if self._caso_id is None or self.cmb_otro.count() == 0:
            return
        otro_id = self.cmb_otro.currentData()
        if otro_id is None:
            return
        ids = vinculos.detectar_vinculos_entre_casos(self._con, self._caso_id, otro_id)
        if ids:
            QMessageBox.information(
                self, "Vínculos", f"Se detectaron {len(ids)} vínculo(s) potencial(es)."
            )
        else:
            QMessageBox.information(
                self, "Vínculos", "No se detectaron vínculos entre los casos."
            )
        self._refrescar_lista()

    def _refrescar_lista(self) -> None:
        while self._lay.count():
            item = self._lay.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        if self._caso_id is None:
            self._lay.addStretch(1)
            return

        lista = vinculos.listar_vinculos(self._con, self._caso_id)
        if not lista:
            vacio = QLabel("No hay vínculos detectados.")
            vacio.setStyleSheet(f"color: {tema.TEXT_DIM}; padding: 20px;")
            self._lay.addWidget(vacio)
        else:
            for v in lista:
                self._lay.addWidget(self._tarjeta_vinculo(v))

        self._lay.addStretch(1)
        n_conf = sum(1 for v in lista if v["confirmado"])
        self.lbl_status.setText(
            f"{len(lista)} vínculos detectados · {n_conf} confirmados"
        )

    def _tarjeta_vinculo(self, v: sqlite3.Row) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            f"background: {tema.SURFACE if hasattr(tema, 'SURFACE') else tema.PANEL_RAISED}; "
            f"border-radius: 8px; padding: 10px;"
        )
        lay = QHBoxLayout(card)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(12)

        info = QVBoxLayout()
        tipo = _TIPO_LABEL.get(v["tipo"], v["tipo"])
        lbl_tipo = QLabel(tipo)
        lbl_tipo.setStyleSheet(f"font-weight: bold; color: {tema.TEXT_PRIMARY};")
        info.addWidget(lbl_tipo)

        detalle = json.loads(v["detalle_json"]) if v["detalle_json"] else {}
        detalle_txt = ", ".join(f"{k}: {v}" for k, v in detalle.items())
        if detalle_txt:
            lbl_det = QLabel(detalle_txt)
            lbl_det.setStyleSheet(f"color: {tema.TEXT_DIM}; font-size: 11px;")
            lbl_det.setWordWrap(True)
            info.addWidget(lbl_det)

        lbl_casos = QLabel(f"Casos: #{v['caso_id_a']} ↔ #{v['caso_id_b']}")
        lbl_casos.setStyleSheet(f"color: {tema.TEXT_DIM}; font-size: 10px;")
        info.addWidget(lbl_casos)

        lay.addLayout(info, 1)

        if v["confirmado"]:
            badge = QLabel("CONFIRMADO")
            badge.setStyleSheet(
                f"color: {tema.TEAL}; font-weight: bold; font-size: 11px; "
                f"padding: 4px 8px; border: 1px solid {tema.TEAL}; border-radius: 4px;"
            )
            lay.addWidget(badge)
        else:
            btn_conf = QPushButton("Confirmar")
            btn_conf.setStyleSheet(
                f"background: {tema.TEAL}; color: white; padding: 6px 12px; "
                f"border-radius: 4px; font-weight: bold;"
            )
            vid = v["id"]
            btn_conf.clicked.connect(lambda _=False, _id=vid: self._confirmar(_id))
            lay.addWidget(btn_conf)

            btn_desc = QPushButton("Descartar")
            btn_desc.setStyleSheet(
                f"background: {tema.DANGER}; color: white; padding: 6px 12px; "
                f"border-radius: 4px;"
            )
            btn_desc.clicked.connect(lambda _=False, _id=vid: self._descartar(_id))
            lay.addWidget(btn_desc)

        return card

    def _confirmar(self, vinculo_id: int) -> None:
        vinculos.confirmar_vinculo(self._con, vinculo_id)
        self._refrescar_lista()

    def _descartar(self, vinculo_id: int) -> None:
        vinculos.descartar_vinculo(self._con, vinculo_id)
        self._refrescar_lista()
