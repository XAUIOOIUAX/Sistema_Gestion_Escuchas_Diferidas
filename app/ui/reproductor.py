"""Reproductor de audio embebido para el panel de detalle (pseudocódigo 6.3.1).

Reproduce el audio de la intervención sin salir de la aplicación: play/pausa,
forma de onda clickeable (seek), tiempos, velocidad de reproducción variable
(clave para escuchas largas) y marcas de momentos clave dibujadas sobre la onda.

La forma de onda se decodifica con el módulo estándar `wave` para archivos WAV
PCM (el formato habitual de las plataformas de interceptación). Para otros
formatos se muestra una barra de progreso plana; la reproducción funciona igual
vía QtMultimedia.
"""

from __future__ import annotations

import struct
import subprocess
import sys
import wave
from pathlib import Path

# En Windows, sin esto cada decodificación abre y cierra una ventana de consola.
_SIN_CONSOLA = 0x08000000 if sys.platform == "win32" else 0

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import sesion
from app.ui import tema

_BUCKETS = 140


def leer_waveform(ruta: Path, buckets: int = _BUCKETS) -> list[float] | None:
    """Devuelve `buckets` picos normalizados (0..1) del audio, o None.

    Primero se intenta leer el WAV directamente, que es gratis. Si el formato
    no es PCM se decodifica con ffmpeg: los audios de las prestadoras vienen en
    G.711 A-law (`pcm_alaw`, 8 kHz), que el módulo `wave` rechaza con "unknown
    format: 6". Justamente en esos —o sea, en todas las escuchas reales— la
    onda quedaba plana y el analista no tenía dónde ver los silencios.
    """
    picos = _picos_de_wav_pcm(ruta, buckets)
    if picos is not None:
        return picos
    return _picos_con_ffmpeg(ruta, buckets)


def _picos_normalizados(picos: list[float]) -> list[float]:
    tope = max(picos) if picos else 0.0
    return [p / tope for p in picos] if tope > 0 else picos


def _picos_con_ffmpeg(ruta: Path, buckets: int) -> list[float] | None:
    """Decodifica cualquier formato a PCM 16 bits mono y saca los picos.

    Se hace en memoria y de una sola pasada: una comunicación de diez minutos
    a 8 kHz son 9 MB, que se procesan en menos de un segundo.
    """
    # Se busca SOLO ffmpeg. `localizar_recursos()` haría además la sonda del
    # Python con whisper, que lanza un subproceso y tarda seis segundos: una
    # eternidad para algo que pasa cada vez que se selecciona una fila.
    from app.servicios.transcripcion import _buscar_ffmpeg

    carpeta = _buscar_ffmpeg()
    if carpeta is None:
        return None
    ejecutable = Path(carpeta) / "ffmpeg.exe"
    if not ejecutable.is_file():
        return None
    try:
        salida = subprocess.run(
            [str(ejecutable), "-nostdin", "-v", "quiet", "-i", str(ruta),
             "-f", "s16le", "-ac", "1", "-acodec", "pcm_s16le", "-"],
            capture_output=True, timeout=60, creationflags=_SIN_CONSOLA,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    if len(salida) < 2:
        return None

    total = len(salida) // 2
    por_bucket = max(1, total // buckets)
    muestras = min(por_bucket, 2048)
    picos = [0.0] * buckets
    for b in range(buckets):
        inicio = min(b * por_bucket, total - 1) * 2
        crudo = salida[inicio:inicio + muestras * 2]
        n = len(crudo) // 2
        if not n:
            continue
        valores = struct.unpack(f"<{n}h", crudo[: n * 2])
        picos[b] = max(abs(v) for v in valores) / 32768.0
    return _picos_normalizados(picos)


def _picos_de_wav_pcm(ruta: Path, buckets: int) -> list[float] | None:
    """Picos de un WAV PCM de 8/16/32 bits, mono o multicanal (primer canal)."""
    try:
        with wave.open(str(ruta), "rb") as wav:
            n_frames = wav.getnframes()
            ancho = wav.getsampwidth()
            canales = wav.getnchannels()
            if n_frames == 0 or ancho not in (1, 2, 4):
                return None

            fmt_por_ancho = {1: "b", 2: "h", 4: "i"}
            fmt = fmt_por_ancho[ancho]
            maximo = float(2 ** (8 * ancho - 1))

            picos = [0.0] * buckets
            frames_por_bucket = max(1, n_frames // buckets)
            # Para audios largos, muestrear un tramo por bucket alcanza y evita
            # decodificar el archivo completo.
            muestras_por_tramo = min(frames_por_bucket, 2048)

            for b in range(buckets):
                wav.setpos(min(b * frames_por_bucket, n_frames - 1))
                crudo = wav.readframes(muestras_por_tramo)
                if not crudo:
                    continue
                n_muestras = len(crudo) // ancho
                if n_muestras == 0:
                    continue
                valores = struct.unpack(f"<{n_muestras}{fmt}", crudo[: n_muestras * ancho])
                # Solo el primer canal.
                canal = valores[::canales] if canales > 1 else valores
                if canal:
                    picos[b] = max(abs(v) for v in canal) / maximo
            return _picos_normalizados(picos)
    except (wave.Error, OSError, struct.error, EOFError):
        return None


class Waveform(QWidget):
    """Forma de onda clickeable con progreso y marcas superpuestas."""

    buscado = Signal(float)  # fracción 0..1 donde se hizo click

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._picos: list[float] | None = None
        self._progreso = 0.0  # 0..1
        self._marcas: list[float] = []  # fracciones 0..1
        self.setFixedHeight(56)
        self.setCursor(Qt.PointingHandCursor)

    def set_picos(self, picos: list[float] | None) -> None:
        self._picos = picos
        self.update()

    def set_progreso(self, fraccion: float) -> None:
        self._progreso = max(0.0, min(1.0, fraccion))
        self.update()

    def set_marcas(self, fracciones: list[float]) -> None:
        self._marcas = [f for f in fracciones if 0.0 <= f <= 1.0]
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self.width() > 0:
            self.buscado.emit(event.position().x() / self.width())

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        painter.fillRect(self.rect(), QColor(tema.BG_DEEP))

        mitad = h / 2
        picos = self._picos or [0.35] * _BUCKETS  # barra plana si no hay WAV
        n = len(picos)
        paso = w / n
        ancho_barra = max(1.0, paso * 0.65)
        x_progreso = self._progreso * w

        for i, pico in enumerate(picos):
            x = i * paso + (paso - ancho_barra) / 2
            alto = max(2.0, pico * (h - 10))
            color = QColor(
                tema.ACCENT if x + ancho_barra / 2 <= x_progreso else tema.LINE
            )
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(
                int(x), int(mitad - alto / 2), int(ancho_barra), int(alto), 1, 1
            )

        # Marcas de momentos clave.
        pen = QPen(QColor(tema.DANGER), 2)
        painter.setPen(pen)
        for frac in self._marcas:
            x = int(frac * w)
            painter.drawLine(x, 2, x, h - 2)

        # Cabezal de reproducción.
        painter.setPen(QPen(QColor(tema.TEXT_PRIMARY), 1))
        painter.drawLine(int(x_progreso), 0, int(x_progreso), h)


# Escalones de velocidad. Más fino cerca de 1× —que es donde se trabaja— y
# grueso en los extremos, para que subir o bajar de a un paso sirva.
_VELOCIDADES = (
    0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.4, 1.6, 1.8, 2.0,
)


# Clave de la preferencia y marca de los perfiles de manos libres. Un auricular
# Bluetooth se presenta al sistema DOS veces: en estéreo (el bueno, el de
# escuchar) y en "manos libres" (el de hablar por teléfono, mono y de calidad
# telefónica). Windows pone de fábrica el que se le antoja, y si queda el
# segundo el audio sale bajísimo o directamente no sale. Es un problema real y
# no se puede pedir al analista que lo adivine.
_PREF_SALIDA = "salida_audio"
_MARCAS_MANOS_LIBRES = ("hands-free", "manos libres", "headset", "communications")


def es_salida_de_manos_libres(descripcion: str) -> bool:
    texto = (descripcion or "").casefold()
    return any(marca in texto for marca in _MARCAS_MANOS_LIBRES)


def destino_al_reanudar(
    posicion_ms: int, retroceso_seg: float, venia_pausado: bool
) -> int:
    """Desde qué milisegundo tiene que volver a sonar.

    Está afuera de la clase a propósito: probar esto contra un QMediaPlayer sin
    fuente cargada no prueba nada —`setPosition` sobre un reproductor vacío se
    ignora y la posición queda en cero, así que la prueba pasa sola y no mira
    nada—. Acá la regla se ve y se verifica.
    """
    if not venia_pausado or retroceso_seg <= 0:
        return posicion_ms
    return max(0, posicion_ms - int(retroceso_seg * 1000))


def _formato_mmss(segundos: float) -> str:
    segundos = max(0, int(round(segundos)))
    return f"{segundos // 60}:{segundos % 60:02d}"


class ReproductorAudio(QWidget):
    """Reproductor compacto: waveform + play/pausa + tiempos + velocidad.

    La velocidad NO altera el tono. Qt 6 usa el backend FFmpeg, que para
    `playbackRate` aplica un filtro de tipo `atempo`: estira el tiempo y
    remuestrea, en vez de reproducir más rápido la misma señal —que es lo que
    sube el tono y vuelve las voces irreconocibles—. Para una escucha
    telefónica eso no es un lujo: a 0,6× una voz tapada se entiende, y con el
    tono corrido no se reconocería a quien habla.
    """

    duracion_conocida = Signal(float)  # segundos, al cargar metadatos
    reproduccion_terminada = Signal()
    posicion_cambiada = Signal(float)  # segundos, mientras suena
    velocidad_cambiada = Signal(float)
    ancla_cambiada = Signal(float)     # el punto al que vuelve Espacio

    # Al reanudar se retrocede esto, para volver a oír el final de la frase que
    # se estaba escribiendo cuando se pausó. Es la función que más se nota de
    # un transcriptor: sin ella, cada pausa obliga a buscar a mano dónde iba.
    RETROCESO_POR_DEFECTO = 2.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._duracion_ms = 0
        self._retroceso_seg = 0.0
        self._venia_pausado = False
        self._tramo: tuple[float, float] | None = None
        self._repetir = False
        # El punto al que vuelve Espacio. Lo mueve todo salto pedido a mano
        # —un clic en la onda, una frase, las flechas— y nunca el avance
        # normal de la reproducción.
        self._ancla = 0.0
        self._player = QMediaPlayer(self)
        self._salida = QAudioOutput(self)
        self._player.setAudioOutput(self._salida)
        self._dispositivos = QMediaDevices(self)
        self._construir()
        self._poblar_salidas()
        self._dispositivos.audioOutputsChanged.connect(self._poblar_salidas)

        self._player.positionChanged.connect(self._on_posicion)
        self._player.durationChanged.connect(self._on_duracion)
        self._player.mediaStatusChanged.connect(self._on_estado_media)
        self._player.errorOccurred.connect(self._on_error)

    def _construir(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self.onda = Waveform()
        self.onda.buscado.connect(self._buscar)
        lay.addWidget(self.onda)

        fila = QHBoxLayout()
        fila.setSpacing(8)

        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedWidth(40)
        self.btn_play.setToolTip("Reproducir / pausar")
        self.btn_play.clicked.connect(self.alternar)
        fila.addWidget(self.btn_play)

        self.lbl_tiempo = QLabel("0:00 / 0:00")
        self.lbl_tiempo.setStyleSheet(
            f"color:{tema.TEXT_MUTED}; font-family:'IBM Plex Mono','Consolas',monospace;"
            "font-size:11px;"
        )
        fila.addWidget(self.lbl_tiempo)
        fila.addStretch(1)

        self.cmb_velocidad = QComboBox()
        for factor in _VELOCIDADES:
            self.cmb_velocidad.addItem(f"{factor:g}×".replace(".", ","), factor)
        self.cmb_velocidad.setCurrentIndex(_VELOCIDADES.index(1.0))
        self.cmb_velocidad.setToolTip("Velocidad de reproducción")
        self.cmb_velocidad.currentIndexChanged.connect(self._cambiar_velocidad)
        fila.addWidget(self.cmb_velocidad)

        self.cmb_salida = QComboBox()
        self.cmb_salida.setMaximumWidth(200)
        self.cmb_salida.setToolTip("Por dónde sale el audio")
        self.cmb_salida.currentIndexChanged.connect(self._cambiar_salida)
        fila.addWidget(self.cmb_salida)

        self.lbl_aviso_salida = QLabel("")
        self.lbl_aviso_salida.setWordWrap(True)
        self.lbl_aviso_salida.setStyleSheet(
            f"color:{tema.DANGER}; font-size:10px;"
        )
        self.lbl_aviso_salida.setVisible(False)
        lay.addLayout(fila)
        lay.addWidget(self.lbl_aviso_salida)

    # --------------------------- salida de audio ----------------------------
    def _poblar_salidas(self) -> None:
        """Llena la lista de salidas y reaplica la que el analista eligió.

        Se rehace cuando el sistema avisa que cambiaron los dispositivos: si el
        auricular se apaga y se vuelve a prender, la elección tiene que volver
        sola en vez de quedar en la salida que Windows haya puesto mientras
        tanto.
        """
        recordada = sesion.preferencia(_PREF_SALIDA)
        salidas = QMediaDevices.audioOutputs()
        self.cmb_salida.blockSignals(True)
        self.cmb_salida.clear()
        elegido = -1
        for i, dispositivo in enumerate(salidas):
            self.cmb_salida.addItem(dispositivo.description(), dispositivo)
            if dispositivo.description() == recordada:
                elegido = i
        self.cmb_salida.setEnabled(bool(salidas))
        if elegido >= 0:
            self.cmb_salida.setCurrentIndex(elegido)
        else:
            # Sin preferencia, la del sistema, que es lo que hacía siempre.
            por_defecto = QMediaDevices.defaultAudioOutput()
            for i, dispositivo in enumerate(salidas):
                if dispositivo.id() == por_defecto.id():
                    self.cmb_salida.setCurrentIndex(i)
                    break
        self.cmb_salida.blockSignals(False)
        self._aplicar_salida(guardar=False)

    def _cambiar_salida(self) -> None:
        self._aplicar_salida(guardar=True)

    def _aplicar_salida(self, guardar: bool) -> None:
        dispositivo = self.cmb_salida.currentData()
        if dispositivo is None:
            return
        self._salida.setDevice(dispositivo)
        if guardar:
            sesion.set_preferencia(_PREF_SALIDA, dispositivo.description())
        manos_libres = es_salida_de_manos_libres(dispositivo.description())
        self.lbl_aviso_salida.setVisible(manos_libres)
        if manos_libres:
            self.lbl_aviso_salida.setText(
                "Esa salida es el perfil de «manos libres» del auricular, el "
                "que usa el teléfono para hablar: suena bajísimo o no suena. "
                "Elegí el mismo auricular en su versión estéreo."
            )

    def salida_actual(self) -> str:
        return self.cmb_salida.currentText()

    # ------------------------------ API ------------------------------------
    def cargar(self, ruta: Path | None) -> None:
        """Carga un archivo (o None para deshabilitar el reproductor)."""
        self._player.stop()
        self._tramo = None
        self._repetir = False
        self._venia_pausado = False
        self.set_ancla(0.0)
        self.onda.set_progreso(0.0)
        if ruta is None:
            self._player.setSource(QUrl())
            self.setEnabled(False)
            self.onda.set_picos(None)
            self.lbl_tiempo.setText("0:00 / 0:00")
            return
        self.setEnabled(True)
        self.onda.set_picos(leer_waveform(ruta))
        self._player.setSource(QUrl.fromLocalFile(str(ruta)))

    def alternar(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
            self._venia_pausado = True
            self.btn_play.setText("▶")
        else:
            # Solo al REANUDAR: arrancar de cero o después de un salto
            # deliberado tiene que sonar donde el analista lo dejó, no dos
            # segundos antes de eso.
            destino = destino_al_reanudar(
                self._player.position(), self._retroceso_seg, self._venia_pausado
            )
            if self._tramo is not None and not (
                self._tramo[0] <= destino / 1000.0 < self._tramo[1]
            ):
                # Con un tramo seleccionado, play suena ESE tramo: si el cursor
                # quedó afuera (o justo en el borde final), vuelve al principio.
                destino = int(self._tramo[0] * 1000)
            if destino != self._player.position():
                self._player.setPosition(destino)
            self._venia_pausado = False
            self._player.setPlaybackRate(self.cmb_velocidad.currentData())
            self._player.play()
            self.btn_play.setText("⏸")

    def esta_reproduciendo(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlayingState

    def set_tramo(
        self, tramo: tuple[float, float] | None, repetir: bool = False
    ) -> None:
        """Acota la reproducción a ese tramo del audio. None la libera.

        Con `repetir` apagado el audio se detiene al llegar al final —es lo que
        hace un selector: seleccionar un pedazo y darle play reproduce ESE
        pedazo—. Con `repetir` prendido vuelve a empezar, que es la forma de
        sacar un pasaje que no se entiende: dejarlo dando vueltas y escribir
        encima sin tocar nada entre pasada y pasada.
        """
        self._tramo = tramo
        self._repetir = bool(repetir)
        if tramo:
            # Marcar un tramo pone la marca en su principio: es de donde uno
            # espera que empiece a sonar lo que acaba de seleccionar.
            self.set_ancla(tramo[0])
            if not (tramo[0] <= self.posicion_actual_seg() <= tramo[1]):
                self._venia_pausado = False
                self._player.setPosition(int(tramo[0] * 1000))

    def set_bucle(self, tramo: tuple[float, float] | None) -> None:
        """Atajo de `set_tramo(..., repetir=True)`."""
        self.set_tramo(tramo, repetir=True)

    def tramo(self) -> tuple[float, float] | None:
        return self._tramo

    def bucle(self) -> tuple[float, float] | None:
        """El tramo, solo si además se está repitiendo."""
        return self._tramo if self._repetir else None

    def set_retroceso(self, segundos: float) -> None:
        """Cuánto retrocede al reanudar. 0 lo apaga."""
        self._retroceso_seg = max(0.0, float(segundos))

    def retroceso(self) -> float:
        return self._retroceso_seg

    def desplazar(self, segundos: float) -> None:
        """Adelanta o retrocede sin tocar el estado de reproducción."""
        destino = self._player.position() + int(segundos * 1000)
        tope = self._duracion_ms if self._duracion_ms > 0 else destino
        destino = max(0, min(destino, tope))
        self.set_ancla(destino / 1000.0)
        self._player.setPosition(destino)

    def velocidad(self) -> float:
        return float(self.cmb_velocidad.currentData() or 1.0)

    def cambiar_velocidad_relativa(self, pasos: int) -> float:
        """Sube o baja un escalón de la lista de velocidades. Devuelve la nueva."""
        indice = max(0, min(len(_VELOCIDADES) - 1,
                            self.cmb_velocidad.currentIndex() + pasos))
        self.cmb_velocidad.setCurrentIndex(indice)
        return self.velocidad()

    def detener(self) -> None:
        self._player.stop()
        self._venia_pausado = False
        self.btn_play.setText("▶")

    def posicion_actual_seg(self) -> float:
        return self._player.position() / 1000.0

    def saltar_a(self, segundos: float) -> None:
        # Un salto pedido a mano manda: no se le aplica el retroceso encima,
        # que dejaría el audio dos segundos antes de donde se pidió.
        self._venia_pausado = False
        self.set_ancla(segundos)
        self._player.setPosition(int(segundos * 1000))

    def set_ancla(self, segundos: float) -> None:
        """Marca el punto desde donde vuelve a sonar con Espacio."""
        self._ancla = max(0.0, float(segundos))
        self.ancla_cambiada.emit(self._ancla)

    def ancla(self) -> float:
        return self._ancla

    def reproducir_desde_el_ancla(self) -> None:
        """Espacio, como en Audacity: suena desde la marca y al parar vuelve ahí.

        Es otra cosa que pausar. Pausar y reanudar sirve para transcribir de
        corrido: el audio sigue de donde iba, unos segundos antes. Esto sirve
        para lo contrario, que es repasar un pedazo: se aprieta, se escucha, se
        aprieta de nuevo y el cursor vuelve al mismo lugar, listo para volver a
        oír exactamente lo mismo sin buscarlo.
        """
        destino = self._ancla
        if self._tramo is not None and not (
            self._tramo[0] <= destino < self._tramo[1]
        ):
            destino = self._tramo[0]
        self._venia_pausado = False
        if self.esta_reproduciendo():
            self._player.pause()
            self.btn_play.setText("▶")
        else:
            self._player.setPlaybackRate(self.cmb_velocidad.currentData())
            self._player.play()
            self.btn_play.setText("⏸")
        self._player.setPosition(int(destino * 1000))

    def set_marcas(self, segundos: list[float]) -> None:
        if self._duracion_ms > 0:
            self.onda.set_marcas([s * 1000 / self._duracion_ms for s in segundos])
        else:
            self._marcas_pendientes = list(segundos)

    # --------------------------- señales internas ---------------------------
    def _buscar(self, fraccion: float) -> None:
        self._venia_pausado = False
        if self._duracion_ms > 0:
            self.set_ancla(fraccion * self._duracion_ms / 1000.0)
            self._player.setPosition(int(fraccion * self._duracion_ms))

    def _cambiar_velocidad(self) -> None:
        self._player.setPlaybackRate(self.cmb_velocidad.currentData())
        self.velocidad_cambiada.emit(self.velocidad())

    def _on_posicion(self, ms: int) -> None:
        if self._tramo is not None and ms / 1000.0 >= self._tramo[1]:
            if self._repetir:
                # Vuelve al principio del tramo sin pasar por `saltar_a`, que
                # desarma el retroceso: acá el salto no lo pidió nadie a mano.
                self._player.setPosition(int(self._tramo[0] * 1000))
                return
            # Sin repetición se para en el borde, como cualquier selector.
            self._player.pause()
            self._venia_pausado = True
            self.btn_play.setText("▶")
            self._player.setPosition(int(self._tramo[1] * 1000))
        if self._duracion_ms > 0:
            self.onda.set_progreso(ms / self._duracion_ms)
        self.lbl_tiempo.setText(
            f"{_formato_mmss(ms / 1000)} / {_formato_mmss(self._duracion_ms / 1000)}"
        )
        self.posicion_cambiada.emit(ms / 1000)

    def _on_duracion(self, ms: int) -> None:
        self._duracion_ms = ms
        self.lbl_tiempo.setText(
            f"0:00 / {_formato_mmss(ms / 1000)}"
        )
        if ms > 0:
            pendientes = getattr(self, "_marcas_pendientes", None)
            if pendientes is not None:
                self.set_marcas(pendientes)
                self._marcas_pendientes = None
            self.duracion_conocida.emit(ms / 1000.0)

    def _on_estado_media(self, estado) -> None:
        if estado == QMediaPlayer.EndOfMedia:
            self.btn_play.setText("▶")
            self.onda.set_progreso(1.0)
            self.reproduccion_terminada.emit()

    def _on_error(self, _error, descripcion: str) -> None:
        self.lbl_tiempo.setText(descripcion or "Error de reproducción")
