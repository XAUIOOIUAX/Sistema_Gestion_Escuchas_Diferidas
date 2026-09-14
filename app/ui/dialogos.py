"""Diálogos reutilizables de la UI."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import sesion
from app.core.colores import PALETA_BASE, normalizar_color_hex
from app.ui import tema


def abrir_archivo(ruta: str | Path) -> None:
    """Abre un archivo con la aplicación predeterminada del sistema."""
    ruta = Path(ruta)
    if sys.platform == "win32":
        os.startfile(str(ruta))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(ruta)])
    else:
        subprocess.Popen(["xdg-open", str(ruta)])


def abrir_carpeta(ruta: str | Path) -> None:
    """Abre el explorador en la carpeta del archivo, seleccionándolo si se puede."""
    ruta = Path(ruta)
    carpeta = ruta.parent if ruta.is_file() else ruta
    if sys.platform == "win32":
        if ruta.is_file():
            # /select resalta el archivo dentro del explorador.
            subprocess.Popen(["explorer", "/select,", str(ruta)])
        else:
            os.startfile(str(carpeta))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(carpeta)])
    else:
        subprocess.Popen(["xdg-open", str(carpeta)])


class DialogoExportacion(QDialog):
    """Confirma una exportación y ofrece abrir el archivo o su carpeta."""

    def __init__(self, ruta: str | Path, titulo: str = "Exportación", parent=None) -> None:
        super().__init__(parent)
        self._ruta = Path(ruta)
        self.setWindowTitle(titulo)
        self.setMinimumWidth(460)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(12)

        icono = QLabel("✓  Archivo generado correctamente")
        icono.setStyleSheet(
            f"color:{tema.TEAL}; font-size:14px; font-weight:600;"
        )
        lay.addWidget(icono)

        detalle = QLabel(str(self._ruta))
        detalle.setWordWrap(True)
        detalle.setStyleSheet(
            f"color:{tema.TEXT_MUTED}; font-family:'IBM Plex Mono','Consolas',"
            "monospace; font-size:11px;"
        )
        lay.addWidget(detalle)

        botones = QHBoxLayout()
        botones.setSpacing(8)

        btn_archivo = QPushButton("Abrir archivo")
        btn_archivo.setObjectName("primary")
        btn_archivo.clicked.connect(self._abrir_archivo)
        botones.addWidget(btn_archivo)

        btn_carpeta = QPushButton("Abrir carpeta")
        btn_carpeta.clicked.connect(self._abrir_carpeta)
        botones.addWidget(btn_carpeta)

        botones.addStretch(1)

        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.clicked.connect(self.accept)
        botones.addWidget(btn_cerrar)

        lay.addLayout(botones)

    def _abrir_archivo(self) -> None:
        try:
            abrir_archivo(self._ruta)
        except OSError:
            pass
        self.accept()

    def _abrir_carpeta(self) -> None:
        try:
            abrir_carpeta(self._ruta)
        except OSError:
            pass
        self.accept()


def mostrar_exportacion(parent: QWidget | None, ruta: str | Path,
                        titulo: str = "Exportación") -> None:
    """Atajo: crea y muestra el diálogo de exportación modal."""
    DialogoExportacion(ruta, titulo, parent).exec()


class DialogoColorAbonado(QDialog):
    """Elige el color de un abonado: paleta base o un color libre.

    La paleta se ofrece primero porque son los colores calibrados para el tema
    oscuro y bien diferenciables entre sí; el selector libre queda como salida
    para cuando se necesita un color concreto.
    """

    _COLUMNAS = 6

    def __init__(self, color_actual: str, etiqueta: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Color del abonado")
        self.setModal(True)
        try:
            self._actual = normalizar_color_hex(color_actual)
        except ValueError:
            self._actual = ""
        self.color: str | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(12)

        if etiqueta:
            cab = QLabel(etiqueta)
            cab.setObjectName("subtitulo")
            lay.addWidget(cab)

        grilla = QGridLayout()
        grilla.setSpacing(6)
        for i, color in enumerate(PALETA_BASE):
            grilla.addWidget(
                self._boton_muestra(color), i // self._COLUMNAS,
                i % self._COLUMNAS,
            )
        lay.addLayout(grilla)

        pie = QHBoxLayout()
        btn_libre = QPushButton("Color personalizado…")
        btn_libre.clicked.connect(self._elegir_libre)
        pie.addWidget(btn_libre)
        pie.addStretch(1)
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.clicked.connect(self.reject)
        pie.addWidget(btn_cancelar)
        lay.addLayout(pie)

    def _boton_muestra(self, color: str) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(38, 38)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(color)
        # El actual se marca con un borde claro grueso; el resto, borde sutil.
        es_actual = color.upper() == self._actual
        borde = f"2px solid {tema.TEXT_PRIMARY}" if es_actual else f"1px solid {tema.LINE}"
        btn.setStyleSheet(
            f"QPushButton {{ background: {color}; border: {borde};"
            f" border-radius: 6px; padding: 0; }}"
        )
        btn.clicked.connect(lambda _=False, c=color: self._elegir(c))
        return btn

    def _elegir(self, color: str) -> None:
        self.color = normalizar_color_hex(color)
        self.accept()

    def _elegir_libre(self) -> None:
        inicial = QColor(self._actual) if self._actual else QColor("#888888")
        elegido = QColorDialog.getColor(inicial, self, "Color del abonado")
        if elegido.isValid():
            self.color = normalizar_color_hex(elegido.name())
            self.accept()


def elegir_color_abonado(parent: QWidget | None, color_actual: str,
                         etiqueta: str = "") -> str | None:
    """Muestra el selector y devuelve el color elegido, o None si se canceló."""
    dlg = DialogoColorAbonado(color_actual, etiqueta, parent)
    if dlg.exec() == QDialog.Accepted:
        return dlg.color
    return None


class DialogoAnalista(QDialog):
    """Pide el nombre con el que se firman las anotaciones de la sesión.

    Se muestra la primera vez que se abre la aplicación en el equipo y cada vez
    que el analista quiere cambiar de nombre desde la barra superior. Lo que se
    escriba acá queda en el historial de cambios de cada registro, en los lotes
    de exportación y en el log de auditoría: por eso el diálogo explica para
    qué se usa en lugar de pedir un dato a ciegas.
    """

    def __init__(self, primera_vez: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Identificación del analista")
        self.setModal(True)
        self.setMinimumWidth(430)
        self.nombre: str | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)

        titulo = QLabel(
            "¿Quién va a trabajar en esta sesión?" if primera_vez
            else "Cambiar el analista de la sesión"
        )
        titulo.setObjectName("titulo")
        lay.addWidget(titulo)

        ayuda = QLabel(
            "Tu nombre queda registrado en cada edición, en los informes que "
            "generes y en el log de auditoría de la causa. Poné el nombre con "
            "el que figurás en el expediente, no un apodo."
        )
        ayuda.setObjectName("subtitulo")
        ayuda.setWordWrap(True)
        lay.addWidget(ayuda)

        self.txt = QLineEdit(sesion.analista())
        self.txt.setPlaceholderText("Apellido, Nombre  ·  grado o cargo")
        self.txt.selectAll()
        self.txt.textChanged.connect(self._validar)
        self.txt.returnPressed.connect(self._guardar)
        lay.addWidget(self.txt)

        pie = QHBoxLayout()
        pie.addStretch(1)
        if not primera_vez:
            btn_cancelar = QPushButton("Cancelar")
            btn_cancelar.clicked.connect(self.reject)
            pie.addWidget(btn_cancelar)
        self.btn_guardar = QPushButton("Guardar")
        self.btn_guardar.setObjectName("primary")
        self.btn_guardar.clicked.connect(self._guardar)
        pie.addWidget(self.btn_guardar)
        lay.addLayout(pie)
        self._validar()

    def _validar(self) -> None:
        self.btn_guardar.setEnabled(bool(self.txt.text().strip()))

    def _guardar(self) -> None:
        nombre = self.txt.text().strip()
        if not nombre:
            return
        self.nombre = sesion.set_analista(nombre)
        self.accept()


def pedir_analista(parent: QWidget | None, primera_vez: bool = False) -> str | None:
    """Muestra el diálogo y devuelve el nombre guardado, o None si se canceló."""
    dlg = DialogoAnalista(primera_vez, parent)
    if dlg.exec() == QDialog.Accepted:
        return dlg.nombre
    return None


class DialogoBorrarCaso(QDialog):
    """Confirma la eliminación de una causa entera pidiendo escribir su nombre.

    Vaciar un caso ya es serio; borrarlo se lleva puesto todo el trabajo hecho
    sobre ese material —niveles de interés, contextos, transcripciones
    corregidas, informes emitidos— sin vuelta atrás. Un «¿Está seguro? Sí/No»
    se contesta por reflejo, así que acá hay que escribir el nombre de la causa:
    es el segundo en el que uno se da cuenta de que eligió la fila equivocada.
    """

    def __init__(self, nombre: str, conteos: dict[str, int],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Eliminar causa")
        self.setModal(True)
        self.setMinimumWidth(460)
        self._nombre = nombre

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)

        titulo = QLabel(f"Eliminar «{nombre}»")
        titulo.setObjectName("titulo")
        titulo.setWordWrap(True)
        lay.addWidget(titulo)

        detalle = QLabel(
            f"Se van a eliminar {conteos.get('Registro', 0)} comunicaciones, "
            f"{conteos.get('Abonado', 0)} abonados, "
            f"{conteos.get('AvisoValidacion', 0)} avisos y "
            f"{conteos.get('LoteExportacion', 0)} lotes de exportación, junto "
            "con los niveles de interés, contextos y transcripciones corregidas "
            "de esta causa.\n\nNo se puede deshacer. Los archivos de audio en "
            "disco no se tocan; el log de auditoría conserva la constancia."
        )
        detalle.setWordWrap(True)
        detalle.setObjectName("subtitulo")
        lay.addWidget(detalle)

        pedido = QLabel("Para confirmar, escribí el nombre de la causa:")
        pedido.setWordWrap(True)
        lay.addWidget(pedido)

        self.txt = QLineEdit()
        self.txt.setPlaceholderText(nombre)
        self.txt.textChanged.connect(self._validar)
        self.txt.returnPressed.connect(self._confirmar)
        lay.addWidget(self.txt)

        pie = QHBoxLayout()
        pie.addStretch(1)
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.clicked.connect(self.reject)
        pie.addWidget(btn_cancelar)
        self.btn_borrar = QPushButton("Eliminar definitivamente")
        self.btn_borrar.setObjectName("danger")
        self.btn_borrar.clicked.connect(self._confirmar)
        pie.addWidget(self.btn_borrar)
        lay.addLayout(pie)
        self._validar()

    def _coincide(self) -> bool:
        return self.txt.text().strip().casefold() == self._nombre.strip().casefold()

    def _validar(self) -> None:
        self.btn_borrar.setEnabled(self._coincide())

    def _confirmar(self) -> None:
        if self._coincide():
            self.accept()


def confirmar_borrado_caso(parent: QWidget | None, nombre: str,
                           conteos: dict[str, int]) -> bool:
    """True solo si el analista escribió el nombre y confirmó."""
    return DialogoBorrarCaso(nombre, conteos, parent).exec() == QDialog.Accepted


class DialogoInformeJudicial(QDialog):
    """Elige qué entregas entran en el informe y con qué fecha de recepción.

    Antes se pedían por separado el número de CD y su identificador, escritos a
    mano, cuando los dos vienen declarados en el DatosCausa.txt de cada entrega
    y ya están guardados. Acá se eligen de una lista; lo único que se tipea es
    la fecha en que el Magistrado suministró el material, que no está en ningún
    archivo.
    """

    def __init__(self, cds: list, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Informe judicial")
        self.setModal(True)
        self.setMinimumWidth(480)
        self._cds = cds
        self.seleccionados: list[int] = []
        self.fecha_recepcion = ""
        self.solo_interes = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)

        titulo = QLabel("Informe judicial")
        titulo.setObjectName("titulo")
        lay.addWidget(titulo)

        sub = QLabel(
            "El documento lleva una sección numerada por entrega, con el "
            "encabezado y los abonados que declara cada CD."
            if cds else
            "Esta causa no tiene entregas registradas (se importó de Excel o de "
            "otra base). El informe va a salir en una sección única."
        )
        sub.setObjectName("subtitulo")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        self.lista = QListWidget()
        self.lista.setSelectionMode(QListWidget.NoSelection)
        for cd in cds:
            texto = f"CD Nº {cd['numero'] or '—'}"
            if cd["identificador"]:
                texto += f"  ·  CD{cd['identificador']}"
            if cd["fecha"]:
                texto += f"  ·  {cd['fecha']}"
            item = QListWidgetItem(texto)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, cd["id"])
            self.lista.addItem(item)
        if cds:
            self.lista.setFixedHeight(min(160, 26 * len(cds) + 12))
            lay.addWidget(self.lista)

        fila = QHBoxLayout()
        fila.addWidget(QLabel("Suministrado por el Magistrado el día:"))
        self.txt_fecha = QLineEdit()
        self.txt_fecha.setPlaceholderText("dd/mm/aaaa")
        fila.addWidget(self.txt_fecha, 1)
        lay.addLayout(fila)

        self.chk_interes = QCheckBox(
            "Incluir solo las comunicaciones marcadas de interés"
        )
        self.chk_interes.setToolTip(
            "El texto del informe dice «cada archivo considerado de interés». "
            "Sin tildar, entran todas las comunicaciones de la entrega."
        )
        lay.addWidget(self.chk_interes)

        pie = QHBoxLayout()
        pie.addStretch(1)
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.clicked.connect(self.reject)
        pie.addWidget(btn_cancelar)
        btn_ok = QPushButton("Generar informe")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self._aceptar)
        pie.addWidget(btn_ok)
        lay.addLayout(pie)

    def _aceptar(self) -> None:
        self.seleccionados = [
            self.lista.item(i).data(Qt.UserRole)
            for i in range(self.lista.count())
            if self.lista.item(i).checkState() == Qt.Checked
        ]
        if self._cds and not self.seleccionados:
            QMessageBox.information(
                self, "Informe judicial", "Elegí al menos una entrega."
            )
            return
        self.fecha_recepcion = self.txt_fecha.text().strip()
        self.solo_interes = self.chk_interes.isChecked()
        self.accept()


class DialogoMigrarMemoria(QDialog):
    """Elige a dónde se llevan las identificaciones de «corresponde a».

    Las mismas personas vuelven a aparecer en otras causas. Lo que hay acá es
    trabajo de investigación —quién es cada número— y hasta ahora quedaba
    encerrado en el caso donde se hizo.

    El destino ofrece la memoria global y las demás causas. Las dos casillas de
    abajo son las decisiones que no se pueden tomar por el analista: si la
    identificación se va o se queda también en el origen, y qué hacer cuando el
    destino ya conoce ese número con otro nombre.
    """

    def __init__(self, cuantas: int, destinos: list[tuple[str, object]],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Migrar identificaciones")
        self.setModal(True)
        self.setMinimumWidth(460)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)

        titulo = QLabel(
            f"Migrar {cuantas} identificación"
            + ("es" if cuantas != 1 else "")
        )
        titulo.setObjectName("titulo")
        lay.addWidget(titulo)

        lay.addWidget(QLabel("Llevar a:"))
        self.cmb_destino = QComboBox()
        for rotulo, valor in destinos:
            self.cmb_destino.addItem(rotulo, valor)
        lay.addWidget(self.cmb_destino)

        self.chk_mover = QCheckBox("Quitarlas de esta memoria (mover en vez de copiar)")
        self.chk_mover.setToolTip(
            "La memoria del caso manda sobre la global: quitarla puede cambiar "
            "a quién resuelve ese número en la causa de origen."
        )
        lay.addWidget(self.chk_mover)

        self.chk_pisar = QCheckBox(
            "Reemplazar si el destino ya tiene otro nombre para el mismo número"
        )
        self.chk_pisar.setToolTip(
            "Sin marcar, esos números se informan como conflicto y no se tocan."
        )
        lay.addWidget(self.chk_pisar)

        nota = QLabel(
            "Lo que quede en conflicto no se quita del origen, aunque se elija "
            "mover: si no entró en el destino, la identificación se perdería."
        )
        nota.setObjectName("subtitulo")
        nota.setWordWrap(True)
        lay.addWidget(nota)

        pie = QHBoxLayout()
        pie.addStretch(1)
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.clicked.connect(self.reject)
        pie.addWidget(btn_cancelar)
        self.btn_migrar = QPushButton("Migrar")
        self.btn_migrar.setDefault(True)
        self.btn_migrar.clicked.connect(self.accept)
        pie.addWidget(self.btn_migrar)
        lay.addLayout(pie)

    def eleccion(self) -> tuple[object, bool, bool]:
        """(destino, mover, pisar). El destino es un caso_id o None (global)."""
        return (
            self.cmb_destino.currentData(),
            self.chk_mover.isChecked(),
            self.chk_pisar.isChecked(),
        )


class DialogoEntregaDesgrabacion(QDialog):
    """Arma la entrega de lo desgrabado: elige el alcance y confirma qué sale.

    El analista termina una jornada de desgrabación y quiere entregar todo
    junto, sin volver a elegir comunicación por comunicación. Lo que se ofrece
    ya viene filtrado a lo revisado y todavía no informado; acá solo se recorta
    (lo de hoy, lo propio) y se puede destildar alguna que se quiera dejar para
    la entrega siguiente.

    No toca la base: recibe las filas candidatas y filtra en memoria.
    """

    #: (etiqueta, clave) del recorte por fecha.
    ALCANCES = (
        ("Todo lo desgrabado sin entregar", "todo"),
        ("Solo lo desgrabado hoy", "hoy"),
    )

    def __init__(
        self, candidatas: list, *, hoy_desde: str, analista: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Entregar desgrabación")
        self.setModal(True)
        self.setMinimumWidth(560)
        self._candidatas = list(candidatas)
        self._hoy_desde = hoy_desde
        self._analista = analista
        self.elegidas: list[int] = []
        self.fecha_recepcion = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)

        titulo = QLabel("Entregar desgrabación")
        titulo.setObjectName("titulo")
        lay.addWidget(titulo)

        sub = QLabel(
            "Sale un informe judicial en Word con las comunicaciones que elijas. "
            "Las que salgan quedan marcadas como informadas y no vuelven a "
            "aparecer acá."
        )
        sub.setObjectName("subtitulo")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        fila = QHBoxLayout()
        self.cmb_alcance = QComboBox()
        for etiqueta, clave in self.ALCANCES:
            self.cmb_alcance.addItem(etiqueta, clave)
        self.cmb_alcance.currentIndexChanged.connect(self._poblar)
        fila.addWidget(self.cmb_alcance, 1)

        self.chk_mias = QCheckBox("Solo las mías")
        self.chk_mias.setToolTip(
            "Deja afuera lo que desgrabó otro analista en esta misma causa."
        )
        self.chk_mias.setEnabled(bool(analista))
        self.chk_mias.toggled.connect(self._poblar)
        fila.addWidget(self.chk_mias)
        lay.addLayout(fila)

        self.lista = QListWidget()
        self.lista.setSelectionMode(QListWidget.NoSelection)
        self.lista.setMinimumHeight(200)
        lay.addWidget(self.lista, 1)

        self.lbl_cuenta = QLabel()
        self.lbl_cuenta.setObjectName("subtitulo")
        lay.addWidget(self.lbl_cuenta)

        fecha = QHBoxLayout()
        fecha.addWidget(QLabel("Suministrado por el Magistrado el día:"))
        self.txt_fecha = QLineEdit()
        self.txt_fecha.setPlaceholderText("dd/mm/aaaa (opcional)")
        fecha.addWidget(self.txt_fecha, 1)
        lay.addLayout(fecha)

        pie = QHBoxLayout()
        pie.addStretch(1)
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.clicked.connect(self.reject)
        pie.addWidget(btn_cancelar)
        self.btn_ok = QPushButton("Generar informe")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.clicked.connect(self._aceptar)
        pie.addWidget(self.btn_ok)
        lay.addLayout(pie)

        self._poblar()

    # ------------------------------------------------------------------
    def filtradas(self) -> list:
        """Las candidatas que pasan el alcance elegido."""
        alcance = self.cmb_alcance.currentData()
        filas = self._candidatas
        if alcance == "hoy":
            filas = [
                r for r in filas
                if (r["transcripcion_revisada_en"] or "") >= self._hoy_desde
            ]
        if self.chk_mias.isChecked() and self._analista:
            filas = [
                r for r in filas
                if (r["transcripcion_revisada_por"] or "") == self._analista
            ]
        return filas

    def _poblar(self) -> None:
        self.lista.clear()
        filas = self.filtradas()
        for r in filas:
            item = QListWidgetItem(_rotulo_de_entrega(r))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, r["id"])
            self.lista.addItem(item)
        self.lbl_cuenta.setText(
            "Ninguna comunicación desgrabada queda pendiente de entrega."
            if not filas else
            f"{len(filas)} comunicación(es) para entregar."
        )
        self.btn_ok.setEnabled(bool(filas))

    def _aceptar(self) -> None:
        self.elegidas = [
            self.lista.item(i).data(Qt.UserRole)
            for i in range(self.lista.count())
            if self.lista.item(i).checkState() == Qt.Checked
        ]
        if not self.elegidas:
            QMessageBox.information(
                self, "Entregar desgrabación",
                "No quedó ninguna comunicación tildada.",
            )
            return
        self.fecha_recepcion = self.txt_fecha.text().strip()
        self.accept()


def _rotulo_de_entrega(r) -> str:
    """Una línea que identifique la comunicación sin abrirla."""
    partes = [f"#{r['orden']}"]
    fecha = r["fecha_inicio_texto"] or r["fecha_inicio_dt"] or ""
    if fecha:
        partes.append(str(fecha))
    puntas = " → ".join(x for x in (r["origen"], r["destino"]) if x)
    if puntas:
        partes.append(puntas)
    quien = r["transcripcion_revisada_por"] or ""
    if quien:
        partes.append(f"desgrabó {quien}")
    return "   ·   ".join(partes)
