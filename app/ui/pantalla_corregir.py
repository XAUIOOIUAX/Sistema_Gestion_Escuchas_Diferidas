"""Corregir: la mesa de trabajo mecanográfica sobre el borrador de Whisper.

Corregir una transcripción no es editar un texto: es escuchar y escribir a la
vez. El cursor tiene que quedarse donde está y el audio obedecer igual —parar,
volver dos segundos, bajar a 0,8×— sin que la mano salga del teclado. Eso es lo
que hacen oTranscribe, Express Scribe e InqScribe, y es lo que no se podía
hacer desde el panel de la Tabla TOTAL, donde el reproductor está al lado pero
hay que ir a buscarlo con el mouse.

Tres decisiones que explican la forma de esta pantalla:

**Una cola, no un archivo suelto.** El analista marca comunicaciones en la
Tabla TOTAL, las transcribe en lote, y acá aparecen las que todavía no revisó,
en orden. Al marcar una como revisada se pasa sola a la siguiente. La cola es
`transcripcion_revisada = 0`: el mismo dato que ya usaban la columna «Rev.» y
el aviso del informe judicial, no un estado nuevo que haya que mantener.

**El editor sigue siendo la lista de frases, no un cuadro de texto libre.** Un
cuadro de texto sería más parecido a oTranscribe, pero perdería los tiempos por
frase —que son los que hacen que un clic salte al segundo exacto— y la
atribución de quién habla, que el informe judicial necesita para numerar los
renglones. Lo que se agrega es el manejo por teclado, no otro editor.

**Los atajos se interceptan antes que el editor, con un filtro de eventos.**
No alcanza con QShortcut: el QLineEdit que tiene el foco consume teclas y el
resultado depende de cuál. El filtro se instala en la aplicación pero solo
actúa cuando el foco está adentro de esta pantalla, así que en el resto del
programa las mismas teclas siguen significando lo de siempre.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QDialog,
    QFileDialog,
    QMessageBox,
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app import repositorios as repo
from app import sesion
from app.analisis.cobertura import sin_confirmar
from app.core.interlocutor import numero_del_interlocutor
from app.exportadores.errores import InformeVacio
from app.exportadores.word_judicial import exportar_informe_judicial
from app.servicios import audios, memoria, transcripcion as svc
from app.ui import tema
from app.ui.dialogos import DialogoEntregaDesgrabacion, mostrar_exportacion
from app.ui.editor_onda import EditorDeOnda
from app.ui.reproductor import ReproductorAudio, _formato_mmss, leer_waveform
from app.ui.transcripcion_sincronizada import TranscripcionSincronizada

# Teclas reservadas para el audio. Se eligieron entre las que un campo de texto
# NO usa —las de función y Escape—, así que interceptarlas no le saca nada al
# que está escribiendo. Escape cierra la frase y suelta la selección: es lo que
# significa en todo Windows, y pesó más que copiarle el Play/Pausa a Express
# Scribe. Pausar sin sacar la mano del texto quedó en Ctrl+Espacio.
# F1 no se toca: es la ayuda de todo el programa, y este filtro se la estaba
# robando. Las de función arrancan en F2, que en Windows es "cambiar esto" en
# todos lados, y siguen agrupadas por lo que hacen: F3/F4 mueven el audio,
# F5/F6 la velocidad, F7/F8 saltan entre el audio y el texto.
_ATAJOS = [
    ("Esc", "Cerrar la frase y soltar la selección"),
    ("Espacio", "Sonar desde la marca; al parar vuelve ahí  (fuera del texto)"),
    ("Ctrl+Espacio", "Pausar y seguir desde donde iba, incluso escribiendo"),
    ("F2", "Corregir el texto de esta frase"),
    ("F3 / F4", "Retroceder / adelantar 5 s"),
    ("F5 / F6", "Más lento / más rápido"),
    ("F7", "Llevar el audio al minuto de la frase que escribo"),
    ("F8", "Llevar la edición a la frase que está sonando"),
    ("F9", "Repetir en bucle el tramo, o la frase que escribo"),
    ("Alt+Shift+← →", "Marcar un tramo del audio sin soltar el teclado"),
    ("Ctrl+1 / Ctrl+2", "Marcar quién habla en esta frase"),
    ("Ctrl+T", "Fijar el minuto de esta frase acá y pasar a la siguiente"),
    ("Ctrl+Shift+T", "Anclarla y correr TODAS las de abajo lo mismo"),
    ("Ctrl+U", "Unir esta frase con la de arriba"),
    ("Ctrl+Supr", "Quitar esta frase"),
    ("Ctrl+↑ / Ctrl+↓", "Frase anterior / siguiente"),
    ("Enter", "Guardar la frase y cerrar el editor"),
    ("Shift+Enter", "Guardar y abrir una frase nueva justo abajo"),
    ("Ctrl+Enter", "Partir la frase donde está el cursor"),
    ("Ctrl+Z / Ctrl+Y", "Deshacer / rehacer lo último que se cambió"),
    ("Ctrl+I", "Escribir la interpretación de esta comunicación"),
    ("Ctrl+G", "Dar por revisada y pasar a la que sigue"),
]

_SALTO_SEG = 5.0

# Las únicas teclas que el filtro mira. Todo lo demás sale por la primera
# comparación, sin recorrer parentescos ni preguntar quién tiene el foco.
_TECLAS = frozenset({
    Qt.Key_Escape, Qt.Key_Space, Qt.Key_F2, Qt.Key_F3, Qt.Key_F4,
    Qt.Key_F5, Qt.Key_F6, Qt.Key_F7, Qt.Key_F8, Qt.Key_F9,
    Qt.Key_1, Qt.Key_2, Qt.Key_T, Qt.Key_I,
    Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right, Qt.Key_G,
    Qt.Key_Z, Qt.Key_Y, Qt.Key_U, Qt.Key_Delete,
    Qt.Key_Return, Qt.Key_Enter,
})

# Cuánto estira la selección cada golpe de flecha. Manteniéndola apretada Qt
# repite la tecla, así que marcar diez segundos es sostenerla un momento.
_PASO_SELECCION = 0.25

# Mientras se escribe una interpretación, estas siguen andando: no escriben
# nada ni tocan ninguna frase, sólo mueven el audio. Es lo que permite volver
# tres segundos para verificar una palabra sin salir de lo que se redacta.
# Todo lo demás (F2, Ctrl+T, Ctrl+1/2, Ctrl+Enter, Ctrl+U, Ctrl+Supr, Enter)
# queda apagado: ahí las teclas son texto.
_TECLAS_DE_AUDIO = frozenset({
    Qt.Key_F3, Qt.Key_F4, Qt.Key_F5, Qt.Key_F6, Qt.Key_F9,
})


def _escribiendo(widget) -> bool:
    """Si el foco está en un campo de texto.

    Es la línea que decide qué teclas se pueden robar. Espacio y las flechas
    son texto: mientras se escribe tienen que llegar al editor, o no se podría
    ni separar dos palabras. Fuera de un campo de texto están libres, y ahí
    valen lo que valen en cualquier reproductor.
    """
    return isinstance(widget, (QLineEdit, QTextEdit, QAbstractSpinBox))


class PantallaCorregir(QWidget):
    """Cola de transcripciones por revisar, con el audio manejado por teclado."""

    datos_cambiaron = Signal()
    ir_a_registro = Signal(int)

    def __init__(self, con: sqlite3.Connection) -> None:
        super().__init__()
        self._con = con
        self._caso_id: int | None = None
        self._pendientes: list[sqlite3.Row] = []
        self._actual: sqlite3.Row | None = None
        self._sincro: TranscripcionSincronizada | None = None
        self._filtrando = False
        self._divisor_repartido = False
        self._lugar_inicial = sesion.lugar()
        self._construir()

    # ------------------------------ datos -------------------------------
    def set_caso(self, caso_id: int) -> None:
        self._caso_id = caso_id
        self.refrescar()

    def refrescar(self) -> None:
        if self._caso_id is None:
            return
        # La que estaba abierta; si es la primera vez en esta ejecución, la que
        # se estaba corrigiendo cuando se cerró el programa.
        anterior = self._actual["id"] if self._actual else None
        if anterior is None:
            guardado = self._lugar_inicial.get("registro_id")
            anterior = guardado if isinstance(guardado, int) and guardado else None
        self._pendientes = self._cargar_pendientes()
        self._poblar_cola()
        if not self._pendientes:
            self._mostrar_vacio()
            return
        indices = [i for i, r in enumerate(self._pendientes) if r["id"] == anterior]
        retomada = bool(indices) and self._actual is None
        self._abrir(indices[0] if indices else 0)
        if retomada:
            self._retomar_el_audio()

    def _retomar_el_audio(self) -> None:
        """Deja el audio en el segundo donde se estaba escuchando.

        Corregir una llamada de dos minutos lleva bastante más que dos minutos.
        Si al volver el audio arranca de cero hay que buscar a mano dónde se
        había quedado, que es el trabajo que esta pantalla existe para evitar.
        """
        guardado = self._lugar_inicial.get("segundo")
        if not isinstance(guardado, (int, float)) or guardado <= 0:
            return
        segundo = float(guardado)

        def ubicar(_duracion: float) -> None:
            self.reproductor.saltar_a(segundo)
            if self._sincro is not None:
                self._sincro.resaltar_en(segundo)
            self.lbl_status.setText(
                f"Retomado en {_formato_mmss(segundo)}, donde quedaste"
            )

        # El salto necesita que el archivo esté cargado: si todavía no se sabe
        # la duración, se espera a que el reproductor la informe.
        if self.reproductor._duracion_ms > 0:
            ubicar(0.0)
        else:
            self.reproductor.duracion_conocida.connect(
                ubicar, Qt.SingleShotConnection
            )

    def recordar_lugar(self) -> None:
        """Anota qué comunicación y qué segundo, para volver acá mañana."""
        if self._actual is None:
            return
        sesion.recordar_lugar(
            registro_id=self._actual["id"],
            segundo=round(self.reproductor.posicion_actual_seg(), 1),
        )

    def _cargar_pendientes(self) -> list[sqlite3.Row]:
        """Las que tienen borrador y todavía nadie revisó, en orden de causa."""
        return self._con.execute(
            """
            SELECT * FROM Registro
            WHERE caso_id = ?
              AND transcripcion_revisada = 0
              AND (
                    -- Lo que Whisper dejó listo para corregir…
                    (tipo = 'llamada' AND TRIM(COALESCE(transcripcion, '')) <> '')
                    -- …y lo que el analista mandó a mano: un SMS, un intento
                    -- de comunicación, una llamada todavía sin transcribir.
                    OR en_desgrabar = 1
                  )
            ORDER BY orden
            """,
            (self._caso_id,),
        ).fetchall()

    # ------------------------------- UI ---------------------------------
    def _construir(self) -> None:
        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        # ------- cola -------
        cola = QFrame()
        cola.setObjectName("panel")
        cola.setFixedWidth(250)
        clay = QVBoxLayout(cola)
        clay.setContentsMargins(14, 14, 14, 14)
        clay.setSpacing(6)
        lbl = QLabel("POR REVISAR")
        lbl.setObjectName("seccion")
        clay.addWidget(lbl)
        self.lista = QListWidget()
        self.lista.currentRowChanged.connect(self._al_elegir_de_la_cola)
        clay.addWidget(self.lista, 1)
        self.lbl_cola = QLabel("")
        self.lbl_cola.setObjectName("subtitulo")
        self.lbl_cola.setWordWrap(True)
        clay.addWidget(self.lbl_cola)
        raiz.addWidget(cola)

        # ------- mesa de trabajo -------
        main = QWidget()
        mlay = QVBoxLayout(main)
        mlay.setContentsMargins(16, 12, 16, 10)
        mlay.setSpacing(8)

        cab = QHBoxLayout()
        titulos = QVBoxLayout()
        self.lbl_titulo = QLabel("Desgrabar")
        self.lbl_titulo.setObjectName("titulo")
        self.lbl_sub = QLabel("")
        self.lbl_sub.setObjectName("subtitulo")
        self.lbl_sub.setWordWrap(True)
        titulos.addWidget(self.lbl_titulo)
        titulos.addWidget(self.lbl_sub)
        cab.addLayout(titulos)
        cab.addStretch(1)

        self.btn_ver_en_tabla = QPushButton("Ver en la Tabla TOTAL")
        self.btn_ver_en_tabla.clicked.connect(self._ver_en_tabla)
        cab.addWidget(self.btn_ver_en_tabla)

        self.btn_entregar = QPushButton("📄 Entregar desgrabación")
        self.btn_entregar.setToolTip(
            "Genera el informe judicial en Word con lo que desgrabaste y "
            "todavía no entregaste, sin tener que elegirlo de nuevo."
        )
        self.btn_entregar.clicked.connect(self._entregar_desgrabacion)
        cab.addWidget(self.btn_entregar)

        self.btn_revisada = QPushButton("✓ Dada por revisada  (Ctrl+G)")
        self.btn_revisada.setObjectName("primary")
        self.btn_revisada.clicked.connect(self._dar_por_revisada)
        cab.addWidget(self.btn_revisada)
        mlay.addLayout(cab)

        self.reproductor = ReproductorAudio()
        self.reproductor.set_retroceso(ReproductorAudio.RETROCESO_POR_DEFECTO)
        self.reproductor.posicion_cambiada.connect(self._al_mover_el_audio)
        # Acá y no en `_abrir()`: el reproductor dura toda la sesión y `_abrir()`
        # corre con cada comunicación, así que conectarlo ahí sumaba una
        # conexión más por cada una y el resaltado terminaba repintándose
        # cuarenta veces por cada avance del audio.
        self.reproductor.posicion_cambiada.connect(self._al_avanzar_el_audio)
        self.reproductor.ancla_cambiada.connect(self._al_mover_el_ancla)
        mlay.addWidget(self.reproductor)

        self.onda = EditorDeOnda()
        self.onda.lienzo.setFocusPolicy(Qt.StrongFocus)
        self.onda.buscado.connect(self.reproductor.saltar_a)
        self.onda.frase_elegida.connect(self._al_elegir_frase_en_la_onda)
        self.onda.agregar_frase_en.connect(self._agregar_frase_en_el_hueco)
        self.onda.tramo_cambiado.connect(self.reproductor.set_tramo)
        mlay.addWidget(self.onda)

        # ------- controles mecanográficos -------
        barra = QHBoxLayout()
        barra.setSpacing(10)
        barra.addWidget(QLabel("Al reanudar, retroceder"))
        self.spin_retroceso = QDoubleSpinBox()
        self.spin_retroceso.setRange(0.0, 10.0)
        self.spin_retroceso.setSingleStep(0.5)
        self.spin_retroceso.setSuffix(" s")
        self.spin_retroceso.setValue(ReproductorAudio.RETROCESO_POR_DEFECTO)
        self.spin_retroceso.setToolTip(
            "Cada vez que se reanuda, el audio vuelve este tanto: alcanza para "
            "volver a oír el final de la frase que se estaba escribiendo."
        )
        self.spin_retroceso.valueChanged.connect(self.reproductor.set_retroceso)
        barra.addWidget(self.spin_retroceso)

        self.btn_modo_texto = QPushButton("📝 Modo texto")
        self.btn_modo_texto.setCheckable(True)
        self.btn_modo_texto.setToolTip(
            "Muestra la transcripción entera como texto para corregirla de un "
            "tirón: borrando un salto de línea se unen dos frases, agregando "
            "uno se parten. Los minutos de lo que no toques se conservan."
        )
        self.btn_modo_texto.toggled.connect(self._alternar_modo_texto)
        barra.addWidget(self.btn_modo_texto)

        self.chk_seguir = QCheckBox("Seguir el audio con la lista")
        self.chk_seguir.setChecked(True)
        self.chk_seguir.setToolTip(
            "Resalta y trae a la vista la frase que suena. Destildalo si "
            "preferís que la lista no se mueva mientras escribís."
        )
        barra.addWidget(self.chk_seguir)
        barra.addStretch(1)

        # Quién es el de afuera se descubre ESCUCHANDO —"soy Marcos", "pasame
        # con Cintia"—, así que el lugar para anotarlo es acá y no otra
        # pantalla. Lo que se escribe va a la memoria de la causa: desde ese
        # momento ese número queda nombrado en toda la Tabla TOTAL y en las
        # comunicaciones que se importen después.
        barra.addWidget(QLabel("El de afuera es:"))
        self.txt_interlocutor = QLineEdit()
        self.txt_interlocutor.setPlaceholderText("nombre del interlocutor")
        self.txt_interlocutor.setMinimumWidth(200)
        self.txt_interlocutor.setToolTip(
            "Se guarda en la memoria «corresponde a» de la causa y queda "
            "puesto en todas las comunicaciones de ese número."
        )
        self.txt_interlocutor.editingFinished.connect(self._guardar_interlocutor)
        barra.addWidget(self.txt_interlocutor)

        self.btn_hab1 = QPushButton("Ctrl+1")
        self.btn_hab1.clicked.connect(lambda: self._atribuir("1"))
        self.btn_hab2 = QPushButton("Ctrl+2")
        self.btn_hab2.clicked.connect(lambda: self._atribuir("2"))
        for b in (self.btn_hab1, self.btn_hab2):
            b.setToolTip("Marca quién habla en la frase que estás escribiendo")
            barra.addWidget(b)
        mlay.addLayout(barra)

        # La transcripción y la interpretación, una al lado de la otra y del
        # mismo alto. El divisor va acá abajo y no envolviendo la pantalla
        # entera: la onda y el reproductor siguen a todo el ancho, que es
        # donde se los necesita.
        caja_transcripcion = QWidget()
        self.contenedor = QVBoxLayout(caja_transcripcion)
        self.contenedor.setContentsMargins(0, 0, 0, 0)

        self.divisor = QSplitter(Qt.Horizontal)
        self.divisor.setChildrenCollapsible(False)
        self.divisor.setHandleWidth(6)
        self.divisor.addWidget(caja_transcripcion)
        self.divisor.addWidget(self._crear_caja_interpretacion())
        self.divisor.setStretchFactor(0, 1)   # al agrandar crece la lista
        self.divisor.setStretchFactor(1, 0)
        self.divisor.splitterMoved.connect(self._recordar_divisor)
        mlay.addWidget(self.divisor, 1)
        self._restaurar_divisor()

        # ------- modo texto -------
        self.caja_texto = QWidget()
        tlay = QVBoxLayout(self.caja_texto)
        tlay.setContentsMargins(0, 0, 0, 0)
        tlay.setSpacing(4)
        ayuda = QLabel(
            "Un renglón por frase. Borrá el salto de línea para unir dos, "
            "agregá uno para partirlas. El «1.» o «2.» del principio marca "
            "quién habla; sacarlo quita la atribución. Los minutos de los "
            "renglones que no toques se conservan tal cual."
        )
        ayuda.setWordWrap(True)
        ayuda.setStyleSheet(f"color:{tema.TEXT_DIM}; font-size:10px;")
        tlay.addWidget(ayuda)
        self.txt_plano = QTextEdit()
        self.txt_plano.setAcceptRichText(False)
        self.txt_plano.setStyleSheet(
            "font-family:'IBM Plex Mono','Consolas',monospace; font-size:12px;"
        )
        tlay.addWidget(self.txt_plano, 1)
        pie_texto = QHBoxLayout()
        pie_texto.addStretch(1)
        btn_cancelar_texto = QPushButton("Descartar y volver a la lista")
        btn_cancelar_texto.clicked.connect(
            lambda: self.btn_modo_texto.setChecked(False)
        )
        pie_texto.addWidget(btn_cancelar_texto)
        btn_aplicar_texto = QPushButton("✓ Aplicar y volver a la lista")
        btn_aplicar_texto.setObjectName("primary")
        btn_aplicar_texto.clicked.connect(self._aplicar_modo_texto)
        pie_texto.addWidget(btn_aplicar_texto)
        tlay.addLayout(pie_texto)
        self.caja_texto.setVisible(False)
        mlay.addWidget(self.caja_texto, 1)

        self.lbl_atajos = QLabel(
            "   ·   ".join(f"<b>{t}</b> {q}" for t, q in _ATAJOS)
        )
        self.lbl_atajos.setTextFormat(Qt.RichText)
        self.lbl_atajos.setWordWrap(True)
        self.lbl_atajos.setStyleSheet(f"color:{tema.TEXT_DIM}; font-size:10px;")
        mlay.addWidget(self.lbl_atajos)

        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("subtitulo")
        mlay.addWidget(self.lbl_status)

        raiz.addWidget(main, 1)

    # --------------------------- abrir una -------------------------------
    def _poblar_cola(self) -> None:
        self.lista.blockSignals(True)
        self.lista.clear()
        for r in self._pendientes:
            duracion = f"  ({_formato_mmss(r['duracion_seg'])})" if r["duracion_seg"] else ""
            item = QListWidgetItem(
                f"{r['orden']}. {r['interlocutor'] or r['interesado'] or ''}{duracion}"
            )
            item.setToolTip(
                f"{r['fecha_inicio_texto'] or ''}\n{r['archivo_audio'] or ''}"
            )
            self.lista.addItem(item)
        self.lista.blockSignals(False)
        self.lbl_cola.setText(self._texto_de_avance())

    def _texto_de_avance(self) -> str:
        """Cuánto falta, que es lo primero que uno quiere saber al sentarse."""
        if self._caso_id is None:
            return ""
        total = self._con.execute(
            "SELECT COUNT(*) FROM Registro WHERE caso_id = ? AND tipo = 'llamada' "
            "AND TRIM(COALESCE(transcripcion, '')) <> ''",
            (self._caso_id,),
        ).fetchone()[0]
        faltan = len(self._pendientes)
        if not total:
            return "Nada transcripto todavía"
        if not faltan:
            return f"Listo: las {total} revisadas"
        return f"{total - faltan} de {total} revisadas · faltan {faltan}"

    # ----------------------- la interpretación ---------------------------
    #: Alto de la caja cuando se está escribiendo.
    ALTO_INTERPRETACION = 110

    #: Ancho de arranque de la columna, y el mínimo abajo del cual el texto
    #: sale en dos palabras por renglón y deja de servir.
    ANCHO_INTERPRETACION = 320
    ANCHO_INTERPRETACION_MINIMO = 230
    _PREF_DIVISOR = "ancho_interpretacion"

    def _crear_caja_interpretacion(self) -> QWidget:
        """Lo que el analista concluye de esta comunicación.

        Va al costado y no en el medio por dos razones. Vive en Desgrabar
        —y no en otra pantalla— porque se escribe ESCUCHANDO: separarla
        obligaría a oír dos veces. Y va en columna propia porque en el medio le
        comía alto a la lista de frases cada vez que se abría.

        Como panel lateral está siempre a la vista sin tapar nada.
        """
        marco = QFrame()
        # objectName: sin él el estilo se le aplica también a las etiquetas y
        # al cuadro de texto —QLabel y QTextEdit heredan de QFrame— y cada uno
        # sale con su propio borde adentro del otro.
        marco.setObjectName("cajaInterpretacion")
        marco.setMinimumWidth(self.ANCHO_INTERPRETACION_MINIMO)
        self.marco_interpretacion = marco
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        self.lbl_rotulo_interpretacion = QLabel("INTERPRETACIÓN")
        self.lbl_rotulo_interpretacion.setObjectName("seccion")
        lay.addWidget(self.lbl_rotulo_interpretacion)

        self.lbl_interpretacion = QLabel("")
        self.lbl_interpretacion.setObjectName("subtitulo")
        self.lbl_interpretacion.setWordWrap(True)
        lay.addWidget(self.lbl_interpretacion)

        self.txt_interpretacion = QTextEdit()
        self.txt_interpretacion.setPlaceholderText(
            "Qué se concluye de esta comunicación.\n\n"
            "Ej.: «De la comunicación del 04/09/2026 a las 17:08 se confirma "
            "que el abonado …0037 es usado por …»."
        )
        # Se arma sola si entrás con el mouse: si no, escribir acá haría que
        # Ctrl+T le anclara el minuto a una frase sin que nadie lo pidiera.
        self.txt_interpretacion.focusInEvent = self._al_entrar_a_interpretar
        lay.addWidget(self.txt_interpretacion, 1)
        self._interpretando = False
        self._pintar_marco_interpretacion()
        return marco

    def _al_entrar_a_interpretar(self, event) -> None:
        QTextEdit.focusInEvent(self.txt_interpretacion, event)
        if not self._interpretando and self._actual is not None:
            if self._sincro is not None:
                self._sincro.cerrar_editores()
            self._interpretando = True
            self._pintar_interpretacion()

    def _restaurar_divisor(self) -> None:
        guardado = sesion.preferencia(self._PREF_DIVISOR)
        try:
            ancho = int(guardado)
        except (TypeError, ValueError):
            ancho = self.ANCHO_INTERPRETACION
        ancho = max(self.ANCHO_INTERPRETACION_MINIMO, min(ancho, 900))
        # El ancho del DIVISOR, no el de la pantalla: la pantalla incluye la
        # cola de la izquierda y los márgenes, y restar sobre ese número dejaba
        # a la interpretación apretada contra su mínimo.
        disponible = self.divisor.width()
        if disponible <= ancho:
            return          # todavía sin repartir; se reintenta al mostrarse
        self.divisor.setSizes([disponible - ancho, ancho])

    def _recordar_divisor(self, *_args) -> None:
        tamanos = self.divisor.sizes()
        if len(tamanos) == 2 and tamanos[1] > 0:
            sesion.set_preferencia(self._PREF_DIVISOR, str(tamanos[1]))

    def _pintar_marco_interpretacion(self) -> None:
        """Armada se ve distinta. Un modo que cambia las teclas y no se ve es
        una trampa: ya costó tres reportes con el cursor de trabajo invisible.

        El selector lleva el objectName para que el borde sea del marco y no
        de cada cosa que tiene adentro.
        """
        borde = tema.TEAL if self._interpretando else tema.LINE
        grosor = 2 if self._interpretando else 1
        self.marco_interpretacion.setStyleSheet(
            f"QFrame#cajaInterpretacion {{ background:{tema.PANEL};"
            f" border:{grosor}px solid {borde}; border-radius:6px; }}"
        )

    def interpretando(self) -> bool:
        """Si el cuadro está armado para escribir."""
        return self._interpretando

    def texto_interpretacion(self) -> str:
        """Lo escrito para la comunicación abierta, venga de la caja o de la base."""
        if self._interpretando:
            return self.txt_interpretacion.toPlainText().strip()
        if self._actual is None:
            return ""
        try:
            return (self._actual["interpretacion"] or "").strip()
        except (IndexError, KeyError):
            return ""

    def _cargar_interpretacion(self) -> None:
        """Trae al cuadro lo escrito para la comunicación que se abre."""
        actual = ""
        if self._actual is not None:
            try:
                actual = self._actual["interpretacion"] or ""
            except (IndexError, KeyError):
                actual = ""
        # blockSignals: poner el texto no tiene que contar como que alguien
        # entró a escribir.
        self.txt_interpretacion.blockSignals(True)
        self.txt_interpretacion.setPlainText(actual)
        self.txt_interpretacion.blockSignals(False)
        self._pintar_interpretacion()

    def _pintar_interpretacion(self) -> None:
        self._pintar_marco_interpretacion()
        if self._interpretando:
            self.lbl_rotulo_interpretacion.setText("INTERPRETACIÓN · ESCRIBIENDO")
            self.lbl_interpretacion.setText(
                "Esc guarda y suelta el teclado. El audio sigue respondiendo: "
                "F3/F4, F5/F6, F9 y Ctrl+Espacio."
            )
            return
        self.lbl_rotulo_interpretacion.setText("INTERPRETACIÓN")
        if self.texto_interpretacion():
            self.lbl_interpretacion.setText("Ctrl+I para corregirla.")
            return
        self.lbl_interpretacion.setText("Ctrl+I para escribirla.")

    def alternar_interpretacion(self) -> None:
        """Ctrl+I: se mete en el cuadro, o sale guardando.

        El cuadro está siempre a la vista en su columna; lo que Ctrl+I cambia
        es DÓNDE van las teclas. Adentro son texto; afuera manejan el audio y
        las frases.
        """
        if self._interpretando:
            self.cerrar_interpretacion()
            return
        if self._actual is None:
            return
        # La frase que estuviera abierta se cierra: dos editores abiertos a la
        # vez es lo que hacía que los atajos cayeran donde no correspondía.
        if self._sincro is not None:
            self._sincro.cerrar_editores()
        self._interpretando = True
        self._pintar_interpretacion()
        self.txt_interpretacion.setFocus()
        self.txt_interpretacion.moveCursor(QTextCursor.End)

    def cerrar_interpretacion(self) -> None:
        """Esc: guarda y suelta el teclado.

        Guarda siempre. Salir perdiendo lo escrito es el tipo de cosa que no se
        perdona la primera vez que pasa.
        """
        if not self._interpretando:
            return
        texto = self.txt_interpretacion.toPlainText()
        self._interpretando = False
        if self._actual is not None:
            registro_id = self._actual["id"]
            repo.guardar_interpretacion(self._con, registro_id, texto)
            self._con.commit()
            self._actual = repo.obtener_registro(self._con, registro_id)
            self.datos_cambiaron.emit()
        self._pintar_interpretacion()
        self.setFocus()

    def _limpiar_editor(self) -> None:
        while self.contenedor.count():
            item = self.contenedor.takeAt(0)
            if w := item.widget():
                w.deleteLater()
        self._sincro = None

    def _mostrar_vacio(self) -> None:
        self._actual = None
        self._limpiar_editor()
        self.reproductor.cargar(None)
        vacio = QLabel(
            "No hay transcripciones esperando revisión.\n\n"
            "Marcá comunicaciones de interés en la Tabla TOTAL y usá "
            "«🎙 Transcribir marcadas»: cuando Whisper termine, los borradores "
            "aparecen acá para corregir."
        )
        vacio.setAlignment(Qt.AlignCenter)
        vacio.setWordWrap(True)
        vacio.setStyleSheet(f"color:{tema.TEXT_DIM};")
        self.contenedor.addWidget(vacio)
        self.lbl_sub.setText("")
        self.btn_revisada.setEnabled(False)
        self.btn_ver_en_tabla.setEnabled(False)
        self.lbl_status.setText("")

    def _al_elegir_de_la_cola(self, fila: int) -> None:
        if 0 <= fila < len(self._pendientes):
            self._abrir(fila)

    def _ficha_sin_frases(self, r: sqlite3.Row) -> QWidget:
        """Lo que se muestra cuando no hay frases con tiempos que corregir.

        Es el caso de un SMS —el texto viene de la prestadora y no se toca— y
        el de una llamada mandada a mano sin pasar por Whisper. No hay nada que
        transcribir, pero sí hay algo que hacer: escuchar o leer, escribir la
        interpretación al costado y cerrarla. Antes decía "se corrige desde la
        Tabla TOTAL", que mandaba al analista a otra pantalla justo cuando
        acababa de traer esto a ésta.
        """
        caja = QWidget()
        lay = QVBoxLayout(caja)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        es_sms = (r["tipo"] or "") == "sms"
        texto = (r["transcripcion"] or "").strip()

        titulo = QLabel("MENSAJE DE TEXTO" if es_sms else "SIN TRANSCRIPCIÓN")
        titulo.setObjectName("seccion")
        lay.addWidget(titulo)

        if texto:
            cuerpo = QTextEdit()
            cuerpo.setPlainText(texto)
            # De sólo lectura a propósito: en un SMS el texto es el registro
            # TEXTUAL de la prestadora. Corregirle una falta de ortografía
            # sería alterar prueba documental. Lo que el analista aporta es la
            # interpretación, que va al costado.
            cuerpo.setReadOnly(True)
            lay.addWidget(cuerpo, 1)
            nota = QLabel(
                "Texto tal como lo entregó la prestadora: no se edita. "
                "Lo que se concluya va en la interpretación, al costado."
                if es_sms else
                "Sin frases con tiempos. Se puede escuchar y dejar la "
                "interpretación al costado."
            )
        else:
            hueco = QLabel(
                "Esta comunicación no trae texto: es un intento, o todavía no "
                "se transcribió.\n\nSe puede escuchar el audio de arriba y "
                "dejar escrito qué significa en la interpretación, al costado. "
                "Ctrl+G la cierra cuando esté lista."
            )
            hueco.setWordWrap(True)
            hueco.setStyleSheet(f"color:{tema.TEXT_DIM};")
            lay.addWidget(hueco, 1)
            nota = QLabel("Para transcribirla con Whisper: Tabla TOTAL.")

        nota.setObjectName("subtitulo")
        nota.setWordWrap(True)
        lay.addWidget(nota)
        return caja

    def _abrir(self, fila: int) -> None:
        if not (0 <= fila < len(self._pendientes)):
            return
        # Lo escrito para la anterior se guarda ANTES de cambiar de registro:
        # si no, `cerrar_interpretacion` lo escribiría sobre la nueva.
        self.cerrar_interpretacion()
        r = self._pendientes[fila]
        self._actual = r
        self.lista.blockSignals(True)
        self.lista.setCurrentRow(fila)
        self.lista.blockSignals(False)
        self.btn_revisada.setEnabled(True)
        self.btn_ver_en_tabla.setEnabled(True)
        self._cargar_interpretacion()

        self.lbl_sub.setText(
            f"#{r['orden']} · {r['fecha_inicio_texto'] or 'sin fecha'} · "
            f"{r['direccion'] or ''} · {r['interesado'] or ''} → "
            f"{r['interlocutor'] or ''}"
        )

        if self.btn_modo_texto.isChecked():
            self.btn_modo_texto.setChecked(False)
        self._limpiar_editor()
        segmentos = repo.segmentos_de_registro(r)
        if segmentos:
            sincro = TranscripcionSincronizada(segmentos)
            # Que ocupe el lugar disponible. Antes tenía el alto clavado en
            # 210 px y dejaba un hueco muerto en el centro de la pantalla; el
            # `ALTURA = 320` que había acá no hacía nada, porque se asignaba
            # después de que el constructor ya había fijado el alto.
            sincro.que_crezca()
            sincro.set_rotulos_hablantes({
                "1": r["interesado"] or "Quien llama",
                "2": r["interlocutor"] or "Quien atiende",
            })
            sincro.saltar_a.connect(self.reproductor.saltar_a)
            sincro.segmentos_editados.connect(self._guardar_segmentos)
            sincro.aviso.connect(self.lbl_status.setText)
            self.contenedor.addWidget(sincro)
            self._sincro = sincro
        else:
            self.contenedor.addWidget(self._ficha_sin_frases(r))

        ruta = self._ruta_audio(r)
        self.reproductor.cargar(ruta)
        # Más picos que en el reproductor chico: acá se hace zoom, y con 140
        # muestras al ampliar se ven escalones en vez de la onda.
        picos = leer_waveform(ruta, buckets=1400) if ruta else []
        self.onda.set_audio(picos or [], float(r["duracion_seg"] or 0.0))
        self.onda.set_segmentos(segmentos)
        self.reproductor.set_marcas(
            [m["segundo"] for m in repo.listar_marcas_audio(self._con, r["id"])]
        )
        numero = self._numero_del_interlocutor(r)
        nombre_de_afuera = (r["interlocutor"] or "").strip()
        self.txt_interlocutor.blockSignals(True)
        # Si todavía no tiene nombre, la columna muestra el número: eso no es
        # un nombre, es el hueco que hay que llenar.
        self.txt_interlocutor.setText(
            "" if not nombre_de_afuera or nombre_de_afuera == numero
            else nombre_de_afuera
        )
        self.txt_interlocutor.setEnabled(bool(numero))
        self.txt_interlocutor.setPlaceholderText(
            f"¿quién es {numero}?" if numero
            else "no se sabe cuál de las dos puntas es"
        )
        self.txt_interlocutor.blockSignals(False)

        for boton, atajo, nombre in (
            (self.btn_hab1, "Ctrl+1", r["interesado"] or "Quien llama"),
            (self.btn_hab2, "Ctrl+2", r["interlocutor"] or "Quien atiende"),
        ):
            corto = nombre if len(nombre) <= 20 else nombre[:19] + "…"
            boton.setText(f"{atajo}  {corto}")
            boton.setToolTip(
                f"Marca que en la frase que estás escribiendo habla {nombre}"
            )
        self.lbl_status.setText("")
        if self._sincro is not None:
            self._sincro.enfocar(0, editar=False)

    def _ruta_audio(self, r: sqlite3.Row) -> Path | None:
        if r["estado"] == "audio_faltante":
            return None
        return audios.localizar(self._con, self._caso_id, r["archivo_audio"] or "")

    def _al_avanzar_el_audio(self, segundo: float) -> None:
        if self._sincro is not None and self.chk_seguir.isChecked():
            self._sincro.resaltar_en(segundo)

    def _al_mover_el_audio(self, segundo: float) -> None:
        self.onda.set_posicion(segundo)

    def _al_mover_el_ancla(self, segundo: float) -> None:
        self.onda.set_ancla(segundo)

    def _al_elegir_frase_en_la_onda(self, indice: int) -> None:
        if self._sincro is not None:
            self._sincro.enfocar(indice)

    def _agregar_frase_en_el_hueco(self, desde: float, hasta: float) -> None:
        """Clic sobre un tramo sin transcribir: se abre una frase ahí.

        El tramo rojo dice "acá se habló y no lo escribió nadie". Lo que sigue
        es escribirlo, así que el clic deja la frase creada, anclada al segundo
        correcto y abierta para tipear, en vez de obligar a buscar el lugar en
        la lista.
        """
        if self._sincro is None:
            return
        segmentos = self._sincro.segmentos()
        anterior = -1
        for i, s in enumerate(segmentos):
            if float(s.get("inicio") or 0.0) <= desde:
                anterior = i
        self._sincro._insertar_debajo(anterior)
        nuevos = self._sincro.segmentos()
        if 0 <= anterior + 1 < len(nuevos):
            self._sincro._reubicar(anterior + 1, desde)
            self._sincro.enfocar(
                next((i for i, s in enumerate(self._sincro.segmentos())
                      if not str(s.get("texto") or "").strip()), anterior + 1)
            )
        self.reproductor.saltar_a(desde)
        self.lbl_status.setText(
            f"Frase nueva en {_formato_mmss(desde)}. El audio está ahí: escuchá y escribí."
        )

    def _guardar_segmentos(self, segmentos: list[dict]) -> None:
        if self._actual is None:
            return
        self.onda.set_segmentos(segmentos)
        repo.guardar_segmentos_transcripcion(
            self._con, self._actual["id"], segmentos
        )
        self._con.execute(
            "UPDATE Registro SET transcripcion = ? WHERE id = ?",
            (svc.texto_de_segmentos(segmentos), self._actual["id"]),
        )
        self._con.commit()
        self.datos_cambiaron.emit()

    # ---------------------------- acciones -------------------------------
    def _numero_del_interlocutor(self, r: sqlite3.Row) -> str:
        return numero_del_interlocutor(
            r["origen"] or "", r["destino"] or "",
            r["abonado_intervenido"] or "", r["direccion"] or "",
        )

    def _guardar_interlocutor(self) -> None:
        """Nombra al de afuera y lo baja a toda la causa.

        No alcanza con escribirlo en esta comunicación: el mismo número
        aparece en otras, y el sentido de identificarlo es justamente que
        aparezca nombrado en todas.
        """
        if self._actual is None or self._caso_id is None:
            return
        numero = self._numero_del_interlocutor(self._actual)
        nombre = self.txt_interlocutor.text().strip()
        if not numero or nombre == (self._actual["interlocutor"] or "").strip():
            return
        if not nombre:
            # Vaciar el campo no borra la identificación: para eso está la
            # memoria en el Índice, donde se ve qué se está sacando.
            self.txt_interlocutor.setText(self._actual["interlocutor"] or "")
            return

        memoria.guardar(self._con, self._caso_id, numero, nombre, "caso")
        tocadas = repo.recalcular_nombres(self._con, self._caso_id)
        self._con.commit()
        repo.log_auditoria(
            self._con, "edito",
            f"Corregir: {numero} identificado como «{nombre}»", self._caso_id,
        )
        self._con.commit()
        self.datos_cambiaron.emit()

        # Se relee la fila para que el rótulo del botón Ctrl+2 y la cola
        # muestren el nombre nuevo sin tener que salir y volver.
        fila = self.lista.currentRow()
        self._pendientes = self._cargar_pendientes()
        self._poblar_cola()
        self._refrescar_rotulos(fila)
        self.lbl_status.setText(
            f"{numero} queda identificado como «{nombre}» · "
            f"{tocadas} comunicaciones actualizadas"
        )

    def _refrescar_rotulos(self, fila: int) -> None:
        """Pone al día lo que muestra el nombre, sin recargar el audio."""
        if not (0 <= fila < len(self._pendientes)):
            return
        self._actual = self._pendientes[fila]
        r = self._actual
        self.lista.blockSignals(True)
        self.lista.setCurrentRow(fila)
        self.lista.blockSignals(False)
        self.lbl_sub.setText(
            f"#{r['orden']} · {r['fecha_inicio_texto'] or 'sin fecha'} · "
            f"{r['direccion'] or ''} · {r['interesado'] or ''} → "
            f"{r['interlocutor'] or ''}"
        )
        corto = (r["interlocutor"] or "Quien atiende")
        self.btn_hab2.setText(
            f"Ctrl+2  {corto if len(corto) <= 20 else corto[:19] + '…'}"
        )
        self.btn_hab2.setToolTip(
            f"Marca que en la frase que estás escribiendo habla {corto}"
        )
        if self._sincro is not None:
            self._sincro.set_rotulos_hablantes({
                "1": r["interesado"] or "Quien llama",
                "2": r["interlocutor"] or "Quien atiende",
            })

    # ---------------------------- modo texto -----------------------------
    def _alternar_modo_texto(self, activo: bool) -> None:
        """Cambia entre la lista de frases y el texto entero.

        Son dos vistas del mismo dato, no dos lugares donde escribir: se entra
        con lo que hay, se sale aplicando o descartando. Mientras el texto está
        abierto la lista se esconde, para que no queden dos versiones editables
        de lo mismo al mismo tiempo.
        """
        if self._sincro is None:
            self.btn_modo_texto.setChecked(False)
            return
        self.caja_texto.setVisible(activo)
        self._sincro.setVisible(not activo)
        if activo:
            self.txt_plano.setPlainText(
                svc.texto_editable(self._sincro.segmentos())
            )
            self.txt_plano.setFocus()
            self.lbl_status.setText(
                "Modo texto: corregí todo junto y aplicá cuando termines"
            )
        else:
            self.lbl_status.setText("")

    def _aplicar_modo_texto(self) -> None:
        if self._sincro is None:
            return
        previos = self._sincro.segmentos()
        nuevos = svc.segmentos_desde_texto(
            self.txt_plano.toPlainText(), previos,
            duracion_total=float(self._actual["duracion_seg"] or 0.0)
            if self._actual else 0.0,
        )
        if not nuevos:
            QMessageBox.information(
                self, "Modo texto",
                "El texto quedó vacío. Si querés dejar la comunicación sin "
                "transcripción, borrá las frases desde la lista.",
            )
            return
        self._sincro.reemplazar_todo(nuevos, "corregir en modo texto")
        self.btn_modo_texto.setChecked(False)
        self.lbl_status.setText(
            f"{len(nuevos)} frases (antes {len(previos)})  ·  Ctrl+Z lo deshace"
        )

    def _atribuir(self, hablante: str) -> None:
        if self._sincro is not None:
            self._sincro.atribuir_al_foco(hablante)

    def _acomodar_el_desfasaje(self) -> None:
        """Ctrl+Shift+T: ancla esta frase y corre todas las de abajo lo mismo.

        Es el arreglo del desfasaje, que es como Whisper falla de verdad: no se
        equivoca en una frase suelta, se va corriendo y de cierto punto en
        adelante TODO queda unos segundos tarde. Corregir de a una es
        interminable, y peor: va descoordinando lo ya corregido con lo que
        falta. Acá se acomoda UNA escuchándola bien y el resto la acompaña.
        """
        if self._sincro is None:
            return
        segundo = self.reproductor.posicion_actual_seg()
        desfasaje = self._sincro.desfasaje_hasta(segundo)
        cuantas = len(self._sincro.segmentos()) - self._sincro.indice_en_foco()
        if self._sincro.anclar_arrastrando(segundo) < 0:
            return
        if abs(desfasaje) < 0.01:
            self.lbl_status.setText("La frase ya estaba en ese minuto")
            return
        self.lbl_status.setText(
            f"Corridas {cuantas} frases {desfasaje:+.1f} s  ·  Ctrl+Z lo deshace"
        )

    def _insertar_marca_de_tiempo(self) -> None:
        """Ctrl+T: la frase queda anclada donde está sonando.

        Una frase agregada a mano hereda un tiempo interpolado entre sus
        vecinas, que sirve para no desordenar la lista pero no para que un clic
        lleve al lugar exacto. Escuchando se sabe dónde empieza de verdad, y
        esta es la forma de fijarlo sin tipear el minuto.
        """
        if self._sincro is None:
            return
        segundo = self.reproductor.posicion_actual_seg()
        if self._sincro.marcar_el_momento(segundo) < 0:
            return
        total = len(self._sincro.segmentos())
        self.lbl_status.setText(
            f"{_formato_mmss(segundo)} fijado  ·  "
            f"{self._sincro.ancladas()} de {total} minutos confirmados"
        )

    def _pendientes_de_esta(self) -> list[str]:
        """Lo que todavía falta en la comunicación abierta.

        Dar por revisada no es un trámite: es lo que el informe judicial mira
        para avisar si hay transcripciones sin revisar. Elevar como revisada
        una en la que quedaron siete segundos de conversación sin transcribir
        es exactamente el error que la pantalla puede ver y el analista no.
        """
        faltas: list[str] = []
        huecos = self.onda.lienzo.huecos()
        if huecos:
            total = sum(b - a for a, b in huecos)
            faltas.append(
                f"· {len(huecos)} tramo(s) con sonido y sin texto "
                f"({total:.0f} s): "
                + ", ".join(_formato_mmss(a) for a, _b in huecos[:6])
            )
        if self._sincro is not None:
            segmentos = self._sincro.segmentos()
            # Sin todos los minutos confirmados no se comparó nada contra la
            # onda. Callarlo dejaría creer que se revisó la cobertura y que
            # está bien, que es peor que no revisarla.
            provisorios = sin_confirmar(segmentos)
            if provisorios:
                faltas.append(
                    f"· {provisorios} frase(s) con el minuto que puso la "
                    "máquina: hasta confirmarlos con Ctrl+T no se puede "
                    "verificar si quedó audio sin transcribir"
                )
            vacias = sum(
                1 for s in segmentos if not str(s.get("texto") or "").strip()
            )
            # Si la marcaste de interés es porque algo dice; que quede escrito
            # qué. Avisa, no impide: hay comunicaciones de interés que se
            # explican solas con la transcripción.
            interes = (self._actual["nivel_interes"] or "ninguno") != "ninguno"
            if interes and not self.texto_interpretacion():
                faltas.append(
                    "· está marcada de interés y no tiene interpretación "
                    "escrita (Ctrl+I)"
                )
            if vacias:
                faltas.append(f"· {vacias} frase(s) agregada(s) y sin escribir")
            # La atribución PARCIAL es el caso peor y era el que no se avisaba.
            # En el Word los renglones sin marcar salen numerados igual que los
            # marcados: el que lee no puede distinguir lo que el analista
            # determinó de lo que el programa dedujo del renglón anterior.
            sin_voz = sum(1 for s in segmentos if not svc.hablante_de(s))
            if segmentos and sin_voz == len(segmentos):
                faltas.append(
                    "· nadie marcó quién habla: el informe va a numerar "
                    "alternando, que es una convención y no un dato"
                )
            elif sin_voz:
                faltas.append(
                    f"· {sin_voz} frase(s) sin marcar quién habla: en el "
                    "informe van a salir numeradas igual que las marcadas, "
                    "sin que se note que esa voz no la determinó nadie"
                )
        return faltas

    def _dar_por_revisada(self) -> None:
        """Cierra la actual y abre la siguiente, sin volver a la cola."""
        if self._actual is None:
            return
        faltas = self._pendientes_de_esta()
        if faltas:
            resp = QMessageBox.question(
                self, "Dar por revisada",
                "Antes de cerrarla, queda esto pendiente:\n\n"
                + "\n".join(faltas)
                + "\n\n¿Darla por revisada igual?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if resp != QMessageBox.Yes:
                return
        registro_id = self._actual["id"]
        fila = self.lista.currentRow()
        repo.marcar_transcripcion_revisada(self._con, registro_id, True)
        repo.log_auditoria(
            self._con, "edito",
            f"Registro #{registro_id}: transcripción desgrabada (pantalla Desgrabar)",
            self._caso_id,
        )
        self._con.commit()
        self.datos_cambiaron.emit()

        self._pendientes = self._cargar_pendientes()
        self._poblar_cola()
        if not self._pendientes:
            self._mostrar_vacio()
            return
        self._abrir(min(fila, len(self._pendientes) - 1))
        self.lbl_status.setText(
            f"Revisada. Quedan {len(self._pendientes)} por corregir."
        )

    def _ver_en_tabla(self) -> None:
        if self._actual is not None:
            self.ir_a_registro.emit(self._actual["id"])

    # --------------------------- la entrega ------------------------------
    def candidatas_a_entregar(self) -> list[sqlite3.Row]:
        """Lo desgrabado en esta causa que todavía no salió en ningún informe."""
        if self._caso_id is None:
            return []
        return repo.desgrabadas_sin_informar(self._con, self._caso_id)

    def _entregar_desgrabacion(self) -> None:
        """Saca en un Word lo desgrabado y no entregado, sin volver a elegirlo.

        Va por el mismo exportador y el mismo lote que el informe de la Tabla
        TOTAL: no es una segunda vía de salida, es un atajo a la que ya existe.
        Si saliera por otro lado, Exportaciones dejaría de ser el registro
        completo de lo que se le entregó al juzgado, que es justamente para lo
        que sirve.
        """
        if self._caso_id is None:
            return
        # Lo que se está corrigiendo ahora todavía no está guardado en la base.
        if self._sincro is not None:
            self._sincro.cerrar_editores()

        candidatas = self.candidatas_a_entregar()
        if not candidatas:
            QMessageBox.information(
                self, "Entregar desgrabación",
                "No hay desgrabaciones pendientes de entrega.\n\n"
                "Acá sale lo que está dado por revisado y todavía no se informó. "
                "Si terminaste una comunicación, cerrala con Ctrl+G.",
            )
            return

        dlg = DialogoEntregaDesgrabacion(
            candidatas, hoy_desde=repo.comienzo_de_hoy(),
            analista=sesion.analista(), parent=self,
        )
        if dlg.exec() != QDialog.Accepted:
            return

        caso = repo.obtener_caso(self._con, self._caso_id)
        nombre = (caso["nombre"] if caso else "caso").replace("/", "-")
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Entregar desgrabación",
            f"Desgrabacion_{nombre}.docx", "Word (*.docx)",
        )
        if not ruta:
            return
        try:
            destino = exportar_informe_judicial(
                self._con, self._caso_id, ruta,
                solo_ids=dlg.elegidas,
                fecha_recepcion=dlg.fecha_recepcion,
            )
        except InformeVacio as exc:
            QMessageBox.information(self, "Entregar desgrabación", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"No se pudo exportar:\n{exc}")
            return

        self.datos_cambiaron.emit()
        mostrar_exportacion(self, destino, "Desgrabación")

    # ------------------ interceptar las teclas del audio -----------------
    def showEvent(self, event) -> None:  # noqa: N802 (API de Qt)
        """El filtro vive lo que dura la pantalla a la vista, y ni un evento más.

        Un filtro puesto en la aplicación recibe TODO lo que pasa en el
        programa: cada tecla, cada repintado, cada temporizador de cada
        pantalla. Dejarlo puesto para siempre es cobrarle a toda la aplicación
        el costo de una pantalla que casi nunca está abierta —y al rehacer las
        pantallas (un cambio de tema) se iban acumulando uno encima de otro—.
        """
        super().showEvent(event)
        if not self._filtrando:
            QApplication.instance().installEventFilter(self)
            self._filtrando = True
        # El ancho de la columna se reparte recién acá: durante `_construir`
        # la pantalla todavía no tiene su tamaño real y el reparto terminaba
        # apretando la interpretación contra su mínimo.
        if not self._divisor_repartido and self.divisor.width() > 0:
            self._restaurar_divisor()
            self._divisor_repartido = True

    def hideEvent(self, event) -> None:  # noqa: N802 (API de Qt)
        super().hideEvent(event)
        self._soltar_filtro()
        # Irse a otra pantalla también anota el lugar: si después el programa
        # se cierra de golpe, ya quedó guardado dónde se estaba.
        self.recordar_lugar()

    def closeEvent(self, event) -> None:  # noqa: N802 (API de Qt)
        self._soltar_filtro()
        self.recordar_lugar()
        super().closeEvent(event)

    def _soltar_filtro(self) -> None:
        if self._filtrando:
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
            self._filtrando = False

    def _atajo_de_audio(self, tecla) -> bool:
        """Las teclas que SÓLO mueven el audio.

        Se separan porque son las únicas que siguen vivas mientras se escribe
        una interpretación: no escriben nada ni tocan ninguna frase, así que
        dejarlas andando no puede romper lo que se está redactando.
        """
        if tecla == Qt.Key_F3:
            self.reproductor.desplazar(-_SALTO_SEG)
            return True
        if tecla == Qt.Key_F4:
            self.reproductor.desplazar(_SALTO_SEG)
            return True
        if tecla == Qt.Key_F5:
            self._avisar_velocidad(self.reproductor.cambiar_velocidad_relativa(-1))
            return True
        if tecla == Qt.Key_F6:
            self._avisar_velocidad(self.reproductor.cambiar_velocidad_relativa(1))
            return True
        if tecla == Qt.Key_F9:
            self._repetir_la_frase_en_foco()
            return True
        return False

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (API de Qt)
        """Atiende los atajos del audio ANTES de que los vea el campo de texto.

        Un QShortcut no alcanza: el widget con el foco consume teclas y cuál
        consume cuál depende del widget. El filtro se instala en la aplicación
        —es la única forma de ver el evento antes que el editor— pero se limita
        a los momentos en que el foco está dentro de esta pantalla, así que en
        el resto del programa Escape y las de función siguen significando lo
        que significaban.

        Devolver True consume la tecla; el editor no se entera y el cursor no
        se mueve, que es todo el punto.
        """
        if event.type() != QEvent.KeyPress or not self.isVisible():
            return False
        # Barato y primero: la enorme mayoría de las teclas no son nuestras.
        if event.key() not in _TECLAS:
            return False
        foco = QApplication.focusWidget()
        if foco is not None and not self.isAncestorOf(foco) and foco is not self:
            return False

        tecla = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        shift = bool(mods & Qt.ShiftModifier)
        alt = bool(mods & Qt.AltModifier)
        escribiendo = _escribiendo(foco)

        # Ctrl+I abre o cierra el cuadro de interpretación, se esté donde se
        # esté. Es la única forma de entrar sin soltar el teclado.
        if tecla == Qt.Key_I and ctrl and not (alt or shift):
            self.alternar_interpretacion()
            return True

        # Escribiendo una interpretación, la pantalla cambia de modo: sólo se
        # atienden Escape (cerrar y guardar), Ctrl+Espacio y las que mueven el
        # audio. El resto son texto y tienen que llegar al cuadro.
        if self._interpretando:
            if tecla == Qt.Key_Escape and not ctrl:
                self.cerrar_interpretacion()
                return True
            if tecla == Qt.Key_Space and ctrl and not alt:
                self.reproductor.alternar()
                return True
            if tecla in _TECLAS_DE_AUDIO and not (ctrl or alt or shift):
                return self._atajo_de_audio(tecla)
            return False

        if tecla == Qt.Key_Escape and not ctrl:
            # Escribiendo, Escape lo atiende el editor: cierra la frase sin
            # guardar. Fuera del texto suelta lo que haya seleccionado, que es
            # lo que Escape significa en el resto del programa.
            if escribiendo:
                return False
            self._deseleccionar_todo()
            return True
        # La que queda para manejar el audio SIN soltar el texto: Escape ahora
        # deselecciona y Espacio es un espacio mientras se escribe, así que sin
        # esto, tipeando no habría forma de pausar.
        if tecla == Qt.Key_Space and ctrl and not alt:
            self.reproductor.alternar()
            return True
        # Espacio solo cuando NO se está escribiendo: si no, no se podría
        # separar dos palabras en la transcripción.
        if tecla == Qt.Key_Space and not (ctrl or alt) and not escribiendo:
            # Espacio NO es lo mismo que Escape. Escape pausa y sigue de donde
            # iba, que es transcribir de corrido. Espacio suena desde la marca
            # y al parar vuelve ahí, que es repasar un pedazo: apretar, oír,
            # apretar, y volver a oír exactamente lo mismo.
            self.reproductor.reproducir_desde_el_ancla()
            self.lbl_status.setText(
                f"Desde la marca en {_formato_mmss(self.reproductor.ancla())}"
            )
            return True
        # Marcar el tramo: Alt+Shift anda siempre —el editor de texto no las
        # usa—; Shift solo cuando no se está escribiendo, porque ahí Shift con
        # flechas es seleccionar texto y eso no se le puede sacar a nadie.
        if tecla in (Qt.Key_Left, Qt.Key_Right) and shift and (alt or not escribiendo):
            paso = _PASO_SELECCION * (4 if ctrl else 1)
            self.onda.mover_borde(
                paso if tecla == Qt.Key_Right else -paso,
                self.reproductor.posicion_actual_seg(),
            )
            return True
        if tecla == Qt.Key_F2 and self._sincro is not None:
            self._corregir_el_texto()
            return True
        if tecla == Qt.Key_F3:
            self.reproductor.desplazar(-_SALTO_SEG)
            return True
        if tecla == Qt.Key_F4:
            self.reproductor.desplazar(_SALTO_SEG)
            return True
        if tecla == Qt.Key_F5:
            self._avisar_velocidad(self.reproductor.cambiar_velocidad_relativa(-1))
            return True
        if tecla == Qt.Key_F6:
            self._avisar_velocidad(self.reproductor.cambiar_velocidad_relativa(1))
            return True
        if tecla == Qt.Key_F7 and self._sincro is not None:
            self.reproductor.saltar_a(self._sincro.segundo_de_la_frase_en_foco())
            return True
        if tecla == Qt.Key_F8 and self._sincro is not None:
            self._sincro.enfocar_lo_que_suena()
            return True
        if tecla == Qt.Key_F9:
            self._repetir_la_frase_en_foco()
            return True
        if ctrl and tecla in (Qt.Key_1, Qt.Key_2):
            self._atribuir("1" if tecla == Qt.Key_1 else "2")
            return True
        if ctrl and tecla == Qt.Key_T:
            if shift:
                self._acomodar_el_desfasaje()
            else:
                self._insertar_marca_de_tiempo()
            return True
        # Partir y unir son las dos correcciones más frecuentes sobre un
        # borrador de Whisper: junta dos turnos en un renglón y parte una sola
        # oración en tres. Las dos tienen que estar en el teclado.
        if ctrl and tecla in (Qt.Key_Return, Qt.Key_Enter) and self._sincro:
            self._sincro.dividir_el_foco()
            return True
        if ctrl and tecla == Qt.Key_U and self._sincro is not None:
            self._sincro.unir_el_foco_con_la_anterior()
            return True
        if ctrl and tecla == Qt.Key_Delete and self._sincro is not None:
            self._sincro.quitar_el_foco()
            self.lbl_status.setText("Frase quitada  ·  Ctrl+Z la trae de vuelta")
            return True
        if ctrl and tecla in (Qt.Key_Up, Qt.Key_Down) and self._sincro is not None:
            self._sincro.mover_foco(-1 if tecla == Qt.Key_Up else 1)
            return True
        if ctrl and tecla in (Qt.Key_Z, Qt.Key_Y) and self._sincro is not None:
            # Escribiendo, Ctrl+Z es el deshacer del campo de texto y no se le
            # puede sacar: ahí deshace lo tipeado. Fuera del texto deshace lo
            # que no tenía vuelta atrás —dividir, unir, quitar una frase—.
            if escribiendo:
                return False
            rehacer = tecla == Qt.Key_Y or shift
            que = (
                self._sincro.rehacer() if rehacer else self._sincro.deshacer()
            )
            self.lbl_status.setText(
                f"{'Rehecho' if rehacer else 'Deshecho'}: {que}" if que
                else ("Nada para rehacer" if rehacer else "Nada para deshacer")
            )
            return True
        if ctrl and tecla == Qt.Key_G:
            self._dar_por_revisada()
            return True
        return False

    def _deseleccionar_todo(self) -> None:
        """Escape fuera del texto: suelta el tramo y deja de repetir.

        Se mira también el tramo del REPRODUCTOR y no solo el dibujo: son dos
        estados distintos y el que acota el audio es el del reproductor. Si
        alguna vez quedaran desfasados, Escape tiene que poder destrabar igual.
        """
        habia = (
            self.onda.lienzo.seleccion() is not None
            or self.onda.btn_bucle.isChecked()
            or self.reproductor.tramo() is not None
        )
        self.onda.btn_bucle.setChecked(False)
        self.onda.limpiar_seleccion()
        if habia:
            self.lbl_status.setText("Sin selección: el audio vuelve a sonar entero")

    def _corregir_el_texto(self) -> None:
        """F2: para el audio y abre la frase que se estaba escuchando.

        El gesto real es "pará, quiero arreglar lo que acabo de oír". Si el
        audio siguiera corriendo, para cuando se termina de escribir la frase
        marcada ya es otra y el próximo atajo cae en el lugar equivocado; y
        además hay que volver atrás a mano para escuchar de nuevo. Al reanudar,
        el retroceso automático devuelve el contexto solo.
        """
        if self._sincro is None:
            return
        sonaba = self.reproductor.esta_reproduciendo()
        if sonaba:
            self.reproductor.alternar()
        # F2 sí abre con todo marcado: es la tecla de reescribir de un tirón.
        self._sincro.enfocar(
            self._sincro.indice_en_foco(), seleccionar_todo=True
        )
        self.lbl_status.setText(
            "Audio en pausa para corregir — Enter guarda y Ctrl+Espacio sigue"
            if sonaba else "Corrigiendo la frase — Enter guarda y cierra"
        )

    def _repetir_la_frase_en_foco(self) -> None:
        """F8: deja dando vueltas la frase que se está escribiendo.

        Sin selección previa el tramo es el de esa frase, que es el caso real:
        no se entiende ESTA frase, no un rango cualquiera del audio.
        """
        if self._sincro is not None and not self.onda.btn_bucle.isChecked():
            indice = self._sincro.indice_en_foco()
            segmentos = self._sincro.segmentos()
            if 0 <= indice < len(segmentos):
                s = segmentos[indice]
                inicio = float(s.get("inicio") or 0.0)
                fin = float(s.get("fin") or inicio)
                self.onda.set_tramo_por_defecto((inicio, max(fin, inicio + 0.5)))
        self.onda.btn_bucle.toggle()

    def _avisar_velocidad(self, factor: float) -> None:
        self.lbl_status.setText(
            f"Velocidad {factor:g}×".replace(".", ",")
            + ("   (el tono no cambia)" if factor != 1.0 else "")
        )
