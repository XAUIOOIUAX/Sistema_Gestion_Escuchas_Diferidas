"""Pantalla de línea de tiempo cronológica (pseudocódigo 6.7).

Muestra registros como marcadores sobre un eje temporal, agrupados por
interesado. Registros sin fecha o con transcripcion_faltante sin fecha se
excluyen. Audio_faltante aparecen con borde punteado. Marcadores de
EventoClave con resaltado de proximidad. Modo comparador de 2 abonados.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app import repositorios as repo
from app.analisis import eventos
from app.ui import tema

_LANE_HEIGHT = 50
_MARKER_RADIUS = 8
# Ancho reservado a la izquierda para el nombre del abonado de cada lane.
_ANCHO_ETIQUETA_LANE = 72
_EVENT_COLOR = "#D7A53D"


def _parse_dt(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        return None


_ETIQUETA_ESTADO = {
    "audio_faltante": "audio faltante",
    "transcripcion_faltante": "transcripción faltante",
}


def _tooltip_marcador(abonado: str, r: sqlite3.Row) -> str:
    """Identifica el registro detrás de un marcador de 8px."""
    lineas = [f"Registro {r['orden']} · {abonado}"]
    dt = _parse_dt(r["fecha_inicio_dt"])
    if dt is not None:
        lineas.append(dt.strftime("%d/%m/%Y %H:%M:%S"))
    if r["origen"] or r["destino"]:
        lineas.append(f"{r['origen'] or '?'} → {r['destino'] or '?'}")
    estado = _ETIQUETA_ESTADO.get(r["estado"])
    if estado:
        lineas.append(f"⚠ {estado}")
    nivel = r["nivel_interes"] or "ninguno"
    if nivel != "ninguno":
        lineas.append(f"Interés: {nivel}")
    return "\n".join(lineas)


class _TimelineCanvas(QWidget):
    """Widget de dibujo de la línea de tiempo."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Necesario para que mouseMoveEvent llegue sin botón apretado.
        self.setMouseTracking(True)
        self._lanes: list[tuple[str, str, list]] = []
        self._eventos: list[sqlite3.Row] = []
        self._dt_min: datetime | None = None
        self._dt_max: datetime | None = None
        self._zoom = 1.0
        self._offset_x = 0.0
        self._dragging = False
        self._drag_start = QPointF()
        self._offset_start_x = 0.0
        self.setMinimumSize(400, 200)

    def set_datos(
        self,
        lanes: list[tuple[str, str, list]],
        eventos_list: list[sqlite3.Row],
        dt_min: datetime | None,
        dt_max: datetime | None,
    ) -> None:
        self._lanes = lanes
        self._eventos = eventos_list
        self._dt_min = dt_min
        self._dt_max = dt_max
        self._zoom = 1.0
        self._offset_x = 0.0
        min_h = max(300, len(lanes) * _LANE_HEIGHT + 80)
        self.setMinimumHeight(min_h)
        self.update()

    def exportar_pixmap(self) -> QPixmap:
        pixmap = QPixmap(self.size())
        pixmap.fill(QColor(tema.BG_DEEP))
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.Antialiasing)
        self._dibujar(p)
        p.end()
        return pixmap

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(tema.BG_DEEP))
        self._dibujar(p)

    def _dt_to_x(self, dt: datetime) -> float:
        if self._dt_min is None or self._dt_max is None:
            return 0
        total = (self._dt_max - self._dt_min).total_seconds() or 1
        frac = (dt - self._dt_min).total_seconds() / total
        margin = 80
        return (margin + frac * (self.width() - margin * 2)) * self._zoom + self._offset_x

    def _dibujar(self, p: QPainter) -> None:
        if not self._lanes or self._dt_min is None:
            p.setPen(QColor(tema.TEXT_DIM))
            p.drawText(self.rect(), Qt.AlignCenter, "Sin registros con fecha para mostrar")
            return

        self._dibujar_eje_tiempo(p)
        self._dibujar_eventos_clave(p)
        self._dibujar_lanes(p)

    def _dibujar_eje_tiempo(self, p: QPainter) -> None:
        if self._dt_min is None or self._dt_max is None:
            return
        y_base = 30
        p.setPen(QPen(QColor(tema.LINE), 1))
        x1 = self._dt_to_x(self._dt_min)
        x2 = self._dt_to_x(self._dt_max)
        p.drawLine(QPointF(x1, y_base), QPointF(x2, y_base))

        total_sec = (self._dt_max - self._dt_min).total_seconds()
        if total_sec <= 3600 * 2:
            step_sec = 600
            fmt = "%H:%M"
        elif total_sec <= 3600 * 48:
            step_sec = 3600
            fmt = "%d/%m %H:%M"
        else:
            step_sec = 3600 * 24
            fmt = "%d/%m/%Y"

        font = p.font()
        font.setPointSize(7)
        p.setFont(font)
        p.setPen(QColor(tema.TEXT_DIM))

        from datetime import timedelta
        t = self._dt_min
        while t <= self._dt_max:
            x = self._dt_to_x(t)
            p.drawLine(QPointF(x, y_base - 4), QPointF(x, y_base + 4))
            p.drawText(int(x) - 30, int(y_base) - 14, 60, 12, Qt.AlignCenter, t.strftime(fmt))
            t += timedelta(seconds=step_sec)

    def _dibujar_eventos_clave(self, p: QPainter) -> None:
        for ev in self._eventos:
            dt = _parse_dt(ev["fecha_hora"])
            if dt is None:
                continue
            if self._dt_min and self._dt_max and (dt < self._dt_min or dt > self._dt_max):
                continue
            x = self._dt_to_x(dt)
            color = QColor(_EVENT_COLOR)
            color.setAlpha(40)
            ventana_min = ev["ventana_minutos"]
            from datetime import timedelta
            x_ini = self._dt_to_x(dt - timedelta(minutes=ventana_min))
            x_fin = self._dt_to_x(dt + timedelta(minutes=ventana_min))
            p.fillRect(QRectF(x_ini, 0, x_fin - x_ini, self.height()), QBrush(color))

            p.setPen(QPen(QColor(_EVENT_COLOR), 2, Qt.DashDotLine))
            p.drawLine(QPointF(x, 0), QPointF(x, self.height()))

            font = p.font()
            font.setPointSize(8)
            font.setBold(True)
            p.setFont(font)
            p.setPen(QColor(_EVENT_COLOR))
            desc = ev["descripcion"] or ""
            p.drawText(int(x) + 4, self.height() - 8, desc[:30])

    def _dibujar_lanes(self, p: QPainter) -> None:
        y_offset = 50
        for nombre, color, regs in self._lanes:
            y = y_offset
            p.setPen(QPen(QColor(tema.LINE), 1, Qt.DotLine))
            x1 = self._dt_to_x(self._dt_min) if self._dt_min else 0
            x2 = self._dt_to_x(self._dt_max) if self._dt_max else self.width()
            p.drawLine(QPointF(x1, y), QPointF(x2, y))

            font = p.font()
            font.setPointSize(8)
            font.setBold(False)
            p.setFont(font)
            p.setPen(QColor(tema.TEXT_DIM))
            # elidedText en vez de nombre[-12:]: quedarse con los últimos 12
            # caracteres convertía "ORIGEN: X / DESTINO: Y" en "TINO: Y", sin
            # ninguna marca de que el texto estaba recortado.
            p.drawText(
                4, int(y) + 4,
                p.fontMetrics().elidedText(nombre, Qt.ElideRight, _ANCHO_ETIQUETA_LANE),
            )

            for r in regs:
                dt = _parse_dt(r["fecha_inicio_dt"])
                if dt is None:
                    continue
                x = self._dt_to_x(dt)
                c = QColor(color)
                pen = QPen(c.darker(130), 2)
                if r["estado"] == "audio_faltante":
                    pen.setStyle(Qt.DashLine)
                p.setPen(pen)
                c.setAlpha(200)
                p.setBrush(QBrush(c))
                p.drawEllipse(QPointF(x, y), _MARKER_RADIUS, _MARKER_RADIUS)

                nivel = r["nivel_interes"] or "ninguno"
                if nivel == "alto":
                    p.setPen(QPen(QColor(tema.ACCENT), 2))
                    p.setBrush(Qt.NoBrush)
                    p.drawEllipse(QPointF(x, y), _MARKER_RADIUS + 4, _MARKER_RADIUS + 4)

            y_offset += _LANE_HEIGHT

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        new_zoom = max(0.3, min(20.0, self._zoom * factor))
        pos = event.position()
        self._offset_x = pos.x() - (pos.x() - self._offset_x) * (new_zoom / self._zoom)
        self._zoom = new_zoom
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_start = event.position()
            self._offset_start_x = self._offset_x
            self.setCursor(Qt.ClosedHandCursor)

    def _registro_en(self, pos) -> tuple[str, sqlite3.Row] | None:
        """Devuelve (abonado, registro) del marcador bajo el cursor, si hay."""
        if self._dt_min is None:
            return None
        y_offset = 50
        for nombre, _color, regs in self._lanes:
            if abs(pos.y() - y_offset) <= _MARKER_RADIUS + 2:
                for r in regs:
                    dt = _parse_dt(r["fecha_inicio_dt"])
                    if dt is None:
                        continue
                    if abs(pos.x() - self._dt_to_x(dt)) <= _MARKER_RADIUS + 2:
                        return nombre, r
            y_offset += _LANE_HEIGHT
        return None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._dragging:
            dx = event.position().x() - self._drag_start.x()
            self._offset_x = self._offset_start_x + dx
            self.update()
            return
        # Cada llamada es un círculo de 8px sin rótulo: sin esto no hay forma
        # de saber a qué registro corresponde.
        hallado = self._registro_en(event.position())
        self.setToolTip(_tooltip_marcador(*hallado) if hallado else "")

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self.setCursor(Qt.ArrowCursor)


class PantallaTimeline(QWidget):
    """Pantalla de línea de tiempo cronológica."""

    def __init__(self, con: sqlite3.Connection) -> None:
        super().__init__()
        self._con = con
        self._caso_id: int | None = None
        self._registros_raw: list[sqlite3.Row] = []
        self._construir()

    def set_caso(self, caso_id: int) -> None:
        self._caso_id = caso_id
        self.refrescar()

    def refrescar(self) -> None:
        if self._caso_id is None:
            return
        self._registros_raw = repo.listar_registros(self._con, self._caso_id)
        self._actualizar_interesados()
        self._aplicar()

    def _construir(self) -> None:
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(12, 10, 12, 10)
        raiz.setSpacing(8)

        cab = QHBoxLayout()
        titulo = QLabel("Línea de tiempo")
        titulo.setObjectName("titulo")
        cab.addWidget(titulo)
        cab.addStretch(1)

        btn_export = QPushButton("Exportar imagen")
        btn_export.setObjectName("primary")
        btn_export.clicked.connect(self._exportar)
        cab.addWidget(btn_export)
        raiz.addLayout(cab)

        filtros = QHBoxLayout()
        filtros.setSpacing(10)

        filtros.addWidget(QLabel("Interesado:"))
        self.cmb_interesado = QComboBox()
        self.cmb_interesado.setMinimumWidth(140)
        self.cmb_interesado.currentIndexChanged.connect(self._aplicar)
        filtros.addWidget(self.cmb_interesado)

        filtros.addWidget(QLabel("Comparar con:"))
        self.cmb_comparar = QComboBox()
        self.cmb_comparar.setMinimumWidth(140)
        self.cmb_comparar.currentIndexChanged.connect(self._aplicar)
        filtros.addWidget(self.cmb_comparar)

        filtros.addStretch(1)

        filtros.addWidget(QLabel("Evento:"))
        self.txt_evento = QLineEdit()
        self.txt_evento.setPlaceholderText("descripción")
        self.txt_evento.setMaximumWidth(150)
        filtros.addWidget(self.txt_evento)
        self.txt_evento_fecha = QLineEdit()
        self.txt_evento_fecha.setPlaceholderText("dd/mm/yyyy HH:MM")
        self.txt_evento_fecha.setMaximumWidth(130)
        filtros.addWidget(self.txt_evento_fecha)
        btn_add_ev = QPushButton("+ Evento")
        btn_add_ev.clicked.connect(self._agregar_evento)
        filtros.addWidget(btn_add_ev)

        raiz.addLayout(filtros)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.canvas = _TimelineCanvas()
        scroll.setWidget(self.canvas)
        raiz.addWidget(scroll, 1)

        self.lbl_status = QLabel("Sin datos")
        self.lbl_status.setObjectName("subtitulo")
        raiz.addWidget(self.lbl_status)

    def _actualizar_interesados(self) -> None:
        interesados = sorted(
            {r["interesado"] for r in self._registros_raw if r["interesado"]}
        )
        for cmb in (self.cmb_interesado, self.cmb_comparar):
            cmb.blockSignals(True)
            cmb.clear()
            cmb.addItem("Todos" if cmb is self.cmb_interesado else "— ninguno —")
            cmb.addItems(interesados)
            cmb.blockSignals(False)

    def _aplicar(self) -> None:
        filtro_int = self.cmb_interesado.currentText()
        filtro_cmp = self.cmb_comparar.currentText()

        validos = []
        for r in self._registros_raw:
            if r["estado"] == "transcripcion_faltante" and not r["fecha_inicio_dt"]:
                continue
            if not r["fecha_inicio_dt"]:
                continue
            if filtro_int != "Todos" and r["interesado"] != filtro_int:
                if filtro_cmp == "— ninguno —" or r["interesado"] != filtro_cmp:
                    continue
            validos.append(r)

        lanes_dict: dict[str, tuple[str, list]] = {}
        for r in validos:
            key = r["interesado"] or r["origen"] or "?"
            if key not in lanes_dict:
                lanes_dict[key] = (r["color_hex"] or "#888888", [])
            lanes_dict[key][1].append(r)

        lanes = [(nombre, color, regs) for nombre, (color, regs) in sorted(lanes_dict.items())]

        dts = [_parse_dt(r["fecha_inicio_dt"]) for r in validos]
        dts = [d for d in dts if d is not None]
        dt_min = min(dts) if dts else None
        dt_max = max(dts) if dts else None

        ev_list = eventos.listar_eventos(self._con, self._caso_id) if self._caso_id else []

        self.canvas.set_datos(lanes, ev_list, dt_min, dt_max)
        self.lbl_status.setText(
            f"{len(validos)} registros · {len(lanes)} interesados · {len(ev_list)} eventos"
        )

    def _agregar_evento(self) -> None:
        if self._caso_id is None:
            return
        desc = self.txt_evento.text().strip()
        fecha = self.txt_evento_fecha.text().strip()
        if not desc or not fecha:
            QMessageBox.information(
                self, "Evento", "Ingrese descripción y fecha del evento."
            )
            return
        eventos.crear_evento(self._con, self._caso_id, desc, fecha)
        self.txt_evento.clear()
        self.txt_evento_fecha.clear()
        self._aplicar()

    def _exportar(self) -> None:
        if self._caso_id is None:
            return
        caso = repo.obtener_caso(self._con, self._caso_id)
        nombre = caso["nombre"] if caso else "timeline"
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Exportar timeline", f"Timeline_{nombre}.png".replace(" ", "_"),
            "Imágenes (*.png)",
        )
        if not ruta:
            return
        self.canvas.exportar_pixmap().save(ruta, "PNG")
        repo.log_auditoria(self._con, "exporto", f"Timeline -> {ruta}", self._caso_id)
        self._con.commit()
        QMessageBox.information(self, "Exportar", f"Imagen guardada en:\n{ruta}")
