"""Panel centralizado de avisos de validación (pseudocódigo 6.9).

Lista los AvisoValidacion del caso, filtrable por tipo y por estado
(pendientes / resueltos / todos), con descripción, sugerencia, enlace al
registro involucrado y acción de marcar como resuelto.
"""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app import repositorios as repo
from app.ui import tema

# Etiquetas legibles por tipo de aviso.
_ETIQUETA_TIPO = {
    "audio_faltante": "Audio faltante",
    "transcripcion_faltante": "Transcripción faltante",
    "cd_no_detectado": "CD no detectado",
    "fecha_invalida": "Fecha inválida",
    "coordenadas_sospechosas": "Coordenadas sospechosas",
    "sin_abonados": "Sin abonados",
    "posible_duplicado_parcial": "Posible duplicado parcial",
}


class PantallaValidaciones(QWidget):
    """Lista de avisos con filtros y resolución."""

    ir_a_registro = Signal(int)  # registro_id
    aviso_resuelto = Signal()

    def __init__(self, con: sqlite3.Connection) -> None:
        super().__init__()
        self._con = con
        self._caso_id: int | None = None
        self._construir()

    def set_caso(self, caso_id: int) -> None:
        self._caso_id = caso_id
        self.refrescar()

    def _construir(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 12)
        layout.setSpacing(10)

        t = QLabel("Validaciones")
        t.setObjectName("titulo")
        layout.addWidget(t)
        self.lbl_resumen = QLabel("")
        self.lbl_resumen.setObjectName("subtitulo")
        self.lbl_resumen.setWordWrap(True)
        layout.addWidget(self.lbl_resumen)

        filtros = QHBoxLayout()
        self.cmb_tipo = QComboBox()
        self.cmb_tipo.addItem("Todos los tipos", None)
        for clave, etiqueta in _ETIQUETA_TIPO.items():
            self.cmb_tipo.addItem(etiqueta, clave)
        self.cmb_tipo.currentIndexChanged.connect(self.refrescar)
        filtros.addWidget(self.cmb_tipo)

        self.cmb_estado = QComboBox()
        self.cmb_estado.addItem("Pendientes", "pendientes")
        self.cmb_estado.addItem("Resueltos", "resueltos")
        self.cmb_estado.addItem("Todos", "todos")
        self.cmb_estado.currentIndexChanged.connect(self.refrescar)
        filtros.addWidget(self.cmb_estado)
        filtros.addStretch(1)
        layout.addLayout(filtros)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.lista = QWidget()
        self.lista_lay = QVBoxLayout(self.lista)
        self.lista_lay.setContentsMargins(0, 0, 0, 0)
        self.lista_lay.setSpacing(8)
        self.lista_lay.addStretch(1)
        scroll.setWidget(self.lista)
        layout.addWidget(scroll, 1)

    def refrescar(self) -> None:
        if self._caso_id is None:
            return
        # Limpiar lista (preservando el stretch final).
        while self.lista_lay.count() > 1:
            item = self.lista_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        tipo = self.cmb_tipo.currentData()
        estado = self.cmb_estado.currentData()
        avisos = repo.listar_avisos(self._con, self._caso_id, tipo, estado)

        por_tipo = repo.contar_avisos_por_tipo(self._con, self._caso_id)
        total_pend = sum(por_tipo.values())
        detalle = ", ".join(
            f"{por_tipo[k]} {_ETIQUETA_TIPO.get(k, k).lower()}"
            for k in sorted(por_tipo)
        )
        self.lbl_resumen.setText(
            f"{total_pend} pendientes" + (f" ({detalle})" if detalle else "")
        )

        if not avisos:
            vacio = QLabel("Sin avisos para los filtros seleccionados.")
            vacio.setObjectName("subtitulo")
            self.lista_lay.insertWidget(0, vacio)
            return

        for aviso in avisos:
            self.lista_lay.insertWidget(self.lista_lay.count() - 1, self._tarjeta(aviso))

    def _tarjeta(self, aviso: sqlite3.Row) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        encabezado = QHBoxLayout()
        badge = QLabel(_ETIQUETA_TIPO.get(aviso["tipo"], aviso["tipo"]))
        resuelto = bool(aviso["resuelto"])
        color = tema.TEAL if resuelto else tema.DANGER
        badge.setStyleSheet(
            f"background: rgba(95,168,160,0.16); color:{color};"
            f"border:1px solid {color}; border-radius:10px; padding:2px 10px; font-size:11px;"
        )
        encabezado.addWidget(badge)
        if aviso["registro_orden"] is not None:
            ref = QLabel(f"Registro Nº {aviso['registro_orden']}")
            ref.setObjectName("subtitulo")
            encabezado.addWidget(ref)
        encabezado.addStretch(1)
        if resuelto:
            est = QLabel(f"✓ resuelto · {aviso['resuelto_por'] or ''}")
            est.setStyleSheet(f"color:{tema.TEAL}; font-size:11px;")
            encabezado.addWidget(est)
        lay.addLayout(encabezado)

        desc = QLabel(aviso["descripcion"] or "")
        desc.setWordWrap(True)
        lay.addWidget(desc)
        sug = QLabel("💡 " + (aviso["sugerencia"] or ""))
        sug.setWordWrap(True)
        sug.setStyleSheet(f"color:{tema.TEXT_DIM}; font-size:12px;")
        lay.addWidget(sug)

        acciones = QHBoxLayout()
        acciones.addStretch(1)
        if aviso["registro_id"] is not None:
            btn_ir = QPushButton("Ir al registro")
            btn_ir.clicked.connect(
                lambda _=False, rid=aviso["registro_id"]: self.ir_a_registro.emit(rid)
            )
            acciones.addWidget(btn_ir)
        if not resuelto:
            btn_ok = QPushButton("Marcar como resuelto")
            btn_ok.setObjectName("primary")
            btn_ok.clicked.connect(
                lambda _=False, aid=aviso["id"]: self._resolver(aid)
            )
            acciones.addWidget(btn_ok)
        lay.addLayout(acciones)
        return card

    def _resolver(self, aviso_id: int) -> None:
        repo.marcar_aviso_resuelto(self._con, aviso_id, usuario="analista")
        repo.log_auditoria(
            self._con, "edito", f"Aviso #{aviso_id} marcado resuelto", self._caso_id
        )
        self._con.commit()
        self.refrescar()
        self.aviso_resuelto.emit()
