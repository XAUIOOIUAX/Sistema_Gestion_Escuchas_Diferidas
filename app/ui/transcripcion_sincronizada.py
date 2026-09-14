"""Transcripción navegable: cada frase sabe en qué segundo del audio se dijo.

Whisper devuelve la transcripción partida en segmentos con tiempos. Guardando
esos tiempos (columna `Registro.transcripcion_segmentos`) el texto deja de ser
un bloque plano y pasa a ser un índice del audio: se hace clic en una frase y
la escucha salta a ese momento, y mientras suena se resalta la frase que se
está oyendo.

Es la diferencia entre buscar a mano dónde se dijo algo e ir directo. En
escuchas de veinte minutos, esa búsqueda es la mayor parte del trabajo.

Sobre esa lista se corrige. Whisper no se equivoca de una sola manera: se
saltea pasajes (los encimados, los que se escuchan mal), mete en un mismo
renglón a dos personas que se responden, parte una sola frase en tres, y a
veces inventa donde no hay nada. Cada una de esas fallas necesita una
operación distinta —agregar arriba, agregar abajo, dividir, unir, quitar— y
todas están en el menú del botón derecho de la frase, más los atajos del
editor. Sin eso, la corrección terminaba haciéndose en el Word exportado y se
perdía en la exportación siguiente.

Los registros sin segmentos (importados de TXT, cargados a mano, transcriptos
antes de esta versión) siguen usando el editor de texto libre de siempre: esta
vista solo aparece cuando hay tiempos que aprovechar.
"""

from __future__ import annotations

from contextlib import contextmanager

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.servicios.transcripcion import (
    HABLANTES,
    esta_anclado,
    numerar_por_hablante,
)
from app.ui import tema

# Duración que se le da a una frase agregada a mano cuando no hay una vecina
# que acote el hueco. Dos segundos es lo que dura una frase corta de teléfono.
_DURACION_NUEVA = 2.0


def formato_mmss(segundos: float) -> str:
    segundos = max(0, int(segundos))
    return f"{segundos // 60}:{segundos % 60:02d}"


def segundos_de(texto: str) -> float | None:
    """Lee un minuto escrito a mano: "1:07", "67", "1:07.5". None si no se entiende.

    Se acepta el segundo suelto además del m:ss porque al corregir un desfasaje
    chico ("está dos segundos tarde") es lo que uno tiene en la cabeza.
    """
    texto = (texto or "").strip().replace(",", ".")
    if not texto:
        return None
    partes = texto.split(":")
    if len(partes) > 2:
        return None
    try:
        if len(partes) == 1:
            total = float(partes[0])
        else:
            minutos, segundos = partes
            if not minutos.strip().lstrip("-").isdigit():
                return None
            total = int(minutos) * 60 + float(segundos)
    except ValueError:
        return None
    return max(0.0, round(total, 2))


class _EditorFrase(QLineEdit):
    """El editor de una frase, con los atajos de corrección seguida.

    Corregir una transcripción es pasar por todas las frases, no por una.
    Con solo el doble clic había que volver al mouse en cada renglón; Enter
    baja a la siguiente y deja las dos manos en el teclado. Ctrl+Enter parte la
    frase donde está el cursor, que es como se separa a dos personas que
    Whisper metió en el mismo renglón.
    """

    cancelado = Signal()
    dividido = Signal(int)     # posición del cursor donde partir
    nueva_abajo = Signal()     # Shift+Enter: cerrar esta y abrir una nueva

    def keyPressEvent(self, event) -> None:  # noqa: N802 (API de Qt)
        if event.key() == Qt.Key_Escape:
            self.cancelado.emit()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ControlModifier:
                self.dividido.emit(self.cursorPosition())
                return
            if event.modifiers() & Qt.ShiftModifier:
                self.nueva_abajo.emit()
                return
        super().keyPressEvent(event)


class _Linea(QFrame):
    """Una frase: su minuto, su texto, y la corrección in situ del texto."""

    saltar = Signal(float)
    editada = Signal(int, str)      # (índice, texto nuevo)
    atribuida = Signal(int, str)    # (índice, hablante "1" / "2" / "")
    insertar = Signal(int, str)     # (índice, "arriba" | "abajo")
    quitar = Signal(int)            # sacar esta frase
    dividir = Signal(int, str, str)  # (índice, texto de arriba, texto de abajo)
    unir = Signal(int)              # unir esta frase con la de arriba
    aviso = Signal(str)             # algo que el analista tiene que saber
    reubicada = Signal(int, float)  # (índice, segundo nuevo de la frase)
    anclar = Signal(int)            # poner la frase donde está sonando el audio
    confirmada = Signal(int)        # Enter: se cerró esta frase
    tomada = Signal(int)            # un clic: esta pasa a ser la del foco

    def __init__(self, indice: int, segmento: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._indice = indice
        self._inicio = float(segmento.get("inicio") or 0.0)
        self._anclado = esta_anclado(segmento)
        self._texto = str(segmento.get("texto") or "")
        self._hablante = str(segmento.get("hablante") or "").strip()
        self._heredado = ""
        self._alternado = False
        self._rotulos: dict[str, str] = {}
        self._activa = False
        self._en_foco = False
        self.setCursor(Qt.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(8)

        # Quién habla. El informe judicial numera cada renglón con "1." (el que
        # llama) o "2." (el que atiende); hasta ahora eso se alternaba a ciegas.
        # Un clic cicla 1 -> 2 -> sin atribuir, mientras se escucha.
        self.btn_hablante = QPushButton()
        self.btn_hablante.setFixedWidth(22)
        self.btn_hablante.setObjectName("hablante")
        self.btn_hablante.setCursor(Qt.PointingHandCursor)
        self.btn_hablante.clicked.connect(self._ciclar_hablante)
        lay.addWidget(self.btn_hablante)

        # El minuto también se corrige. Whisper lo calcula sobre el audio, así
        # que suele estar bien, pero una frase agregada a mano hereda un tiempo
        # interpolado entre sus vecinas: sirve para no desordenar la lista, no
        # para saltar al lugar exacto donde se dijo.
        self.lbl_tiempo = QLabel(formato_mmss(self._inicio))
        self.lbl_tiempo.setFixedWidth(34)
        self.lbl_tiempo.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._pintar_tiempo()
        lay.addWidget(self.lbl_tiempo)

        self.editor_tiempo = _EditorFrase(formato_mmss(self._inicio))
        self.editor_tiempo.hide()
        self.editor_tiempo.setFixedWidth(44)
        self.editor_tiempo.setToolTip("Minutos:segundos, o los segundos sueltos")
        self.editor_tiempo.editingFinished.connect(self._confirmar_tiempo)
        self.editor_tiempo.cancelado.connect(self._cancelar_tiempo)
        lay.addWidget(self.editor_tiempo)

        self.lbl_texto = QLabel(self._texto or "(frase vacía — doble clic para escribirla)")
        self.lbl_texto.setWordWrap(True)
        lay.addWidget(self.lbl_texto, 1)

        # El editor ocupa el lugar del texto solo mientras se corrige la frase.
        self.editor = _EditorFrase(self._texto)
        self.editor.hide()
        self.editor.setToolTip(
            "Enter: guardar y pasar a la siguiente  ·  Ctrl+Enter: partir la "
            "frase acá  ·  Esc: descartar el cambio"
        )
        self.editor.editingFinished.connect(self._confirmar)
        self.editor.cancelado.connect(self._cancelar)
        self.editor.dividido.connect(self._dividir_en)
        self.editor.nueva_abajo.connect(self._cerrar_y_seguir)
        lay.addWidget(self.editor, 1)

        self._pintar()
        self._pintar_hablante()

    # ------------------------------------------------------------------
    @property
    def inicio(self) -> float:
        return self._inicio

    def texto(self) -> str:
        return self._texto

    def hablante(self) -> str:
        return self._hablante

    def _ciclar_hablante(self) -> None:
        siguiente = {"": "1", "1": "2", "2": ""}
        self._hablante = siguiente[self._hablante]
        self._pintar_hablante()
        self.atribuida.emit(self._indice, self._hablante)

    def set_rotulos(self, rotulos: dict[str, str]) -> None:
        """Quién es "1" y quién es "2" en ESTA comunicación.

        El informe numera los renglones, pero el analista no piensa en "1" y
        "2": piensa en Paredes y en Ledesma. Los nombres salen del propio
        registro (Interesado e Interlocutor), así que no hay nada que cargar.
        """
        self._rotulos = dict(rotulos or {})
        self._pintar_hablante()

    def set_heredado(self, numero: str, alternado: bool = False) -> None:
        """Con qué número va a salir esta frase en el informe judicial.

        Una frase sin atribuir no sale en blanco: el informe le pone el número
        de la anterior, o alterna si no hay ninguna marcada. Eso era invisible
        hasta exportar el Word, así que la única forma de revisar la atribución
        era leer el informe terminado. Acá se muestra apagado: lo que se ve en
        la columna es exactamente lo que va a decir el documento.
        """
        self._heredado = numero if numero in HABLANTES else ""
        self._alternado = alternado
        self._pintar_hablante()

    def _pintar_hablante(self) -> None:
        propio = self._hablante
        self.btn_hablante.setText(propio or self._heredado or "·")
        # El marcado a mano se ve firme; el que el informe deduce, apagado.
        if propio:
            self.btn_hablante.setStyleSheet(
                f"color:{tema.TEXT_PRIMARY}; font-weight:700;"
            )
        elif self._heredado:
            self.btn_hablante.setStyleSheet(
                f"color:{tema.TEXT_DIM}; font-style:italic;"
            )
        else:
            self.btn_hablante.setStyleSheet("")

        rotulos = getattr(self, "_rotulos", {}) or {}
        def nombre(n: str) -> str:
            return rotulos.get(n) or (
                "el que llama" if n == "1" else "el que atiende"
            )
        if propio:
            texto = f"Habla {nombre(propio)}  ({propio}. en el informe)"
        elif self._heredado and self._alternado:
            # Nadie marcó nada en toda la comunicación: el informe alterna, que
            # es una convención vieja y no un dato. Hay que poder verlo.
            texto = (
                f"Nadie marcó quién habla, así que el informe va a adivinar "
                f"alternando y a esta le toca {self._heredado}."
            )
        elif self._heredado:
            texto = (
                f"Sin marcar. El informe lo va a poner como {self._heredado}. "
                f"({nombre(self._heredado)}), siguiendo a la frase anterior"
            )
        else:
            texto = "Sin atribuir — el informe va a adivinar alternando"
        self.btn_hablante.setToolTip(texto + "  ·  clic para cambiar")

    def set_hablante(self, hablante: str) -> None:
        """Fija el interlocutor sin ciclar. Es lo que hacen Ctrl+1 y Ctrl+2."""
        hablante = hablante if hablante in ("1", "2") else ""
        if hablante == self._hablante:
            hablante = ""      # volver a apretar la misma tecla lo quita
        self._hablante = hablante
        self._pintar_hablante()
        self.atribuida.emit(self._indice, self._hablante)

    def insertar_en_el_cursor(self, texto: str) -> None:
        """Mete texto donde está el cursor, abriendo la frase si hace falta.

        Es como entra una marca de tiempo: el analista está escuchando, apreta
        el atajo y la marca queda en el renglón que está escribiendo.
        """
        if self.editor.isHidden():
            self.editar()
        # `insert()` REEMPLAZA lo que esté seleccionado, y la frase se abre con
        # todo seleccionado para poder reescribirla de un tirón: insertar sin
        # soltar la selección se comía la frase entera. Se junta el cursor al
        # principio de lo seleccionado, que además es donde va una marca de
        # tiempo: dice dónde EMPIEZA lo que sigue.
        if self.editor.hasSelectedText():
            inicio = self.editor.selectionStart()
            self.editor.deselect()
            self.editor.setCursorPosition(inicio)
        self.editor.insert(texto)

    def _pintar_tiempo(self) -> None:
        """El minuto dice si lo confirmó alguien o lo adivinó la máquina."""
        self.lbl_tiempo.setText(
            formato_mmss(self._inicio) if self._anclado
            else f"~{formato_mmss(self._inicio)}"
        )
        self.lbl_tiempo.setToolTip(
            "Minuto confirmado escuchando  ·  doble clic para corregirlo"
            if self._anclado else
            "Minuto provisorio: lo calculó Whisper y suele estar corrido.\n"
            "Ctrl+T lo fija donde está sonando  ·  doble clic para escribirlo"
        )

    def set_activa(self, activa: bool) -> None:
        if activa != self._activa:
            self._activa = activa
            self._pintar()

    def set_en_foco(self, en_foco: bool) -> None:
        """Marca la frase sobre la que van a actuar los atajos.

        Es distinta de la que suena: mientras se sincroniza, el audio va por
        un lado y el cursor de trabajo por otro, y ver las dos es justamente lo
        que hace falta. Sin esta marca el foco era invisible, así que Ctrl+T y
        Ctrl+1/2 caían sobre una frase que el analista no estaba mirando.
        """
        if en_foco != self._en_foco:
            self._en_foco = en_foco
            self._pintar()

    def _pintar(self) -> None:
        mono = "font-family:'IBM Plex Mono','Consolas',monospace; font-size:10px;"
        # El filete izquierdo es el cursor de trabajo; el fondo ámbar, lo que
        # suena. Cuando coinciden se ven las dos cosas sobre el mismo renglón.
        filete = (
            f"border-left: 3px solid {tema.TEAL};" if self._en_foco
            else "border-left: 3px solid transparent;"
        )
        if self._activa:
            self.setStyleSheet(
                "QFrame { background: rgba(215,165,61,0.14);"
                f" {filete} border-radius: 4px; }}"
            )
            self.lbl_texto.setStyleSheet(f"color:{tema.TEXT_PRIMARY}; font-size:12px;")
            self.lbl_tiempo.setStyleSheet(
                f"color:{tema.ACCENT}; {mono} font-weight:600;"
            )
            if not self._anclado:
                self.lbl_tiempo.setStyleSheet(
                    f"color:{tema.ACCENT}; {mono} font-style:italic;"
                )
        else:
            self.setStyleSheet(
                "QFrame { background: "
                + ("rgba(95,168,160,0.10);" if self._en_foco else "transparent;")
                + f" {filete} border-radius: 4px; }}"
            )
            # La frase que todavía no se escribió se muestra apagada y en
            # cursiva: es un hueco marcado, no una frase de la conversación.
            if self._texto:
                self.lbl_texto.setStyleSheet(
                    f"color:{tema.TEXT_MUTED}; font-size:12px;"
                )
            else:
                self.lbl_texto.setStyleSheet(
                    f"color:{tema.TEXT_DIM}; font-size:12px; font-style:italic;"
                )
            self.lbl_tiempo.setStyleSheet(
                f"color:{tema.TEXT_MUTED}; {mono} font-weight:600;"
                if self._anclado else
                f"color:{tema.TEXT_DIM}; {mono} font-style:italic;"
            )

    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802 (API de Qt)
        if (
            event.button() == Qt.LeftButton
            and self.editor.isHidden()
            and self.editor_tiempo.isHidden()
        ):
            # Tocar una frase es ponerse a trabajar sobre ella. Antes el clic
            # solo movía el audio y el foco se quedaba donde estuviera, así que
            # Ctrl+T terminaba fijándole el minuto a otra frase.
            self.tomada.emit(self._indice)
            self.saltar.emit(self._inicio)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            # Doble clic sobre el minuto corrige el minuto; sobre el resto del
            # renglón, el texto. Es la misma regla que en cualquier planilla:
            # se edita la celda que se tocó.
            punto = event.position().toPoint()
            if self.lbl_tiempo.geometry().contains(punto):
                self.editar_tiempo()
            else:
                self.editar(x=punto.x())
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        """Menú de la frase: una entrada por cada forma en que Whisper falla.

        Se saltea pasajes (agregar arriba/abajo), mete a dos personas en el
        mismo renglón (dividir), parte una frase en pedazos (unir con la de
        arriba) e inventa donde no hay nada (quitar).
        """
        menu = QMenu(self)
        menu.addAction("Corregir esta frase", self.editar)
        menu.addSeparator()
        menu.addAction(
            "Agregar una frase arriba",
            lambda: self.insertar.emit(self._indice, "arriba"),
        )
        menu.addAction(
            "Agregar una frase debajo",
            lambda: self.insertar.emit(self._indice, "abajo"),
        )
        menu.addAction("Corregir el minuto…", self.editar_tiempo)
        menu.addAction(
            "Poner el minuto donde está sonando",
            lambda: self.anclar.emit(self._indice),
        )
        menu.addSeparator()
        act_dividir = menu.addAction("Dividir en dos frases…", self._pedir_division)
        act_dividir.setToolTip(
            "Abre la frase para que pongas el cursor donde empieza el otro "
            "interlocutor y presiones Ctrl+Enter"
        )
        act_unir = menu.addAction(
            "Unir con la frase de arriba", lambda: self.unir.emit(self._indice)
        )
        act_unir.setEnabled(self._indice > 0)
        menu.addSeparator()
        menu.addAction("Quitar esta frase", lambda: self.quitar.emit(self._indice))
        menu.exec(event.globalPos())

    def _pedir_division(self) -> None:
        """Abre el editor con el cursor en el medio, listo para Ctrl+Enter."""
        self.editar()
        self.editor.deselect()
        self.editor.setCursorPosition(len(self.editor.text()) // 2)

    def editar(self, seleccionar_todo: bool = False, x: int | None = None) -> None:
        """Pasa la frase a modo edición.

        Por omisión NO selecciona nada: abrir con todo seleccionado hacía que
        el doble clic sobre una palabra marcara la frase entera, y que arrastrar
        para elegir un pedazo empezara peleando contra una selección que uno no
        pidió. Solo F2 —que es la tecla de "reescribir esto de un tirón"— abre
        con todo marcado.

        Con `x` (la coordenada del clic) el cursor queda donde se tocó, que es
        lo que uno espera de cualquier campo de texto.
        """
        self.editor.setText(self._texto)
        self.lbl_texto.hide()
        self.editor.show()
        self.editor.setFocus()
        if seleccionar_todo:
            self.editor.selectAll()
            return
        self.editor.deselect()
        if x is None:
            self.editor.setCursorPosition(len(self._texto))
            return
        relativo = QPoint(max(0, x - self.editor.x()), self.editor.height() // 2)
        self.editor.setCursorPosition(self.editor.cursorPositionAt(relativo))

    def editar_tiempo(self) -> None:
        """Pasa el minuto a modo edición."""
        self.editor_tiempo.setText(formato_mmss(self._inicio))
        self.lbl_tiempo.hide()
        self.editor_tiempo.show()
        self.editor_tiempo.setFocus()
        self.editor_tiempo.selectAll()

    def _cerrar_editor_tiempo(self) -> None:
        self.editor_tiempo.hide()
        self.lbl_tiempo.show()

    def _cancelar_tiempo(self) -> None:
        self._cerrar_editor_tiempo()

    def _confirmar_tiempo(self) -> None:
        if self.editor_tiempo.isHidden():
            return  # editingFinished también dispara al ocultar el editor
        crudo = self.editor_tiempo.text()
        self._cerrar_editor_tiempo()
        nuevo = segundos_de(crudo)
        # Un minuto que no se entiende se descarta en silencio y la frase queda
        # donde estaba: no hay forma de adivinar qué se quiso escribir, y un
        # cartel por cada tipeo sería peor que volver a escribirlo.
        if nuevo is None or abs(nuevo - self._inicio) < 0.005:
            return
        self.reubicada.emit(self._indice, nuevo)

    def set_inicio(self, segundo: float, anclado: bool = True) -> None:
        self._inicio = float(segundo)
        self._anclado = anclado
        self._pintar_tiempo()
        self._pintar()

    def _cerrar_y_seguir(self) -> None:
        """Shift+Enter: guarda esta frase y abre una nueva justo abajo.

        Es lo que se necesita cuando Whisper juntó dos turnos en un renglón o
        se comió una respuesta: se termina de escribir lo que va acá y se sigue
        con lo que sigue, sin ir al menú ni al mouse.
        """
        self._confirmar()
        self.insertar.emit(self._indice, "abajo")

    def _cerrar_editor(self) -> None:
        self.editor.hide()
        self.lbl_texto.show()

    def _cancelar(self) -> None:
        """Esc: se deja la frase como estaba, sin guardar nada.

        Sin esta salida, el único modo de cerrar el editor era confirmar: una
        corrección empezada por error había que deshacerla a mano.
        """
        self._cerrar_editor()

    def _dividir_en(self, posicion: int) -> None:
        """Ctrl+Enter: parte la frase en el cursor y la convierte en dos.

        Es el arreglo del error más común de Whisper en una escucha telefónica:
        dos personas que se responden rápido terminan en un mismo segmento, y
        el informe judicial numera por renglón, así que ese renglón le atribuye
        a uno lo que dijo el otro.

        Cuando no se puede partir, se dice. Antes volvía en silencio y el
        analista concluía —con razón— que la tecla no andaba: la frase se abre
        con todo seleccionado y el cursor queda al final, así que apretar
        Ctrl+Enter apenas abierta caía siempre en este caso.
        """
        crudo = self.editor.text()
        arriba = " ".join(crudo[:posicion].split())
        abajo = " ".join(crudo[posicion:].split())
        if not arriba or not abajo:
            self.aviso.emit(
                "Para partir la frase, poné el cursor donde empieza el otro "
                "interlocutor: Ctrl+Enter corta ahí."
            )
            return
        self._cerrar_editor()
        self.dividir.emit(self._indice, arriba, abajo)

    def _confirmar(self) -> None:
        if self.editor.isHidden():
            return  # editingFinished también dispara al ocultar el editor
        nuevo = " ".join(self.editor.text().split())
        self._cerrar_editor()
        if nuevo != self._texto:
            # Vaciar una frase que decía algo no la borra: para eso está
            # "Quitar esta frase", que es una decisión y no un descuido.
            if nuevo or not self._texto:
                self._texto = nuevo
                self.lbl_texto.setText(
                    nuevo or "(frase vacía — doble clic para escribirla)"
                )
                self._pintar()
                self.editada.emit(self._indice, nuevo)
        elif not nuevo:
            # Se agregó una frase y se la dejó en blanco: avisar igual, para
            # que la lista pueda descartar el hueco que nadie llenó.
            self.editada.emit(self._indice, "")
        self.confirmada.emit(self._indice)


class TranscripcionSincronizada(QWidget):
    """Lista de frases con su minuto, sincronizada con el reproductor."""

    saltar_a = Signal(float)           # segundo pedido por el analista
    segmentos_editados = Signal(list)  # segmentos completos tras corregir uno
    aviso = Signal(str)                # algo que el analista tiene que saber

    ALTURA = 210

    def __init__(self, segmentos: list[dict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._segmentos = [dict(s) for s in segmentos]
        self._lineas: list[_Linea] = []
        self._activa = -1
        # Último segundo que informó el reproductor. Es lo que permite "poner
        # el minuto donde está sonando": se escucha dónde empieza de verdad la
        # frase y se la ancla ahí, sin tipear nada.
        self._segundo_actual = 0.0
        self._rotulos: dict[str, str] = {}
        self._foco = 0
        # Pila de estados anteriores para deshacer. Son unos cientos de dicts
        # chicos por copia: guardar treinta no cuesta nada y es lo único que
        # separa un "quitar esta frase" apretado de más de perder el texto.
        self._hechos: list[tuple[str, list[dict]]] = []
        self._deshechos: list[tuple[str, list[dict]]] = []
        self._agrupando = False

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(4)

        self._ayuda = QLabel()
        self._ayuda.setWordWrap(True)
        self._ayuda.setStyleSheet(f"color:{tema.TEXT_DIM}; font-size:10px;")
        raiz.addWidget(self._ayuda)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        # Alto fijo por defecto: en el panel de la Tabla TOTAL la lista
        # comparte lugar con los datos de la comunicación y no puede crecer a
        # costa de ellos. En Desgrabar sí —ahí es el trabajo— y se lo suelta
        # con `que_crezca()`.
        self._scroll.setFixedHeight(self.ALTURA)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._cuerpo = QWidget()
        self._cuerpo_lay = QVBoxLayout(self._cuerpo)
        self._cuerpo_lay.setContentsMargins(0, 0, 4, 0)
        self._cuerpo_lay.setSpacing(1)
        self._scroll.setWidget(self._cuerpo)
        raiz.addWidget(self._scroll)

        # Agregar al final va al final de la LISTA, no en una barra aparte: el
        # renglón de puntos se lee como que la conversación sigue ahí. Antes era
        # un botón del porte de "Transcribir con Whisper" compitiendo con él, y
        # duplicaba lo que ya hace el botón derecho sobre una frase.
        self.btn_agregar_final = QPushButton("＋  agregar una frase al final")
        self.btn_agregar_final.setCursor(Qt.PointingHandCursor)
        self.btn_agregar_final.setFlat(True)
        self.btn_agregar_final.setStyleSheet(
            "QPushButton { text-align:left; padding:5px 8px; font-size:11px;"
            f" color:{tema.TEXT_DIM}; background:transparent;"
            f" border:none; border-top:1px dashed {tema.LINE}; }}"
            f"QPushButton:hover {{ color:{tema.ACCENT}; }}"
        )
        self.btn_agregar_final.setToolTip(
            "Para el cierre de la llamada que Whisper no alcanzó a transcribir"
        )
        self.btn_agregar_final.clicked.connect(
            lambda: self._insertar_debajo(len(self._segmentos) - 1)
        )

        self._reconstruir_lineas()

    # ------------------------------------------------------------------
    def _reconstruir_lineas(self) -> None:
        """Rehace los renglones desde los segmentos actuales.

        Se rehace entero en vez de insertar un widget en el medio porque cada
        renglón guarda su índice: correrlos de a uno al agregar o quitar es la
        clase de contabilidad que se desincroniza a la primera distracción.
        """
        while self._cuerpo_lay.count():
            item = self._cuerpo_lay.takeAt(0)
            w = item.widget()
            if w is not None and w is not self.btn_agregar_final:
                w.deleteLater()
        self._lineas = []
        for i, seg in enumerate(self._segmentos):
            linea = _Linea(i, seg)
            linea.saltar.connect(self.saltar_a)
            linea.editada.connect(self._al_editar)
            linea.atribuida.connect(self._al_atribuir)
            linea.insertar.connect(self._al_insertar)
            linea.quitar.connect(self._quitar)
            linea.dividir.connect(self._dividir)
            linea.unir.connect(self._unir_con_anterior)
            linea.reubicada.connect(self._reubicar)
            linea.anclar.connect(self._anclar_donde_suena)
            linea.confirmada.connect(self._al_confirmar)
            linea.aviso.connect(self.aviso)
            linea.tomada.connect(self._tomar_foco)
            linea.set_rotulos(self._rotulos)
            self._cuerpo_lay.addWidget(linea)
            self._lineas.append(linea)
        self._cuerpo_lay.addWidget(self.btn_agregar_final)
        self._cuerpo_lay.addStretch(1)
        self._activa = -1
        self._pintar_foco()
        self._actualizar_heredados()
        self._actualizar_ayuda()

    def _traer_a_la_vista(self, linea: _Linea) -> None:
        """Mueve la lista SOLO si la frase quedó fuera de lo que se ve.

        `ensureWidgetVisible` corre el scroll aunque la frase ya esté a la
        vista, porque exige un margen contra los bordes. Con el audio sonando
        eso es un tirón por frase: la lista se mueve sola justo cuando uno está
        apuntando con el mouse, y el clic termina cayendo en otro renglón. Es
        lo que hacía imposible corregir escuchando.
        """
        viewport = self._scroll.viewport()
        arriba = linea.mapTo(self._cuerpo, linea.rect().topLeft()).y()
        abajo = arriba + linea.height()
        desplazamiento = self._scroll.verticalScrollBar().value()
        if arriba >= desplazamiento and abajo <= desplazamiento + viewport.height():
            return
        self._scroll.ensureWidgetVisible(linea, 0, 40)

    def _actualizar_heredados(self) -> None:
        """Le dice a cada renglón con qué número va a salir en el informe."""
        alternado = not any(s.get("hablante") for s in self._segmentos)
        # strict: los renglones se construyen desde los segmentos. Si alguna
        # vez quedaran desfasados, sin esto cada renglón mostraría el número
        # del de al lado y nadie se enteraría.
        for linea, (numero, _texto) in zip(
            self._lineas, numerar_por_hablante(self._segmentos), strict=True
        ):
            linea.set_heredado(numero, alternado)

    # --------------------------- agregar frases -------------------------
    def _al_insertar(self, indice: int, donde: str) -> None:
        if donde == "arriba":
            self._insertar_debajo(indice - 1)
        else:
            self._insertar_debajo(indice)

    def _insertar_debajo(self, indice: int) -> None:
        """Agrega una frase vacía después de la indicada y la abre para escribir.

        Con `indice = -1` la frase queda ARRIBA DE TODO: es el saludo o el
        "hola" que Whisper se comió al principio de la llamada, que sin esto no
        había forma de reponer porque solo se podía agregar hacia abajo.

        El tiempo se calcula entre la frase de arriba y la de abajo: la frase
        nueva queda anclada donde corresponde, así el orden se mantiene y al
        hacerle clic el audio salta al lugar aproximado.
        """
        if indice < -1 or indice >= len(self._segmentos):
            indice = len(self._segmentos) - 1
        self._recordar("agregar una frase")

        anterior = self._segmentos[indice] if indice >= 0 else None
        siguiente = (
            self._segmentos[indice + 1] if indice + 1 < len(self._segmentos) else None
        )
        desde = (
            float(anterior.get("fin") or anterior.get("inicio") or 0.0)
            if anterior else 0.0
        )
        hasta = (
            float(siguiente.get("inicio") or desde + _DURACION_NUEVA)
            if siguiente else desde + _DURACION_NUEVA
        )
        if hasta <= desde:
            hasta = desde + _DURACION_NUEVA

        nuevo = {
            "inicio": round(desde, 2),
            "fin": round(min(hasta, desde + _DURACION_NUEVA), 2),
            "texto": "",
        }
        self._segmentos.insert(indice + 1, nuevo)
        self._reconstruir_lineas()
        self.segmentos_editados.emit(self.segmentos())

        linea = self._lineas[indice + 1]
        self._traer_a_la_vista(linea)
        linea.editar()

    # --------------------------- dividir y unir -------------------------
    def _dividir(self, indice: int, arriba: str, abajo: str) -> None:
        """Parte una frase en dos, repartiendo su tramo de audio entre ambas.

        El corte se reparte en proporción a lo que ocupa cada mitad del texto:
        no es exacto —habría que volver a alinear el audio— pero deja a cada
        frase apuntando a su propio tramo, que es para lo que sirve el clic.
        """
        if not (0 <= indice < len(self._segmentos)):
            return
        self._recordar("dividir una frase")
        seg = self._segmentos[indice]
        inicio = float(seg.get("inicio") or 0.0)
        fin = float(seg.get("fin") or inicio)
        total = len(arriba) + len(abajo)
        corte = inicio + (fin - inicio) * (len(arriba) / total) if total and fin > inicio else inicio

        primera = dict(seg)
        primera.update({"texto": arriba, "fin": round(corte, 2)})
        segunda = dict(seg)
        segunda.update({"texto": abajo, "inicio": round(corte, 2), "fin": round(fin, 2)})
        # La atribución de voz NO se hereda: dividir es justo lo que se hace
        # cuando el renglón tenía a dos personas, así que copiar el hablante a
        # las dos mitades sería propagar el error que se está arreglando.
        segunda.pop("hablante", None)

        self._segmentos[indice:indice + 1] = [primera, segunda]
        self._reconstruir_lineas()
        self.segmentos_editados.emit(self.segmentos())
        self._traer_a_la_vista(self._lineas[indice + 1])

    def _unir_con_anterior(self, indice: int) -> None:
        """Junta esta frase con la de arriba: el inverso de dividir.

        Whisper también parte una sola oración en pedazos cuando el que habla
        hace una pausa. Cada pedazo sale como un renglón numerado distinto en
        el informe, como si fueran intervenciones separadas.
        """
        if not (1 <= indice < len(self._segmentos)):
            return
        self._recordar("unir dos frases")
        previa, actual = self._segmentos[indice - 1], self._segmentos[indice]
        texto = " ".join(
            t for t in (str(previa.get("texto") or ""), str(actual.get("texto") or ""))
            if t
        )
        unida = dict(previa)
        unida["texto"] = texto
        unida["fin"] = round(
            max(float(previa.get("fin") or 0.0), float(actual.get("fin") or 0.0)), 2
        )
        # Si la de arriba no tenía voz atribuida y esta sí, la unión la hereda:
        # es el único dato de los dos y perderlo obligaría a volver a marcar.
        if not previa.get("hablante") and actual.get("hablante"):
            unida["hablante"] = actual["hablante"]

        self._segmentos[indice - 1:indice + 1] = [unida]
        self._reconstruir_lineas()
        self.segmentos_editados.emit(self.segmentos())
        self._traer_a_la_vista(self._lineas[indice - 1])

    # ---------------------------- el minuto -----------------------------
    def _anclar_donde_suena(self, indice: int) -> None:
        self._reubicar(indice, self._segundo_actual)

    def _reubicar(self, indice: int, segundo: float) -> None:
        """Mueve la frase al minuto indicado y reordena la lista.

        La lista TIENE que quedar ordenada por tiempo: el resaltado que sigue
        al audio recorre los segmentos de arriba hacia abajo y corta en el
        primero que todavía no empezó. Con una frase fuera de lugar, todo lo
        que viene después deja de encenderse.

        La frase conserva su duración: se la está corriendo, no estirando.
        """
        if not (0 <= indice < len(self._segmentos)):
            return
        self._recordar("confirmar el minuto")
        seg = self._segmentos[indice]
        seg["anclado"] = True
        inicio = float(seg.get("inicio") or 0.0)
        dura = max(0.0, float(seg.get("fin") or inicio) - inicio)
        seg["inicio"] = round(max(0.0, segundo), 2)
        seg["fin"] = round(seg["inicio"] + dura, 2)

        # NO se reordena. La frase se queda donde está en el diálogo: ese
        # orden es el que Whisper acertó. Reordenar por tiempo mandaba la frase
        # corregida a otro lugar de la lista, y el analista perdía el renglón y
        # la secuencia de la conversación justo mientras la estaba arreglando.
        self._reconstruir_lineas()
        self.segmentos_editados.emit(self.segmentos())
        if 0 <= indice < len(self._lineas):
            self._traer_a_la_vista(self._lineas[indice])

    def _al_confirmar(self, indice: int) -> None:  # noqa: D401
        """Enter cierra la frase y deja el teclado libre para el audio.

        Antes abría la de abajo, para corregir de corrido. Pero corregir un
        borrador no es escribir de cero: la mayoría de las frases están bien y
        uno pasa escuchando, no tipeando. Encadenar editores obligaba a cerrar
        a mano el que se abría solo cada vez, y mientras estaba abierto el
        teclado era del texto y no del audio.
        """
        self._foco = max(0, min(indice, len(self._lineas) - 1))
        self._pintar_foco()

    def _quitar(self, indice: int, recordar: bool = True) -> None:
        if not (0 <= indice < len(self._segmentos)):
            return
        if recordar:
            self._recordar("quitar una frase")
        self._segmentos.pop(indice)
        self._reconstruir_lineas()
        self.segmentos_editados.emit(self.segmentos())

    def segmentos(self) -> list[dict]:
        return [dict(s) for s in self._segmentos]

    # ------------------------------ deshacer ----------------------------
    MAX_DESHACER = 30

    @contextmanager
    def _como_un_solo_paso(self, que: str):
        """Todo lo que pase adentro se deshace con un solo Ctrl+Z.

        Hay gestos que por dentro son dos operaciones —Ctrl+T escribe la marca
        y además mueve el minuto— pero para el analista fueron uno solo, así
        que tienen que deshacerse de una.
        """
        self._recordar(que)
        previo, self._agrupando = self._agrupando, True
        try:
            yield
        finally:
            self._agrupando = previo

    def _recordar(self, que: str) -> None:
        """Guarda cómo estaba la transcripción antes de tocarla."""
        if self._agrupando:
            return
        self._hechos.append((que, self.segmentos()))
        del self._hechos[:-self.MAX_DESHACER]
        self._deshechos.clear()

    def puede_deshacer(self) -> bool:
        return bool(self._hechos)

    def puede_rehacer(self) -> bool:
        return bool(self._deshechos)

    def deshacer(self) -> str:
        """Vuelve al estado anterior. Devuelve qué se deshizo, o ''."""
        if not self._hechos:
            return ""
        que, anterior = self._hechos.pop()
        self._deshechos.append((que, self.segmentos()))
        self._restaurar(anterior)
        return que

    def rehacer(self) -> str:
        if not self._deshechos:
            return ""
        que, siguiente = self._deshechos.pop()
        self._hechos.append((que, self.segmentos()))
        self._restaurar(siguiente)
        return que

    def reemplazar_todo(self, segmentos: list[dict], que: str) -> None:
        """Cambia la transcripción entera de una, deshacible en un paso."""
        self._recordar(que)
        self._restaurar(segmentos)

    def _restaurar(self, segmentos: list[dict]) -> None:
        self._segmentos = [dict(s) for s in segmentos]
        self._reconstruir_lineas()
        self.segmentos_editados.emit(self.segmentos())

    # ------------------- manejo desde el teclado ------------------------
    def que_crezca(self, alto_minimo: int = 160) -> None:
        """Suelta el alto fijo para que la lista ocupe el lugar disponible.

        Con el alto clavado, agrandar la ventana no agrandaba la lista: dejaba
        un hueco arriba y las frases seguían apretadas en el mismo rectángulo.
        """
        self._scroll.setMaximumHeight(16777215)     # el tope que usa Qt
        self._scroll.setMinimumHeight(alto_minimo)

    def set_rotulos_hablantes(self, rotulos: dict[str, str]) -> None:
        self._rotulos = dict(rotulos or {})
        for linea in self._lineas:
            linea.set_rotulos(self._rotulos)

    def _tomar_foco(self, indice: int) -> None:
        """Esta frase pasa a ser la del cursor de trabajo.

        Primero se cierra lo que estuviera abierto en otra: mientras haya un
        editor abierto, `indice_en_foco` devuelve ESA frase, así que tomar otra
        sin cerrarlo dejaba las dos en desacuerdo —y Ctrl+T le fijaba el minuto
        a la que el analista ya no estaba mirando—.
        """
        self.cerrar_editores()
        self._foco = indice
        self._pintar_foco()

    def cerrar_editores(self) -> None:
        """Guarda y cierra cualquier frase abierta."""
        for linea in list(self._lineas):
            if not linea.editor.isHidden():
                linea._confirmar()
            if not linea.editor_tiempo.isHidden():
                linea._confirmar_tiempo()

    def _pintar_foco(self) -> None:
        """Deja marcada una sola frase: la que los atajos van a tocar."""
        actual = self.indice_en_foco()
        for i, linea in enumerate(self._lineas):
            linea.set_en_foco(i == actual)

    def indice_en_foco(self) -> int:
        """La frase sobre la que actúan los atajos.

        Mientras se escribe, la que se está escribiendo. Si no hay ninguna
        abierta, LA QUE SUENA: el analista está escuchando, oye algo mal
        transcripto y aprieta F2 o Ctrl+2 esperando caer sobre eso.

        Esto estaba al revés a propósito y era el error. El foco se quedaba en
        la última frase tocada, que es invisible —el resaltado señala otra—, así
        que F2 abría una frase de arriba y Ctrl+2 le cambiaba el interlocutor a
        quien no correspondía. Un atajo no puede actuar sobre algo que no se ve.
        """
        for i, linea in enumerate(self._lineas):
            if not linea.editor.isHidden() or not linea.editor_tiempo.isHidden():
                self._foco = i
                return i
        return max(0, min(self._foco, len(self._lineas) - 1))

    def enfocar(
        self, indice: int, editar: bool = True, seleccionar_todo: bool = False
    ) -> None:
        if not (0 <= indice < len(self._lineas)):
            return
        self._foco = indice
        linea = self._lineas[indice]
        self._pintar_foco()
        self._traer_a_la_vista(linea)
        if editar:
            linea.editar(seleccionar_todo)

    def mover_foco(self, pasos: int) -> None:
        self.enfocar(self.indice_en_foco() + pasos)

    def enfocar_lo_que_suena(self) -> None:
        """Lleva la edición a la frase que está sonando en este momento."""
        if 0 <= self._activa < len(self._lineas):
            self.enfocar(self._activa)

    def dividir_el_foco(self) -> None:
        """Ctrl+Enter estando o no estando dentro del texto.

        Sin el editor abierto no había dónde cortar y la tecla no hacía nada.
        Ahora abre la frase con el cursor en el medio, que es de donde uno lo
        va a mover: el corte se pide dos veces pero nunca se queda en silencio.
        """
        indice = self.indice_en_foco()
        if not (0 <= indice < len(self._lineas)):
            return
        linea = self._lineas[indice]
        if linea.editor.isHidden():
            linea.editar()
            linea.editor.deselect()
            linea.editor.setCursorPosition(len(linea.editor.text()) // 2)
            self.aviso.emit(
                "Movés el cursor a donde empieza el otro interlocutor y "
                "Ctrl+Enter parte la frase ahí."
            )
            return
        linea._dividir_en(linea.editor.cursorPosition())

    def unir_el_foco_con_la_anterior(self) -> None:
        """Lo contrario de partir, que hace falta igual de seguido.

        Whisper parte una sola oración en pedazos cuando el que habla hace una
        pausa, y cada pedazo sale como un renglón numerado distinto.
        """
        indice = self.indice_en_foco()
        if indice <= 0:
            self.aviso.emit("La primera frase no tiene ninguna arriba.")
            return
        self._unir_con_anterior(indice)
        self.enfocar(indice - 1, editar=False)

    def quitar_el_foco(self) -> None:
        indice = self.indice_en_foco()
        if 0 <= indice < len(self._segmentos):
            self._quitar(indice)
            self.enfocar(min(indice, len(self._lineas) - 1), editar=False)

    def atribuir_al_foco(self, hablante: str) -> None:
        indice = self.indice_en_foco()
        if 0 <= indice < len(self._lineas):
            self._lineas[indice].set_hablante(hablante)

    def insertar_en_el_foco(self, texto: str) -> None:
        indice = self.indice_en_foco()
        if 0 <= indice < len(self._lineas):
            self.enfocar(indice, editar=False)
            self._lineas[indice].insertar_en_el_cursor(texto)

    def anclar_arrastrando(self, segundo: float) -> int:
        """Ancla la frase en foco y corre TODAS las de abajo lo mismo.

        Es el arreglo del desfasaje, que es como falla Whisper de verdad: no
        se equivoca en una frase suelta, se va corriendo y a partir de cierto
        punto TODO queda unos segundos tarde. Corregirlas de a una es
        interminable y además descoordina lo ya corregido con lo que falta.
        Acá se acomoda una escuchándola bien y el resto la acompaña, conservando
        la separación entre frases, que sí es correcta.
        """
        indice = self.indice_en_foco()
        if not (0 <= indice < len(self._segmentos)):
            return -1
        linea = self._lineas[indice]
        if not linea.editor.isHidden():
            linea._confirmar()
        desfasaje = segundo - float(self._segmentos[indice].get("inicio") or 0.0)
        if abs(desfasaje) < 0.01:
            return indice

        with self._como_un_solo_paso("acomodar el desfasaje"):
            self._recordar("acomodar el desfasaje")
            for i, seg in enumerate(self._segmentos[indice:]):
                inicio = float(seg.get("inicio") or 0.0)
                fin = float(seg.get("fin") or inicio)
                seg["inicio"] = round(max(0.0, inicio + desfasaje), 2)
                seg["fin"] = round(max(seg["inicio"], fin + desfasaje), 2)
                # Solo la que se escuchó queda confirmada. Las de abajo se
                # corrieron con ella, que es mejor que antes pero sigue siendo
                # una conjetura: decir que están confirmadas sería mentir.
                if i == 0:
                    seg["anclado"] = True
        self._reconstruir_lineas()
        self.segmentos_editados.emit(self.segmentos())
        self.enfocar(indice, editar=False)
        return indice

    def desfasaje_hasta(self, segundo: float) -> float:
        """Cuánto habría que correr la frase en foco para que caiga acá."""
        indice = self.indice_en_foco()
        if not (0 <= indice < len(self._segmentos)):
            return 0.0
        return segundo - float(self._segmentos[indice].get("inicio") or 0.0)

    def marcar_el_momento(self, segundo: float) -> int:
        """Ctrl+T: ancla la frase en el segundo que está sonando.

        Ya NO escribe la marca en el texto. Escribirla parecía útil —era lo que
        pedía el pliego, copiado de oTranscribe— pero este texto se imprime
        tal cual en el informe judicial, y ahí «[0:18] Hola.» no va; peor
        todavía cuando el cursor caía en medio de una palabra y quedaba
        «Ahí[0:32]». El minuto ya vive en la columna de la izquierda, que es
        donde corresponde: es un dato de la frase, no parte de lo que se dijo.

        Devuelve dónde quedó la frase después de reordenar.
        """
        indice = self.indice_en_foco()
        if not (0 <= indice < len(self._segmentos)):
            return -1
        # Si se estaba escribiendo, primero se guarda: reubicar rehace los
        # renglones y el editor abierto se llevaría lo tipeado.
        linea = self._lineas[indice]
        if not linea.editor.isHidden():
            linea._confirmar()
        self._reubicar(indice, segundo)
        # Y se pasa a la siguiente. Anclar es un trabajo en cadena: se escucha,
        # empieza una frase, se aprieta, se espera la próxima. Quedarse en la
        # misma obligaría a bajar a mano entre golpe y golpe, que es justo el
        # ritmo que hay que no romper.
        self.enfocar(min(indice + 1, len(self._lineas) - 1), editar=False)
        return indice

    def ancladas(self) -> int:
        return sum(1 for s in self._segmentos if esta_anclado(s))

    def segundo_de_la_frase_en_foco(self) -> float:
        indice = self.indice_en_foco()
        if 0 <= indice < len(self._segmentos):
            return float(self._segmentos[indice].get("inicio") or 0.0)
        return 0.0

    def resaltar_en(self, segundo: float) -> None:
        """Marca la frase que suena en ese segundo y la trae a la vista.

        No supone que la lista esté ordenada por tiempo. El ORDEN de las frases
        es dato confiable —Whisper transcribe de corrido, y es el orden en que
        se dijeron las cosas—, pero los TIEMPOS no: el motor se desfasa y hay
        que corregirlos de a uno. Suponer que están ordenados obligaba a
        reordenar la lista con cada corrección, o sea a romper lo único que
        estaba bien para honrar lo que estaba mal.
        """
        self._segundo_actual = float(segundo)
        indice = -1
        mejor = -1.0
        for i, seg in enumerate(self._segmentos):
            inicio = float(seg.get("inicio") or 0.0)
            fin = float(seg.get("fin") or inicio)
            if inicio - 0.01 <= segundo <= max(fin, inicio) + 0.01:
                indice = i
                break
            # Si ninguna lo contiene, la última que empezó antes.
            if inicio <= segundo + 0.01 and inicio >= mejor:
                mejor, indice = inicio, i
        if indice == self._activa:
            return
        if 0 <= self._activa < len(self._lineas):
            self._lineas[self._activa].set_activa(False)
        self._activa = indice
        # El foco sigue al resaltado mientras no se esté escribiendo, pero solo
        # si el minuto de esa frase está confirmado. Con tiempos provisorios el
        # resaltado va por donde Whisper cree, no por donde se está hablando:
        # mover el cursor con eso le pisaría al analista la frase que está
        # anclando justo mientras la ancla.
        if (
            indice >= 0
            and esta_anclado(self._segmentos[indice])
            and all(
                l.editor.isHidden() and l.editor_tiempo.isHidden()
                for l in self._lineas
            )
        ):
            self._foco = indice
            self._pintar_foco()
        if 0 <= indice < len(self._lineas):
            linea = self._lineas[indice]
            linea.set_activa(True)
            # Solo se sigue el audio si el analista no está corrigiendo: mover
            # el scroll debajo del cursor mientras escribe es exasperante.
            if linea.editor.isHidden() and linea.editor_tiempo.isHidden():
                self._traer_a_la_vista(linea)

    def _al_editar(self, indice: int, texto: str) -> None:
        if not (0 <= indice < len(self._segmentos)):
            return
        if not texto and not self._segmentos[indice].get("texto"):
            # Se agregó un renglón y se lo dejó en blanco. Si queda, ocupa un
            # lugar en la lista y corre la alternancia 1./2. del informe para
            # todo lo que viene después. El hueco que nadie llenó se descarta.
            # Sin recordarlo: el estado anterior ya lo guardó el agregado, así
            # que un solo Ctrl+Z tiene que deshacer las dos mitades.
            self._quitar(indice, recordar=False)
            return
        self._recordar("corregir el texto")
        self._segmentos[indice]["texto"] = texto
        self.segmentos_editados.emit(self.segmentos())

    def _al_atribuir(self, indice: int, hablante: str) -> None:
        if not (0 <= indice < len(self._segmentos)):
            return
        self._recordar("marcar quién habla")
        if hablante:
            self._segmentos[indice]["hablante"] = hablante
        else:
            self._segmentos[indice].pop("hablante", None)
        self._actualizar_heredados()
        self._actualizar_ayuda()
        self.segmentos_editados.emit(self.segmentos())

    def sin_atribuir(self) -> int:
        """Frases que todavía no tienen interlocutor asignado."""
        return sum(1 for s in self._segmentos if not s.get("hablante"))

    def _actualizar_ayuda(self) -> None:
        faltan = self.sin_atribuir()
        base = ("El filete verde marca la frase sobre la que actúan los "
                "atajos; el fondo ámbar, la que suena  ·  clic para trabajar "
                "sobre una y llevar el audio ahí  ·  doble clic para corregir "
                "el texto, o el minuto  ·  Ctrl+Enter parte la frase en el "
                "cursor  ·  botón derecho para agregar, unir o quitar  ·  "
                "el ~ dice que el minuto todavía es el que calculó Whisper")
        self._ayuda.setText(
            base if not faltan else f"{base}  ·  {faltan} sin atribuir"
        )
