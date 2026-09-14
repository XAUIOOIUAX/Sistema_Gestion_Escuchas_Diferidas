"""Pantalla Índice (pseudocódigo 6.4).

Alta y edición de abonados del caso (el color se asigna automáticamente al
crearlos y se puede corregir a mano desde la columna Color) y administración
de la memoria de "corresponde a", tanto la del caso como la global.
"""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QStyledItemDelegate,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import repositorios as repo
from app.core.normalizers import normalizar_numero
from app.ui import tema
from app.servicios import memoria
from app.ui.dialogos import DialogoMigrarMemoria, elegir_color_abonado

_COL_A_COLOR = 0
_COL_A_INTERV = 1
_COL_A_NUMERO = 2
_COL_A_NOMBRE = 3
_COL_A_OBS = 4
_COL_A_REGS = 5

# Memoria «corresponde a»
_COL_M_NUMERO = 0
_COL_M_NOMBRE = 1
_COL_M_FECHA = 2
_COL_M_QUITAR = 3


class _DelegadoColor(QStyledItemDelegate):
    """Dibuja el punto de color del abonado en vez de meter un widget.

    Antes cada fila llevaba un QWidget contenedor con su layout y un
    QPushButton adentro: tres widgets por abonado. Con 400 abonados —una
    intervención larga los tiene— poblar el Índice tardaba cuatro segundos, y
    en un equipo modesto bastante más. Un delegado lo pinta sin crear nada; el
    clic lo atiende la tabla.
    """

    DIAMETRO = 18

    def paint(self, painter: QPainter, option, index):  # noqa: N802 (API de Qt)
        super().paint(painter, option, index)
        color = index.data(Qt.UserRole + 2)
        if not color:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        centro = option.rect.center()
        radio = self.DIAMETRO // 2
        circulo = QRect(
            centro.x() - radio + 1, centro.y() - radio + 1,
            self.DIAMETRO, self.DIAMETRO,
        )
        painter.setBrush(QColor(color))
        painter.setPen(QPen(QColor(tema.LINE), 1))
        painter.drawEllipse(circulo)
        painter.restore()


class PantallaIndice(QWidget):
    """Índice de abonados del caso + memoria de 'corresponde a'."""

    datos_cambiaron = Signal()

    def __init__(self, con: sqlite3.Connection) -> None:
        super().__init__()
        self._con = con
        self._caso_id: int | None = None
        self._abonados: list[sqlite3.Row] = []
        self._memoria: list[sqlite3.Row] = []
        self._cargando = False
        self._cargando_mem = False
        self._construir()

    def set_caso(self, caso_id: int) -> None:
        self._caso_id = caso_id
        self.refrescar()

    def refrescar(self) -> None:
        if self._caso_id is None:
            return
        self._poblar_abonados()
        self._poblar_memoria()

    # ------------------------- construcción UI -----------------------------
    def _construir(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 16, 22, 10)
        lay.setSpacing(10)

        cab = QHBoxLayout()
        titulos = QVBoxLayout()
        t = QLabel("Índice de abonados")
        t.setObjectName("titulo")
        s = QLabel(
            "Abonados intervenidos de la causa (líneas pinchadas). Marcá "
            "«Interv.» si algún número debería figurar y no fue detectado."
        )
        s.setObjectName("subtitulo")
        titulos.addWidget(t)
        titulos.addWidget(s)
        cab.addLayout(titulos)
        cab.addStretch(1)

        self.chk_solo_interv = QCheckBox("Solo intervenidos")
        self.chk_solo_interv.setChecked(True)
        self.chk_solo_interv.toggled.connect(self._poblar_abonados)
        cab.addWidget(self.chk_solo_interv)

        btn_alta = QPushButton("+ Agregar abonado")
        btn_alta.setObjectName("primary")
        btn_alta.clicked.connect(self._alta_abonado)
        cab.addWidget(btn_alta)
        lay.addLayout(cab)

        self.tabla = QTableWidget(0, 6)
        self.tabla.setHorizontalHeaderLabels(
            ["Color", "Interv.", "Número", "Pertenece a", "Observaciones", "Registros"]
        )
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.verticalHeader().setDefaultSectionSize(34)
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setAlternatingRowColors(True)
        hh = self.tabla.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        # Medir 30 filas alcanza: son números de abonado y conteos, de ancho
        # parejo. Sin esto se mide cada celda de cada columna en cada carga.
        hh.setResizeContentsPrecision(30)
        hh.setSectionResizeMode(_COL_A_NOMBRE, QHeaderView.Stretch)
        hh.setSectionResizeMode(_COL_A_OBS, QHeaderView.Stretch)
        # Las columnas de color e "Interv." llevan cell-widgets/checkbox, que
        # ResizeToContents no mide → hay que fijarles el ancho o se colapsan.
        hh.setSectionResizeMode(_COL_A_COLOR, QHeaderView.Fixed)
        hh.resizeSection(_COL_A_COLOR, 48)
        hh.setSectionResizeMode(_COL_A_INTERV, QHeaderView.Fixed)
        hh.resizeSection(_COL_A_INTERV, 64)
        self.tabla.setItemDelegateForColumn(_COL_A_COLOR, _DelegadoColor(self.tabla))
        self.tabla.cellClicked.connect(self._on_celda_clickeada)
        self.tabla.itemChanged.connect(self._on_item_editado)
        lay.addWidget(self.tabla, 2)

        # ------- memoria corresponde_a -------
        mem_cab = QHBoxLayout()
        lbl_mem = QLabel("MEMORIA «CORRESPONDE A»")
        lbl_mem.setObjectName("seccion")
        mem_cab.addWidget(lbl_mem)
        self.cmb_alcance = QComboBox()
        self.cmb_alcance.addItems(["Caso actual", "Global (todos los casos)"])
        self.cmb_alcance.currentIndexChanged.connect(self._poblar_memoria)
        mem_cab.addWidget(self.cmb_alcance)
        mem_cab.addStretch(1)

        self.btn_mem_migrar = QPushButton("Migrar a…")
        self.btn_mem_migrar.setToolTip(
            "Llevar las identificaciones seleccionadas a otra causa o a la "
            "memoria global, para no volver a tipearlas"
        )
        self.btn_mem_migrar.setEnabled(False)
        self.btn_mem_migrar.clicked.connect(self._migrar_memoria)
        mem_cab.addWidget(self.btn_mem_migrar)

        btn_mem_alta = QPushButton("+ Agregar")
        btn_mem_alta.clicked.connect(self._alta_memoria)
        mem_cab.addWidget(btn_mem_alta)
        lay.addLayout(mem_cab)

        self.tabla_mem = QTableWidget(0, 4)
        self.tabla_mem.setHorizontalHeaderLabels(
            ["Número", "Corresponde a", "Actualizado", ""]
        )
        self.tabla_mem.verticalHeader().setVisible(False)
        self.tabla_mem.verticalHeader().setDefaultSectionSize(42)
        # Se corrige acá mismo. Una identificación se escribe cuando todavía no
        # se sabe bien de quién es ("Cintia (no identificada)") y se precisa
        # después; sin poder editarla había que quitarla y volver a cargarla
        # entera, que es justo el trabajo que esta memoria viene a evitar.
        self.tabla_mem.setEditTriggers(
            QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed
        )
        self.tabla_mem.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla_mem.setSelectionMode(QTableWidget.ExtendedSelection)
        self.tabla_mem.itemSelectionChanged.connect(self._on_seleccion_memoria)
        self.tabla_mem.itemChanged.connect(self._on_item_memoria_editado)
        self.tabla_mem.setAlternatingRowColors(True)
        hh2 = self.tabla_mem.horizontalHeader()
        hh2.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh2.setSectionResizeMode(1, QHeaderView.Stretch)
        hh2.setSectionResizeMode(3, QHeaderView.Fixed)
        hh2.resizeSection(3, 90)
        lay.addWidget(self.tabla_mem, 1)

        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("subtitulo")
        lay.addWidget(self.lbl_status)

    # --------------------------- abonados ----------------------------------
    def _poblar_abonados(self) -> None:
        self._cargando = True
        hay_interv = repo.contar_abonados_intervenidos(self._con, self._caso_id) > 0
        # Si no hay ninguno marcado (caso viejo), mostramos todos aunque el
        # filtro esté activo, para que el usuario pueda marcarlos.
        solo = self.chk_solo_interv.isChecked() and hay_interv
        self._abonados = repo.listar_abonados(
            self._con, self._caso_id, solo_intervenidos=solo
        )
        self.tabla.setRowCount(0)
        for a in self._abonados:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)

            color_actual = a["color_hex"] or "#888888"
            punto = QTableWidgetItem()
            punto.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            punto.setData(Qt.UserRole + 2, color_actual)
            punto.setToolTip("Clic para cambiar el color del abonado")
            self.tabla.setItem(fila, _COL_A_COLOR, punto)

            chk = QTableWidgetItem()
            chk.setFlags(
                (chk.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable
            )
            chk.setCheckState(
                Qt.Checked if a["intervenido"] else Qt.Unchecked
            )
            chk.setTextAlignment(Qt.AlignCenter)
            chk.setData(Qt.UserRole, a["id"])
            self.tabla.setItem(fila, _COL_A_INTERV, chk)

            num = QTableWidgetItem(a["numero_normalizado"])
            num.setFlags(num.flags() & ~Qt.ItemIsEditable)
            num.setData(Qt.UserRole, a["id"])
            self.tabla.setItem(fila, _COL_A_NUMERO, num)

            self.tabla.setItem(
                fila, _COL_A_NOMBRE, QTableWidgetItem(a["pertenece_a"] or "")
            )
            self.tabla.setItem(
                fila, _COL_A_OBS, QTableWidgetItem(a["observaciones"] or "")
            )

            regs = QTableWidgetItem(str(a["n_registros"]))
            regs.setFlags(regs.flags() & ~Qt.ItemIsEditable)
            regs.setTextAlignment(Qt.AlignCenter)
            self.tabla.setItem(fila, _COL_A_REGS, regs)
        self._cargando = False

        n_interv = repo.contar_abonados_intervenidos(self._con, self._caso_id)
        if not hay_interv:
            self.lbl_status.setText(
                f"{len(self._abonados)} abonados · ninguno marcado como "
                "intervenido todavía (marcá los que correspondan)"
            )
        else:
            self.lbl_status.setText(
                f"{n_interv} abonados intervenidos · "
                f"{len(self._abonados)} en la lista"
            )

    def _on_item_editado(self, item: QTableWidgetItem) -> None:
        if self._cargando:
            return
        if item.column() == _COL_A_INTERV:
            self._toggle_intervenido(item)
            return
        if item.column() not in (_COL_A_NOMBRE, _COL_A_OBS):
            return
        fila = item.row()
        id_item = self.tabla.item(fila, _COL_A_NUMERO)
        if id_item is None:
            return
        abonado_id = id_item.data(Qt.UserRole)
        numero = id_item.text()
        campo = "pertenece_a" if item.column() == _COL_A_NOMBRE else "observaciones"
        valor = item.text().strip()
        try:
            repo.actualizar_abonado(self._con, abonado_id, campo, valor)
            repo.log_auditoria(
                self._con, "edito",
                f"Índice: abonado {numero} {campo} -> '{valor}'", self._caso_id,
            )
            self._con.commit()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Índice", f"No se pudo guardar:\n{exc}")
            return

        if campo == "pertenece_a":
            # Sin preguntar: nombrar un abonado ES actualizar las columnas
            # Interesado e Interlocutor de la Tabla TOTAL, no una acción
            # aparte. Y se recalcula la causa entera, no solo las filas de este
            # número, para que el resultado no dependa del orden en que se fue
            # nombrando.
            n = repo.recalcular_nombres(self._con, self._caso_id)
            self._con.commit()
            if n:
                self.datos_cambiaron.emit()
                self.lbl_status.setText(
                    f"{n} comunicaciones actualizadas en la Tabla TOTAL"
                )

    def _on_celda_clickeada(self, fila: int, columna: int) -> None:
        """El punto de color ya no es un botón: el clic lo atiende la tabla."""
        if columna != _COL_A_COLOR or not (0 <= fila < len(self._abonados)):
            return
        abonado = self._abonados[fila]
        self._cambiar_color(
            abonado["id"], abonado["numero_normalizado"],
            abonado["color_hex"] or "#888888",
        )

    def _cambiar_color(self, abonado_id: int, numero: str, actual: str) -> None:
        nuevo = elegir_color_abonado(
            self, actual, f"Abonado {numero}"
        )
        if nuevo is None or nuevo == (actual or "").upper():
            return
        try:
            color = repo.actualizar_color_abonado(self._con, abonado_id, nuevo)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Índice", f"No se pudo guardar:\n{exc}")
            return
        repo.log_auditoria(
            self._con, "edito",
            f"Índice: color del abonado {numero} -> {color}", self._caso_id,
        )
        self._con.commit()
        self.datos_cambiaron.emit()
        self._poblar_abonados()

    def _toggle_intervenido(self, item: QTableWidgetItem) -> None:
        abonado_id = item.data(Qt.UserRole)
        if abonado_id is None:
            return
        intervenido = item.checkState() == Qt.Checked
        numero_item = self.tabla.item(item.row(), _COL_A_NUMERO)
        numero = numero_item.text() if numero_item else ""
        repo.marcar_abonado_intervenido(self._con, abonado_id, intervenido)
        repo.log_auditoria(
            self._con, "edito",
            f"Índice: {numero} marcado como "
            f"{'intervenido' if intervenido else 'NO intervenido'}",
            self._caso_id,
        )
        self._con.commit()
        self.datos_cambiaron.emit()
        # Repoblar por si el filtro "solo intervenidos" debe ocultar/mostrar filas.
        self._poblar_abonados()

    def _alta_abonado(self) -> None:
        if self._caso_id is None:
            return
        numero, ok = QInputDialog.getText(
            self, "Agregar abonado", "Número del abonado:"
        )
        if not ok or not numero.strip():
            return
        numero_norm = normalizar_numero(numero.strip())
        nombre, _ = QInputDialog.getText(
            self, "Agregar abonado", "Pertenece a (opcional):"
        )
        # Alta manual en el Índice = línea intervenida.
        abonado = repo.obtener_o_crear_abonado(
            self._con, self._caso_id, numero_norm, intervenido=True
        )
        if nombre.strip():
            repo.actualizar_abonado(self._con, abonado["id"], "pertenece_a", nombre.strip())
        repo.log_auditoria(
            self._con, "edito", f"Índice: alta abonado {numero_norm}", self._caso_id
        )
        self._con.commit()
        self._poblar_abonados()
        self.datos_cambiaron.emit()

    # ---------------------------- memoria -----------------------------------
    def _alcance(self) -> str:
        return "global" if self.cmb_alcance.currentIndex() == 1 else "caso"

    def _poblar_memoria(self) -> None:
        caso = None if self._alcance() == "global" else self._caso_id
        if caso is None and self._alcance() == "caso":
            # Sin causa abierta no hay memoria de caso que mostrar. Se vacía en
            # vez de dejar la anterior: los ids de la tabla son los que se
            # migran, y migrar los de otra causa sería mover a ciegas.
            self._memoria = []
            self.tabla_mem.setRowCount(0)
            self._on_seleccion_memoria()
            return
        self._memoria = repo.listar_memoria_corresponde(self._con, caso)
        self._cargando_mem = True
        self.tabla_mem.setRowCount(0)
        for m in self._memoria:
            fila = self.tabla_mem.rowCount()
            self.tabla_mem.insertRow(fila)
            self.tabla_mem.setItem(
                fila, _COL_M_NUMERO, QTableWidgetItem(m["numero_normalizado"])
            )
            self.tabla_mem.setItem(
                fila, _COL_M_NOMBRE, QTableWidgetItem(m["nombre"] or "")
            )
            # La fecha la pone el sistema: se muestra, no se escribe.
            fecha = QTableWidgetItem(m["fecha_actualizacion"] or "")
            fecha.setFlags(fecha.flags() & ~Qt.ItemIsEditable)
            self.tabla_mem.setItem(fila, _COL_M_FECHA, fecha)
            btn = QPushButton("Quitar")
            btn.clicked.connect(
                lambda _=False, _id=m["id"]: self._borrar_memoria(_id)
            )
            self.tabla_mem.setCellWidget(fila, _COL_M_QUITAR, btn)
        self._cargando_mem = False
        self._on_seleccion_memoria()

    def _on_item_memoria_editado(self, item: QTableWidgetItem) -> None:
        """Guarda la corrección hecha sobre el número o el nombre.

        Si no se puede guardar, la fila vuelve a lo que decía la base. Dejar el
        texto nuevo en pantalla después de un error es peor que no editar: se
        lee como guardado y no lo está.
        """
        if self._cargando_mem:
            return
        if item.column() not in (_COL_M_NUMERO, _COL_M_NOMBRE):
            return
        fila = item.row()
        if not (0 <= fila < len(self._memoria)):
            return
        entrada = self._memoria[fila]

        numero = self.tabla_mem.item(fila, _COL_M_NUMERO).text()
        nombre = self.tabla_mem.item(fila, _COL_M_NOMBRE).text()
        if item.column() == _COL_M_NUMERO:
            numero = normalizar_numero(numero.strip())

        try:
            repo.actualizar_memoria_corresponde(
                self._con, entrada["id"], self._alcance(), numero, nombre.strip()
            )
            repo.log_auditoria(
                self._con, "edito",
                f"Memoria «corresponde a» ({self._alcance()}): "
                f"{entrada['numero_normalizado']} -> {numero} / '{nombre.strip()}'",
                self._caso_id,
            )
            self._con.commit()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Memoria", str(exc))
            self._poblar_memoria()
            return
        self._memoria_cambio("Identificación corregida")

    def _memoria_cambio(self, que_paso: str) -> None:
        """Refresca la memoria y baja el cambio a la Tabla TOTAL.

        La memoria alimenta la columna Interlocutor, que está guardada en cada
        comunicación. Sin este recálculo, corregir un nombre acá no se veía en
        la grilla hasta que se tocara algo del Índice.
        """
        self._poblar_memoria()
        if self._caso_id is not None:
            n = repo.recalcular_nombres(self._con, self._caso_id)
            self._con.commit()
            if n:
                que_paso += f" · {n} comunicaciones actualizadas en la Tabla TOTAL"
        self.lbl_status.setText(que_paso)
        self.datos_cambiaron.emit()

    def _on_seleccion_memoria(self) -> None:
        self.btn_mem_migrar.setEnabled(bool(self._memoria_seleccionada()))

    def _memoria_seleccionada(self) -> list[int]:
        """Los ids de las entradas seleccionadas, en el orden de la tabla."""
        filas = sorted(
            i.row() for i in self.tabla_mem.selectionModel().selectedRows()
        )
        return [self._memoria[f]["id"] for f in filas if f < len(self._memoria)]

    def _destinos_posibles(self) -> list[tuple[str, object]]:
        """A dónde se puede migrar desde donde estamos parados.

        Nunca se ofrece el propio origen: migrar a donde uno ya está no es una
        opción que el analista tenga que descartar leyéndola.
        """
        origen = self._origen_memoria()
        opciones: list[tuple[str, object]] = []
        if origen is not None:
            opciones.append(("Memoria global (todos los casos)", None))
        for caso in repo.listar_casos(self._con):
            if caso["id"] != origen:
                opciones.append((caso["nombre"], caso["id"]))
        return opciones

    def _origen_memoria(self) -> int | None:
        return None if self._alcance() == "global" else self._caso_id

    def _migrar_memoria(self) -> None:
        ids = self._memoria_seleccionada()
        if not ids:
            return
        destinos = self._destinos_posibles()
        if not destinos:
            QMessageBox.information(
                self, "Migrar identificaciones",
                "No hay otra causa ni memoria global a donde llevarlas.",
            )
            return

        dlg = DialogoMigrarMemoria(len(ids), destinos, self)
        # QDialog.Accepted, no dlg.Accepted: en PySide6 el enum no está en
        # la instancia y acceder ahí levanta AttributeError.
        if dlg.exec() != QDialog.Accepted:
            return
        destino, mover, pisar = dlg.eleccion()

        r = memoria.migrar(
            self._con, ids,
            origen=self._origen_memoria(), destino=destino,
            quitar_del_origen=mover, pisar=pisar,
        )
        self._memoria_cambio("Identificaciones migradas")
        self._informar_migracion(r)

    def _informar_migracion(self, r: memoria.ResultadoMigracion) -> None:
        """Dice qué pasó con cada número, no solo cuántos entraron.

        Los conflictos son lo importante del mensaje: son los que el analista
        tiene que resolver a mano, y si no se los nombra se da por hecho que
        migró todo.
        """
        partes = [f"{len(r.migradas)} identificación(es) migrada(s)."]
        if r.pisadas:
            partes.append(
                f"{len(r.pisadas)} reemplazaron el nombre que había en el destino."
            )
        if r.ya_estaban:
            partes.append(f"{len(r.ya_estaban)} ya figuraban igual en el destino.")
        if r.quitadas:
            partes.append(f"{r.quitadas} se quitaron de la memoria de origen.")

        if not r.conflictos:
            self.lbl_status.setText(" ".join(partes))
            QMessageBox.information(
                self, "Migrar identificaciones", "\n".join(partes)
            )
            return

        detalle = "\n".join(
            f"  • {c.numero}: acá «{c.nombre_origen}», en el destino "
            f"«{c.nombre_destino}»"
            for c in r.conflictos[:12]
        )
        if len(r.conflictos) > 12:
            detalle += f"\n  … y {len(r.conflictos) - 12} más."
        partes.append(
            f"\n{len(r.conflictos)} quedaron SIN migrar porque el destino ya "
            f"conoce ese número con otro nombre:\n{detalle}\n\n"
            "Se dejaron como estaban, de los dos lados. Para imponer el nombre "
            "de esta causa, volvé a migrarlas marcando «Reemplazar»."
        )
        self.lbl_status.setText(
            f"{len(r.migradas)} migrada(s), {len(r.conflictos)} en conflicto."
        )
        QMessageBox.warning(self, "Migrar identificaciones", "\n".join(partes))

    def _alta_memoria(self) -> None:
        numero, ok = QInputDialog.getText(
            self, "Memoria", "Número del abonado:"
        )
        if not ok or not numero.strip():
            return
        nombre, ok = QInputDialog.getText(
            self, "Memoria", "Corresponde a (nombre):"
        )
        if not ok or not nombre.strip():
            return
        repo.guardar_corresponde_a(
            self._con,
            self._caso_id or 0,
            normalizar_numero(numero.strip()),
            nombre.strip(),
            self._alcance(),
        )
        self._memoria_cambio("Identificación agregada")

    def _borrar_memoria(self, memoria_id: int) -> None:
        resp = QMessageBox.question(
            self,
            "Quitar de memoria",
            "¿Quitar esta asociación de la memoria? Los registros ya asignados "
            "no se modifican.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        repo.borrar_memoria_corresponde(self._con, memoria_id, self._alcance())
        self._con.commit()
        self._memoria_cambio("Identificación quitada")
