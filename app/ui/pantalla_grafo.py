"""Pantalla del grafo de vínculos entre abonados (pseudocódigo 6.6).

El dibujo y los controles. Qué entra en el grafo y con qué peso lo decide
`app.analisis.grafo`, que se puede probar contra una causa real sin abrir una
ventana: ahí está explicado por qué el grafo que había señalaba mal.

Los tres controles de arriba no son adornos. Con todo prendido, una causa de
238 comunicaciones dibuja 34 nodos donde el más grande es un código de
promociones; con los valores de fábrica quedan 28 nodos con el investigado en
el centro, y subiendo el peso mínimo a tres quedan los ocho que se leen de un
vistazo.
"""

from __future__ import annotations

import math
import sqlite3

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap, QWheelEvent
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
from app.analisis.grafo import Arista, Nodo, Opciones, construir, resumen
from app.ui import tema
from app.ui.dialogos import mostrar_exportacion

_MAX_ETIQUETA = 22


def _tooltip_nodo(nodo: Nodo) -> str:
    """Todo lo que la etiqueta dibujada no alcanza a decir."""
    partes = [nodo.etiqueta]
    if nodo.intervenido:
        partes.append("Línea intervenida de la causa")
    if len(nodo.numeros) > 1:
        partes.append(f"{len(nodo.numeros)} líneas: " + ", ".join(sorted(nodo.numeros)))
    elif nodo.numeros and nodo.etiqueta not in nodo.numeros:
        partes.append(next(iter(nodo.numeros)))

    if nodo.n_conexiones == 0:
        partes.append("sin vínculos")
    elif nodo.n_conexiones == 1:
        partes.append("1 comunicación")
    else:
        partes.append(f"{nodo.n_conexiones} comunicaciones")
    if nodo.n_internas:
        partes.append(f"{nodo.n_internas} entre sus propias líneas")
    if nodo.n_sin_contraparte:
        partes.append(
            f"{nodo.n_sin_contraparte} audios sin metadatos (no se sabe con quién)"
        )
    return "\n".join(partes)


def _layout_circular(nodos: dict[str, Nodo], cx: float, cy: float, radio: float) -> None:
    """Posiciona nodos en círculo, el más conectado en el medio."""
    if not nodos:
        return
    ordenados = sorted(nodos.values(), key=lambda n: n.n_conexiones, reverse=True)
    ordenados[0].x = cx
    ordenados[0].y = cy
    if len(ordenados) == 1:
        return
    n = len(ordenados) - 1
    for i, nodo in enumerate(ordenados[1:]):
        angulo = (2 * math.pi * i) / n
        nodo.x = cx + radio * math.cos(angulo)
        nodo.y = cy + radio * math.sin(angulo)


class _GrafoCanvas(QWidget):
    """Widget de dibujo del grafo con zoom y pan."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._nodos: dict[str, Nodo] = {}
        self._aristas: list[Arista] = []
        self._zoom = 1.0
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._dragging = False
        self._drag_start = QPointF()
        self._offset_start_x = 0.0
        self._offset_start_y = 0.0
        self._nodo_arrastrado: Nodo | None = None
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)

    def set_datos(self, nodos: dict[str, Nodo], aristas: list[Arista]) -> None:
        self._nodos = nodos
        self._aristas = aristas
        radio = min(self.width(), self.height()) * 0.35
        _layout_circular(self._nodos, self.width() / 2, self.height() / 2, radio)
        self._zoom = 1.0
        self._offset_x = 0.0
        self._offset_y = 0.0
        self.update()

    # ------------------------------ dibujo ------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(tema.BG_DEEP))
        self._dibujar(painter, self._zoom, self._offset_x, self._offset_y)

    def exportar_pixmap(self, escala: float = 2.0) -> QPixmap:
        """La imagen del grafo ENTERO, no la porción que se ve en pantalla.

        Antes se exportaba `self.size()` con el zoom y el desplazamiento que
        hubiera puestos: la imagen que iba al expediente salía a resolución de
        pantalla y recortada por donde estuviera corrido el dibujo.
        """
        if not self._nodos:
            pixmap = QPixmap(self.size())
            pixmap.fill(QColor(tema.BG_DEEP))
            return pixmap

        margen = 90.0
        xs = [n.x for n in self._nodos.values()]
        ys = [n.y for n in self._nodos.values()]
        ancho = (max(xs) - min(xs) + 2 * margen) * escala
        alto = (max(ys) - min(ys) + 2 * margen) * escala
        pixmap = QPixmap(max(1, int(ancho)), max(1, int(alto)))
        pixmap.fill(QColor(tema.BG_DEEP))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        self._dibujar(
            painter, escala,
            (margen - min(xs)) * escala, (margen - min(ys)) * escala,
        )
        painter.end()
        return pixmap

    def _transform(self, x: float, y: float, zoom=None, ox=None, oy=None) -> QPointF:
        zoom = self._zoom if zoom is None else zoom
        ox = self._offset_x if ox is None else ox
        oy = self._offset_y if oy is None else oy
        return QPointF(x * zoom + ox, y * zoom + oy)

    def _radio_de(self, nodo: Nodo, zoom: float) -> float:
        max_conex = max((n.n_conexiones for n in self._nodos.values()), default=1)
        proporcion = nodo.n_conexiones / max(1, max_conex)
        return max(12, min(40, int(15 + proporcion * 25))) * zoom

    def _dibujar(self, painter: QPainter, zoom: float, ox: float, oy: float) -> None:
        if not self._nodos:
            painter.setPen(QColor(tema.TEXT_DIM))
            painter.drawText(
                self.rect(), Qt.AlignCenter,
                "Sin vínculos para mostrar con estos filtros",
            )
            return

        max_peso = max((a.peso for a in self._aristas), default=1)
        for arista in self._aristas:
            o, d = self._nodos.get(arista.origen), self._nodos.get(arista.destino)
            if not o or not d:
                continue
            p1 = self._transform(o.x, o.y, zoom, ox, oy)
            p2 = self._transform(d.x, d.y, zoom, ox, oy)
            grosor = max(1, min(6, int(arista.peso / max(1, max_peso) * 6)))
            color = QColor(arista.color)
            color.setAlpha(140)
            painter.setPen(QPen(color, grosor))
            painter.drawLine(p1, p2)

            mid = QPointF((p1.x() + p2.x()) / 2, (p1.y() + p2.y()) / 2)
            font = painter.font()
            font.setPointSize(8)
            painter.setFont(font)
            painter.setPen(QColor(tema.TEXT_DIM))
            painter.drawText(int(mid.x()) + 4, int(mid.y()) - 4, str(arista.peso))

        max_conex = max((n.n_conexiones for n in self._nodos.values()), default=1)
        for nodo in self._nodos.values():
            p = self._transform(nodo.x, nodo.y, zoom, ox, oy)
            radio = self._radio_de(nodo, zoom)
            color = QColor(nodo.color)
            es_central = nodo.n_conexiones == max_conex and max_conex > 0

            # Las líneas intervenidas llevan anillo: son la columna vertebral
            # de la causa y tienen que distinguirse de un contacto cualquiera,
            # esté o no en el centro del dibujo.
            if es_central:
                painter.setPen(QPen(QColor(tema.ACCENT), 3))
            elif nodo.intervenido:
                painter.setPen(QPen(QColor(tema.ACCENT_DIM), 3))
            else:
                painter.setPen(QPen(color.darker(130), 2))
            color.setAlpha(180)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(p, radio, radio)

            if len(nodo.numeros) > 1:
                # Una persona con varias líneas: se avisa en el nodo, porque
                # agrupadas se ven como una sola y eso no puede ser invisible.
                font = painter.font()
                font.setPointSize(8)
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(QColor(tema.TEXT_PRIMARY))
                painter.drawText(
                    int(p.x() - radio), int(p.y() - 8), int(radio * 2), 16,
                    Qt.AlignCenter, f"{len(nodo.numeros)} líneas",
                )

            font = painter.font()
            font.setPointSize(9 if es_central or nodo.intervenido else 8)
            font.setBold(es_central or nodo.intervenido)
            painter.setFont(font)
            painter.setPen(QColor(tema.TEXT_PRIMARY))
            etiqueta = nodo.etiqueta
            if len(etiqueta) > _MAX_ETIQUETA:
                etiqueta = etiqueta[:_MAX_ETIQUETA - 1] + "…"
            painter.drawText(
                int(p.x() - 85), int(p.y() + radio + 14), 170, 16,
                Qt.AlignCenter, etiqueta,
            )

    # ----------------------------- interacción --------------------------
    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        new_zoom = max(0.3, min(10.0, self._zoom * factor))
        pos = event.position()
        self._offset_x = pos.x() - (pos.x() - self._offset_x) * (new_zoom / self._zoom)
        self._offset_y = pos.y() - (pos.y() - self._offset_y) * (new_zoom / self._zoom)
        self._zoom = new_zoom
        self.update()

    def _nodo_en(self, pos: QPointF) -> Nodo | None:
        """El nodo bajo el cursor (en coordenadas de pantalla), si hay."""
        for nodo in self._nodos.values():
            p = self._transform(nodo.x, nodo.y)
            dx, dy = pos.x() - p.x(), pos.y() - p.y()
            if (dx * dx + dy * dy) ** 0.5 <= self._radio_de(nodo, self._zoom):
                return nodo
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            nodo = self._nodo_en(event.position())
            if nodo is not None:
                # Arrastrar solo ese nodo para reorganizar el grafo a mano.
                self._nodo_arrastrado = nodo
                self.setCursor(Qt.ClosedHandCursor)
                return
            self._dragging = True
            self._drag_start = event.position()
            self._offset_start_x = self._offset_x
            self._offset_start_y = self._offset_y
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._nodo_arrastrado is not None:
            pos = event.position()
            self._nodo_arrastrado.x = (pos.x() - self._offset_x) / self._zoom
            self._nodo_arrastrado.y = (pos.y() - self._offset_y) / self._zoom
            self.update()
        elif self._dragging:
            d = event.position() - self._drag_start
            self._offset_x = self._offset_start_x + d.x()
            self._offset_y = self._offset_start_y + d.y()
            self.update()
        else:
            nodo = self._nodo_en(event.position())
            self.setCursor(Qt.OpenHandCursor if nodo else Qt.ArrowCursor)
            self.setToolTip(_tooltip_nodo(nodo) if nodo else "")

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self._nodo_arrastrado = None
            self.setCursor(Qt.ArrowCursor)


class PantallaGrafo(QWidget):
    """Pantalla de grafo de vínculos entre abonados."""

    def __init__(self, con: sqlite3.Connection) -> None:
        super().__init__()
        self._con = con
        self._caso_id: int | None = None
        self._nodos: dict[str, Nodo] = {}
        self._aristas: list[Arista] = []
        self._cargando = False
        self._construir()

    def set_caso(self, caso_id: int) -> None:
        self._caso_id = caso_id
        self.refrescar()

    def opciones(self) -> Opciones:
        return Opciones(
            agrupar_por_persona=self.chk_agrupar.isChecked(),
            ocultar_servicios=self.chk_servicios.isChecked(),
            peso_minimo=int(self.cmb_peso.currentData() or 1),
        )

    def refrescar(self) -> None:
        if self._caso_id is None:
            return
        registros = repo.listar_registros(self._con, self._caso_id)
        abonados = repo.listar_abonados(self._con, self._caso_id)
        self._nodos, self._aristas = construir(
            registros,
            nombres=repo.nombres_conocidos(self._con, self._caso_id),
            colores={a["numero_normalizado"]: a["color_hex"] for a in abonados},
            intervenidos={
                a["numero_normalizado"] for a in abonados if a["intervenido"]
            },
            color_externo=tema.TEXT_DIM,
            opciones=self.opciones(),
        )
        self.canvas.set_datos(self._nodos, self._aristas)
        self._actualizar_leyenda()
        self.lbl_status.setText(resumen(self._nodos, self._aristas))

    # ------------------------- construcción UI --------------------------
    def _construir(self) -> None:
        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        main = QWidget()
        mlay = QVBoxLayout(main)
        mlay.setContentsMargins(12, 10, 12, 10)
        mlay.setSpacing(8)

        cab = QHBoxLayout()
        titulo = QLabel("Grafo de vínculos")
        titulo.setObjectName("titulo")
        cab.addWidget(titulo)
        cab.addStretch(1)

        btn_reset = QPushButton("Resetear vista")
        btn_reset.clicked.connect(self.refrescar)
        cab.addWidget(btn_reset)

        btn_export = QPushButton("Exportar imagen")
        btn_export.setObjectName("primary")
        btn_export.clicked.connect(self._exportar_imagen)
        cab.addWidget(btn_export)
        mlay.addLayout(cab)

        filtros = QHBoxLayout()
        filtros.setSpacing(12)

        self.chk_servicios = QCheckBox("Ocultar códigos de servicio")
        self.chk_servicios.setChecked(True)
        self.chk_servicios.setToolTip(
            "Los 1520, 55110, 2C7140 de las prestadoras, bancos y promociones. "
            "Mandan decenas de mensajes, así que sin filtrarlos se llevan el "
            "centro del grafo y tapan los vínculos que importan."
        )
        self.chk_servicios.toggled.connect(self._al_cambiar_filtro)
        filtros.addWidget(self.chk_servicios)

        self.chk_agrupar = QCheckBox("Agrupar las líneas de la misma persona")
        self.chk_agrupar.setChecked(True)
        self.chk_agrupar.setToolTip(
            "Quien tiene varias líneas en la causa se dibuja como un solo nodo. "
            "Destildalo para ver línea por línea."
        )
        self.chk_agrupar.toggled.connect(self._al_cambiar_filtro)
        filtros.addWidget(self.chk_agrupar)

        filtros.addWidget(QLabel("Vínculos con al menos:"))
        self.cmb_peso = QComboBox()
        for etiqueta, valor in (
            ("1 comunicación", 1), ("2", 2), ("3", 3), ("5", 5), ("10", 10),
        ):
            self.cmb_peso.addItem(etiqueta, valor)
        self.cmb_peso.setToolTip(
            "Deja fuera los contactos de una sola vez, que son la mayoría y no "
            "dejan ver la estructura de la causa."
        )
        self.cmb_peso.currentIndexChanged.connect(self._al_cambiar_filtro)
        filtros.addWidget(self.cmb_peso)
        filtros.addStretch(1)
        mlay.addLayout(filtros)

        self.canvas = _GrafoCanvas()
        mlay.addWidget(self.canvas, 1)

        self.lbl_leyenda = QLabel(
            "El tamaño del nodo es la cantidad de comunicaciones  ·  el anillo "
            "marca las líneas intervenidas  ·  el número sobre cada línea es "
            "cuántas veces hablaron  ·  se puede arrastrar cada nodo"
        )
        self.lbl_leyenda.setObjectName("subtitulo")
        self.lbl_leyenda.setWordWrap(True)
        mlay.addWidget(self.lbl_leyenda)

        self.lbl_status = QLabel("Sin datos")
        self.lbl_status.setObjectName("subtitulo")
        mlay.addWidget(self.lbl_status)

        raiz.addWidget(main, 1)

        panel = QFrame()
        panel.setObjectName("panel")
        panel.setFixedWidth(230)
        play = QVBoxLayout(panel)
        play.setContentsMargins(14, 14, 14, 14)
        play.setSpacing(6)

        lbl = QLabel("ABONADOS")
        lbl.setObjectName("seccion")
        play.addWidget(lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._leyenda_w = QWidget()
        self._leyenda_lay = QVBoxLayout(self._leyenda_w)
        self._leyenda_lay.setContentsMargins(0, 0, 0, 0)
        self._leyenda_lay.setSpacing(4)
        self._leyenda_lay.addStretch(1)
        scroll.setWidget(self._leyenda_w)
        play.addWidget(scroll, 1)

        raiz.addWidget(panel)

    def _al_cambiar_filtro(self) -> None:
        if not self._cargando:
            self.refrescar()

    def _actualizar_leyenda(self) -> None:
        while self._leyenda_lay.count():
            item = self._leyenda_lay.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        ordenados = sorted(
            self._nodos.values(), key=lambda n: n.n_conexiones, reverse=True
        )
        for nodo in ordenados:
            fila = QWidget()
            fl = QHBoxLayout(fila)
            fl.setContentsMargins(0, 2, 0, 2)
            fl.setSpacing(6)
            dot = QLabel()
            dot.setFixedSize(12, 12)
            borde = tema.ACCENT if nodo.intervenido else tema.LINE
            dot.setStyleSheet(
                f"background: {nodo.color}; border-radius: 6px; "
                f"border: {'2px' if nodo.intervenido else '1px'} solid {borde};"
            )
            fl.addWidget(dot)
            sufijo = f" · {len(nodo.numeros)} líneas" if len(nodo.numeros) > 1 else ""
            lbl = QLabel(f"{nodo.etiqueta} ({nodo.n_conexiones}){sufijo}")
            lbl.setStyleSheet(
                f"color: {tema.TEXT_PRIMARY}; font-size: 11px;"
                + (" font-weight: 600;" if nodo.intervenido else "")
            )
            lbl.setWordWrap(True)
            lbl.setToolTip(_tooltip_nodo(nodo))
            fl.addWidget(lbl, 1)
            self._leyenda_lay.addWidget(fila)

        self._leyenda_lay.addStretch(1)

    def _exportar_imagen(self) -> None:
        if self._caso_id is None:
            return
        caso = repo.obtener_caso(self._con, self._caso_id)
        nombre = caso["nombre"] if caso else "grafo"
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Exportar grafo", f"Grafo_{nombre}.png".replace(" ", "_"),
            "Imágenes (*.png)",
        )
        if not ruta:
            return
        self.canvas.exportar_pixmap().save(ruta, "PNG")
        # Queda como lote, igual que el informe y el Excel: la imagen que se
        # eleva es una pieza del expediente y tiene que figurar en el registro
        # de lo exportado.
        repo.crear_lote_exportacion(self._con, self._caso_id, "imagen_grafo")
        repo.log_auditoria(
            self._con, "exporto",
            f"Grafo ({resumen(self._nodos, self._aristas)}) -> {ruta}",
            self._caso_id,
        )
        self._con.commit()
        mostrar_exportacion(self, ruta, "Exportar grafo")
