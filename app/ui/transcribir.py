"""UI de transcripción automática: proceso Whisper + diálogo de lote.

`ProcesoTranscripcion` envuelve el worker en un QProcess (no bloquea la GUI) y
emite una señal por cada audio transcripto. `DialogoTranscribirLote` procesa
todos los registros pendientes con barra de progreso y permite cancelar.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

import json

from app.servicios import transcripcion as svc
from app.ui import tema


def _duracion_estimada(ruta: Path) -> float:
    """Segundos de audio a partir del tamaño del archivo.

    Los WAV de las prestadoras vienen en G.711 a 8 kHz mono: 8000 bytes por
    segundo. Es una estimación para el cartel de "esto va a tardar tanto", no
    un dato que se guarde; por eso no se abre el archivo.
    """
    try:
        return max(0.0, (Path(ruta).stat().st_size - 44) / 8000)
    except OSError:
        return 0.0


class ProcesoTranscripcion(QObject):
    """Worker Whisper como QProcess: audios por stdin, JSON por stdout."""

    resultado = Signal(dict)      # {"archivo", "ok", "texto"/"error", ...}
    progreso = Signal(str)        # línea legible de stderr del worker
    terminado = Signal(int)       # cantidad procesada
    fallo = Signal(str)           # error fatal (no se pudo arrancar / recursos)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._buffer = ""
        self._procesados = 0

    @property
    def activo(self) -> bool:
        return self._proc is not None and self._proc.state() != QProcess.NotRunning

    def iniciar(
        self, archivos: list[Path], vocabulario: str = "",
        opcion: svc.OpcionMotor | None = None,
    ) -> bool:
        """Lanza el worker para la lista de audios. False si faltan recursos.

        `vocabulario` son los nombres y lugares de la causa: viajan en el
        prompt para que el modelo no tenga que adivinarlos.
        """
        recursos = svc.localizar_recursos(opcion.motor if opcion else None)
        if opcion is not None:
            recursos.modelo = opcion.modelo
        if not recursos.disponible:
            self.fallo.emit(
                "No se puede transcribir. Falta: " + ", ".join(recursos.faltantes())
            )
            return False

        comando = svc.comando_worker(
            recursos, vocabulario, opcion.motor if opcion else None
        )
        self._buffer = ""
        self._procesados = 0

        # El lote anterior dejó su QProcess colgado como hijo: ya terminó, pero
        # sigue vivo con sus conexiones. Diez lotes son diez objetos que nadie
        # va a volver a usar.
        if self._proc is not None:
            # Soltar las señales ANTES de borrarlo: si no, el proceso viejo
            # todavía puede emitir mientras se lo está destruyendo, y los
            # manejadores apuntan al lote nuevo.
            viejo = self._proc
            for senal in (
                viejo.readyReadStandardOutput, viejo.readyReadStandardError,
                viejo.finished, viejo.errorOccurred,
            ):
                try:
                    senal.disconnect()
                except RuntimeError:
                    pass          # no tenía nada conectado
            viejo.deleteLater()
        self._proc = QProcess(self)
        # Forzar UTF-8 en el worker: sin esto los acentos de la transcripción
        # se corrompen (Windows usa cp1252 por defecto en el proceso hijo).
        entorno = QProcessEnvironment.systemEnvironment()
        entorno.insert("PYTHONUTF8", "1")
        entorno.insert("PYTHONIOENCODING", "utf-8")
        self._proc.setProcessEnvironment(entorno)
        self._proc.setProgram(comando[0])
        self._proc.setArguments(comando[1:])
        self._proc.readyReadStandardOutput.connect(self._leer_stdout)
        self._proc.readyReadStandardError.connect(self._leer_stderr)
        self._proc.finished.connect(self._al_terminar)
        # El mensaje se le pide al proceso que falló, no a `self._proc`: son el
        # mismo ahora, pero al arrancar otro lote dejan de serlo y el error de
        # uno terminaba contando lo que le pasó al otro.
        self._proc.errorOccurred.connect(
            lambda _e, p=self._proc: self.fallo.emit(
                f"No se pudo ejecutar el worker: {p.errorString()}"
            )
        )
        self._proc.start()
        if not self._proc.waitForStarted(15000):
            self.fallo.emit("El proceso de transcripción no arrancó.")
            return False

        datos = "".join(f"{a}\n" for a in archivos)
        self._proc.write(datos.encode("utf-8"))
        self._proc.closeWriteChannel()
        return True

    def cancelar(self) -> None:
        if self.activo:
            self._proc.kill()

    def _leer_stdout(self) -> None:
        self._buffer += bytes(self._proc.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )
        while "\n" in self._buffer:
            linea, self._buffer = self._buffer.split("\n", 1)
            linea = linea.strip()
            if not linea:
                continue
            try:
                obj = json.loads(linea)
            except json.JSONDecodeError:
                continue
            if obj.get("fin"):
                if obj.get("error"):
                    self.fallo.emit(obj["error"])
            else:
                self._procesados += 1
                self.resultado.emit(obj)

    def _leer_stderr(self) -> None:
        texto = bytes(self._proc.readAllStandardError()).decode(
            "utf-8", errors="replace"
        )
        for linea in texto.splitlines():
            if linea.strip():
                self.progreso.emit(linea.strip())

    def _al_terminar(self) -> None:
        self._leer_stdout()
        self.terminado.emit(self._procesados)


class DialogoTranscribirLote(QDialog):
    """Transcribe en lote los audios pendientes, con progreso y cancelación.

    `pendientes` es una lista de tuplas (registro_id, orden, ruta_audio).
    Por cada resultado llama a `aplicar(registro_id, texto, duracion,
    segmentos)` — el llamador decide cómo persistir (campo transcripcion,
    tiempos e historial).
    """

    def __init__(
        self,
        pendientes: list[tuple[int, int, Path]],
        aplicar,
        parent=None,
        vocabulario: str = "",
    ) -> None:
        super().__init__(parent)
        self._vocabulario = vocabulario
        self.setWindowTitle("Transcripción automática (Whisper)")
        self.setMinimumSize(560, 380)
        self._pendientes = pendientes
        self._aplicar = aplicar
        self._por_archivo = {str(ruta): (rid, orden) for rid, orden, ruta in pendientes}
        self._ok = 0
        self._error = 0

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        self._lbl = QLabel(
            f"{len(pendientes)} audios pendientes de transcripción.\n"
            "La primera transcripción demora más (se carga el modelo en memoria)."
        )
        self._lbl.setWordWrap(True)
        lay.addWidget(self._lbl)

        # Sin GPU la elección de modelo es la diferencia entre veinte minutos y
        # una hora, así que se decide por lote y no en un archivo de config.
        self._opciones = svc.opciones_de_motor()
        fila_motor = QHBoxLayout()
        fila_motor.addWidget(QLabel("Modelo:"))
        self.cmb_motor = QComboBox()
        for opcion in self._opciones:
            self.cmb_motor.addItem(opcion.etiqueta, opcion)
        self.cmb_motor.currentIndexChanged.connect(self._describir_motor)
        fila_motor.addWidget(self.cmb_motor, 1)
        lay.addLayout(fila_motor)

        self._lbl_motor = QLabel("")
        self._lbl_motor.setWordWrap(True)
        self._lbl_motor.setStyleSheet(f"color:{tema.TEXT_DIM}; font-size:11px;")
        lay.addWidget(self._lbl_motor)
        self._describir_motor()

        self._barra = QProgressBar()
        self._barra.setMaximum(len(pendientes))
        self._barra.setValue(0)
        lay.addWidget(self._barra)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(
            f"font-family:'IBM Plex Mono','Consolas',monospace; font-size:11px;"
            f"color:{tema.TEXT_MUTED};"
        )
        lay.addWidget(self._log, 1)

        fila = QHBoxLayout()
        fila.addStretch(1)
        self._btn_iniciar = QPushButton("Iniciar")
        self._btn_iniciar.setObjectName("primary")
        self._btn_iniciar.clicked.connect(self._iniciar)
        fila.addWidget(self._btn_iniciar)
        self._btn_cerrar = QPushButton("Cancelar")
        self._btn_cerrar.clicked.connect(self._cancelar_o_cerrar)
        fila.addWidget(self._btn_cerrar)
        lay.addLayout(fila)

        self._proceso = ProcesoTranscripcion(self)
        self._proceso.resultado.connect(self._on_resultado)
        self._proceso.progreso.connect(self._on_progreso)
        self._proceso.terminado.connect(self._on_terminado)
        self._proceso.fallo.connect(self._on_fallo)

    # ------------------------------------------------------------------
    def _opcion_elegida(self):
        return self.cmb_motor.currentData() if self._opciones else None

    def _describir_motor(self) -> None:
        """Explica qué implica el modelo elegido y estima cuánto va a tardar."""
        opcion = self._opcion_elegida()
        if opcion is None:
            self._lbl_motor.setText("No se encontró ningún modelo en este equipo.")
            return
        segundos = sum(
            _duracion_estimada(ruta) for _rid, _orden, ruta in self._pendientes
        )
        minutos = segundos * svc.factor_tiempo(opcion.motor, opcion.modelo) / 60
        estimacion = (
            f"  ·  ~{minutos:.0f} min para estos {len(self._pendientes)} audios"
            if segundos else ""
        )
        self._lbl_motor.setText(opcion.nota + estimacion)

    def _iniciar(self) -> None:
        self._btn_iniciar.setEnabled(False)
        self.cmb_motor.setEnabled(False)
        archivos = [ruta for _rid, _orden, ruta in self._pendientes]
        self._log.append("Iniciando worker de transcripción...")
        self._proceso.iniciar(archivos, self._vocabulario, self._opcion_elegida())

    def _cancelar_o_cerrar(self) -> None:
        if self._proceso.activo:
            self._proceso.cancelar()
            self._log.append("Cancelado por el usuario.")
        self.reject() if not (self._ok or self._error) else self.accept()

    def _on_progreso(self, linea: str) -> None:
        self._log.append(linea)

    def _on_resultado(self, obj: dict) -> None:
        rid_orden = self._por_archivo.get(obj.get("archivo", ""))
        if rid_orden is None:
            return
        rid, orden = rid_orden
        if obj.get("ok"):
            # Con tiempos se arma el texto a partir de los segmentos (un
            # renglón por frase, alineado con el audio); sin ellos se cae en la
            # limpieza del texto plano de siempre.
            segmentos = svc.normalizar_segmentos(obj.get("segmentos"))
            texto = (
                svc.texto_de_segmentos(segmentos) if segmentos
                else svc.normalizar_transcripcion(obj.get("texto", ""))
            )
            try:
                self._aplicar(rid, texto, obj.get("duracion") or 0.0, segmentos)
                self._ok += 1
                detalle = (
                    f"{len(texto)} caracteres en {len(segmentos)} frases"
                    if segmentos else f"{len(texto)} caracteres"
                )
                self._log.append(f"✔ Registro {orden}: {detalle}.")
            except Exception as exc:  # noqa: BLE001
                self._error += 1
                self._log.append(f"✖ Registro {orden}: no se pudo guardar ({exc}).")
        else:
            self._error += 1
            self._log.append(f"✖ Registro {orden}: {obj.get('error', 'error')}")
        self._barra.setValue(self._ok + self._error)

    def _on_terminado(self, _n: int) -> None:
        self._lbl.setText(
            f"Terminado: {self._ok} transcriptos, {self._error} con error."
        )
        self._btn_cerrar.setText("Cerrar")

    def _on_fallo(self, mensaje: str) -> None:
        self._log.append(f"ERROR: {mensaje}")
        self._lbl.setText(mensaje)
        self._btn_iniciar.setEnabled(True)
        self._btn_cerrar.setText("Cerrar")
