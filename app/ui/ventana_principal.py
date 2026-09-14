"""Ventana principal: topbar + sidebar de navegación + stack de pantallas."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import repositorios as repo
from app import sesion
from app.ui import tema
from app.ui.atajos import mostrar_atajos
from app.ui.dialogos import pedir_analista
from app.ui.pantalla_auditoria import PantallaAuditoria
from app.ui.pantalla_casos import PantallaCasos
from app.ui.pantalla_corregir import PantallaCorregir
from app.ui.pantalla_exportaciones import PantallaExportaciones
from app.ui.pantalla_grafo import PantallaGrafo
from app.ui.pantalla_importar import PantallaImportar
from app.ui.pantalla_indice import PantallaIndice
from app.ui.pantalla_mapa import PantallaMapa
from app.ui.pantalla_papelera import PantallaPapelera
from app.ui.pantalla_resumen import PantallaResumen
from app.ui.pantalla_timeline import PantallaTimeline
from app.ui.pantalla_total import PantallaTotal
from app.ui.pantalla_validaciones import PantallaValidaciones
from app.ui.pantalla_vinculos import PantallaVinculos

# Las once pantallas agrupadas por fase del trabajo. El orden es el mismo de
# siempre: los índices del stack se derivan de esta lista y las pantallas se
# agregan en ese orden, así que agrupar no mueve nada de lugar.
_GRUPOS = [
    ("PREPARAR", [
        ("Casos", False),
        ("Importar", True),
    ]),
    ("TRABAJAR", [
        ("Resumen", True),
        ("Tabla TOTAL", True),
        ("Desgrabar", True),
        ("Índice", True),
        ("Validaciones", True),
    ]),
    ("ANALIZAR", [
        ("Mapa", True),
        ("Grafo", True),
        ("Timeline", True),
        ("Vínculos", True),
    ]),
    ("CERRAR", [
        ("Exportaciones", True),
        ("Papelera", True),
        ("Auditoría", False),
    ]),
]
_ENTRADAS = [entrada for _titulo, entradas in _GRUPOS for entrada in entradas]
# Nombres que tuvo una pantalla antes. Solo sirven para que un rastro de sesión
# viejo siga abriendo donde el analista había quedado: sin esto, el primer
# arranque después de un renombre lo devuelve a Casos sin explicación.
_ANTES_SE_LLAMABA = {"Corregir": "Desgrabar"}
_IDX = {etiqueta: i for i, (etiqueta, _req) in enumerate(_ENTRADAS)}
_IDX_RESUMEN = _IDX["Resumen"]
_IDX_TOTAL = _IDX["Tabla TOTAL"]
_IDX_CORREGIR = _IDX["Desgrabar"]
_IDX_INDICE = _IDX["Índice"]
_IDX_VALIDACIONES = _IDX["Validaciones"]
_IDX_MAPA = _IDX["Mapa"]
_IDX_GRAFO = _IDX["Grafo"]
_IDX_TIMELINE = _IDX["Timeline"]
_IDX_VINCULOS = _IDX["Vínculos"]
_IDX_EXPORTACIONES = _IDX["Exportaciones"]
_IDX_PAPELERA = _IDX["Papelera"]
_IDX_AUDITORIA = _IDX["Auditoría"]


class _MapaPendiente(QWidget):
    """Ocupa el lugar del Mapa hasta que alguien entra a esa pantalla.

    El Mapa monta un QtWebEngine, que es lo más caro de todo el arranque —casi
    la mitad del tiempo hasta ver la ventana— y se construía siempre, aunque la
    causa no se mirara nunca en el mapa. Este marcador no cuesta nada; la
    pantalla de verdad se arma la primera vez que se la abre.
    """

    def __init__(self) -> None:
        super().__init__()
        self.caso_id: int | None = None
        lay = QVBoxLayout(self)
        aviso = QLabel("Preparando el mapa...")
        aviso.setObjectName("subtitulo")
        aviso.setAlignment(Qt.AlignCenter)
        lay.addWidget(aviso)

    def set_caso(self, caso_id: int) -> None:
        self.caso_id = caso_id

    def refrescar(self) -> None:
        pass


class VentanaPrincipal(QMainWindow):
    """Contenedor raíz de la aplicación."""

    def __init__(self, con: sqlite3.Connection) -> None:
        super().__init__()
        self._con = con
        self._caso_id: int | None = None
        self._caso_nombre = ""
        # Se lee ANTES de construir nada. Armar la ventana navega —arranca en
        # Casos, abrir una causa entra por el Resumen— y cada navegación anota
        # el lugar, así que para cuando se quisiera leer ya estaría pisado por
        # el propio arranque.
        self._lugar_inicial = sesion.lugar()
        self.setWindowTitle("Sistema de Gestión de Escuchas Diferidas")
        # Tamaño inicial acotado a la pantalla disponible (evita que la ventana
        # se salga de pantalla en monitores chicos o con escalado).
        from PySide6.QtGui import QGuiApplication
        disp = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(min(1340, disp.width() - 40), min(760, disp.height() - 60))
        self.setMinimumSize(900, 560)
        self._construir()

    def _construir(self) -> None:
        central = QWidget()
        central.setObjectName("fondo")
        raiz = QVBoxLayout(central)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)
        raiz.addWidget(self._crear_topbar())

        cuerpo = QHBoxLayout()
        cuerpo.setContentsMargins(0, 0, 0, 0)
        cuerpo.setSpacing(0)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(190)
        # Los títulos de grupo son filas del propio QListWidget, así que la fila
        # del sidebar deja de coincidir con el índice del stack: se traduce con
        # estos dos mapas.
        self._fila_de_stack: dict[int, int] = {}
        self._stack_de_fila: dict[int, int] = {}
        for titulo, entradas in _GRUPOS:
            self._agregar_titulo_grupo(titulo)
            for etiqueta, _req in entradas:
                fila = self.sidebar.count()
                indice = _IDX[etiqueta]
                self._fila_de_stack[indice] = fila
                self._stack_de_fila[fila] = indice
                QListWidgetItem(etiqueta, self.sidebar)
        self.sidebar.currentRowChanged.connect(self._cambiar_pantalla)
        cuerpo.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self._crear_pantallas()
        cuerpo.addWidget(self.stack, 1)

        raiz.addLayout(cuerpo, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Listo")

        self._conectar_pantallas()

        # Ctrl+B: la convención de casi todos los editores para el panel
        # lateral. No la pisa el filtro de Desgrabar, que sólo mira las suyas.
        atajo_menu = QShortcut(QKeySequence("Ctrl+B"), self)
        atajo_menu.activated.connect(self.alternar_menu)

        atajo_ayuda = QShortcut(QKeySequence("F1"), self)
        atajo_ayuda.activated.connect(lambda: mostrar_atajos(self))

        self.sidebar.setCurrentRow(self._fila_de_stack[_IDX["Casos"]])
        # Si se dejó oculto, se abre oculto: al analista que trabaja todo el
        # día en Desgrabar no hay que hacerle esconderlo cada mañana.
        self.mostrar_menu(not sesion.preferencia(self._PREF_MENU))
        self._actualizar_disponibilidad()
        self._retomar_donde_quedo()

    # --------------------------- retomar la sesión --------------------------
    def _retomar_donde_quedo(self) -> None:
        """Vuelve a la causa y la pantalla donde se cerró el programa.

        Un analista trabaja una causa por vez y durante semanas: obligarlo a
        elegirla de una lista cada mañana no es una decisión, es un trámite. Lo
        que se guarda es el LUGAR, no el trabajo —eso ya está en la base desde
        que se escribió—, así que si la causa se borró o el archivo del perfil
        se perdió, lo único que pasa es que arranca en Casos como antes.
        """
        lugar = self._lugar_inicial
        caso_id = lugar.get("caso_id")
        if not isinstance(caso_id, int):
            return
        caso = repo.obtener_caso(self._con, caso_id)
        if caso is None:
            # Se borró la causa: el rastro no sirve más y confunde.
            sesion.olvidar_lugar()
            return
        self._abrir_caso(caso_id, caso["nombre"])
        pantalla = lugar.get("pantalla")
        pantalla = _ANTES_SE_LLAMABA.get(pantalla, pantalla)
        if isinstance(pantalla, str) and pantalla in _IDX:
            indice = _IDX[pantalla]
            _etiqueta, requiere = _ENTRADAS[indice]
            if not requiere or self._caso_id is not None:
                self.sidebar.setCurrentRow(self._fila_de_stack[indice])
        self.statusBar().showMessage(
            f"Se retomó «{caso['nombre']}», donde quedaste la última vez", 8000
        )

    def closeEvent(self, event) -> None:  # noqa: N802 (API de Qt)
        # Última anotación antes de irse: las pantallas guardan lo suyo cuando
        # cambia, pero el segundo del audio se mueve todo el tiempo y solo tiene
        # sentido anotarlo al cerrar.
        self.p_corregir.recordar_lugar()
        sesion.recordar_lugar(caso_id=self._caso_id)
        super().closeEvent(event)

    def _reconstruir_pantallas(self) -> None:
        """Rehace las pantallas para que tomen la paleta nueva.

        El Mapa se conserva: crearlo levanta un QtWebEngine entero, que en un
        equipo sin GPU utilizable tarda decenas de segundos —cambiar de tema
        pasaba a ser una espera, no un clic—. Su parte temática (leyenda,
        rótulos, exportación PNG) se dibuja en `refrescar()`, así que basta con
        refrescarlo. Quedan con la paleta vieja hasta el próximo arranque un
        separador y un cartel de error suyos, que se construyen una sola vez.
        """
        # Si todavía es el marcador no hay nada que conservar: que se rehaga
        # como marcador y el QtWebEngine siga sin construirse.
        conservados = (
            {} if isinstance(self.p_mapa, _MapaPendiente) else {"p_mapa": self.p_mapa}
        )
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            if w not in conservados.values():
                w.deleteLater()
        self._crear_pantallas(conservados)
        self._conectar_pantallas()
        self.p_mapa.refrescar()

    def _crear_pantallas(self, conservados: dict | None = None) -> None:
        conservados = conservados or {}
        self.p_casos = PantallaCasos(self._con)
        self.p_importar = PantallaImportar(self._con)
        self.p_resumen = PantallaResumen(self._con)
        self.p_total = PantallaTotal(self._con)
        self.p_corregir = PantallaCorregir(self._con)
        self.p_indice = PantallaIndice(self._con)
        self.p_validaciones = PantallaValidaciones(self._con)
        self.p_mapa = conservados.get("p_mapa") or _MapaPendiente()
        self.p_grafo = PantallaGrafo(self._con)
        self.p_timeline = PantallaTimeline(self._con)
        self.p_vinculos = PantallaVinculos(self._con)
        self.p_exportaciones = PantallaExportaciones(self._con)
        self.p_papelera = PantallaPapelera(self._con)
        self.p_auditoria = PantallaAuditoria(self._con)
        for w in (self.p_casos, self.p_importar, self.p_resumen, self.p_total,
                  self.p_corregir, self.p_indice,
                  self.p_validaciones, self.p_mapa, self.p_grafo,
                  self.p_timeline, self.p_vinculos, self.p_exportaciones,
                  self.p_papelera, self.p_auditoria):
            self.stack.addWidget(w)

    def _conectar_pantallas(self) -> None:
        self.p_casos.caso_abierto.connect(self._abrir_caso)
        self.p_resumen.ir_a_pantalla.connect(self._ir_a_pantalla)
        self.p_resumen.seguir_escuchando.connect(self._seguir_escuchando)
        self.p_resumen.ver_cd.connect(self._ver_cd)
        self.p_casos.caso_vaciado.connect(self._tras_vaciar_caso)
        self.p_casos.caso_borrado.connect(self._tras_borrar_caso)
        self.p_importar.importacion_finalizada.connect(self._tras_importar)
        self.p_total.datos_cambiaron.connect(self._actualizar_badge_avisos)
        self.p_total.datos_cambiaron.connect(self.p_papelera.refrescar)
        # Transcribir en lote llena la cola de Corregir, y dar por revisada allá
        # apaga el ✓ de la columna «Rev.» acá: las dos pantallas miran el mismo
        # dato y tienen que enterarse una de la otra.
        self.p_total.datos_cambiaron.connect(self.p_corregir.refrescar)
        self.p_corregir.datos_cambiaron.connect(self.p_total.refrescar)
        self.p_corregir.ir_a_registro.connect(self._ir_a_registro)
        self.p_indice.datos_cambiaron.connect(self._tras_editar_indice)
        self.p_validaciones.ir_a_registro.connect(self._ir_a_registro)
        self.p_validaciones.aviso_resuelto.connect(self._actualizar_badge_avisos)
        self.p_exportaciones.lote_deshecho.connect(self._tras_deshacer_lote)
        self.p_papelera.datos_cambiaron.connect(self._tras_restaurar)

    # --------------------------- el menú lateral --------------------------
    _PREF_MENU = "menu_oculto"

    def alternar_menu(self) -> None:
        """Muestra u oculta el menú lateral, y lo recuerda.

        En Desgrabar el menú no se usa —se trabaja una comunicación tras otra
        sin cambiar de pantalla— y esos 190 px se los está sacando a la lista
        de frases y a la onda.
        """
        self.mostrar_menu(not self.sidebar.isVisible())

    def mostrar_menu(self, visible: bool) -> None:
        self.sidebar.setVisible(visible)
        # Oculto, el botón queda como única forma de volver: que se note que
        # hay algo escondido y no parezca que el menú se perdió.
        self.btn_menu.setText("◧" if visible else "▶")
        self.btn_menu.setToolTip(
            "Ocultar el menú lateral  (Ctrl+B)" if visible
            else "Mostrar el menú lateral  (Ctrl+B)"
        )
        sesion.set_preferencia(self._PREF_MENU, "" if visible else "1")

    def menu_visible(self) -> bool:
        return self.sidebar.isVisible()

    def _crear_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topbar")
        bar.setFixedHeight(52)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(18, 0, 18, 0)
        lay.setSpacing(16)

        # El ◧ era un adorno de la marca; pasa a ser el interruptor del menú.
        # En Desgrabar el menú no se usa y esos 190 px se los saca al trabajo.
        self.btn_menu = QPushButton("◧")
        self.btn_menu.setObjectName("analista")
        self.btn_menu.setFixedWidth(34)
        self.btn_menu.setToolTip("Mostrar u ocultar el menú lateral  (Ctrl+B)")
        self.btn_menu.clicked.connect(self.alternar_menu)
        lay.addWidget(self.btn_menu)

        marca = QLabel("Escuchas Diferidas")
        marca.setObjectName("brand")
        lay.addWidget(marca)

        self.lbl_caso = QLabel("Ningún caso abierto")
        self.lbl_caso.setObjectName("caseTag")
        lay.addWidget(self.lbl_caso)
        lay.addStretch(1)

        self.txt_buscar = QLineEdit()
        self.txt_buscar.setObjectName("buscador")
        self.txt_buscar.setPlaceholderText("🔍  Buscar abonado, antena, fecha...")
        self.txt_buscar.setFixedWidth(300)
        self.txt_buscar.setEnabled(False)
        self.txt_buscar.returnPressed.connect(self._buscar_global)
        lay.addWidget(self.txt_buscar)

        # Quién firma lo que se haga en esta sesión. Va a la vista porque el
        # nombre se persiste entre arranques: sin verlo, es fácil trabajar una
        # jornada entera firmando con el nombre del turno anterior.
        self.btn_analista = QPushButton()
        self.btn_analista.setObjectName("analista")
        self.btn_analista.setCursor(Qt.PointingHandCursor)
        self.btn_analista.clicked.connect(self._cambiar_analista)
        self._pintar_analista()
        lay.addWidget(self.btn_analista)

        # Los atajos no se descubren solos: hay que dejar dónde mirarlos.
        self.btn_ayuda = QPushButton("?")
        self.btn_ayuda.setObjectName("analista")
        self.btn_ayuda.setFixedWidth(32)
        self.btn_ayuda.setCursor(Qt.PointingHandCursor)
        self.btn_ayuda.setToolTip("Atajos de teclado  ·  F1")
        self.btn_ayuda.clicked.connect(lambda: mostrar_atajos(self))
        lay.addWidget(self.btn_ayuda)

        self.btn_tema = QPushButton()
        self.btn_tema.setObjectName("analista")
        self.btn_tema.setFixedWidth(32)
        self.btn_tema.setCursor(Qt.PointingHandCursor)
        self.btn_tema.clicked.connect(self._alternar_tema)
        self._pintar_boton_tema()
        lay.addWidget(self.btn_tema)
        return bar

    def _pintar_boton_tema(self) -> None:
        # El botón muestra a dónde se va, no dónde se está: es lo que espera
        # quien lo va a apretar.
        claro = tema.modo() == "claro"
        self.btn_tema.setText("☾" if claro else "☀")
        self.btn_tema.setToolTip(
            "Cambiar a modo oscuro" if claro else "Cambiar a modo claro"
        )

    def _alternar_tema(self) -> None:
        self.cambiar_tema("oscuro" if tema.modo() == "claro" else "claro")

    def cambiar_tema(self, modo: str) -> None:
        """Aplica la paleta y reconstruye las pantallas con los colores nuevos.

        La hoja de estilos global se puede recambiar en caliente, pero muchos
        widgets fijan su color al construirse (`setStyleSheet` con un valor de
        `tema`). Reconstruir el stack es lo que hace que no quede la mitad de la
        pantalla con la paleta vieja. Se paga perdiendo los filtros y la fila
        seleccionada; a cambio, cambiar de tema no deja nada a medio pintar.
        """
        aplicado = tema.set_modo(modo)
        sesion.set_preferencia("tema", aplicado)

        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(tema.QSS)

        caso_id, nombre = self._caso_id, self._caso_nombre
        indice_actual = self.stack.currentIndex()
        self._reconstruir_pantallas()
        if caso_id is not None:
            self._abrir_caso(caso_id, nombre)
            self.sidebar.setCurrentRow(self._fila_de_stack[indice_actual])
        self._pintar_boton_tema()
        self.statusBar().showMessage(f"Modo {aplicado}", 4000)

    def _pintar_analista(self) -> None:
        nombre = sesion.analista() or "sin identificar"
        self.btn_analista.setText(f"👤  {nombre}")
        self.btn_analista.setToolTip(
            f"Las ediciones, informes y avisos que resuelvas quedan firmados "
            f"como «{nombre}». Clic para cambiarlo."
        )

    def _cambiar_analista(self) -> None:
        if pedir_analista(self) is not None:
            self._pintar_analista()
            self.statusBar().showMessage(
                f"A partir de ahora se firma como {sesion.analista()}", 6000
            )

    # ----------------------------- lógica ----------------------------------
    def _abrir_caso(self, caso_id: int, nombre: str) -> None:
        if caso_id != self._caso_id:
            # Cambiar de causa invalida el lugar de la anterior: la
            # comunicación que se estaba corrigiendo no existe en esta.
            sesion.recordar_lugar(registro_id=0, segundo=0.0)
        self._caso_id = caso_id
        self._caso_nombre = nombre
        # Las causas que ya venían trabajándose no tienen Interlocutor: la
        # columna no existía cuando se importaron. Se completa una sola vez, al
        # abrirlas, en vez de dejarlas mostrando huecos hasta que alguien
        # renombre un abonado.
        repo.completar_nombres_faltantes(self._con, caso_id)
        self.lbl_caso.setText(f"Causa activa: {nombre}")
        self.txt_buscar.setEnabled(True)
        self.p_importar.set_caso(caso_id)
        self.p_resumen.set_caso(caso_id)
        self.p_total.set_caso(caso_id)
        self.p_corregir.set_caso(caso_id)
        self.p_indice.set_caso(caso_id)
        self.p_validaciones.set_caso(caso_id)
        self.p_mapa.set_caso(caso_id)
        self.p_grafo.set_caso(caso_id)
        self.p_timeline.set_caso(caso_id)
        self.p_vinculos.set_caso(caso_id)
        self.p_exportaciones.set_caso(caso_id)
        self.p_papelera.set_caso(caso_id)
        self.p_auditoria.set_caso(caso_id)
        self._actualizar_disponibilidad()
        self._actualizar_badge_avisos()
        # Se entra por el Resumen, no por la grilla: abrir una causa de meses
        # atrás y toparse con 400 filas sin contexto no ayudaba a retomarla.
        self.sidebar.setCurrentRow(self._fila_de_stack[_IDX_RESUMEN])

    def _buscar_global(self) -> None:
        if self._caso_id is None:
            return
        self.sidebar.setCurrentRow(self._fila_de_stack[_IDX_TOTAL])
        self.p_total.buscar(self.txt_buscar.text())

    def _ir_a_pantalla(self, etiqueta: str) -> None:
        """Navegación pedida por una pantalla (los botones del Resumen)."""
        indice = _IDX.get(etiqueta)
        if indice is not None:
            self.sidebar.setCurrentRow(self._fila_de_stack[indice])

    def _ver_cd(self, numero: str) -> None:
        """Del Resumen a la Tabla TOTAL, filtrada a esa entrega."""
        self.sidebar.setCurrentRow(self._fila_de_stack[_IDX_TOTAL])
        self.p_total.filtrar_por_cd(numero)

    def _seguir_escuchando(self) -> None:
        self.sidebar.setCurrentRow(self._fila_de_stack[_IDX_TOTAL])
        self.p_total.filtrar_pendientes()

    def _tras_importar(self) -> None:
        self.p_resumen.refrescar()
        self.p_total.refrescar()
        self.p_indice.refrescar()
        self.p_validaciones.refrescar()
        self.p_mapa.refrescar()
        self.p_grafo.refrescar()
        self.p_timeline.refrescar()
        self._actualizar_badge_avisos()

    def _tras_editar_indice(self) -> None:
        self.p_total.refrescar()
        self.p_grafo.refrescar()
        self.p_mapa.refrescar()
        # El timeline también colorea por abonado: sin esto quedaba con los
        # colores viejos hasta cambiar de caso.
        self.p_timeline.refrescar()

    def _tras_borrar_caso(self, caso_id: int) -> None:
        """La causa ya no existe: si era la abierta, hay que soltarla.

        Sin esto las once pantallas quedan mostrando registros de una causa
        borrada y el primer refresco falla contra filas que no están.
        """
        if caso_id != self._caso_id:
            return
        self._caso_id = None
        self._caso_nombre = ""
        self.lbl_caso.setText("Ningún caso abierto")
        self.txt_buscar.setEnabled(False)
        self.txt_buscar.clear()
        self._actualizar_badge_avisos()
        self._actualizar_disponibilidad()
        self.sidebar.setCurrentRow(self._fila_de_stack[_IDX["Casos"]])
        self.statusBar().showMessage("Causa eliminada", 6000)

    def _tras_vaciar_caso(self, caso_id: int) -> None:
        if caso_id == self._caso_id:
            self._tras_importar()

    def _ir_a_registro(self, registro_id: int) -> None:
        """Abre la Tabla TOTAL y selecciona el registro del aviso."""
        self.sidebar.setCurrentRow(self._fila_de_stack[_IDX_TOTAL])
        self.p_total.refrescar()
        self.p_total.seleccionar_registro(registro_id)

    def _tras_restaurar(self) -> None:
        """Volvió material a la causa: todas las vistas tienen que enterarse."""
        self._tras_importar()

    def _tras_deshacer_lote(self) -> None:
        self.p_total.refrescar()
        self._actualizar_badge_avisos()

    def _agregar_titulo_grupo(self, titulo: str) -> None:
        """Fila de encabezado: ni seleccionable ni navegable con el teclado."""
        item = QListWidgetItem(titulo, self.sidebar)
        item.setFlags(Qt.NoItemFlags)
        item.setForeground(QColor(tema.TEXT_MUTED))
        fuente = item.font()
        fuente.setPointSize(max(7, fuente.pointSize() - 2))
        fuente.setBold(True)
        item.setFont(fuente)
        item.setSizeHint(QSize(0, 30))

    def _actualizar_badge_avisos(self) -> None:
        """Refleja la cantidad de avisos pendientes en la entrada del sidebar."""
        item = self.sidebar.item(self._fila_de_stack[_IDX_VALIDACIONES])
        if self._caso_id is None:
            item.setText("Validaciones")
            return
        pend = repo.contar_avisos_pendientes(self._con, self._caso_id)
        item.setText(f"Validaciones  ●{pend}" if pend else "Validaciones")

    def _actualizar_disponibilidad(self) -> None:
        hay_caso = self._caso_id is not None
        for fila, indice in self._stack_de_fila.items():
            _etiqueta, requiere = _ENTRADAS[indice]
            item = self.sidebar.item(fila)
            flags = item.flags()
            if requiere and not hay_caso:
                item.setFlags(flags & ~Qt.ItemIsEnabled)
            else:
                item.setFlags(flags | Qt.ItemIsEnabled)

    def _cambiar_pantalla(self, fila: int) -> None:
        indice = self._stack_de_fila.get(fila)
        if indice is None:
            # Título de grupo o fila inválida: no hay pantalla que mostrar.
            return
        _etiqueta, requiere = _ENTRADAS[indice]
        if requiere and self._caso_id is None:
            self.sidebar.setCurrentRow(self._fila_de_stack[_IDX["Casos"]])
            return
        self.stack.setCurrentIndex(indice)
        sesion.recordar_lugar(pantalla=_ENTRADAS[indice][0])
        refrescos = {
            _IDX_RESUMEN: self.p_resumen,
            _IDX_TOTAL: self.p_total,
            _IDX_CORREGIR: self.p_corregir,
            _IDX_INDICE: self.p_indice,
            _IDX_VALIDACIONES: self.p_validaciones,
            _IDX_MAPA: self.p_mapa,
            _IDX_GRAFO: self.p_grafo,
            _IDX_TIMELINE: self.p_timeline,
            _IDX_VINCULOS: self.p_vinculos,
            _IDX_EXPORTACIONES: self.p_exportaciones,
            _IDX_PAPELERA: self.p_papelera,
            _IDX_AUDITORIA: self.p_auditoria,
        }
        if indice == _IDX_MAPA and isinstance(self.p_mapa, _MapaPendiente):
            self._materializar_mapa()
        pantalla = refrescos.get(indice)
        if pantalla is not None:
            pantalla.refrescar()

    def _materializar_mapa(self) -> None:
        """Construye el Mapa de verdad y lo pone en el lugar del marcador."""
        marcador = self.p_mapa
        caso_id = getattr(marcador, "caso_id", None)
        self.p_mapa = PantallaMapa(self._con)
        self.stack.insertWidget(_IDX_MAPA, self.p_mapa)
        self.stack.removeWidget(marcador)
        marcador.deleteLater()
        if caso_id is not None:
            self.p_mapa.set_caso(caso_id)
        self.stack.setCurrentIndex(_IDX_MAPA)
