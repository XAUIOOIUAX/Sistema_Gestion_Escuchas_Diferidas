"""Pantalla principal: Tabla TOTAL del caso activo + panel de detalle lateral.

Implementa la grilla de la sección 6.3 del pseudocódigo (columnas visibles, color
de fila por abonado, badge de estado, filtros y búsqueda libre), el panel de
detalle 6.3.1 (reproducción, contexto/transcripción editable, corresponde_a,
ubicación) y la exportación a Excel / Word.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPen, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.flow_layout import FlowLayout

from app import repositorios as repo
from app import sesion
from app.core.colores import NIVELES_INTERES
from app.core.fechas import parsear_fecha_hora_ar
from app.exportadores.excel_exportador import exportar_caso_a_excel
from app.exportadores.errores import InformeVacio
from app.exportadores.word_judicial import exportar_informe_judicial
from app.servicios import audios, edicion, memoria
from app.servicios import papelera
from app.servicios import transcripcion as svc_transcripcion
from app.ui import atajos as atajos_teclado
from app.ui import tema
from app.ui.dialogos import DialogoInformeJudicial, mostrar_exportacion
from app.ui.reproductor import ReproductorAudio, _formato_mmss
from app.ui.transcribir import DialogoTranscribirLote, ProcesoTranscripcion
from app.core.interlocutor import SIN_INTERLOCUTOR, numero_del_interlocutor
from app.ui.transcripcion_sincronizada import TranscripcionSincronizada

# Columnas de la grilla (pseudocódigo 6.3). Corresponde_a y la geolocalización
# viven en el panel de detalle.
_COL_ORDEN = 0
_COL_INTERESADO = 1
_COLUMNAS = [
    "Orden",
    "Interesado",
    "Interlocutor",
    "CD",
    "Dirección",
    "Origen",
    "Destino",
    "Fecha inicio",
    "Fecha fin",
    "Antenas",
    "Contexto",
    "Interés",
    "Archivo audio",
    "Dur.",
    "Oído",
    "Rev.",
    "Inf.",
    "Estado",
]
# Cada columna con su nombre: los índices sueltos se corrían solos cada vez que
# se agregaba una columna en el medio, y el que se olvidaba no fallaba, pintaba
# la celda equivocada.
_COL_INTERLOCUTOR = 2
_COL_CD = 3
_COL_DIRECCION = 4
_COL_ORIGEN = 5
_COL_DESTINO = 6
_COL_FECHA_INICIO = 7
_COL_FECHA_FIN = 8
_COL_ANTENAS = 9
_COL_CONTEXTO = 10
_COL_INTERES = 11
_COL_ARCHIVO = 12
_COL_DURACION = 13
_COL_ESCUCHADO = 14
_COL_REVISADA = 15
_COL_INFORMADA = 16
_COL_ESTADO = len(_COLUMNAS) - 1

_BADGE_ESTADO = {
    "completo": "",
    "audio_faltante": "⚠ Audio faltante",
    "transcripcion_faltante": "⚠ Transcripción faltante",
}

_ETIQUETA_INTERES = {
    "ninguno": "—",
    "interes": "★  De interés",
    # Valores de una base anterior a la unificación, por si alguno sobrevive.
    "bajo": "★  De interés",
    "medio": "★  De interés",
    "alto": "★  De interés",
}

_FILTRO_ESTADO = {
    # La primera opción se auto-rotula, igual que el resto de los filtros: el
    # combo tiene que decir de qué es aunque no haya nada seleccionado.
    "Estado: todos": None,
    "Completo": "completo",
    "Audio faltante": "audio_faltante",
    "Transcripción faltante": "transcripcion_faltante",
}


_ANCHO_MIN_FILTRO = 118

# Interesado se dimensiona a su contenido entre estos límites. El padding sale
# del QSS (6px 10px por celda) más un margen para el borde.
_PAD_CELDA = 24
_ANCHO_MIN_INTERESADO = 150
_ANCHO_MAX_INTERESADO = 320


def _ajustar_ancho_combo(cmb: QComboBox) -> None:
    """Dimensiona el combo para que su etiqueta («Interesado: todos») entre.

    Con un ancho fijo para todos, las etiquetas más largas quedaban cortadas
    ("Interesado: tc") y el filtro dejaba de decir de qué era. La barra usa un
    FlowLayout, así que ensancharlos solo hace que bajen de renglón.
    """
    # El ancho sale siempre de la etiqueta (ítem 0), nunca de los valores: así
    # un "pertenece a" largo no estira el combo. Los valores se leen completos
    # en el desplegable, que se dimensiona aparte y sí va topeado.
    texto = cmb.itemText(0) if cmb.count() else ""
    # Margen para la flecha del desplegable y el padding del QSS.
    ancho = cmb.fontMetrics().horizontalAdvance(texto) + 46
    cmb.setFixedWidth(max(_ANCHO_MIN_FILTRO, ancho))
    if cmb.count():
        largo = max(
            cmb.fontMetrics().horizontalAdvance(cmb.itemText(i))
            for i in range(cmb.count())
        )
        cmb.view().setMinimumWidth(min(largo + 32, 420))


def _tooltip_linea(r: sqlite3.Row) -> str:
    """Explica a qué abonado corresponde el color de la fila."""
    linea = r["linea_color"]
    if not linea:
        return (
            "Sin color: ninguno de los dos números figura entre los abonados "
            "del caso."
        )
    if r["linea_intervenida"]:
        return f"El color identifica la línea intervenida: {linea}"
    # Ningún abonado de la comunicación está marcado como intervenido: el color
    # salió del desempate, y presentarlo como línea pinchada sería falso.
    return (
        f"El color corresponde al abonado {linea}, que no está marcado como "
        "intervenido. Marcalo en Índice para que la fila refleje la línea "
        "pinchada."
    )


def _texto_contraste(color: QColor) -> str:
    """Devuelve negro o blanco según la luminancia del color de fondo, para que
    el texto del chip de color sea legible."""
    lum = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return "#1A1306" if lum > 150 else "#FFFFFF"


# Rol donde viaja la clave de orden de cada celda. El texto que se muestra no
# sirve para ordenar: "04/09/2026" es anterior a "1/12/2025" alfabéticamente, y
# el CD "10" iría antes que el "2".
_ROL_ORDEN = Qt.UserRole + 3

# Rol donde viaja "esta comunicación ya salió en un informe". Va en la celda de
# Orden porque la marca se pinta al filo izquierdo de la fila.
_ROL_INFORMADA = Qt.UserRole + 4


def _clave_orden(r, col: int, texto: str):
    """Con qué valor se ordena cada columna.

    Las fechas van por su forma ISO (`fecha_inicio_dt`), no por el texto en
    formato argentino: "04/09/2026" es anterior a "1/12/2025" si se comparan
    como cadenas. Los números —Orden, CD, duración— van como números, para que
    el CD 10 no quede entre el 1 y el 2. El resto, texto en minúsculas.
    """
    if col == _COL_ORDEN:
        return r["orden"] or 0
    if col in (_COL_FECHA_INICIO, _COL_FECHA_FIN):
        # Se prefiere el datetime derivado, y si falta se parsea el texto: un
        # registro sin `fecha_inicio_dt` no puede arruinar el orden de la
        # columna que más se usa para ordenar.
        if col == _COL_FECHA_INICIO and r["fecha_inicio_dt"]:
            return str(r["fecha_inicio_dt"])
        momento = parsear_fecha_hora_ar(
            r["fecha_inicio_texto"] if col == _COL_FECHA_INICIO
            else r["fecha_fin_texto"]
        )
        # Sin fecha legible van al final, no mezcladas al principio.
        return momento.isoformat(sep=" ") if momento else "9999"
    if col == _COL_DURACION:
        return r["duracion_seg"] or 0.0
    if col == _COL_CD:
        crudo = (r["cd"] or "").strip()
        return (0, int(crudo)) if crudo.isdigit() else (1, crudo.lower())
    if col == _COL_INTERLOCUTOR:
        # Ordenar por Interlocutor es agrupar las comunicaciones con la misma
        # persona. Los que ya tienen nombre van primero: entre ellos está lo
        # identificado, que es por donde se empieza a leer una causa.
        valor = (r["interlocutor"] or "").strip()
        if not valor or valor == SIN_INTERLOCUTOR:
            return (2, "")
        return (1, valor) if valor.isdigit() else (0, valor.lower())
    if col == _COL_INFORMADA:
        return 0 if r["informada"] else 1
    if col == _COL_INTERES:
        return list(NIVELES_INTERES).index(r["nivel_interes"] or "ninguno")
    return (texto or "").lower()


class _Celda(QTableWidgetItem):
    """Celda que se ordena por su valor real y no por lo que muestra."""

    def __lt__(self, otra):  # noqa: D105 — API de Qt
        propia, ajena = self.data(_ROL_ORDEN), otra.data(_ROL_ORDEN)
        if propia is None or ajena is None:
            return super().__lt__(otra)
        try:
            return propia < ajena
        except TypeError:
            return str(propia) < str(ajena)


class _DelegadoFila(QStyledItemDelegate):
    """Rivas el fondo de cada celda: rayado, color del abonado, hover y selección.

    El QSS define reglas para ``QTableWidget::item`` (padding y borde). Con una
    hoja de estilos activa Qt dibuja el fondo de la celda mediante
    QStyleSheetStyle e ignora ``QTableWidgetItem.setBackground()``, así que la
    marca de colores no llegaba a verse. ``setForeground()`` en cambio sí se
    aplicaba: en los abonados de color claro el texto de contraste quedaba
    casi negro sobre el fondo oscuro del tema y el número de orden desaparecía.

    Por el mismo motivo el resaltado de selección también se pinta acá. El que
    dibujaba el estilo era un velo de 12% de opacidad sobre un fondo casi negro
    que ya venía teñido con el color del abonado: en la práctica la fila activa
    no se distinguía de las demás, y con dieciséis columnas eso significa
    perder el renglón a mitad de camino. Se pinta en cuatro capas, de atrás
    hacia adelante:

      1. rayado de filas alternas — el ancla para seguir el renglón;
      2. color del abonado — la marca de la línea intervenida;
      3. banda ámbar con filetes arriba y abajo — la fila que se está leyendo.

    Sobre el filo izquierdo se agrega un filete violeta en las comunicaciones
    que ya salieron en un informe judicial.

    Hubo una cuarta capa que seguía al mouse. Se sacó: mientras se escucha un
    audio el cursor queda apoyado en cualquier lado, y ver encenderse fila tras
    fila se lee como si la selección se estuviera moviendo sola. La selección
    nunca cambiaba de verdad, pero el efecto alcanzaba para perder de vista cuál
    era el registro que se estaba trabajando. La única fila resaltada es la
    seleccionada.

    Después se llama al pintado normal con ``State_Selected`` desactivado, para
    que el estilo no vuelva a dibujar su propio resaltado encima del nuestro.
    """

    def __init__(self, tabla: QTableWidget) -> None:
        super().__init__(tabla)
        self._tabla = tabla

    def paint(self, painter, option, index):  # noqa: N802 (API de Qt)
        seleccionada = bool(option.state & QStyle.State_Selected)
        painter.save()
        if index.row() % 2:
            painter.fillRect(option.rect, QColor(tema.FILA_ALTERNA))
        fondo = index.data(Qt.BackgroundRole)
        if fondo is not None:
            painter.fillRect(option.rect, fondo)
        # Filete al filo izquierdo: la comunicación ya salió en un informe
        # judicial. La columna "Inf." lo dice con precisión, pero el filete es
        # lo que se ve sin buscarlo cuando se recorre la grilla.
        if index.column() == _COL_ORDEN and index.data(_ROL_INFORMADA):
            r = option.rect
            painter.fillRect(r.left(), r.top(), 4, r.height(),
                             QColor(tema.VIOLET))
        if seleccionada:
            painter.fillRect(option.rect, QColor(*tema.FILA_SELECCION_BRILLO))
            painter.fillRect(option.rect, QColor(*tema.FILA_SELECCION))
            r = option.rect
            painter.setPen(QPen(QColor(*tema.FILA_SELECCION_BORDE), 2))
            painter.drawLine(r.left(), r.top() + 1, r.right(), r.top() + 1)
            painter.drawLine(r.left(), r.bottom() - 1, r.right(), r.bottom() - 1)
            # Dentro de la fila activa, la celda donde está parado el teclado:
            # es la que se está leyendo cuando se recorre a lo ancho.
            if index == self._tabla.currentIndex():
                painter.setPen(QPen(QColor(*tema.CELDA_ACTUAL_BORDE), 1))
                painter.drawRect(r.adjusted(1, 2, -2, -3))
        painter.restore()

        opt = QStyleOptionViewItem(option)
        opt.state &= ~QStyle.State_Selected
        super().paint(painter, opt, index)


class _DelegadoCombo(_DelegadoFila):
    """Contexto e Interés: el desplegable existe solo mientras se edita.

    Antes cada fila llevaba dos QComboBox permanentes, puestos con
    `setCellWidget`. Son widgets completos —con su propia vista, su modelo y su
    hoja de estilos— y con trescientas comunicaciones eran seiscientos widgets
    vivos: poblar la tabla pasaba de medio segundo a más de dos minutos, y en
    una máquina modesta directamente no termina.

    Un delegado dibuja el texto y arma el combo recién cuando el analista entra
    a editar la celda, que es una sola por vez. Se hereda de _DelegadoFila para
    no perder el rayado ni la banda de la fila activa en estas dos columnas.
    """

    def __init__(self, tabla: QTableWidget, pantalla: "PantallaTotal",
                 opciones) -> None:
        super().__init__(tabla)
        self._pantalla = pantalla
        self._opciones = opciones  # callable -> [(etiqueta, valor), ...]

    def paint(self, painter, option, index):  # noqa: N802 (API de Qt)
        super().paint(painter, option, index)
        # Marca de "esto se despliega": sin el combo a la vista, nada indicaba
        # que la celda se pudiera cambiar.
        painter.save()
        painter.setPen(QColor(tema.TEXT_DIM))
        painter.drawText(
            option.rect.adjusted(0, 0, -6, 0),
            Qt.AlignRight | Qt.AlignVCenter, "▾",
        )
        painter.restore()

    def createEditor(self, parent, option, index):  # noqa: N802
        combo = QComboBox(parent)
        combo.setObjectName("celdaCombo")
        for etiqueta, valor in self._opciones():
            combo.addItem(etiqueta, valor)
        return combo

    def setEditorData(self, editor, index):  # noqa: N802
        actual = index.data(Qt.UserRole + 2)
        posicion = editor.findData(actual)
        if posicion < 0:
            # Un valor que no está en el catálogo (contexto escrito a mano en
            # otra importación): se agrega para no perderlo al editar.
            editor.insertItem(0, str(actual or ""), actual)
            posicion = 0
        editor.setCurrentIndex(posicion)

    def setModelData(self, editor, model, index):  # noqa: N802
        self._pantalla.aplicar_valor_celda(
            index.row(), index.column(), editor.currentData(), editor.currentText()
        )


class PantallaTotal(QWidget):
    """Grilla de registros + panel de detalle con edición inline."""

    datos_cambiaron = Signal()

    def __init__(self, con: sqlite3.Connection) -> None:
        super().__init__()
        self._con = con
        self._caso_id: int | None = None
        self._filas: list[sqlite3.Row] = []
        self._contextos: list[str] = []
        self._por_id: dict[int, sqlite3.Row] = {}
        self._cargando = False
        self._reproductor: ReproductorAudio | None = None
        # Último lote enviado a la papelera, para el Ctrl+Z inmediato.
        self._ultimo_lote = ""
        self._construir()
        self._crear_atajos()

    # --------------------------- atajos ------------------------------------
    def _crear_atajos(self) -> None:
        """Atajos del bucle de trabajo: escuchar, juzgar, marcar, siguiente.

        Van en dos capas. Los Ctrl+… valen en toda la pantalla, incluso con el
        cursor dentro de un campo de texto. Las teclas sueltas (espacio, 1/2/3,
        E) valen solo con la grilla enfocada, que es donde no compiten con la
        escritura; ahí es donde el analista pasa el día, y marcar un registro
        pasa de tres clics a una tecla. La lista vive en `ui/atajos.py`, que es
        también lo que muestra la ayuda de F1.
        """
        self._acciones_grilla = {
            "reproducir": self._atajo_reproducir,
            "escuchado": self._atajo_escuchado,
            "a_desgrabar": self._mandar_a_desgrabar,
            "deseleccionar": self._atajo_deseleccionar,
            "eliminar": self._eliminar_seleccionadas,
            "interes_ninguno": lambda: self._atajo_interes("ninguno"),
            "interes_marcar": lambda: self._atajo_interes("interes"),
            "interes_alternar": self._atajo_alternar_interes,
        }
        self._teclas_grilla = {
            tecla: self._acciones_grilla[accion]
            for _etiqueta, tecla, accion, _desc in atajos_teclado.GRILLA
            if accion is not None
        }
        self.tabla.installEventFilter(self)

        for secuencia, accion in (
            ("Ctrl+Space", self._atajo_reproducir),
            ("Alt+Down", lambda: self._mover_seleccion(1)),
            ("Alt+Up", lambda: self._mover_seleccion(-1)),
            ("Ctrl+E", self._atajo_escuchado),
            ("Ctrl+F", self._atajo_buscar),
            ("Ctrl+Z", self._deshacer_borrado),
        ):
            atajo = QShortcut(QKeySequence(secuencia), self)
            atajo.setContext(Qt.WidgetWithChildrenShortcut)
            atajo.activated.connect(accion)

    def _atajo_reproducir(self) -> None:
        if self._reproductor is not None:
            self._reproductor.alternar()

    def _atajo_buscar(self) -> None:
        self.txt_buscar.setFocus()
        self.txt_buscar.selectAll()

    def _atajo_escuchado(self) -> None:
        r = self._registro_seleccionado()
        if r is None:
            return
        self._marcar_escuchado(r["id"], not r["escuchado"])

    def _atajo_deseleccionar(self) -> None:
        self.tabla.clearSelection()

    def _atajo_alternar_interes(self) -> None:
        """Marca o desmarca la comunicación: con el interés binario, una tecla.

        El valor se lee de la CELDA y no del registro cacheado: la celda es lo
        que se actualiza al marcar, y el caché recién se refresca en el próximo
        `refrescar()`. Leyéndolo del caché, apretar dos veces marcaba dos veces
        en vez de alternar.
        """
        fila = self.tabla.currentRow()
        if fila < 0:
            return
        item = self.tabla.item(fila, _COL_INTERES)
        actual = item.data(Qt.UserRole + 2) if item else "ninguno"
        marcada = (actual or "ninguno") != "ninguno"
        self._atajo_interes("ninguno" if marcada else "interes")

    def _marcar_interes_desde_el_panel(self, registro_id: int, marcada: bool) -> None:
        """La casilla del panel, por el mismo camino que la celda de la grilla.

        No escribe en la base por su cuenta: mueve la celda. Así el guardado,
        el historial de cambios y lo que se ve en la grilla siguen pasando por
        un solo lugar, y la columna de Interés queda al día sola.
        """
        fila = self._fila_de_registro(registro_id)
        if fila < 0:
            return
        nivel = "interes" if marcada else "ninguno"
        self.aplicar_valor_celda(
            fila, _COL_INTERES, nivel, _ETIQUETA_INTERES.get(nivel, nivel)
        )

    def _atajo_interes(self, nivel: str) -> None:
        """Cambia el nivel de interés de la fila seleccionada desde el teclado.

        Se mueve el combo de la grilla en vez de escribir directo en la base:
        así el guardado, el historial y lo que se ve en pantalla siguen pasando
        por el mismo camino que un cambio hecho con el mouse.
        """
        fila = self.tabla.currentRow()
        if fila < 0:
            return
        self.aplicar_valor_celda(
            fila, _COL_INTERES, nivel, _ETIQUETA_INTERES.get(nivel, nivel)
        )

    def eventFilter(self, obj, event):  # noqa: N802 (API de Qt)
        """Teclas sin modificador mientras la grilla tiene el foco."""
        if obj is self.tabla and event.type() == QEvent.KeyPress:
            # Con cualquier modificador el evento no es nuestro: lo reclaman
            # los QShortcut (Ctrl+E, Ctrl+Espacio) o la navegación de Qt.
            sin_modificador = event.modifiers() in (
                Qt.NoModifier, Qt.KeypadModifier
            )
            accion = self._teclas_grilla.get(event.key())
            if sin_modificador and accion is not None:
                accion()
                return True
        return super().eventFilter(obj, event)

    def _mover_seleccion(self, delta: int) -> None:
        """Salta al registro visible anterior/siguiente, salteando los filtrados."""
        fila = self.tabla.currentRow()
        if fila < 0:
            visibles = [
                f for f in range(self.tabla.rowCount())
                if not self.tabla.isRowHidden(f)
            ]
            if visibles:
                self.tabla.selectRow(visibles[0])
            return
        f = fila + delta
        while 0 <= f < self.tabla.rowCount():
            if not self.tabla.isRowHidden(f):
                self.tabla.selectRow(f)
                self.tabla.scrollToItem(self.tabla.item(f, _COL_ORDEN))
                return
            f += delta

    def set_caso(self, caso_id: int) -> None:
        self._caso_id = caso_id
        self.refrescar()

    def seleccionar_registro(self, registro_id: int) -> bool:
        """Selecciona la fila del registro indicado y abre su detalle. True si existe."""
        fila = self._fila_de_registro(registro_id)
        if fila < 0:
            return False
        self.tabla.setRowHidden(fila, False)
        self.tabla.selectRow(fila)
        self.tabla.scrollToItem(self.tabla.item(fila, 0))
        return True

    def filtrar_por_cd(self, numero: str) -> None:
        """Deja la grilla mostrando solo las comunicaciones de una entrega."""
        self._limpiar_filtros()
        indice = self.cmb_f_cd.findText(numero)
        if indice >= 0:
            self.cmb_f_cd.setCurrentIndex(indice)
        for fila in range(self.tabla.rowCount()):
            if not self.tabla.isRowHidden(fila):
                self.tabla.selectRow(fila)
                self.tabla.setFocus()
                break

    def filtrar_pendientes(self) -> None:
        """Deja la grilla mostrando solo lo que todavía no se escuchó.

        Es la puerta de entrada desde el Resumen: el analista viene de ver
        «faltan 238» y espera caer en esas 238, ya parado en la primera.
        """
        self._limpiar_filtros()
        self.cmb_f_escucha.setCurrentText("Pendientes")
        for fila in range(self.tabla.rowCount()):
            if not self.tabla.isRowHidden(fila):
                self.tabla.selectRow(fila)
                self.tabla.setFocus()
                break

    def buscar(self, texto: str) -> None:
        """Punto de entrada de la búsqueda global (topbar)."""
        self.txt_buscar.setText(texto)
        self._aplicar_filtros()

    # ------------------------- construcción UI -----------------------------
    def _construir(self) -> None:
        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        main = QWidget()
        mlay = QVBoxLayout(main)
        mlay.setContentsMargins(22, 16, 22, 10)
        mlay.setSpacing(10)

        cab = QHBoxLayout()
        titulos = QVBoxLayout()
        self.lbl_titulo = QLabel("Tabla TOTAL")
        self.lbl_titulo.setObjectName("titulo")
        self.lbl_sub = QLabel("Comunicaciones registradas")
        self.lbl_sub.setObjectName("subtitulo")
        # Que los títulos no fijen el ancho mínimo de toda la pantalla. Pedían
        # 312 px por el largo de su texto, y eso se le restaba al panel de
        # detalle: el divisor no se podía arrastrar más allá de ahí. Un título
        # es lo primero que puede ceder espacio, no lo último.
        for etiqueta in (self.lbl_titulo, self.lbl_sub):
            etiqueta.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        titulos.addWidget(self.lbl_titulo)
        titulos.addWidget(self.lbl_sub)
        cab.addLayout(titulos, 1)
        cab.addStretch(1)
        self.btn_actualizar = QPushButton("⟳ Actualizar")
        self.btn_actualizar.setToolTip(
            "Vuelve a leer la causa y recompone Interesado e Interlocutor con "
            "los nombres que haya hoy en el Índice y en la memoria "
            "«corresponde a»  ·  F5"
        )
        self.btn_actualizar.setShortcut("F5")
        self.btn_actualizar.clicked.connect(self._actualizar_a_mano)
        cab.addWidget(self.btn_actualizar)

        self.btn_transcribir = QPushButton("🎙 Transcribir marcadas")
        self.btn_transcribir.setToolTip(
            "Transcribe con Whisper las comunicaciones marcadas de interés que "
            "todavía no tienen texto. Se marcan con la tecla I o desde la "
            "columna Interés."
        )
        self.btn_transcribir.clicked.connect(self._transcribir_lote)
        cab.addWidget(self.btn_transcribir)

        # Exportaciones agrupadas en un solo menú desplegable (ahorra ancho).
        self.btn_export = QToolButton()
        self.btn_export.setText("Exportar  ▾")
        self.btn_export.setObjectName("primary")
        self.btn_export.setPopupMode(QToolButton.InstantPopup)
        menu_export = QMenu(self.btn_export)
        menu_export.addAction("Exportar a Excel", self._exportar_excel)
        menu_export.addAction("Informe judicial", self._exportar_judicial)
        self.btn_export.setMenu(menu_export)
        cab.addWidget(self.btn_export)
        mlay.addLayout(cab)

        cont_filtros = QWidget()
        cont_filtros.setLayout(self._crear_barra_filtros())
        mlay.addWidget(cont_filtros)

        self.tabla = QTableWidget(0, len(_COLUMNAS))
        self.tabla.setHorizontalHeaderLabels(_COLUMNAS)
        self.tabla.horizontalHeaderItem(_COL_ORDEN).setToolTip(
            "El color de la fila identifica la línea intervenida"
        )
        self.tabla.horizontalHeaderItem(_COL_INFORMADA).setToolTip(
            "📄 = la comunicación ya salió en un informe judicial"
        )
        self.tabla.horizontalHeaderItem(_COL_INTERLOCUTOR).setToolTip(
            "Con quién habló la línea intervenida: la otra punta de la "
            "comunicación. Sale del Índice de abonados, y de la memoria "
            "«corresponde a» si el Índice no lo tiene. Mientras no tenga "
            "nombre muestra el número."
        )
        self.tabla.horizontalHeaderItem(_COL_INTERESADO).setToolTip(
            "Quién está identificado en la comunicación. Puede nombrar a los "
            "dos extremos, y no siempre coincide con la línea intervenida que "
            "marca el color."
        )
        self.tabla.verticalHeader().setVisible(False)
        # Solo Contexto e Interés son editables (sus items llevan el flag);
        # el resto de las celdas no lo tiene, así que estos disparadores no las
        # tocan. Un clic sobre la celda ya seleccionada abre el desplegable.
        self.tabla.setEditTriggers(
            QTableWidget.DoubleClicked
            | QTableWidget.SelectedClicked
            | QTableWidget.EditKeyPressed
        )
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        # Selección extendida: con Ctrl y Shift se arma el conjunto a borrar
        # cuando una carga salió mal. El panel de detalle sigue el cursor, así
        # que seleccionar varias no cambia lo que se está escuchando.
        self.tabla.setSelectionMode(QTableWidget.ExtendedSelection)
        self.tabla.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabla.customContextMenuRequested.connect(self._menu_grilla)
        self.tabla.setShowGrid(False)
        self._delegado = _DelegadoFila(self.tabla)
        self.tabla.setItemDelegate(self._delegado)
        self._delegado_contexto = _DelegadoCombo(
            self.tabla, self, self._opciones_contexto
        )
        self._delegado_interes = _DelegadoCombo(
            self.tabla, self, self._opciones_interes
        )
        self.tabla.setItemDelegateForColumn(_COL_CONTEXTO, self._delegado_contexto)
        self.tabla.setItemDelegateForColumn(_COL_INTERES, self._delegado_interes)
        hh = self.tabla.horizontalHeader()
        # ResizeToContents mide cada celda de cada columna en cada repoblado:
        # con 300 filas son miles de mediciones de texto. Se ajusta una vez al
        # cargar los datos (ver _ajustar_anchos) y después queda interactivo,
        # que además deja al analista arrastrar las columnas.
        hh.setSectionResizeMode(QHeaderView.Interactive)
        # Al medir los anchos, mirar 30 filas alcanza: son columnas de formato
        # fijo (números, fechas, CD) donde la fila 200 no es más ancha que la 3.
        hh.setResizeContentsPrecision(30)
        # Clic en el encabezado para ordenar por esa columna. Se apaga mientras
        # se puebla (patrón estándar de Qt): con el orden activo, cada fila que
        # entra reordena la tabla y poblar pasa a ser cuadrático.
        self.tabla.setSortingEnabled(True)
        hh.setSortIndicatorShown(True)
        # Sin fijarlo, al reactivar el orden Qt aplica el indicador que tenga
        # puesto y la grilla aparece al revés. El orden de fábrica es el de
        # importación, que es como el analista recorrió el material.
        hh.setSortIndicator(_COL_ORDEN, Qt.AscendingOrder)
        hh.setToolTip("Clic para ordenar por esta columna")
        # Interesado es el campo que identifica de quién es la comunicación, así
        # que no puede quedar elidido. Con Stretch colapsaba al mínimo cada vez
        # que el ancho total de las 16 columnas superaba el viewport (que es lo
        # normal), mostrando "NO ..." mientras columnas menos útiles sobraban de
        # espacio. Interactive deja que la dimensione _ajustar_columna_interesado
        # al cargar los datos, y que el usuario la arrastre si quiere.
        hh.setSectionResizeMode(_COL_INTERESADO, QHeaderView.Interactive)
        self.tabla.itemSelectionChanged.connect(self._on_seleccion)
        mlay.addWidget(self.tabla, 1)

        # El color de la fila codifica la línea intervenida, que es un dato
        # distinto del que muestra la columna Interesado (esa puede nombrar a
        # los dos extremos). Sin decirlo, el código de color no se deduce.
        self.lbl_leyenda_color = QLabel(
            "El color de cada fila identifica la línea intervenida de la "
            "comunicación. Pasá el mouse por la columna Orden para ver cuál es. "
            "El filete violeta al costado izquierdo, y la columna «Inf.», "
            "marcan las que ya salieron en un informe judicial."
        )
        self.lbl_leyenda_color.setObjectName("subtitulo")
        self.lbl_leyenda_color.setWordWrap(True)
        mlay.addWidget(self.lbl_leyenda_color)

        self.lbl_status = QLabel("Sin registros")
        self.lbl_status.setObjectName("subtitulo")
        mlay.addWidget(self.lbl_status)

        self.panel = self._crear_panel_detalle()

        # Divisor arrastrable en vez de un ancho fijo. El panel muestra la
        # transcripción y los datos de celda, que en una comunicación larga no
        # entran en 330 px; y en una pantalla chica, esos 330 px se los sacaba
        # a la grilla. Cuánto espacio merece cada lado depende de qué se esté
        # haciendo, así que lo decide el analista y el programa lo recuerda.
        self.divisor = QSplitter(Qt.Horizontal)
        self.divisor.setChildrenCollapsible(False)
        self.divisor.setHandleWidth(6)
        self.divisor.addWidget(main)
        self.divisor.addWidget(self.panel)
        # Al agrandar la ventana crece la grilla, no el panel.
        self.divisor.setStretchFactor(0, 1)
        self.divisor.setStretchFactor(1, 0)
        raiz.addWidget(self.divisor, 1)
        self.divisor.splitterMoved.connect(self._recordar_divisor)
        self._restaurar_divisor()

    def _crear_barra_filtros(self) -> FlowLayout:
        # FlowLayout: los filtros pasan a la línea siguiente si no entran a lo
        # ancho, así nunca se cortan aunque la ventana sea angosta.
        barra = FlowLayout(spacing=8)

        self.txt_buscar = QLineEdit()
        self.txt_buscar.setPlaceholderText("Buscar abonado, antena, fecha...")
        self.txt_buscar.setClearButtonEnabled(True)
        self.txt_buscar.setToolTip("Buscar en todos los campos  ·  Ctrl+F")
        self.txt_buscar.setFixedWidth(230)
        self.txt_buscar.textChanged.connect(self._aplicar_filtros)
        barra.addWidget(self.txt_buscar)

        self.cmb_f_interesado = QComboBox()
        self.cmb_f_direccion = QComboBox()
        self.cmb_f_cd = QComboBox()
        self.cmb_f_interes = QComboBox()
        self.cmb_f_estado = QComboBox()
        # Poblar antes de conectar: addItems dispara currentIndexChanged y la
        # pantalla todavía no terminó de construirse.
        self.cmb_f_escucha = QComboBox()
        self.cmb_f_tipo = QComboBox()
        self.cmb_f_revision = QComboBox()
        self.cmb_f_informe = QComboBox()
        self.cmb_f_interes.addItems(["Interés: todos", "De interés", "Sin marcar"])
        self.cmb_f_estado.addItems(list(_FILTRO_ESTADO))
        self.cmb_f_escucha.addItems(["Escucha: todas", "Pendientes", "Escuchadas"])
        self.cmb_f_tipo.addItems(["Tipo: todos", "Llamadas", "SMS"])
        self.cmb_f_revision.addItems(["Revisión: todas", "Sin revisar", "Revisadas"])
        self.cmb_f_informe.addItems(
            ["Informe: todas", "Ya informadas", "Sin informar"]
        )
        for cmb, etiqueta in (
            (self.cmb_f_interesado, "Interesado"),
            (self.cmb_f_direccion, "Dirección"),
            (self.cmb_f_cd, "CD"),
            (self.cmb_f_interes, "Interés"),
            (self.cmb_f_estado, "Estado"),
            (self.cmb_f_escucha, "Escucha"),
            (self.cmb_f_tipo, "Tipo"),
            (self.cmb_f_revision, "Revisión"),
            (self.cmb_f_informe, "Informe"),
        ):
            cmb.setToolTip(f"Filtrar por {etiqueta.lower()}")
            _ajustar_ancho_combo(cmb)
            cmb.currentIndexChanged.connect(self._aplicar_filtros)
            barra.addWidget(cmb)

        btn_limpiar = QPushButton("Limpiar filtros")
        btn_limpiar.clicked.connect(self._limpiar_filtros)
        barra.addWidget(btn_limpiar)

        self.chip_faltantes = QPushButton("")
        self.chip_faltantes.setObjectName("chipAlerta")
        self.chip_faltantes.setVisible(False)
        self.chip_faltantes.setToolTip("Ver solo los registros con archivos faltantes")
        self.chip_faltantes.clicked.connect(self._filtrar_faltantes)
        barra.addWidget(self.chip_faltantes)
        return barra

    # ------------------------ el ancho del panel ---------------------------
    #: Lo que medía cuando era fijo. Sigue siendo el ancho de arranque.
    ANCHO_PANEL = 330
    #: Menos que esto el panel deja de servir: la transcripción queda en una
    #: columna de dos palabras por renglón.
    ANCHO_PANEL_MINIMO = 240
    _PREF_DIVISOR = "ancho_panel_detalle"

    def _restaurar_divisor(self) -> None:
        guardado = sesion.preferencia(self._PREF_DIVISOR)
        try:
            ancho = int(guardado)
        except (TypeError, ValueError):
            ancho = self.ANCHO_PANEL
        # Una preferencia vieja de otra pantalla no puede dejar el panel
        # inservible ni comerse la grilla entera.
        ancho = max(self.ANCHO_PANEL_MINIMO, min(ancho, 900))
        self.divisor.setSizes([max(1, self.width() - ancho), ancho])

    def _recordar_divisor(self, *_args) -> None:
        tamanos = self.divisor.sizes()
        if len(tamanos) == 2 and tamanos[1] > 0:
            # str: `sesion.preferencia()` solo devuelve cadenas, así que un int
            # se guardaba y al releerlo caía en el valor por defecto. El ancho
            # se perdía en silencio entre un arranque y el siguiente.
            sesion.set_preferencia(self._PREF_DIVISOR, str(tamanos[1]))

    def _crear_panel_detalle(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setMinimumWidth(self.ANCHO_PANEL_MINIMO)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(8)

        self.d_eyebrow = QLabel("REGISTRO")
        self.d_eyebrow.setObjectName("seccion")
        self.d_nombre = QLabel("—")
        self.d_nombre.setObjectName("titulo")
        self.d_nombre.setTextFormat(Qt.RichText)
        self.d_od = QLabel("")
        self.d_od.setObjectName("subtitulo")
        lay.addWidget(self.d_eyebrow)
        lay.addWidget(self.d_nombre)
        lay.addWidget(self.d_od)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{tema.LINE};")
        lay.addWidget(sep)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.d_cuerpo = QWidget()
        self.d_cuerpo_lay = QVBoxLayout(self.d_cuerpo)
        self.d_cuerpo_lay.setContentsMargins(0, 0, 4, 0)
        self.d_cuerpo_lay.setSpacing(6)
        self.d_cuerpo_lay.addStretch(1)
        scroll.setWidget(self.d_cuerpo)
        lay.addWidget(scroll, 1)
        return panel

    # ---------------------------- datos ------------------------------------
    def _actualizar_a_mano(self) -> None:
        """Rehace la grilla desde la base, recalculando los nombres.

        Las columnas Interesado e Interlocutor están GUARDADAS en cada
        comunicación —tienen que estarlo, salen al Excel y se ordenan y filtran
        por ellas—, así que dependen de que algo las recomponga cuando cambia
        un nombre. Cada pantalla que toca nombres lo hace sola, pero esto es la
        red: después de editar la base por fuera, o si alguna vez algo no
        avisa, el analista tiene cómo ponerla al día sin cerrar el programa.
        """
        if self._caso_id is None:
            return
        tocadas = repo.recalcular_nombres(self._con, self._caso_id)
        self._con.commit()
        self.refrescar()
        self.datos_cambiaron.emit()
        self.lbl_status.setText(
            f"Actualizado · {tocadas} comunicaciones cambiaron de nombre"
            if tocadas else "Actualizado · los nombres ya estaban al día"
        )

    def refrescar(self) -> None:
        if self._caso_id is None:
            return
        caso = repo.obtener_caso(self._con, self._caso_id)
        self.lbl_sub.setText(
            f"Comunicaciones registradas — {caso['nombre']}" if caso else ""
        )
        self._contextos = repo.listar_contextos(self._con, self._caso_id)
        self._recargar_filas()
        self._poblar()
        self._ajustar_columna_interesado()
        self._poblar_filtros()
        self._aplicar_filtros()

        n_audio = sum(1 for r in self._filas if r["estado"] == "audio_faltante")
        n_txt = sum(1 for r in self._filas if r["estado"] == "transcripcion_faltante")
        n_faltantes = n_audio + n_txt
        self.chip_faltantes.setVisible(n_faltantes > 0)
        self.chip_faltantes.setText(
            f"⚠ {n_faltantes} registros con archivos faltantes"
        )

    def _ajustar_columna_interesado(self) -> None:
        """Ajusta los anchos una sola vez, al terminar de cargar los datos.

        Las columnas quedan en modo Interactive: medir el contenido en cada
        repoblado costaba miles de mediciones de texto por carga. Acá se mide
        una vez —y sobre una muestra de filas— y después el analista puede
        arrastrar las columnas si quiere.

        Interesado se calcula aparte, sobre TODAS las filas y no sobre las
        visibles: si dependiera del filtro activo, la columna cambiaría de
        ancho cada vez que se filtra y el ojo perdería la referencia.
        """
        self.tabla.resizeColumnsToContents()
        fm = self.tabla.fontMetrics()
        necesario = max(
            (fm.horizontalAdvance(r["interesado"] or "") for r in self._filas),
            default=0,
        )
        ancho = min(
            max(necesario + _PAD_CELDA, _ANCHO_MIN_INTERESADO),
            _ANCHO_MAX_INTERESADO,
        )
        self.tabla.horizontalHeader().resizeSection(_COL_INTERESADO, ancho)

    def _poblar_filtros(self) -> None:
        """Regenera las opciones de los combos de filtro preservando la elección."""
        combos = (
            (self.cmb_f_interesado, "Interesado: todos",
             sorted({r["interesado"] for r in self._filas if r["interesado"]})),
            (self.cmb_f_direccion, "Dirección: todas",
             sorted({r["direccion"] for r in self._filas if r["direccion"]})),
            (self.cmb_f_cd, "CD: todos",
             sorted({r["cd"] for r in self._filas if r["cd"]})),
        )
        for cmb, todos, opciones in combos:
            actual = cmb.currentText()
            cmb.blockSignals(True)
            cmb.clear()
            cmb.addItem(todos)
            cmb.addItems(opciones)
            if actual in opciones:
                cmb.setCurrentText(actual)
            cmb.blockSignals(False)
            # Los valores llegan recién acá, así que el desplegable se
            # redimensiona ahora (el ancho del combo lo fija la etiqueta).
            _ajustar_ancho_combo(cmb)

    def _limpiar_filtros(self) -> None:
        self._solo_faltantes = False
        for cmb in (self.cmb_f_interesado, self.cmb_f_direccion, self.cmb_f_cd,
                    self.cmb_f_interes, self.cmb_f_estado, self.cmb_f_escucha,
                    self.cmb_f_tipo, self.cmb_f_revision, self.cmb_f_informe):
            cmb.blockSignals(True)
            cmb.setCurrentIndex(0)
            cmb.blockSignals(False)
        self.txt_buscar.blockSignals(True)
        self.txt_buscar.clear()
        self.txt_buscar.blockSignals(False)
        self._aplicar_filtros()

    def _filtrar_faltantes(self) -> None:
        """Chip de alerta: alterna entre ver solo faltantes y ver todo."""
        self._solo_faltantes = not getattr(self, "_solo_faltantes", False)
        self._aplicar_filtros()

    def _pasa_filtros(self, r: sqlite3.Row) -> bool:
        if getattr(self, "_solo_faltantes", False) and r["estado"] == "completo":
            return False
        f_int = self.cmb_f_interesado.currentText()
        if self.cmb_f_interesado.currentIndex() > 0 and (r["interesado"] or "") != f_int:
            return False
        f_dir = self.cmb_f_direccion.currentText()
        if self.cmb_f_direccion.currentIndex() > 0 and (r["direccion"] or "") != f_dir:
            return False
        f_cd = self.cmb_f_cd.currentText()
        if self.cmb_f_cd.currentIndex() > 0 and (r["cd"] or "") != f_cd:
            return False
        # El filtro es binario: "De interés" o "Sin marcar".
        if self.cmb_f_interes.currentIndex() > 0 and (
            ((r["nivel_interes"] or "ninguno") != "ninguno")
            != (self.cmb_f_interes.currentText() == "De interés")
        ):
            return False
        estado = _FILTRO_ESTADO.get(self.cmb_f_estado.currentText())
        if estado and r["estado"] != estado:
            return False
        idx_escucha = self.cmb_f_escucha.currentIndex()
        if idx_escucha == 1:
            # "Pendientes de escucha": solo llamadas con audio y sin escuchar.
            tiene_audio = (
                r["tipo"] == "llamada"
                and r["estado"] != "audio_faltante"
                and bool(r["archivo_audio"])
            )
            if r["escuchado"] or not tiene_audio:
                return False
        if idx_escucha == 2 and not r["escuchado"]:
            return False
        idx_tipo = self.cmb_f_tipo.currentIndex()
        if idx_tipo == 1 and r["tipo"] != "llamada":
            return False
        if idx_tipo == 2 and r["tipo"] != "sms":
            return False
        idx_rev = self.cmb_f_revision.currentIndex()
        if idx_rev in (1, 2):
            tiene_txt = (
                r["tipo"] == "llamada" and bool((r["transcripcion"] or "").strip())
            )
            if idx_rev == 1 and (not tiene_txt or r["transcripcion_revisada"]):
                return False  # "Sin revisar": llamadas con texto no revisado
            if idx_rev == 2 and not r["transcripcion_revisada"]:
                return False  # "Revisadas"
        idx_inf = self.cmb_f_informe.currentIndex()
        if idx_inf == 1 and not r["informada"]:
            return False
        if idx_inf == 2 and r["informada"]:
            return False

        texto = self.txt_buscar.text().strip().lower()
        if texto:
            campos = (
                r["interesado"], r["origen"], r["destino"], r["origen_crudo"],
                r["destino_crudo"], r["antenas"], r["fecha_inicio_texto"],
                r["fecha_fin_texto"], r["interlocutor"], r["corresponde_a"],
                r["contexto"],
                r["transcripcion"], r["archivo_audio"], r["localidad"], r["cd"],
            )
            blob = " ".join(str(c or "") for c in campos).lower()
            if texto not in blob:
                return False
        return True

    def _aplicar_filtros(self) -> None:
        if self._cargando:
            return
        visibles = 0
        for fila in range(self.tabla.rowCount()):
            r = self._registro_de_fila(fila)
            pasa = bool(r) and self._pasa_filtros(r)
            self.tabla.setRowHidden(fila, not pasa)
            visibles += pasa
        self._actualizar_status(visibles)

    def _actualizar_status(self, visibles: int) -> None:
        n_audio = sum(1 for r in self._filas if r["estado"] == "audio_faltante")
        n_txt = sum(1 for r in self._filas if r["estado"] == "transcripcion_faltante")
        pend = repo.contar_avisos_pendientes(self._con, self._caso_id)
        filtro = (
            f" · mostrando {visibles}" if visibles != len(self._filas) else ""
        )
        prog = repo.progreso_escucha(self._con, self._caso_id)
        escucha = ""
        if prog["total"]:
            escucha = f" · escuchados {prog['escuchados']}/{prog['total']}"
            if prog["segundos"]:
                horas = int(prog["segundos"] // 3600)
                minutos = int((prog["segundos"] % 3600) // 60)
                escucha += f" · {horas}h {minutos:02d}m de audio"
        self.lbl_status.setText(
            f"{len(self._filas)} registros{filtro} · {n_audio} audio faltante · "
            f"{n_txt} transcripción faltante · {pend} avisos pendientes{escucha}"
        )

    def _poblar(self) -> None:
        self.tabla.setSortingEnabled(False)
        self._cargando = True
        self.tabla.setRowCount(0)
        for r in self._filas:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            es_sms = r["tipo"] == "sms"
            tiene_txt = bool((r["transcripcion"] or "").strip())
            # Indicador de revisión: solo aplica a llamadas con transcripción
            # (los SMS traen texto de la prestadora, no de IA).
            if es_sms or not tiene_txt:
                rev_txt = ""
            elif r["transcripcion_revisada"]:
                rev_txt = "✓"
            else:
                rev_txt = "⚠"
            texto = {
                0: str(r["orden"] or ""),
                _COL_INTERESADO: r["interesado"] or "",
                _COL_INTERLOCUTOR: r["interlocutor"] or SIN_INTERLOCUTOR,
                _COL_CD: r["cd"] or "",
                _COL_DIRECCION: r["direccion"] or "",
                _COL_ORIGEN: r["origen"] or "",
                _COL_DESTINO: r["destino"] or "",
                _COL_FECHA_INICIO: r["fecha_inicio_texto"] or "—",
                _COL_FECHA_FIN: r["fecha_fin_texto"] or "—",
                _COL_ANTENAS: r["antenas"] or "",
                _COL_ARCHIVO: "✉ SMS" if es_sms else (r["archivo_audio"] or ""),
                _COL_DURACION: _formato_mmss(r["duracion_seg"]) if r["duracion_seg"] else "",
                _COL_ESCUCHADO: "✓" if r["escuchado"] else "",
                _COL_REVISADA: rev_txt,
                _COL_INFORMADA: "📄" if r["informada"] else "",
                _COL_ESTADO: "✉ SMS" if es_sms else _BADGE_ESTADO.get(r["estado"], ""),
            }
            for col, val in texto.items():
                item = _Celda(val)
                item.setData(_ROL_ORDEN, _clave_orden(r, col, val))
                # Los QTableWidgetItem nacen editables. Con los disparadores de
                # edición encendidos para Contexto e Interés, dejarlo así haría
                # que un doble clic en Origen o en la fecha abriera un editor
                # que nadie guarda: el analista vería cambiar el dato y al
                # refrescar volvería el original. Solo esas dos columnas se
                # editan, y el flag se lo pone _celda_editable.
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if col == _COL_ORDEN:
                    item.setData(Qt.UserRole, r["id"])
                    item.setData(_ROL_INFORMADA, bool(r["informada"]))
                    item.setToolTip(_tooltip_linea(r))
                if col == _COL_ESTADO and es_sms:
                    item.setForeground(QColor(tema.VIOLET))
                elif col == _COL_ESTADO and r["estado"] != "completo":
                    item.setForeground(QColor(tema.DANGER))
                if col == _COL_ESCUCHADO and r["escuchado"]:
                    item.setForeground(QColor(tema.TEAL))
                    item.setTextAlignment(Qt.AlignCenter)
                if col == _COL_INFORMADA and r["informada"]:
                    item.setForeground(QColor(tema.VIOLET))
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setToolTip(
                        "Ya salió en un informe judicial. Se puede revertir "
                        "deshaciendo ese lote desde Exportaciones."
                    )
                if col == _COL_REVISADA and rev_txt:
                    item.setForeground(
                        QColor(tema.TEAL if rev_txt == "✓" else tema.ACCENT)
                    )
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setToolTip(
                        "Transcripción revisada por el analista" if rev_txt == "✓"
                        else "Transcripción sin revisar"
                    )
                self.tabla.setItem(fila, col, item)

            self._celda_editable(
                fila, _COL_CONTEXTO, r["contexto"] or "", r["contexto"] or "",
            )
            nivel = r["nivel_interes"] or "ninguno"
            self._celda_editable(
                fila, _COL_INTERES, _ETIQUETA_INTERES.get(nivel, nivel), nivel,
            )

            color = r["color_hex"]
            if color:
                # Tinte visible en toda la fila + chip de color sólido en la
                # columna Orden, para que la marca de colores del abonado se note.
                c = QColor(color)
                c.setAlpha(46)
                for col in range(len(_COLUMNAS)):
                    it = self.tabla.item(fila, col)
                    if it is not None:
                        it.setBackground(c)
                item_orden = self.tabla.item(fila, _COL_ORDEN)
                if item_orden is not None:
                    solido = QColor(color)
                    item_orden.setBackground(solido)
                    item_orden.setForeground(QColor(_texto_contraste(solido)))
                    item_orden.setTextAlignment(Qt.AlignCenter)
        self._por_id = {r["id"]: r for r in self._filas}
        self._cargando = False
        self.tabla.setSortingEnabled(True)

    def _celda_editable(self, fila: int, columna: int, etiqueta: str,
                        valor: object) -> None:
        """Celda de las que se despliegan: muestra la etiqueta, guarda el valor."""
        item = _Celda(etiqueta)
        item.setData(Qt.UserRole + 2, valor)
        item.setData(
            _ROL_ORDEN,
            list(NIVELES_INTERES).index(valor)
            if columna == _COL_INTERES and valor in NIVELES_INTERES
            else str(valor or "").lower(),
        )
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        self.tabla.setItem(fila, columna, item)

    def _opciones_contexto(self) -> list[tuple[str, str]]:
        opciones = [("", "")]
        opciones += [(c, c) for c in self._contextos if c]
        return opciones

    def _opciones_interes(self) -> list[tuple[str, str]]:
        return [(_ETIQUETA_INTERES[n], n) for n in NIVELES_INTERES]


    def aplicar_valor_celda(self, fila: int, columna: int, valor: object,
                            etiqueta: str) -> None:
        """Guarda lo elegido en una celda desplegable y refleja la etiqueta."""
        if not (0 <= fila < len(self._filas)):
            return
        campo = "contexto" if columna == _COL_CONTEXTO else "nivel_interes"
        registro = self._registro_de_fila(fila)
        if registro is None:
            return
        registro_id = registro["id"]
        item = self.tabla.item(fila, columna)
        if item is not None:
            item.setText(etiqueta)
            item.setData(Qt.UserRole + 2, valor)
        if columna == _COL_INTERES:
            self._sincronizar_casilla_interes(fila, valor)
        self._editar(registro_id, campo, valor)

    def _esta_de_interes(self, registro_id: int, registro: sqlite3.Row) -> bool:
        """Si está marcada, según la CELDA y no el registro cacheado.

        El caché de `self._filas` se recarga recién en el próximo `refrescar()`,
        así que después de marcar y cambiar de fila volvía a decir que no estaba
        marcada. La celda es lo que se actualiza al marcar y es la que vale.
        """
        fila = self._fila_de_registro(registro_id)
        if fila >= 0:
            item = self.tabla.item(fila, _COL_INTERES)
            if item is not None:
                valor = item.data(Qt.UserRole + 2)
                if valor is not None:
                    return (valor or "ninguno") != "ninguno"
        return (registro["nivel_interes"] or "ninguno") != "ninguno"

    def _sincronizar_casilla_interes(self, fila: int, valor: object) -> None:
        """Deja la casilla del panel igual que la celda.

        Marcar con la tecla I o con el desplegable no rehace el panel, así que
        sin esto la casilla quedaba mostrando lo contrario de lo que dice la
        grilla para el mismo registro.

        `blockSignals`: ponerla no puede contar como que alguien la tocó, o
        cada marca dispararía otra edición encima.
        """
        casilla = getattr(self, "chk_interes", None)
        if casilla is None or fila != self.tabla.currentRow():
            return
        casilla.blockSignals(True)
        casilla.setChecked((valor or "ninguno") != "ninguno")
        casilla.blockSignals(False)

    def _editar(self, registro_id: int, campo: str, valor: object) -> None:
        if self._cargando:
            return
        try:
            edicion.editar_campo(self._con, registro_id, campo, valor)
            self.datos_cambiaron.emit()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Edición", f"No se pudo editar:\n{exc}")

    # --------------------------- detalle -----------------------------------
    def _filas_seleccionadas(self) -> list[int]:
        """Filas seleccionadas Y visibles, en el orden de la grilla.

        Las ocultas por el filtro quedan afuera a propósito: Ctrl+A selecciona
        todo el modelo, incluidas las que el filtro esconde. Sin este recorte,
        filtrar por el CD 5 y hacer Ctrl+A para borrarlo se llevaría la causa
        entera. Se borra lo que se está viendo.
        """
        return sorted(
            {
                i.row() for i in self.tabla.selectionModel().selectedRows()
                if not self.tabla.isRowHidden(i.row())
            }
        )

    def _menu_grilla(self, punto) -> None:
        """Menú contextual de la grilla: por ahora, eliminar lo seleccionado."""
        filas = self._filas_seleccionadas()
        if not filas:
            return
        menu = QMenu(self)
        mandar = menu.addAction(
            "Mandar a Desgrabar" if len(filas) == 1
            else f"Mandar {len(filas)} a Desgrabar"
        )
        mandar.triggered.connect(self._mandar_a_desgrabar)
        menu.addSeparator()
        accion = menu.addAction(
            "Enviar 1 comunicación a la papelera..."
            if len(filas) == 1 else
            f"Enviar {len(filas)} comunicaciones a la papelera..."
        )
        accion.triggered.connect(self._eliminar_seleccionadas)
        if self._caso_id is not None and papelera.contar(self._con, self._caso_id):
            deshacer = menu.addAction("Deshacer el último borrado  ·  Ctrl+Z")
            deshacer.triggered.connect(self._deshacer_borrado)
        menu.exec(self.tabla.viewport().mapToGlobal(punto))

    def _mandar_a_desgrabar(self) -> None:
        """Pone lo elegido en la cola de Desgrabar, sea del tipo que sea.

        La cola se armaba sola con lo que Whisper había transcripto, que es una
        pregunta sobre la máquina y no sobre la causa: un SMS donde el abonado
        toma roaming internacional, o un intento de comunicación a las tres de
        la mañana, quedaban afuera aunque fueran lo más importante del día.
        Acá lo decide una persona, de a una o de a quince.
        """
        filas = self._filas_seleccionadas()
        if not filas or self._caso_id is None:
            return
        registros = [r for r in (self._registro_de_fila(f) for f in filas) if r]
        if not registros:
            return

        # Reabrir algo ya cerrado borra la constancia de quién lo dio por
        # desgrabado: se pregunta antes, no después.
        cerradas = [r for r in registros if r["transcripcion_revisada"]]
        if cerradas:
            resp = QMessageBox.question(
                self, "Mandar a Desgrabar",
                f"{len(cerradas)} de las elegidas ya estaban dadas por "
                "desgrabadas.\n\nReabrirlas borra la constancia de quién las "
                "cerró y cuándo. ¿Mandarlas igual?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if resp != QMessageBox.Yes:
                registros = [r for r in registros if not r["transcripcion_revisada"]]
                if not registros:
                    return

        n = repo.mandar_a_desgrabar(self._con, [r["id"] for r in registros])
        repo.log_auditoria(
            self._con, "edito",
            f"{n} comunicación(es) mandada(s) a Desgrabar",
            self._caso_id,
        )
        self._con.commit()
        self.datos_cambiaron.emit()
        self.refrescar()
        QMessageBox.information(
            self, "Mandar a Desgrabar",
            f"{n} comunicación(es) en la mesa de trabajo.\n\n"
            "Se pueden escuchar, interpretar y cerrar desde Desgrabar, sin "
            "pasar por Whisper.",
        )

    def _eliminar_seleccionadas(self) -> None:
        """Manda a la papelera las comunicaciones elegidas, previa confirmación.

        El caso de uso es una carga equivocada: el mismo día importado dos
        veces desde carpetas distintas, o una entrega que no era de esta causa.
        No se borran: quedan en la papelera con todo su trabajo —transcripción,
        contexto, interés, marcas de audio— y vuelven enteras si hizo falta.
        """
        filas = self._filas_seleccionadas()
        if not filas or self._caso_id is None:
            return
        registros = [r for r in (self._registro_de_fila(f) for f in filas) if r]
        if not registros:
            return

        muestra = "\n".join(
            f"  · Nº {r['orden']}   {r['origen']} → {r['destino']}   "
            f"{r['fecha_inicio_texto'] or 's/fecha'}"
            for r in registros[:8]
        )
        if len(registros) > 8:
            muestra += f"\n  … y {len(registros) - 8} más"

        resp = QMessageBox.question(
            self,
            "Enviar a la papelera",
            f"Se van a sacar de la causa {len(registros)} comunicaciones:\n\n"
            f"{muestra}\n\n"
            "Van a la papelera con su transcripción, su contexto y sus marcas: "
            "se pueden restaurar enteras desde la pantalla Papelera, o acá "
            "mismo con Ctrl+Z.\n\n¿Continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return

        try:
            self._ultimo_lote = papelera.enviar(
                self._con, self._caso_id, [r["id"] for r in registros]
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"No se pudo eliminar:\n{exc}")
            return

        self.refrescar()
        self.datos_cambiaron.emit()
        self.lbl_status.setText(
            f"{len(registros)} comunicaciones en la papelera  ·  Ctrl+Z para deshacer"
        )

    def _deshacer_borrado(self) -> None:
        """Devuelve lo último que se mandó a la papelera (Ctrl+Z)."""
        if self._caso_id is None:
            return
        lote = self._ultimo_lote or papelera.ultimo_lote(self._con, self._caso_id)
        if not lote:
            self.lbl_status.setText("No hay nada reciente que deshacer")
            return
        resultado = papelera.restaurar_lote(self._con, self._caso_id, lote)
        self._ultimo_lote = ""
        self.refrescar()
        self.datos_cambiaron.emit()
        if resultado.ya_existentes:
            QMessageBox.information(
                self, "Papelera",
                f"{resultado.restauradas} restauradas.\n\n"
                f"{len(resultado.ya_existentes)} no se pudieron devolver porque "
                "la causa ya las tiene otra vez (se reimportaron mientras "
                "estaban en la papelera).",
            )
        self.lbl_status.setText(
            f"{resultado.restauradas} comunicaciones restauradas"
        )

    def _recargar_filas(self) -> None:
        """Relee los registros del caso y rehace el índice por id.

        Los dos van siempre juntos: `_por_id` es lo que traduce fila de la
        grilla a registro, y si queda con datos viejos la pantalla sigue
        andando pero decidiendo sobre el estado anterior —marcar como escuchado
        dejaba de alternar, por ejemplo—.
        """
        self._filas = repo.listar_registros(self._con, self._caso_id)
        self._por_id = {r["id"]: r for r in self._filas}

    def _registro_de_fila(self, fila: int) -> sqlite3.Row | None:
        """Registro de una fila de la grilla, por su id y no por su posición.

        Con la tabla ordenable, la fila 3 de la pantalla no es el cuarto
        registro de `self._filas`: el id viaja en la celda de Orden y es lo
        único que se mantiene válido al reordenar.
        """
        if fila < 0:
            return None
        item = self.tabla.item(fila, _COL_ORDEN)
        return self._por_id.get(item.data(Qt.UserRole)) if item else None

    def _fila_de_registro(self, registro_id: int) -> int:
        """Fila en la que está ese registro ahora mismo, o -1."""
        for fila in range(self.tabla.rowCount()):
            item = self.tabla.item(fila, _COL_ORDEN)
            if item is not None and item.data(Qt.UserRole) == registro_id:
                return fila
        return -1

    def _registro_seleccionado(self) -> sqlite3.Row | None:
        return self._registro_de_fila(self.tabla.currentRow())

    def _on_seleccion(self) -> None:
        r = self._registro_seleccionado()
        if r is None:
            return
        self.d_eyebrow.setText(f"REGISTRO Nº {r['orden']}")
        color = r["color_hex"] or tema.TEXT_DIM
        nombre = r["interesado"] or "—"
        self.d_nombre.setText(
            f'<span style="color:{color};">●</span> {nombre}'
        )
        self.d_od.setText(f"{r['origen'] or '—'} → {r['destino'] or '—'}")
        self._reconstruir_cuerpo(r)

    def _reconstruir_cuerpo(self, r: sqlite3.Row) -> None:
        # El panel se reconstruye entero: el reproductor anterior ya no existe.
        self._reproductor = None
        while self.d_cuerpo_lay.count():
            item = self.d_cuerpo_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if r["estado"] != "completo":
            self._agregar_alerta(r)

        if r["tipo"] == "sms":
            self._agregar_sms(r)
        else:
            self._agregar_reproduccion(r)
        self._agregar_contexto(r)
        self._agregar_corresponde_a(r)
        self._agregar_seccion(
            "UBICACIÓN / ANTENA",
            [
                ("Localidad", r["localidad"]),
                ("Provincia", r["provincia"]),
                ("Latitud", r["latitud"]),
                ("Longitud", r["longitud"]),
                ("Azimuth", r["azimuth"]),
                ("Radio cobertura", r["radio"]),
            ],
        )
        self.d_cuerpo_lay.addStretch(1)

    def _agregar_sms(self, r: sqlite3.Row) -> None:
        caja = QLabel("✉  Mensaje de texto (SMS)")
        caja.setStyleSheet(
            f"background: rgba(144,133,201,0.16); border:1px solid {tema.VIOLET};"
            f"border-radius:8px; padding:8px 10px; color:{tema.VIOLET}; font-weight:600;"
        )
        self.d_cuerpo_lay.addWidget(caja)

    def _agregar_reproduccion(self, r: sqlite3.Row) -> None:
        lbl = QLabel("REPRODUCCIÓN")
        lbl.setObjectName("seccion")
        lbl.setStyleSheet(f"color:{tema.TEXT_DIM}; margin-top:8px;")
        self.d_cuerpo_lay.addWidget(lbl)

        archivo = r["archivo_audio"] or "—"
        lbl_arch = QLabel(archivo)
        lbl_arch.setWordWrap(True)
        lbl_arch.setStyleSheet(
            f"color:{tema.TEXT_MUTED}; font-family:'IBM Plex Mono','Consolas',monospace;"
            "font-size:11px;"
        )
        self.d_cuerpo_lay.addWidget(lbl_arch)

        if r["estado"] == "audio_faltante" or not r["archivo_audio"]:
            return

        rid = r["id"]
        ruta = self._localizar_audio(r["archivo_audio"])

        if ruta is None:
            aviso = QLabel(
                "Audio no localizado: la carpeta usada en la importación no "
                "está disponible."
            )
            aviso.setWordWrap(True)
            aviso.setStyleSheet(f"color:{tema.TEXT_DIM}; font-style:italic;")
            self.d_cuerpo_lay.addWidget(aviso)
        else:
            reproductor = ReproductorAudio()
            self._reproductor = reproductor
            # El atajo lo define esta pantalla, no el reproductor, pero el
            # usuario lo busca en el botón de play.
            reproductor.btn_play.setToolTip("Reproducir / pausar  ·  Ctrl+Espacio")
            reproductor.cargar(ruta)
            reproductor.duracion_conocida.connect(
                lambda seg, _r=r: self._guardar_duracion(_r, seg)
            )
            reproductor.reproduccion_terminada.connect(
                lambda _rid=rid: self._marcar_escuchado(_rid, True)
            )
            self.d_cuerpo_lay.addWidget(reproductor)
            self._agregar_otra_captura(r, reproductor, lbl_arch)

            fila_acciones = QHBoxLayout()
            btn_abrir = QPushButton("Abrir externo")
            btn_abrir.setToolTip("Abrir con el reproductor del sistema")
            btn_abrir.clicked.connect(
                lambda _=False, _ruta=ruta: os.startfile(str(_ruta))
            )
            btn_marca = QPushButton("⚑ Marcar momento")
            btn_marca.setToolTip(
                "Guarda una marca en el instante actual de la reproducción"
            )
            btn_marca.clicked.connect(
                lambda _=False, _rid=rid, _rep=reproductor: self._agregar_marca(
                    _rid, _rep
                )
            )
            cont_acciones = QWidget()
            fila_acciones.setContentsMargins(0, 0, 0, 0)
            fila_acciones.addWidget(btn_marca, 1)
            fila_acciones.addWidget(btn_abrir)
            cont_acciones.setLayout(fila_acciones)
            self.d_cuerpo_lay.addWidget(cont_acciones)

            # Contenedor de la lista de marcas (se repuebla sin tocar el player).
            self._marcas_widget = QWidget()
            self._marcas_lay = QVBoxLayout(self._marcas_widget)
            self._marcas_lay.setContentsMargins(0, 0, 0, 0)
            self._marcas_lay.setSpacing(2)
            self.d_cuerpo_lay.addWidget(self._marcas_widget)
            self._poblar_marcas(rid, reproductor)

        self.btn_escuchado = QPushButton()
        self.btn_escuchado.setCheckable(True)
        self.btn_escuchado.setToolTip("Marcar / desmarcar como escuchado  ·  Ctrl+E")
        self._pintar_boton_escuchado(bool(r["escuchado"]))
        self.btn_escuchado.clicked.connect(
            lambda marcado, _rid=rid: self._marcar_escuchado(_rid, marcado)
        )
        self.d_cuerpo_lay.addWidget(self.btn_escuchado)

        # De interés se decide ACÁ, escuchando, no volviendo a la grilla. Es la
        # conclusión que se saca en el mismo momento que «escuchado», y tenerla
        # en otra pantalla partía en dos una sola decisión.
        self.chk_interes = QCheckBox("Comunicación de interés")
        self.chk_interes.setChecked(self._esta_de_interes(rid, r))
        self.chk_interes.setToolTip(
            "Lo que se marca acá es lo que se transcribe y lo que entra al "
            "informe judicial, que habla de «cada archivo considerado de "
            "interés».  ·  Tecla I con la grilla enfocada"
        )
        self.chk_interes.toggled.connect(
            lambda ok, _rid=rid: self._marcar_interes_desde_el_panel(_rid, ok)
        )
        self.d_cuerpo_lay.addWidget(self.chk_interes)

    def _pintar_boton_escuchado(self, escuchado: bool) -> None:
        self.btn_escuchado.setChecked(escuchado)
        self.btn_escuchado.setText(
            "✓ Escuchado" if escuchado else "Marcar como escuchado"
        )
        self.btn_escuchado.setStyleSheet(
            f"color:{tema.TEAL}; border-color:{tema.TEAL};" if escuchado else ""
        )

    def _agregar_otra_captura(self, r: sqlite3.Row, reproductor: ReproductorAudio,
                              lbl_archivo: QLabel) -> None:
        """Botón para pasar a la otra grabación de la misma comunicación.

        Cuando las dos líneas estaban intervenidas, la prestadora entrega la
        misma llamada dos veces. Es una sola comunicación —una sola fila— pero
        son dos audios, y muchas veces uno se escucha bastante mejor: el que
        grabó la central más cercana. Antes el segundo se descartaba al
        importar y no había forma de llegar a él.
        """
        if "audio_alternativo" not in r.keys() or not r["audio_alternativo"]:
            return

        capturas = [r["archivo_audio"], r["audio_alternativo"]]
        estado = {"actual": 0}

        boton = QPushButton("⇄  Otra captura de esta comunicación")
        boton.setToolTip(
            "La misma llamada, grabada desde la otra línea intervenida. "
            "Suele escucharse distinto."
        )

        def alternar() -> None:
            estado["actual"] = 1 - estado["actual"]
            nombre = capturas[estado["actual"]]
            ruta = self._localizar_audio(nombre)
            if ruta is None:
                QMessageBox.warning(
                    self, "Audio", f"No encontré el archivo:\n{nombre}"
                )
                estado["actual"] = 1 - estado["actual"]
                return
            reproductor.cargar(ruta)
            lbl_archivo.setText(f"{nombre}   (captura {estado['actual'] + 1} de 2)")

        boton.clicked.connect(alternar)
        self.d_cuerpo_lay.addWidget(boton)
        lbl_archivo.setText(f"{capturas[0]}   (captura 1 de 2)")

    def _marcar_escuchado(self, registro_id: int, escuchado: bool) -> None:
        repo.marcar_escuchado(self._con, registro_id, escuchado)
        self._con.commit()
        self._recargar_filas()
        seleccionado = self._registro_seleccionado()
        if (
            hasattr(self, "btn_escuchado")
            and seleccionado is not None
            and seleccionado["id"] == registro_id
        ):
            self._pintar_boton_escuchado(escuchado)
        self._actualizar_celda(
            registro_id, _COL_ESCUCHADO, "✓" if escuchado else "",
            color=tema.TEAL if escuchado else None, centrado=True,
        )
        self._aplicar_filtros()

    def _guardar_duracion(self, r: sqlite3.Row, segundos: float) -> None:
        if r["duracion_seg"] or segundos <= 0:
            return
        repo.guardar_duracion(self._con, r["id"], segundos)
        self._con.commit()
        self._recargar_filas()
        self._actualizar_celda(r["id"], _COL_DURACION, _formato_mmss(segundos))

    def _actualizar_celda(
        self, registro_id: int, col: int, texto: str,
        color: str | None = None, centrado: bool = False,
    ) -> None:
        fila = self._fila_de_registro(registro_id)
        if fila < 0:
            return
        item = self.tabla.item(fila, col)
        if item is None:
            item = _Celda()
            self.tabla.setItem(fila, col, item)
        item.setText(texto)
        if color:
            item.setForeground(QColor(color))
        if centrado:
            item.setTextAlignment(Qt.AlignCenter)

    # ------------------------- marcas de audio -----------------------------
    def _poblar_marcas(self, registro_id: int, reproductor: ReproductorAudio) -> None:
        while self._marcas_lay.count():
            item = self._marcas_lay.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        marcas = repo.listar_marcas_audio(self._con, registro_id)
        reproductor.set_marcas([m["segundo"] for m in marcas])
        for m in marcas:
            fila = QWidget()
            flay = QHBoxLayout(fila)
            flay.setContentsMargins(0, 0, 0, 0)
            flay.setSpacing(6)

            btn_ir = QPushButton(_formato_mmss(m["segundo"]))
            btn_ir.setFixedWidth(52)
            btn_ir.setToolTip("Saltar a este momento")
            btn_ir.setStyleSheet(
                f"color:{tema.ACCENT}; font-family:'IBM Plex Mono','Consolas',monospace;"
                "font-size:11px; padding:2px 4px;"
            )
            btn_ir.clicked.connect(
                lambda _=False, _s=m["segundo"], _rep=reproductor: _rep.saltar_a(_s)
            )
            flay.addWidget(btn_ir)

            lbl = QLabel(m["nota"] or "(sin nota)")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"color:{tema.TEXT_PRIMARY}; font-size:11px;")
            flay.addWidget(lbl, 1)

            btn_x = QPushButton("✕")
            btn_x.setFixedWidth(26)
            btn_x.setToolTip("Borrar marca")
            btn_x.setStyleSheet("padding:2px 4px; font-size:10px;")
            btn_x.clicked.connect(
                lambda _=False, _id=m["id"], _rid=registro_id, _rep=reproductor:
                self._borrar_marca(_id, _rid, _rep)
            )
            flay.addWidget(btn_x)

            self._marcas_lay.addWidget(fila)

    def _agregar_marca(self, registro_id: int, reproductor: ReproductorAudio) -> None:
        segundo = reproductor.posicion_actual_seg()
        nota, ok = QInputDialog.getText(
            self,
            "Marcar momento",
            f"Nota para la marca en {_formato_mmss(segundo)}:",
        )
        if not ok:
            return
        repo.crear_marca_audio(self._con, registro_id, segundo, nota.strip())
        repo.log_auditoria(
            self._con, "edito",
            f"Marca de audio en registro #{registro_id} ({_formato_mmss(segundo)}): "
            f"{nota.strip()}",
            self._caso_id,
        )
        self._con.commit()
        self._poblar_marcas(registro_id, reproductor)

    def _borrar_marca(
        self, marca_id: int, registro_id: int, reproductor: ReproductorAudio
    ) -> None:
        repo.borrar_marca_audio(self._con, marca_id)
        self._con.commit()
        self._poblar_marcas(registro_id, reproductor)

    def _localizar_audio(self, nombre: str) -> Path | None:
        """Busca el audio por nombre bajo las rutas usadas en las importaciones."""
        return audios.localizar(self._con, self._caso_id, nombre)

    def _agregar_contexto(self, r: sqlite3.Row) -> None:
        es_sms = r["tipo"] == "sms"
        lbl = QLabel(
            "CONTEXTO / CONTENIDO DEL MENSAJE" if es_sms
            else "CONTEXTO / TRANSCRIPCIÓN"
        )
        lbl.setObjectName("seccion")
        lbl.setStyleSheet(f"color:{tema.TEXT_DIM}; margin-top:8px;")
        self.d_cuerpo_lay.addWidget(lbl)

        rid = r["id"]

        combo = QComboBox()
        combo.setEditable(True)
        opciones = list(self._contextos)
        actual = r["contexto"] or ""
        if actual and actual not in opciones:
            opciones.insert(0, actual)
        combo.addItems(opciones)
        combo.setCurrentText(actual)
        combo.lineEdit().setPlaceholderText("Contexto (elegir o escribir)")
        # Se guarda al confirmar (Enter / perder foco / elegir opción), no por tecla.
        combo.lineEdit().editingFinished.connect(
            lambda _rid=rid, _c=combo: self._guardar_contexto(_rid, _c.currentText())
        )
        combo.activated.connect(
            lambda _i, _rid=rid, _c=combo: self._guardar_contexto(_rid, _c.currentText())
        )
        self.d_cuerpo_lay.addWidget(combo)

        # Con tiempos de Whisper la transcripción es navegable; sin ellos
        # (TXT importado, carga manual, transcripciones viejas) se sigue
        # editando como texto libre.
        segmentos = repo.segmentos_de_registro(r)
        editor: QTextEdit | None = None
        if segmentos and not es_sms:
            sincro = TranscripcionSincronizada(segmentos)
            if self._reproductor is not None:
                sincro.saltar_a.connect(self._reproductor.saltar_a)
                self._reproductor.posicion_cambiada.connect(sincro.resaltar_en)
            sincro.segmentos_editados.connect(
                lambda segs, _rid=rid: self._guardar_segmentos(_rid, segs)
            )
            self.d_cuerpo_lay.addWidget(sincro)
        else:
            editor = QTextEdit()
            editor.setPlaceholderText(
                "Transcripción / notas de la escucha (texto libre)..."
            )
            editor.setPlainText(r["transcripcion"] or "")
            editor.setFixedHeight(120)
            self.d_cuerpo_lay.addWidget(editor)

            btn = QPushButton("Guardar transcripción")
            btn.clicked.connect(
                lambda _=False, _rid=rid, _e=editor: self._guardar_transcripcion(
                    _rid, _e.toPlainText()
                )
            )
            self.d_cuerpo_lay.addWidget(btn)

        # Control humano: marcar la transcripción como revisada por el analista.
        # No aplica a SMS (el texto lo provee la prestadora, no una IA).
        if not es_sms:
            chk_rev = QCheckBox("Transcripción revisada por el analista")
            chk_rev.setChecked(bool(r["transcripcion_revisada"]))
            chk_rev.setToolTip(
                "Marca que revisaste y corregiste el texto. El informe judicial "
                "avisa si hay transcripciones sin revisar."
            )
            chk_rev.toggled.connect(
                lambda ok, _rid=rid: self._marcar_revisada(_rid, ok)
            )
            self.d_cuerpo_lay.addWidget(chk_rev)

        if r["estado"] != "audio_faltante" and r["archivo_audio"]:
            btn_auto = QPushButton("🎙 Transcribir con Whisper")
            btn_auto.setToolTip(
                "Transcripción automática local; el resultado queda en el "
                "editor y se puede corregir"
            )
            btn_auto.clicked.connect(
                lambda _=False, _r=r, _b=btn_auto:
                self._transcribir_individual(_r, _b)
            )
            self.d_cuerpo_lay.addWidget(btn_auto)

    def _marcar_revisada(self, registro_id: int, revisada: bool) -> None:
        repo.marcar_transcripcion_revisada(self._con, registro_id, revisada)
        repo.log_auditoria(
            self._con, "edito",
            f"Registro #{registro_id}: transcripción "
            f"{'revisada' if revisada else 'marcada sin revisar'}",
            self._caso_id,
        )
        self._con.commit()
        # Actualizar la fila cacheada y el indicador de la columna Rev.
        self._recargar_filas()
        fila = self._fila_de_registro(registro_id)
        item = self.tabla.item(fila, _COL_REVISADA) if fila >= 0 else None
        if item is not None:
            item.setText("✓" if revisada else "⚠")
            item.setForeground(QColor(tema.TEAL if revisada else tema.ACCENT))
            item.setTextAlignment(Qt.AlignCenter)
        self.datos_cambiaron.emit()

    def _guardar_contexto(self, registro_id: int, valor: str) -> None:
        self._editar(registro_id, "contexto", valor.strip())
        # Reflejar en el combo de la grilla sin repoblar todo.
        fila = self._fila_de_registro(registro_id)
        item = self.tabla.item(fila, _COL_CONTEXTO) if fila >= 0 else None
        if item is not None:
            item.setText(valor)
            item.setData(Qt.UserRole + 2, valor)

    # ---------------------- transcripción automática -----------------------
    def _pendientes_transcripcion(
        self, solo_marcadas: bool = True
    ) -> tuple[list[tuple[int, int, object]], int]:
        """Audios a transcribir: (registro_id, orden, ruta), y cuántos faltan en disco.

        Por defecto solo las marcadas DE INTERÉS. Transcribir una causa entera
        son horas de máquina y la mayor parte del material no va a ningún lado:
        el investigador escucha, marca lo que sirve, y se transcribe eso. Es
        además el mismo conjunto del que habla el informe judicial —"cada
        archivo considerado de interés"—, así que las dos puntas coinciden.
        """
        pendientes = []
        sin_archivo = 0
        for r in self._filas:
            if r["estado"] == "audio_faltante" or not r["archivo_audio"]:
                continue
            if solo_marcadas and (r["nivel_interes"] or "ninguno") == "ninguno":
                continue
            if (r["transcripcion"] or "").strip():
                continue
            ruta = self._localizar_audio(r["archivo_audio"])
            if ruta is None:
                sin_archivo += 1
                continue
            pendientes.append((r["id"], r["orden"], ruta))
        return pendientes, sin_archivo

    def _transcribir_lote(self) -> None:
        if self._caso_id is None:
            return
        recursos = svc_transcripcion.localizar_recursos()
        if not recursos.disponible:
            QMessageBox.warning(
                self, "Transcripción",
                "No se puede transcribir. Falta: "
                + ", ".join(recursos.faltantes())
                + "\n\nVer configuración en app/config.py "
                "(RUTA_MODELO_WHISPER, RUTA_FFMPEG, PYTHON_WHISPER).",
            )
            return
        pendientes, sin_archivo = self._pendientes_transcripcion()
        if not pendientes:
            sueltas, _ = self._pendientes_transcripcion(solo_marcadas=False)
            if sueltas:
                resp = QMessageBox.question(
                    self, "Transcripción",
                    "No hay comunicaciones marcadas de interés sin transcribir."
                    "\n\n"
                    f"Hay {len(sueltas)} sin marcar y sin transcripción; "
                    "transcribirlas todas puede llevar horas.\n\n"
                    "¿Transcribirlas igual?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                if resp != QMessageBox.Yes:
                    return
                pendientes = sueltas
            else:
                mensaje = "No hay audios pendientes de transcripción."
                if sin_archivo:
                    mensaje += f"\n({sin_archivo} audios no se localizaron en disco.)"
                QMessageBox.information(self, "Transcripción", mensaje)
                return
        if sin_archivo:
            QMessageBox.information(
                self, "Transcripción",
                f"{sin_archivo} audios no se localizaron en disco y van a "
                "quedar fuera del lote.",
            )
        dlg = DialogoTranscribirLote(
            pendientes, self._aplicar_transcripcion, self,
            vocabulario=repo.vocabulario_causa(self._con, self._caso_id),
        )
        dlg.exec()
        self.refrescar()
        self.datos_cambiaron.emit()

    def _aplicar_transcripcion(
        self, registro_id: int, texto: str, duracion: float,
        segmentos: list[dict] | None = None,
    ) -> None:
        """Persiste una transcripción automática (con historial) y la duración."""
        edicion.editar_campo(
            self._con, registro_id, "transcripcion", texto, usuario="whisper"
        )
        repo.guardar_segmentos_transcripcion(self._con, registro_id, segmentos)
        if duracion:
            reg = repo.obtener_registro(self._con, registro_id)
            if reg is not None and not reg["duracion_seg"]:
                repo.guardar_duracion(self._con, registro_id, duracion)
                self._con.commit()

    def _transcribir_individual(self, r: sqlite3.Row, btn: QPushButton) -> None:
        ruta = self._localizar_audio(r["archivo_audio"])
        if ruta is None:
            QMessageBox.warning(
                self, "Transcripción",
                f"No encontré el archivo de audio:\n{r['archivo_audio']}",
            )
            return
        btn.setEnabled(False)
        btn.setText("Transcribiendo... (puede demorar)")

        proc = ProcesoTranscripcion(self)
        self._proc_individual = proc  # evitar GC mientras corre
        rid = r["id"]

        def al_resultado(obj: dict) -> None:
            if not obj.get("ok"):
                QMessageBox.warning(
                    self, "Transcripción", f"Falló: {obj.get('error', '')}"
                )
                return
            segmentos = svc_transcripcion.normalizar_segmentos(obj.get("segmentos"))
            texto = (
                svc_transcripcion.texto_de_segmentos(segmentos) if segmentos
                else svc_transcripcion.normalizar_transcripcion(obj.get("texto", ""))
            )
            self._aplicar_transcripcion(
                rid, texto, obj.get("duracion") or 0.0, segmentos
            )
            self._recargar_filas()
            self.datos_cambiaron.emit()
            # Si el registro sigue seleccionado, rehacer el panel: con los
            # tiempos recién guardados pasa a mostrarse la vista sincronizada.
            actual = self._registro_seleccionado()
            if actual is not None and actual["id"] == rid:
                self._reconstruir_cuerpo(actual)

        def al_terminar(_n: int) -> None:
            try:
                btn.setEnabled(True)
                btn.setText("🎙 Transcribir con Whisper")
            except RuntimeError:
                pass  # el panel se reconstruyó y el botón ya no existe

        proc.resultado.connect(al_resultado)
        proc.terminado.connect(al_terminar)
        proc.fallo.connect(
            lambda m: QMessageBox.warning(self, "Transcripción", m)
        )
        proc.iniciar([ruta], repo.vocabulario_causa(self._con, self._caso_id))

    def _guardar_segmentos(self, registro_id: int, segmentos: list[dict]) -> None:
        """Guarda una corrección hecha sobre una frase de la vista sincronizada.

        Los segmentos son la fuente de verdad de esa vista, pero el campo
        `transcripcion` sigue siendo el que se exporta y el que busca el filtro:
        se regenera a partir de ellos para que no queden en desacuerdo.
        """
        repo.guardar_segmentos_transcripcion(self._con, registro_id, segmentos)
        self._guardar_transcripcion(
            registro_id, svc_transcripcion.texto_de_segmentos(segmentos)
        )
        self._con.commit()

    def _guardar_transcripcion(self, registro_id: int, texto: str) -> None:
        try:
            cambio = edicion.editar_campo(
                self._con, registro_id, "transcripcion", texto.strip()
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Edición", f"No se pudo guardar:\n{exc}")
            return
        if cambio:
            self._recargar_filas()
            self.datos_cambiaron.emit()

    def _agregar_corresponde_a(self, r: sqlite3.Row) -> None:
        lbl = QLabel("CORRESPONDE A")
        lbl.setObjectName("seccion")
        lbl.setStyleSheet(f"color:{tema.TEXT_DIM}; margin-top:8px;")
        self.d_cuerpo_lay.addWidget(lbl)

        edit = QLineEdit(r["corresponde_a"] if r["corresponde_a"] != "NO IDENTIFICADO" else "")
        edit.setPlaceholderText("sin asignar")
        rid = r["id"]
        edit.editingFinished.connect(
            lambda _rid=rid, _e=edit: self._editar(_rid, "corresponde_a", _e.text().strip() or "NO IDENTIFICADO")
        )
        self.d_cuerpo_lay.addWidget(edit)

        btn = QPushButton("Recordar para futuros registros")
        btn.clicked.connect(lambda _=False, _r=r, _e=edit: self._recordar(_r, _e.text().strip()))
        self.d_cuerpo_lay.addWidget(btn)

    def _numero_a_recordar(self, r: sqlite3.Row) -> str:
        """A qué número se le está poniendo nombre acá.

        Es el del INTERLOCUTOR: cuando el analista escribe "Marcos Rivas" está
        nombrando a la persona del otro lado, no a la línea intervenida. Antes
        se tomaba el origen sin mirar, así que en una SALIENTE el nombre iba a
        parar a la línea pinchada —el propio investigado quedaba registrado con
        el nombre de su interlocutor— y la columna Interlocutor no cambiaba,
        porque el nombre se había guardado bajo el número equivocado.
        """
        numero = numero_del_interlocutor(
            r["origen"] or "", r["destino"] or "",
            r["abonado_intervenido"] or "", r["direccion"] or "",
        )
        if numero:
            return numero
        # Sin saber cuál es la otra punta se cae al comportamiento de siempre.
        origen = r["origen"] or ""
        return origen if origen and origen != "NO IDENTIFICADO" else (r["destino"] or "")

    def _recordar(self, r: sqlite3.Row, nombre: str) -> None:
        numero = self._numero_a_recordar(r)
        if not nombre or not numero or numero == "NO IDENTIFICADO":
            QMessageBox.information(
                self, "Memoria", "Necesito un nombre y un número de abonado válido."
            )
            return
        resp = QMessageBox.question(
            self,
            "Aplicar a registros existentes",
            f"Se va a recordar que el número {numero} corresponde a "
            f"«{nombre}».\n\n¿Aplicar también a las comunicaciones ya cargadas "
            "con ese número?",
            QMessageBox.Yes | QMessageBox.No,
        )
        aplicar = resp == QMessageBox.Yes
        n = memoria.guardar(
            self._con, self._caso_id, numero, nombre, "caso", aplicar_a_existentes=aplicar
        )
        # La memoria alimenta la columna Interlocutor, que está guardada en
        # cada comunicación: sin esto el nombre quedaba en la memoria y la
        # grilla seguía mostrando el número.
        tocadas = repo.recalcular_nombres(self._con, self._caso_id)
        self._con.commit()
        self.refrescar()
        self.datos_cambiaron.emit()
        QMessageBox.information(
            self, "Memoria",
            f"El número {numero} queda registrado como «{nombre}».\n\n"
            f"Columna Interlocutor: {tocadas} comunicaciones actualizadas.\n"
            f"Campo «Corresponde a»: {n} actualizadas.",
        )

    def _agregar_alerta(self, r: sqlite3.Row) -> None:
        caja = QLabel(
            "⚠ Registro incompleto: "
            + ("audio no disponible." if r["estado"] == "audio_faltante"
               else "sin transcripción .txt; metadatos no disponibles.")
        )
        caja.setWordWrap(True)
        caja.setStyleSheet(
            f"background: rgba(201,96,90,0.16); border:1px solid {tema.DANGER};"
            f"border-radius:8px; padding:10px; color:{tema.DANGER};"
        )
        self.d_cuerpo_lay.addWidget(caja)

    def _agregar_seccion(self, titulo: str, campos: list[tuple[str, str]]) -> None:
        lbl = QLabel(titulo)
        lbl.setObjectName("seccion")
        lbl.setStyleSheet(f"color:{tema.TEXT_DIM}; margin-top:8px;")
        self.d_cuerpo_lay.addWidget(lbl)
        for clave, valor in campos:
            fila = QWidget()
            flay = QHBoxLayout(fila)
            flay.setContentsMargins(0, 2, 0, 2)
            k = QLabel(clave)
            k.setStyleSheet(f"color:{tema.TEXT_DIM};")
            vacio = not valor or valor in ("—", "NO IDENTIFICADO")
            v = QLabel(valor if not vacio else "sin datos")
            v.setStyleSheet(
                f"color:{tema.TEXT_DIM}; font-style:italic;"
                if vacio
                else f"color:{tema.TEXT_PRIMARY};"
            )
            v.setAlignment(Qt.AlignRight)
            v.setWordWrap(True)
            flay.addWidget(k)
            flay.addStretch(1)
            flay.addWidget(v)
            self.d_cuerpo_lay.addWidget(fila)

    # -------------------------- exportación --------------------------------
    def _exportar_excel(self) -> None:
        if self._caso_id is None:
            return
        caso = repo.obtener_caso(self._con, self._caso_id)
        sugerido = f"{(caso['nombre'] if caso else 'caso')}.xlsx".replace("/", "-")
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Exportar a Excel", sugerido, "Excel (*.xlsx)"
        )
        if not ruta:
            return
        try:
            destino = exportar_caso_a_excel(self._con, self._caso_id, ruta)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"No se pudo exportar:\n{exc}")
            return
        mostrar_exportacion(self, destino, "Exportar a Excel")

    def _exportar_judicial(self) -> None:
        if self._caso_id is None:
            return
        caso = repo.obtener_caso(self._con, self._caso_id)
        nombre_caso = caso["nombre"] if caso else "caso"

        # Control humano: avisar si hay transcripciones de IA sin revisar.
        sin_revisar = repo.contar_transcripciones_sin_revisar(
            self._con, self._caso_id
        )
        if sin_revisar:
            resp = QMessageBox.warning(
                self,
                "Transcripciones sin revisar",
                f"Hay {sin_revisar} transcripción(es) automática(s) SIN revisar "
                "por el analista.\n\nLas transcripciones de Whisper pueden "
                "contener errores. Se recomienda revisarlas antes de generar un "
                "informe judicial.\n\n¿Generar el informe de todos modos?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if resp != QMessageBox.Yes:
                return

        # El número de CD y su identificador salen del DatosCausa.txt de cada
        # entrega, guardado al importar: acá solo se elige cuáles entran y se
        # completa la fecha de recepción, que no viene en ningún archivo.
        entregas = repo.listar_cds(self._con, self._caso_id)
        dlg = DialogoInformeJudicial(entregas, self)
        if dlg.exec() != QDialog.Accepted:
            return

        sugerido = f"Informe_judicial_{nombre_caso}.docx".replace("/", "-")
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Exportar informe judicial", sugerido, "Word (*.docx)"
        )
        if not ruta:
            return
        try:
            destino = exportar_informe_judicial(
                self._con, self._caso_id, ruta,
                cds=dlg.seleccionados or None,
                solo_interes=dlg.solo_interes,
                fecha_recepcion=dlg.fecha_recepcion,
            )
        except InformeVacio as exc:
            QMessageBox.information(self, "Informe judicial", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"No se pudo exportar:\n{exc}")
            return
        mostrar_exportacion(self, destino, "Informe judicial")
