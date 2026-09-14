"""Pantalla de mapa de cobertura (pseudocódigo 6.5).

Renderiza sectores de cobertura (azimuth + radio) por registro sobre un mapa
real (Google / OpenStreetMap) embebido con QtWebEngine + Leaflet. Los sectores
se colorean por abonado; soporta filtros, leyenda lateral, secuencia temporal
y exportación a imagen.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app import repositorios as repo
from app.core.colores import estilo_por_interes
from app.ui import tema
from app.ui.dialogos import mostrar_exportacion

_SECTOR_SPAN_DEG = 60
_RECURSOS_DIR = Path(__file__).resolve().parent / "recursos"


def _parse_float(val: str | None) -> float | None:
    if not val:
        return None
    try:
        return float(val.replace(",", "."))
    except (ValueError, TypeError):
        return None


class _RegistroMapa:
    """Datos preprocesados de un registro para dibujar en el mapa."""

    __slots__ = (
        "lat", "lon", "azimuth", "radio_km", "color_hex", "nivel_interes",
        "estado", "interesado", "orden", "registro_id", "fecha_dt",
        "direccion", "origen", "destino",
    )

    def __init__(self, row: sqlite3.Row) -> None:
        self.lat = _parse_float(row["latitud"])
        self.lon = _parse_float(row["longitud"])
        self.azimuth = _parse_float(row["azimuth"])
        self.radio_km = _parse_float(row["radio"])
        self.color_hex = row["color_hex"] or "#888888"
        self.nivel_interes = row["nivel_interes"] or "ninguno"
        self.estado = row["estado"]
        self.interesado = row["interesado"] or ""
        self.orden = row["orden"]
        self.registro_id = row["id"]
        self.fecha_dt = row["fecha_inicio_dt"]
        self.direccion = row["direccion"] or ""
        self.origen = row["origen"] or ""
        self.destino = row["destino"] or ""

    @property
    def valido(self) -> bool:
        return self.lat is not None and self.lon is not None

    def a_dict(self) -> dict[str, object]:
        estilo = estilo_por_interes(self.color_hex, self.nivel_interes)
        return {
            "lat": self.lat,
            "lon": self.lon,
            "az": self.azimuth,
            "radio": self.radio_km,
            "color": self.color_hex,
            "fill": estilo["color"],
            "weight": estilo["borde"],
            "dash": self.estado == "audio_faltante",
            "orden": self.orden,
            "interesado": self.interesado,
            "fecha": str(self.fecha_dt or ""),
            "direccion": self.direccion,
            "origen": self.origen,
            "destino": self.destino,
            "nivel": self.nivel_interes,
        }


class _MapaWeb(QWebEngineView):
    """Visor Leaflet embebido (capas Google / OpenStreetMap)."""

    # Emite el motivo cuando el visor no se puede usar, para que la pantalla lo
    # muestre en vez de dejar un rectángulo vacío sin explicación.
    fallo = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self._registros: list[_RegistroMapa] = []
        self._listo = False
        self._payload_pendiente: str | None = None
        # La página se carga desde file://; sin esto Chromium bloquea las
        # teselas remotas (Google/OSM) y el mapa queda en negro.
        self.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        self.loadFinished.connect(self._al_cargar)
        self._html = _RECURSOS_DIR / "mapa.html"
        if not self._html.is_file():
            # Falta un recurso de la instalación: avisarlo es mucho más útil
            # que un visor en blanco.
            QTimer.singleShot(
                0,
                lambda: self.fallo.emit(
                    f"No se encontró el archivo del mapa:\n{self._html}"
                ),
            )
            return
        self.load(QUrl.fromLocalFile(str(self._html)))

    def _al_cargar(self, ok: bool) -> None:
        self._listo = ok
        if not ok:
            self.fallo.emit(
                "El visor de mapas no pudo cargarse.\n\n"
                "Suele ser un problema de aceleración gráfica del equipo. "
                "Probá iniciar la aplicación con la variable de entorno "
                "QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu"
            )
            return
        if self._payload_pendiente is not None:
            self.page().runJavaScript(f"actualizarDatos({self._payload_pendiente});")
            self._payload_pendiente = None

    def set_registros(self, registros: list[_RegistroMapa], secuencia: bool) -> None:
        self._registros = registros
        if secuencia:
            registros = sorted(
                registros, key=lambda r: (str(r.fecha_dt or ""), r.orden)
            )
        payload = json.dumps(
            {
                "registros": [r.a_dict() for r in registros],
                "secuencia": secuencia,
                "span": _SECTOR_SPAN_DEG,
            },
            ensure_ascii=False,
        )
        if self._listo:
            self.page().runJavaScript(f"actualizarDatos({payload});")
        else:
            self._payload_pendiente = payload

    def resetear_vista(self) -> None:
        if self._listo:
            self.page().runJavaScript("resetearVista();")

    def exportar_pixmap(self) -> QPixmap:
        return self.grab()


class PantallaMapa(QWidget):
    """Pantalla de mapa de cobertura con filtros y leyenda."""

    def __init__(self, con: sqlite3.Connection) -> None:
        super().__init__()
        self._con = con
        self._caso_id: int | None = None
        self._registros_raw: list[sqlite3.Row] = []
        self._interesados: list[str] = []
        self._construir()

    def set_caso(self, caso_id: int) -> None:
        self._caso_id = caso_id
        self.refrescar()

    def refrescar(self) -> None:
        if self._caso_id is None:
            return
        self._registros_raw = repo.listar_registros(self._con, self._caso_id)
        self._actualizar_interesados()
        self._aplicar_filtros()

    def _construir(self) -> None:
        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        main = QWidget()
        mlay = QVBoxLayout(main)
        mlay.setContentsMargins(12, 10, 12, 10)
        mlay.setSpacing(8)

        cab = QHBoxLayout()
        titulo = QLabel("Mapa de cobertura")
        titulo.setObjectName("titulo")
        cab.addWidget(titulo)
        cab.addStretch(1)

        self.btn_reset = QPushButton("Resetear vista")
        self.btn_reset.clicked.connect(self._resetear_vista)
        cab.addWidget(self.btn_reset)

        self.btn_export = QPushButton("Exportar imagen")
        self.btn_export.setObjectName("primary")
        self.btn_export.clicked.connect(self._exportar_imagen)
        cab.addWidget(self.btn_export)
        mlay.addLayout(cab)

        filtros = QHBoxLayout()
        filtros.setSpacing(10)

        filtros.addWidget(QLabel("Interesado:"))
        self.cmb_interesado = QComboBox()
        self.cmb_interesado.setMinimumWidth(140)
        self.cmb_interesado.currentIndexChanged.connect(self._aplicar_filtros)
        filtros.addWidget(self.cmb_interesado)

        filtros.addWidget(QLabel("Dirección:"))
        self.cmb_direccion = QComboBox()
        self.cmb_direccion.addItems(["Todos", "ENTRANTE", "SALIENTE", "DESCONOCIDO"])
        self.cmb_direccion.currentIndexChanged.connect(self._aplicar_filtros)
        filtros.addWidget(self.cmb_direccion)

        filtros.addWidget(QLabel("Interés:"))
        self.cmb_interes = QComboBox()
        self.cmb_interes.addItems(["Todos", "De interés", "Sin marcar"])
        self.cmb_interes.currentIndexChanged.connect(self._aplicar_filtros)
        filtros.addWidget(self.cmb_interes)

        self.chk_secuencia = QCheckBox("Secuencia temporal")
        self.chk_secuencia.toggled.connect(self._aplicar_filtros)
        filtros.addWidget(self.chk_secuencia)

        filtros.addStretch(1)
        mlay.addLayout(filtros)

        self.canvas = _MapaWeb()
        self.canvas.fallo.connect(self._mostrar_fallo)
        mlay.addWidget(self.canvas, 1)

        # Ocupa el lugar del visor cuando este no puede funcionar.
        self.lbl_fallo = QLabel()
        self.lbl_fallo.setWordWrap(True)
        self.lbl_fallo.setAlignment(Qt.AlignCenter)
        self.lbl_fallo.setVisible(False)
        self.lbl_fallo.setStyleSheet(
            f"color:{tema.DANGER}; border:1px solid {tema.DANGER};"
            "border-radius:8px; padding:18px; font-size:12px;"
        )
        mlay.addWidget(self.lbl_fallo, 1)

        self.lbl_status = QLabel("Sin datos")
        self.lbl_status.setObjectName("subtitulo")
        mlay.addWidget(self.lbl_status)

        raiz.addWidget(main, 1)

        self._panel_leyenda = self._crear_panel_leyenda()
        raiz.addWidget(self._panel_leyenda)

    def _crear_panel_leyenda(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setFixedWidth(220)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(6)

        lbl = QLabel("LEYENDA")
        lbl.setObjectName("seccion")
        lay.addWidget(lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._leyenda_widget = QWidget()
        self._leyenda_lay = QVBoxLayout(self._leyenda_widget)
        self._leyenda_lay.setContentsMargins(0, 0, 0, 0)
        self._leyenda_lay.setSpacing(4)
        self._leyenda_lay.addStretch(1)
        scroll.setWidget(self._leyenda_widget)
        lay.addWidget(scroll, 1)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{tema.LINE};")
        lay.addWidget(sep)

        self.lbl_info = QLabel("")
        self.lbl_info.setObjectName("subtitulo")
        self.lbl_info.setWordWrap(True)
        lay.addWidget(self.lbl_info)

        return panel

    def _actualizar_interesados(self) -> None:
        interesados = sorted(
            {r["interesado"] for r in self._registros_raw if r["interesado"]}
        )
        self.cmb_interesado.blockSignals(True)
        self.cmb_interesado.clear()
        self.cmb_interesado.addItem("Todos")
        self.cmb_interesado.addItems(interesados)
        self.cmb_interesado.blockSignals(False)
        self._interesados = interesados

    def _aplicar_filtros(self) -> None:
        filtro_interesado = self.cmb_interesado.currentText()
        filtro_dir = self.cmb_direccion.currentText()
        filtro_interes = self.cmb_interes.currentText()

        filtrados = []
        for row in self._registros_raw:
            if row["estado"] == "transcripcion_faltante":
                continue
            rm = _RegistroMapa(row)
            if not rm.valido:
                continue
            if filtro_interesado != "Todos" and rm.interesado != filtro_interesado:
                continue
            if filtro_dir != "Todos" and rm.direccion != filtro_dir:
                continue
            if filtro_interes != "Todos":
                marcada = (rm.nivel_interes or "ninguno") != "ninguno"
                if marcada != (filtro_interes == "De interés"):
                    continue
            filtrados.append(rm)

        self.canvas.set_registros(filtrados, self.chk_secuencia.isChecked())
        self._actualizar_leyenda(filtrados)

        n_sin_coord = sum(
            1 for r in self._registros_raw
            if r["estado"] != "transcripcion_faltante"
            and not (_parse_float(r["latitud"]) and _parse_float(r["longitud"]))
        )
        self.lbl_status.setText(
            f"{len(filtrados)} registros en mapa · {n_sin_coord} sin coordenadas (excluidos)"
        )

    def _actualizar_leyenda(self, registros: list[_RegistroMapa]) -> None:
        while self._leyenda_lay.count():
            item = self._leyenda_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        abonados: dict[str, str] = {}
        for r in registros:
            key = r.interesado or r.origen
            if key and key not in abonados:
                abonados[key] = r.color_hex

        for nombre, color in abonados.items():
            fila = QWidget()
            flay = QHBoxLayout(fila)
            flay.setContentsMargins(0, 2, 0, 2)
            flay.setSpacing(6)

            dot = QLabel()
            dot.setFixedSize(12, 12)
            dot.setStyleSheet(
                f"background: {color}; border-radius: 6px; border: 1px solid {tema.LINE};"
            )
            flay.addWidget(dot)

            lbl = QLabel(nombre)
            lbl.setStyleSheet(f"color: {tema.TEXT_PRIMARY}; font-size: 11px;")
            lbl.setWordWrap(True)
            flay.addWidget(lbl, 1)

            self._leyenda_lay.addWidget(fila)

        self._leyenda_lay.addStretch(1)
        self.lbl_info.setText(
            f"{len(abonados)} abonados\n{len(registros)} registros"
        )

    def _mostrar_fallo(self, motivo: str) -> None:
        self.canvas.setVisible(False)
        self.lbl_fallo.setText(f"⚠  {motivo}")
        self.lbl_fallo.setVisible(True)
        self.btn_reset.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.lbl_status.setText("Mapa no disponible")

    def _resetear_vista(self) -> None:
        self.canvas.resetear_vista()

    def _exportar_imagen(self) -> None:
        if self._caso_id is None:
            return
        caso = repo.obtener_caso(self._con, self._caso_id)
        nombre = caso["nombre"] if caso else "mapa"
        sugerido = f"Mapa_{nombre}.png".replace("/", "-").replace(" ", "_")
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Exportar mapa", sugerido, "Imágenes (*.png)"
        )
        if not ruta:
            return

        pixmap = self.canvas.exportar_pixmap()

        result = QPixmap(pixmap.width() + 220, pixmap.height())
        result.fill(QColor(tema.PANEL))
        painter = QPainter(result)
        painter.drawPixmap(0, 0, pixmap)

        x_panel = pixmap.width() + 10
        painter.setPen(QColor(tema.TEXT_PRIMARY))
        font = painter.font()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(x_panel, 25, nombre)

        font.setBold(False)
        font.setPointSize(9)
        painter.setFont(font)
        painter.setPen(QColor(tema.TEXT_DIM))
        ahora = datetime.now().strftime("%d/%m/%Y %H:%M")
        painter.drawText(x_panel, 45, f"Generado: {ahora}")

        filtros_txt = []
        if self.cmb_interesado.currentText() != "Todos":
            filtros_txt.append(f"Interesado: {self.cmb_interesado.currentText()}")
        if self.cmb_direccion.currentText() != "Todos":
            filtros_txt.append(f"Dir: {self.cmb_direccion.currentText()}")
        if self.cmb_interes.currentText() != "Todos":
            filtros_txt.append(f"Interés: {self.cmb_interes.currentText()}")
        if filtros_txt:
            painter.drawText(x_panel, 65, " | ".join(filtros_txt))

        y = 90
        painter.setPen(QColor(tema.TEXT_DIM))
        painter.drawText(x_panel, y, "LEYENDA")
        y += 20

        for i in range(self._leyenda_lay.count()):
            item = self._leyenda_lay.itemAt(i)
            w = item.widget()
            if w is None:
                continue
            flay = w.layout()
            if flay is None or flay.count() < 2:
                continue
            dot_w = flay.itemAt(0).widget()
            lbl_w = flay.itemAt(1).widget()
            if dot_w and lbl_w:
                color = dot_w.palette().color(dot_w.backgroundRole())
                ss = dot_w.styleSheet()
                for part in ss.split(";"):
                    if "background" in part and "#" in part:
                        color = QColor(part.split(":")[1].strip())
                        break
                painter.setBrush(QBrush(color))
                painter.setPen(QPen(QColor(tema.LINE)))
                painter.drawEllipse(x_panel, y - 8, 10, 10)
                painter.setPen(QColor(tema.TEXT_PRIMARY))
                painter.drawText(x_panel + 16, y, lbl_w.text())
                y += 18

        painter.end()
        result.save(ruta, "PNG")

        repo.log_auditoria(
            self._con, "exporto",
            f"Mapa de cobertura -> {ruta}",
            self._caso_id,
        )
        self._con.commit()
        mostrar_exportacion(self, ruta, "Exportar mapa")
