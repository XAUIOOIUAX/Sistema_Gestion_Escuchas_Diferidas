"""Vista de onda con la transcripción debajo, al modo de Audacity.

Audacity muestra dos cosas apiladas: la forma de onda arriba y una pista de
etiquetas abajo, cada etiqueta cubriendo el tramo de audio al que corresponde.
Esa es exactamente la estructura de una transcripción con tiempos, y es la
única vista donde se pueden ver juntas tres cosas que por separado no se notan:

  · dónde empieza y termina de verdad cada frase, contra dónde la puso Whisper;
  · dónde hay voz sin ninguna frase encima —lo que el motor se comió, que
    leyendo el texto no se puede descubrir porque no deja hueco—;
  · dónde hay silencio partido en dos frases que deberían ser una.

Lo que NO hace, y es deliberado: no toca el archivo de audio. Ni amplificar, ni
reducir ruido, ni recortar. Ese material es prueba, y procesarlo es una pericia
con su propia constancia, no algo que un reproductor haga en silencio mientras
alguien transcribe. Acá se mira y se escucha; el original queda como vino en
el CD.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.analisis.cobertura import huecos_con_audio, resumen_huecos
from app.servicios.transcripcion import esta_anclado
from app.ui import tema

_ALTO_ONDA = 96
_ALTO_ETIQUETAS = 54
_ZOOM_MIN = 1.0
_ZOOM_MAX = 60.0


def _mmss(segundos: float) -> str:
    segundos = max(0, int(segundos))
    return f"{segundos // 60}:{segundos % 60:02d}"


class _Lienzo(QWidget):
    """Onda arriba, frases abajo, todo sobre el mismo eje de tiempo."""

    buscado = Signal(float)            # segundo donde se hizo clic
    frase_elegida = Signal(int)        # índice de la frase clickeada
    seleccion_hecha = Signal(float, float)
    hueco_elegido = Signal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._picos: list[float] = []
        self._segmentos: list[dict] = []
        self._huecos: list[tuple[float, float]] = []
        self._duracion = 0.0
        self._posicion = 0.0
        self._ancla: float | None = None
        self._zoom = 1.0
        self._desde = 0.0                  # segundo del borde izquierdo
        self._seleccion: tuple[float, float] | None = None
        self._arrastrando: float | None = None
        self.setMinimumHeight(_ALTO_ONDA + _ALTO_ETIQUETAS)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(Qt.IBeamCursor)

    # ------------------------------ datos -------------------------------
    def set_audio(self, picos: list[float], duracion: float) -> None:
        self._picos = list(picos or [])
        self._duracion = max(0.0, float(duracion))
        self._desde = 0.0
        self._seleccion = None
        self._recalcular_huecos()
        self.update()

    def set_segmentos(self, segmentos: list[dict]) -> None:
        self._segmentos = [dict(s) for s in segmentos]
        self._recalcular_huecos()
        self.update()

    def _recalcular_huecos(self) -> None:
        self._huecos = huecos_con_audio(
            self._picos, self._duracion, self._segmentos
        )

    def huecos(self) -> list[tuple[float, float]]:
        return list(self._huecos)

    def set_posicion(self, segundo: float) -> None:
        self._posicion = float(segundo)
        # Seguir el cursor cuando se sale de la ventana visible; con zoom 1 la
        # ventana es el audio entero y esto no hace nada.
        ventana = self._ventana()
        if ventana and not (self._desde <= self._posicion <= self._desde + ventana):
            self._desde = max(0.0, self._posicion - ventana / 3)
        self.update()

    def set_ancla(self, segundo: float | None) -> None:
        self._ancla = segundo
        self.update()

    def ancla(self) -> float | None:
        return self._ancla

    def seleccion(self) -> tuple[float, float] | None:
        return self._seleccion

    def set_seleccion(self, tramo: tuple[float, float] | None) -> None:
        self._seleccion = tramo
        self.update()

    # ------------------------------ zoom --------------------------------
    def _ventana(self) -> float:
        return self._duracion / self._zoom if self._duracion else 0.0

    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, valor: float, centro: float | None = None) -> None:
        nuevo = max(_ZOOM_MIN, min(_ZOOM_MAX, float(valor)))
        if centro is None:
            centro = self._posicion or (self._desde + self._ventana() / 2)
        self._zoom = nuevo
        ventana = self._ventana()
        self._desde = max(0.0, min(centro - ventana / 2, self._duracion - ventana))
        self.update()

    def set_desde(self, segundo: float) -> None:
        self._desde = max(0.0, min(float(segundo), self._duracion - self._ventana()))
        self.update()

    def desde(self) -> float:
        return self._desde

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.ControlModifier or self._zoom > 1.0:
            factor = 1.25 if event.angleDelta().y() > 0 else 1 / 1.25
            self.set_zoom(self._zoom * factor, self._segundo_en(event.position().x()))
            event.accept()
            return
        super().wheelEvent(event)

    # ---------------------------- geometría ------------------------------
    def _segundo_en(self, x: float) -> float:
        ventana = self._ventana()
        if not ventana or self.width() <= 0:
            return 0.0
        return self._desde + (x / self.width()) * ventana

    def _x_de(self, segundo: float) -> float:
        ventana = self._ventana()
        if not ventana:
            return 0.0
        return (segundo - self._desde) / ventana * self.width()

    # ------------------------------ mouse --------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        x, y = event.position().x(), event.position().y()
        if y > _ALTO_ONDA:
            indice = self._frase_en(self._segundo_en(x))
            if indice >= 0:
                self.frase_elegida.emit(indice)
                return
            for a, b in self._huecos:
                if a <= self._segundo_en(x) <= b:
                    self.hueco_elegido.emit(a, b)
                    return
        self._arrastrando = self._segundo_en(x)
        self._seleccion = None
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._arrastrando is None:
            self.setToolTip(self._tooltip_en(event.position()))
            return
        actual = self._segundo_en(event.position().x())
        self._seleccion = (min(self._arrastrando, actual), max(self._arrastrando, actual))
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._arrastrando is None:
            return
        soltado = self._segundo_en(event.position().x())
        # Un clic sin arrastrar es pedir que suene desde ahí, no seleccionar.
        if abs(soltado - self._arrastrando) < 0.15:
            self._seleccion = None
            self.seleccion_hecha.emit(0.0, 0.0)   # sin selección
            self.buscado.emit(max(0.0, soltado))
        else:
            self._seleccion = (
                max(0.0, min(self._arrastrando, soltado)),
                max(self._arrastrando, soltado),
            )
            self.seleccion_hecha.emit(*self._seleccion)
        self._arrastrando = None
        self.update()

    def _frase_en(self, segundo: float) -> int:
        for i, s in enumerate(self._segmentos):
            inicio = float(s.get("inicio") or 0.0)
            fin = float(s.get("fin") or inicio)
            if inicio <= segundo <= max(fin, inicio + 0.2):
                return i
        return -1

    def _tooltip_en(self, pos) -> str:
        segundo = self._segundo_en(pos.x())
        if pos.y() > _ALTO_ONDA:
            indice = self._frase_en(segundo)
            if indice >= 0:
                s = self._segmentos[indice]
                minuto = _mmss(s.get("inicio") or 0)
                if not esta_anclado(s):
                    minuto = f"~{minuto} (provisorio)"
                return f"{minuto}  {s.get('texto') or ''}"
            for a, b in self._huecos:
                if a <= segundo <= b:
                    return (
                        f"{_mmss(a)} – {_mmss(b)}: acá suena algo y no hay "
                        "ninguna frase.\nClic para agregar una."
                    )
        return _mmss(segundo)

    # ------------------------------ dibujo -------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.fillRect(self.rect(), QColor(tema.BG_DEEP))
        if not self._picos or self._duracion <= 0:
            p.setPen(QColor(tema.TEXT_DIM))
            p.drawText(self.rect(), Qt.AlignCenter, "Sin audio para mostrar")
            return

        ancho, ventana = self.width(), self._ventana()
        medio = _ALTO_ONDA / 2

        # Selección, por detrás de todo.
        if self._seleccion:
            x1, x2 = self._x_de(self._seleccion[0]), self._x_de(self._seleccion[1])
            p.fillRect(QRectF(x1, 0, max(1.0, x2 - x1), self.height()),
                       QColor(*tema.FILA_SELECCION))

        # Onda. Una columna de píxel por píxel, tomando el pico más alto del
        # tramo que le toca: con zoom eso es un pico real y no un promedio que
        # aplana justo lo que se está buscando.
        p.setPen(QPen(QColor(tema.ACCENT_DIM), 1))
        por_pixel = max(1, int(len(self._picos) / max(1, ancho) / max(1, self._zoom)))
        for x in range(ancho):
            segundo = self._desde + (x / ancho) * ventana
            i = int(segundo / self._duracion * len(self._picos))
            if not (0 <= i < len(self._picos)):
                continue
            pico = max(self._picos[i:i + por_pixel] or [self._picos[i]])
            alto = pico * (medio - 4)
            p.drawLine(x, int(medio - alto), x, int(medio + alto))

        p.setPen(QPen(QColor(tema.LINE), 1))
        p.drawLine(0, int(medio), ancho, int(medio))
        p.drawLine(0, _ALTO_ONDA, ancho, _ALTO_ONDA)

        self._dibujar_frases(p)
        self._dibujar_huecos(p)

        # La marca: de acá vuelve a sonar con Espacio. Se dibuja punteada y
        # en otro color para que no se confunda con el cursor que avanza —son
        # dos cosas distintas y justamente la gracia es ver cuánto se alejaron—.
        if self._ancla is not None:
            xa = self._x_de(self._ancla)
            if 0 <= xa <= ancho and abs(xa - self._x_de(self._posicion)) > 1.5:
                p.setPen(QPen(QColor(tema.TEAL), 2, Qt.DashLine))
                p.drawLine(int(xa), 0, int(xa), self.height())

        # Cursor de reproducción, arriba de todo.
        x = self._x_de(self._posicion)
        if 0 <= x <= ancho:
            p.setPen(QPen(QColor(tema.ACCENT), 2))
            p.drawLine(int(x), 0, int(x), self.height())

    def _dibujar_frases(self, p: QPainter) -> None:
        fuente = p.font()
        fuente.setPointSize(8)
        p.setFont(fuente)
        for i, s in enumerate(self._segmentos):
            inicio = float(s.get("inicio") or 0.0)
            fin = max(float(s.get("fin") or inicio), inicio + 0.15)
            x1, x2 = self._x_de(inicio), self._x_de(fin)
            if x2 < 0 or x1 > self.width():
                continue
            rect = QRectF(x1, _ALTO_ONDA + 4, max(2.0, x2 - x1), _ALTO_ETIQUETAS - 10)
            color = QColor(tema.ACCENT if s.get("hablante") == "1" else tema.TEAL)
            if not s.get("hablante"):
                color = QColor(tema.TEXT_DIM)
            # Lo confirmado escuchando se pinta lleno; lo que todavía es la
            # conjetura de Whisper, apenas insinuado y con el borde punteado.
            # El dibujo no puede dar la misma firmeza a las dos cosas.
            anclado = esta_anclado(s)
            color.setAlpha((60 if i % 2 else 90) if anclado else 25)
            p.fillRect(rect, QBrush(color))
            p.setPen(QPen(
                QColor(tema.LINE), 1, Qt.SolidLine if anclado else Qt.DotLine
            ))
            p.drawRect(rect)
            if rect.width() > 26:
                p.setPen(QColor(tema.TEXT_PRIMARY))
                p.drawText(
                    rect.adjusted(3, 0, -3, 0),
                    Qt.AlignVCenter | Qt.AlignLeft,
                    str(s.get("texto") or ""),
                )

    def _dibujar_huecos(self, p: QPainter) -> None:
        """Lo que suena y nadie transcribió. Es lo que hay que ir a escuchar."""
        for a, b in self._huecos:
            x1, x2 = self._x_de(a), self._x_de(b)
            if x2 < 0 or x1 > self.width():
                continue
            rect = QRectF(x1, _ALTO_ONDA + 4, max(2.0, x2 - x1), _ALTO_ETIQUETAS - 10)
            color = QColor(tema.DANGER)
            color.setAlpha(55)
            p.fillRect(rect, QBrush(color))
            p.setPen(QPen(QColor(tema.DANGER), 1, Qt.DashLine))
            p.drawRect(rect)


class EditorDeOnda(QWidget):
    """La vista de onda con sus controles: zoom, selección y repetición."""

    buscado = Signal(float)
    frase_elegida = Signal(int)
    agregar_frase_en = Signal(float, float)
    tramo_cambiado = Signal(object, bool)   # (desde, hasta)|None, repetir

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bucle: tuple[float, float] | None = None
        self._construir()

    def _construir(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self.lienzo = _Lienzo()
        self.lienzo.buscado.connect(self.buscado)
        self.lienzo.frase_elegida.connect(self.frase_elegida)
        self.lienzo.seleccion_hecha.connect(self._al_seleccionar)
        self.lienzo.hueco_elegido.connect(self._al_elegir_hueco)
        lay.addWidget(self.lienzo)

        self.barra_scroll = QScrollBar(Qt.Horizontal)
        self.barra_scroll.setVisible(False)
        self.barra_scroll.valueChanged.connect(
            lambda v: self.lienzo.set_desde(v / 100.0)
        )
        lay.addWidget(self.barra_scroll)

        fila = QHBoxLayout()
        fila.setSpacing(8)

        self.btn_menos = QPushButton("－")
        self.btn_menos.setFixedWidth(32)
        self.btn_menos.setToolTip("Alejar")
        self.btn_menos.clicked.connect(lambda: self._zoom_relativo(1 / 1.6))
        self.btn_mas = QPushButton("＋")
        self.btn_mas.setFixedWidth(32)
        self.btn_mas.setToolTip("Acercar  ·  también con la rueda del mouse")
        self.btn_mas.clicked.connect(lambda: self._zoom_relativo(1.6))
        self.btn_todo = QPushButton("Ver todo")
        self.btn_todo.clicked.connect(lambda: self._aplicar_zoom(1.0))
        for b in (self.btn_menos, self.btn_mas, self.btn_todo):
            fila.addWidget(b)

        self.btn_bucle = QPushButton("🔁 Repetir el tramo  (F9)")
        self.btn_bucle.setCheckable(True)
        self.btn_bucle.setToolTip(
            "Repite sin parar el tramo seleccionado, o la frase que estás "
            "escribiendo si no seleccionaste nada. Es la forma de sacar un "
            "pasaje que no se entiende: escucharlo diez veces sin tocar nada."
        )
        self.btn_bucle.toggled.connect(self._alternar_bucle)
        fila.addWidget(self.btn_bucle)

        self.lbl_seleccion = QLabel("")
        self.lbl_seleccion.setObjectName("subtitulo")
        fila.addWidget(self.lbl_seleccion)
        fila.addStretch(1)

        self.lbl_huecos = QLabel("")
        self.lbl_huecos.setWordWrap(True)
        fila.addWidget(self.lbl_huecos)
        lay.addLayout(fila)

    # ------------------------------- datos -------------------------------
    def set_audio(self, picos: list[float], duracion: float) -> None:
        self.lienzo.set_audio(picos, duracion)
        self._bucle = None
        self.btn_bucle.blockSignals(True)
        self.btn_bucle.setChecked(False)
        self.btn_bucle.blockSignals(False)
        self.lbl_seleccion.setText("")
        self._actualizar_scroll()
        self._actualizar_huecos()

    def set_segmentos(self, segmentos: list[dict]) -> None:
        self.lienzo.set_segmentos(segmentos)
        self._actualizar_huecos()

    def set_posicion(self, segundo: float) -> None:
        self.lienzo.set_posicion(segundo)
        self._actualizar_scroll(mover=False)

    def set_ancla(self, segundo: float | None) -> None:
        self.lienzo.set_ancla(segundo)

    def _actualizar_huecos(self) -> None:
        huecos = self.lienzo.huecos()
        self.lbl_huecos.setText(resumen_huecos(huecos))
        self.lbl_huecos.setStyleSheet(
            f"color:{tema.DANGER if huecos else tema.TEXT_DIM}; font-size:11px;"
        )

    # -------------------------------- zoom -------------------------------
    def _zoom_relativo(self, factor: float) -> None:
        self._aplicar_zoom(self.lienzo.zoom() * factor)

    def _aplicar_zoom(self, valor: float) -> None:
        self.lienzo.set_zoom(valor)
        self._actualizar_scroll()

    def _actualizar_scroll(self, mover: bool = True) -> None:
        ventana = self.lienzo._ventana()
        total = self.lienzo._duracion
        hay_que_mover = total > 0 and ventana < total - 0.01
        self.barra_scroll.setVisible(hay_que_mover)
        if not hay_que_mover:
            return
        self.barra_scroll.blockSignals(True)
        self.barra_scroll.setRange(0, int((total - ventana) * 100))
        self.barra_scroll.setPageStep(int(ventana * 100))
        if mover:
            self.barra_scroll.setValue(int(self.lienzo.desde() * 100))
        self.barra_scroll.blockSignals(False)

    # ------------------------------- bucle -------------------------------
    def _al_seleccionar(self, desde: float, hasta: float) -> None:
        """Seleccionar acota la reproducción, aunque no se pida repetir.

        Es lo que hace cualquier selector de audio: se marca un pedazo y play
        suena ese pedazo. Repetir es lo de más, no lo que habilita el límite.
        """
        if hasta - desde < 0.15:
            self.lienzo.set_seleccion(None)
            self._bucle = None
            self.btn_bucle.setChecked(False)
            self.lbl_seleccion.setText("")
            self.tramo_cambiado.emit(None, False)
            return
        self.lbl_seleccion.setText(
            f"Selección {_mmss(desde)}–{_mmss(hasta)} ({hasta - desde:.1f} s)"
            + ("  ·  repitiendo" if self.btn_bucle.isChecked() else "")
        )
        self._bucle = (desde, hasta) if self.btn_bucle.isChecked() else None
        self.tramo_cambiado.emit((desde, hasta), self.btn_bucle.isChecked())

    def mover_borde(self, segundos: float, desde_el_cursor: float) -> None:
        """Estira o achica la selección con el teclado (Shift + flechas).

        Si todavía no hay selección se abre una desde donde está sonando: es el
        punto que el analista tiene en la cabeza cuando decide marcar un tramo.
        """
        actual = self.lienzo.seleccion()
        if actual is None:
            inicio = max(0.0, desde_el_cursor)
            nuevo = (inicio, inicio + abs(segundos)) if segundos > 0 else (
                max(0.0, inicio - abs(segundos)), inicio
            )
        elif segundos > 0:
            nuevo = (actual[0], actual[1] + segundos)
        else:
            # Hacia la izquierda se achica por el final mientras haya de dónde;
            # cuando ya no queda, se corre el principio.
            if actual[1] + segundos > actual[0] + 0.15:
                nuevo = (actual[0], actual[1] + segundos)
            else:
                nuevo = (max(0.0, actual[0] + segundos), actual[1])
        tope = self.lienzo._duracion or nuevo[1]
        nuevo = (max(0.0, nuevo[0]), min(nuevo[1], tope))
        self.lienzo.set_seleccion(nuevo)
        self._al_seleccionar(*nuevo)

    def limpiar_seleccion(self) -> None:
        self.lienzo.set_seleccion(None)
        self._al_seleccionar(0.0, 0.0)

    def _al_elegir_hueco(self, desde: float, hasta: float) -> None:
        self.agregar_frase_en.emit(desde, hasta)

    def set_tramo_por_defecto(self, tramo: tuple[float, float] | None) -> None:
        """El tramo que se repite cuando no hay nada seleccionado a mano."""
        self._tramo_por_defecto = tramo

    def _alternar_bucle(self, activo: bool) -> None:
        if not activo:
            self._bucle = None
            # La selección queda: se deja de repetir, no se deja de acotar.
            seleccion = self.lienzo.seleccion()
            self.tramo_cambiado.emit(seleccion, False)
            if seleccion:
                self.lbl_seleccion.setText(
                    f"Selección {_mmss(seleccion[0])}–{_mmss(seleccion[1])} "
                    f"({seleccion[1] - seleccion[0]:.1f} s)"
                )
            return
        tramo = self.lienzo.seleccion() or getattr(self, "_tramo_por_defecto", None)
        if not tramo or tramo[1] - tramo[0] < 0.2:
            self.btn_bucle.setChecked(False)
            self.lbl_seleccion.setText(
                "Seleccioná un tramo en la onda, o poné el cursor en una frase"
            )
            return
        self._bucle = tramo
        self.lienzo.set_seleccion(tramo)
        self.lbl_seleccion.setText(
            f"Repitiendo {_mmss(tramo[0])}–{_mmss(tramo[1])}"
        )
        self.tramo_cambiado.emit(tramo, True)

    def bucle(self) -> tuple[float, float] | None:
        return self._bucle
