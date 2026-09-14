"""Servicio de transcripción automática con Whisper (integración del
Transcriptor Forense al sistema principal).

La transcripción corre en un proceso separado (`whisper_worker.py`) lanzado
con un Python que tenga openai-whisper + torch instalados — el venv de la app
no los necesita (torch no está disponible para todos los intérpretes y pesa
gigas). Este módulo se ocupa de:

- localizar los recursos: modelo .pt, ffmpeg y el Python con whisper;
- armar el comando del worker;
- normalizar el texto crudo que devuelve Whisper (port del NormalizadorTexto
  del Transcriptor Forense).
"""

from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from app import config

RUTA_WORKER: Path = Path(__file__).resolve().parent / "whisper_worker.py"

# Flag de Windows para no abrir ventanas de consola por cada subproceso.
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


# ---------------------------------------------------------------------------
# Localización de recursos
# ---------------------------------------------------------------------------

@dataclass
class RecursosWhisper:
    modelo: Path | None = None
    ffmpeg_dir: Path | None = None
    python: Path | None = None

    @property
    def disponible(self) -> bool:
        return None not in (self.modelo, self.ffmpeg_dir, self.python)

    def faltantes(self) -> list[str]:
        faltan = []
        if self.modelo is None:
            faltan.append("modelo Whisper (.pt)")
        if self.ffmpeg_dir is None:
            faltan.append("ffmpeg.exe")
        if self.python is None:
            faltan.append("Python con whisper instalado")
        return faltan


def _buscar_modelo(motor: str = "openai") -> Path | None:
    """Modelo del motor pedido, o None si no hay ninguno a mano.

    El motor 'openai' usa un archivo .pt; el 'faster' usa una CARPETA con el
    modelo convertido a CTranslate2. Si no hay carpeta local, se devuelve el
    nombre pelado y faster-whisper lo resuelve desde su caché.
    """
    if motor == "faster":
        for base in config.DIRS_RECURSOS_WHISPER:
            carpeta = Path(base) / "modelos" / "faster-whisper"
            if not carpeta.is_dir():
                continue
            # De mayor a menor calidad: se usa el mejor que esté disponible.
            for nombre in ("large-v3", "large-v2", "medium", "small", "base"):
                candidato = carpeta / nombre
                if (candidato / "model.bin").is_file():
                    return candidato
        # Sin carpeta local: el nombre alcanza para que faster-whisper lo
        # busque en su caché (y solo ahí, porque el equipo puede estar aislado).
        return Path(config.WHISPER_MODELO_FASTER)

    if config.RUTA_MODELO_WHISPER and Path(config.RUTA_MODELO_WHISPER).is_file():
        return Path(config.RUTA_MODELO_WHISPER)
    for base in config.DIRS_RECURSOS_WHISPER:
        carpeta = Path(base) / "modelos" / "whisper"
        if carpeta.is_dir():
            for nombre in ("small.pt", "base.pt", "medium.pt", "turbo.pt", "tiny.pt"):
                candidato = carpeta / nombre
                if candidato.is_file():
                    return candidato
    return None


def _buscar_ffmpeg() -> Path | None:
    if config.RUTA_FFMPEG and (Path(config.RUTA_FFMPEG) / "ffmpeg.exe").is_file():
        return Path(config.RUTA_FFMPEG)
    for base in config.DIRS_RECURSOS_WHISPER:
        for sub in ("ffmpeg", Path("ffmpeg") / "bin"):
            carpeta = Path(base) / sub
            if (carpeta / "ffmpeg.exe").is_file():
                return carpeta
    return None


def _python_tiene_whisper(python: Path) -> bool:
    try:
        r = subprocess.run(
            [str(python), "-c", "import whisper"],
            capture_output=True, timeout=60, creationflags=CREATE_NO_WINDOW,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _candidatos_python() -> list[Path]:
    """Intérpretes donde buscar whisper, en orden de preferencia.

    Empaquetado, `sys.executable` es el .exe de la aplicación y `sys.base_prefix`
    apunta adentro del bundle: probarlos con `-c "import whisper"` lanzaría
    copias del propio programa. Ahí se busca un Python instalado en el equipo,
    que es como funciona el Transcriptor Forense: el motor pesa gigas y no viaja
    dentro del ejecutable.
    """
    candidatos: list[Path] = []
    if config.PYTHON_WHISPER:
        candidatos.append(Path(config.PYTHON_WHISPER))

    if config.EMPAQUETADO:
        candidatos.extend(_pythons_del_sistema())
        return candidatos

    # El "home" del venv actual (el Python base del que se creó).
    candidatos.append(Path(sys.base_prefix) / "python.exe")
    candidatos.append(Path(sys.executable))
    return candidatos


def _pythons_del_sistema() -> list[Path]:
    """Pythons instalados en el equipo, del más nuevo al más viejo."""
    encontrados: list[Path] = []
    bases = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python",
        Path(os.environ.get("PROGRAMFILES", "")),
        Path("C:/"),
    ]
    for base in bases:
        if not base.is_dir():
            continue
        try:
            for carpeta in sorted(base.glob("Python3*"), reverse=True):
                candidato = carpeta / "python.exe"
                if candidato.is_file():
                    encontrados.append(candidato)
        except OSError:
            continue
    # Y el que esté en el PATH, si lo hay.
    desde_path = shutil.which("python")
    if desde_path:
        encontrados.append(Path(desde_path))
    return encontrados


def localizar_recursos(motor: str | None = None) -> RecursosWhisper:
    """Autodetecta modelo, ffmpeg y Python. Cachea el resultado del Python."""
    recursos = RecursosWhisper(
        modelo=_buscar_modelo(motor or config.WHISPER_MOTOR),
        ffmpeg_dir=_buscar_ffmpeg(),
    )
    global _python_cache
    if _python_cache is not None and _python_cache.is_file():
        recursos.python = _python_cache
    else:
        for cand in _candidatos_python():
            if cand.is_file() and _python_tiene_whisper(cand):
                recursos.python = cand
                _python_cache = cand
                break
    return recursos


_python_cache: Path | None = None


@dataclass
class OpcionMotor:
    """Una combinación motor+modelo que este equipo puede usar de verdad."""

    etiqueta: str
    motor: str
    modelo: Path
    nota: str = ""


# Cuánto tarda cada modelo por segundo de audio, medido en un equipo sin GPU
# (4 CPU lógicas) sobre una comunicación real de 2:48. Sirve para estimarle al
# analista cuánto va a esperar antes de que arranque, no para prometer nada.
FACTOR_TIEMPO = {
    ("openai", "small"): 0.73,
    ("faster", "small"): 1.02,
    ("faster", "medium"): 1.6,
    ("faster", "large-v2"): 2.4,
    ("faster", "large-v3"): 2.42,
}


def factor_tiempo(motor: str, modelo: Path | str) -> float:
    """Segundos de máquina por segundo de audio. 1.0 si el modelo es desconocido."""
    nombre = Path(str(modelo)).stem.replace(".pt", "")
    return FACTOR_TIEMPO.get((motor, nombre), 1.0)


def opciones_de_motor() -> list[OpcionMotor]:
    """Motores y modelos realmente disponibles, del más rápido al más preciso.

    Se listan solo los que están en el equipo: sin conexión y sin la carpeta de
    recursos conectada, ofrecer large-v3 sería mentirle al analista.
    """
    opciones: list[OpcionMotor] = []

    modelo_openai = _buscar_modelo("openai")
    if modelo_openai is not None:
        nombre = modelo_openai.stem
        opciones.append(OpcionMotor(
            f"Rápido — {nombre}", "openai", modelo_openai,
            "El de siempre. Alcanza para el barrido inicial de una causa.",
        ))

    for base in config.DIRS_RECURSOS_WHISPER:
        carpeta = Path(base) / "modelos" / "faster-whisper"
        if not carpeta.is_dir():
            continue
        for sub in sorted(carpeta.iterdir()):
            if (sub / "model.bin").is_file():
                opciones.append(OpcionMotor(
                    f"Preciso — {sub.name}", "faster", sub,
                    "Más lento, pero recorta los silencios (VAD) y acierta "
                    "palabras que el modelo chico inventa.",
                ))
    return opciones


def prompt_para(vocabulario_causa: str = "") -> str:
    """Contexto (initial_prompt) que se le pasa al modelo antes de transcribir.

    Devuelve "" —o sea, sin prompt— salvo que se active en `config`. Las dos
    perillas están apagadas por defecto porque medidas sobre audio real
    empeoraron el resultado; el detalle de la medición está en config.py.
    """
    base = config.WHISPER_PROMPT_BASE
    if not base:
        return ""
    extra = " ".join((vocabulario_causa or "").split())
    if extra and config.WHISPER_PROMPT_VOCABULARIO:
        return f"{base} Nombres y lugares que pueden aparecer: {extra}"
    return base


def comando_worker(
    recursos: RecursosWhisper,
    vocabulario_causa: str = "",
    motor: str | None = None,
) -> list[str]:
    """Arma la línea de comando del worker (los audios van por stdin)."""
    if not recursos.disponible:
        raise RuntimeError(
            "Faltan recursos para transcribir: " + ", ".join(recursos.faltantes())
        )
    return [
        str(recursos.python),
        str(RUTA_WORKER),
        "--modelo", str(recursos.modelo),
        "--ffmpeg", str(recursos.ffmpeg_dir),
        "--idioma", config.WHISPER_IDIOMA,
        "--prompt", prompt_para(vocabulario_causa),
        "--motor", motor or config.WHISPER_MOTOR,
    ]


# ---------------------------------------------------------------------------
# Normalización de texto (port del NormalizadorTexto del Transcriptor Forense)
# ---------------------------------------------------------------------------

def limpiar_texto(texto: str) -> str:
    """Normaliza saltos de línea, espacios duplicados y espacios ante signos."""
    if not texto:
        return ""
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\s+([,.;:!?])", r"\1", texto)
    lineas = [linea.strip() for linea in texto.split("\n")]
    return "\n".join(l for l in lineas if l).strip()


def quitar_repeticiones_simples(texto: str) -> str:
    """Reduce repeticiones consecutivas ('dale dale dale' -> 'dale dale')."""
    palabras = (texto or "").split()
    if not palabras:
        return ""
    resultado: list[str] = []
    anterior = None
    repeticiones = 0
    for palabra in palabras:
        base = re.sub(r"[^\wáéíóúÁÉÍÓÚñÑ]", "", palabra).lower()
        if base and base == anterior:
            repeticiones += 1
            if repeticiones < 2:
                resultado.append(palabra)
        else:
            anterior = base
            repeticiones = 0
            resultado.append(palabra)
    return " ".join(resultado)


def dividir_en_lineas(texto: str) -> list[str]:
    """Divide en líneas de diálogo por saltos y signos de cierre (. ! ? ;)."""
    if not texto:
        return []
    lineas: list[str] = []
    for bloque in texto.split("\n"):
        bloque = bloque.strip()
        if not bloque:
            continue
        for parte in re.split(r"(?<=[\.\!\?\;])\s+", bloque):
            parte = parte.strip()
            if len(parte) >= 2:
                lineas.append(parte)
    return lineas


def normalizar_transcripcion(texto_crudo: str) -> str:
    """Limpieza completa: devuelve el texto listo para el campo transcripcion,
    con una línea de diálogo por renglón."""
    limpio = limpiar_texto(texto_crudo)
    limpio = quitar_repeticiones_simples(limpio)
    return "\n".join(dividir_en_lineas(limpio))


# ---------------------------------------------------------------------------
# Segmentos con tiempos
# ---------------------------------------------------------------------------

# Los dos interlocutores de una comunicación, como los numera el informe:
# "1." el que llama, "2." el que atiende.
HABLANTES = ("1", "2")


def esta_anclado(segmento: dict) -> bool:
    """Si el minuto de esa frase lo confirmó una persona escuchando.

    Los tiempos que trae Whisper son una conjetura: el motor se desfasa, y a
    partir de cierto punto toda la transcripción queda unos segundos corrida.
    Sirven para ordenar la lista, no para afirmar cuándo se dijo algo —que es
    lo que un informe judicial afirma cuando lo imprime—.

    Por eso se distinguen: provisorio es lo que dijo la máquina, anclado es lo
    que el analista fijó escuchando. Lo que se ve en pantalla dice cuál es
    cuál, en vez de presentarlos como si valieran lo mismo.
    """
    return bool(segmento.get("anclado"))


def normalizar_segmentos(segmentos_crudos: list[dict] | None) -> list[dict]:
    """Limpia los segmentos de Whisper conservando sus tiempos.

    Se aplica la misma limpieza que al texto plano, pero por frase: así el
    renglón que ve el analista y el segundo del audio siguen apareados. Los
    segmentos que quedan vacíos después de limpiar (silencios que Whisper
    rotula con puntos suspensivos, muletillas repetidas) se descartan.
    """
    limpios: list[dict] = []
    for seg in segmentos_crudos or []:
        if not isinstance(seg, dict):
            continue
        texto = quitar_repeticiones_simples(limpiar_texto(str(seg.get("texto") or "")))
        texto = " ".join(texto.split())
        # Whisper rotula los silencios y la música con segmentos que no tienen
        # ni una letra ("...", "♪"): ocupan un renglón y no dicen nada.
        if not any(c.isalnum() for c in texto):
            continue
        try:
            inicio = round(float(seg.get("inicio") or 0.0), 2)
            fin = round(float(seg.get("fin") or 0.0), 2)
        except (TypeError, ValueError):
            continue
        nuevo = {"inicio": inicio, "fin": max(fin, inicio), "texto": texto}
        # El hablante lo pone el analista escuchando; si el segmento ya venía
        # con uno (al reprocesar o al releer de la base) se conserva.
        hablante = str(seg.get("hablante") or "").strip()
        if hablante in HABLANTES:
            nuevo["hablante"] = hablante
        # Lo que viene del motor nunca está anclado; al releer de la base, sí
        # conserva lo que el analista haya confirmado.
        if seg.get("anclado"):
            nuevo["anclado"] = True
        limpios.append(nuevo)
    return limpios


def hablante_de(segmento: dict) -> str:
    """'1', '2' o '' si todavía nadie atribuyó esa frase."""
    valor = str((segmento or {}).get("hablante") or "").strip()
    return valor if valor in HABLANTES else ""


def numerar_por_hablante(segmentos: list[dict]) -> list[tuple[str, str]]:
    """Devuelve (numero, texto) por frase, como los pide el informe judicial.

    El informe estándar numera cada renglón con el interlocutor que lo dijo:
    "1." el que llama, "2." el que atiende. Si el analista atribuyó las voces,
    manda eso. Las frases que quedaron sin atribuir heredan la del renglón
    anterior —dentro de un turno lo normal es que siga hablando el mismo— y,
    mientras no haya ninguna atribuida, se alterna como se hacía antes.

    La alternancia es una convención, no un dato: es lo que había cuando no se
    podía saber quién hablaba. Con las voces atribuidas el informe deja de
    adivinar.
    """
    filas: list[tuple[str, str]] = []
    ultimo = ""
    hay_atribuidas = any(hablante_de(s) for s in segmentos)
    for i, seg in enumerate(segmentos):
        propio = hablante_de(seg)
        if propio:
            ultimo = propio
            numero = propio
        elif hay_atribuidas and ultimo:
            numero = ultimo
        else:
            numero = "1" if i % 2 == 0 else "2"
        filas.append((numero, seg.get("texto", "")))
    return filas


def texto_de_segmentos(segmentos: list[dict]) -> str:
    """Arma el texto plano del campo `transcripcion` a partir de los segmentos.

    Un renglón por segmento: lo que se exporta y se busca queda alineado con lo
    que se ve en el panel, renglón por renglón.
    """
    return "\n".join(s["texto"] for s in segmentos if s.get("texto"))


def segmento_en(segmentos: list[dict], segundo: float) -> int:
    """Índice del segmento que suena en ese segundo, o -1 si ninguno.

    En el silencio entre dos frases devuelve la que terminó recién, que es lo
    que el ojo espera: el renglón resaltado no parpadea en cada pausa.
    """
    indice = -1
    for i, seg in enumerate(segmentos):
        if segundo + 0.01 >= seg.get("inicio", 0.0):
            indice = i
        else:
            break
    return indice


# =========================== modo texto plano ==============================
#
# Corregir renglón por renglón sirve para arreglar una palabra, pero no para
# lo que Whisper hace mal de verdad: partir una sola oración en cinco pedazos
# y juntar dos turnos en uno. Eso se arregla de un tirón sobre el texto entero
# —borrando un salto de línea se unen dos frases, agregando uno se parten—, que
# es escribir, no navegar por una lista.
#
# Lo caro es no perder los tiempos al volver. Las frases que el analista no
# tocó tienen que conservar el suyo; las nuevas se reparten el hueco entre sus
# vecinas. Se resuelve comparando el texto viejo con el nuevo y reconociendo
# los tramos que quedaron iguales, que es lo que hace `difflib`.

_RE_HABLANTE = re.compile(r"^\s*([12])\s*[.:\-]\s*(.*)$")

# Duración que se le da a una frase nueva cuando no hay una vecina que acote
# el hueco (al final del todo, o en una transcripción que quedó vacía).
_SEGUNDOS_POR_FRASE_NUEVA = 2.0


def texto_editable(segmentos: list[dict]) -> str:
    """La transcripción como texto plano, un renglón por frase.

    El renglón lleva adelante "1." o "2." cuando el analista atribuyó la voz,
    igual que el informe judicial. Las que no atribuyó van sin prefijo: si se
    escribiera el número que el informe deduce, volver del modo texto lo
    dejaría fijado sin que nadie lo haya decidido.
    """
    renglones = []
    for s in segmentos:
        texto = str(s.get("texto") or "").strip()
        hablante = hablante_de(s)
        renglones.append(f"{hablante}. {texto}" if hablante else texto)
    return "\n".join(renglones)


def _parsear(texto: str) -> list[tuple[str, str]]:
    filas = []
    for renglon in (texto or "").splitlines():
        limpio = " ".join(renglon.split())
        if not limpio:
            continue          # los renglones en blanco se descartan
        coincidencia = _RE_HABLANTE.match(limpio)
        if coincidencia and coincidencia.group(2).strip():
            filas.append((coincidencia.group(1), coincidencia.group(2).strip()))
        else:
            filas.append(("", limpio))
    return filas


def _interpolar(segmentos: list[dict], duracion_total: float) -> None:
    """Le pone tiempo a las frases nuevas, entre las que sí lo tienen."""
    n = len(segmentos)
    i = 0
    while i < n:
        if segmentos[i].get("inicio") is not None:
            i += 1
            continue
        j = i
        while j < n and segmentos[j].get("inicio") is None:
            j += 1
        # Bordes del hueco: lo que terminó antes y lo que empieza después.
        desde = float(segmentos[i - 1].get("fin") or 0.0) if i > 0 else 0.0
        if j < n:
            hasta = float(segmentos[j].get("inicio") or desde)
        else:
            hasta = max(
                duracion_total, desde + (j - i) * _SEGUNDOS_POR_FRASE_NUEVA
            )
        if hasta <= desde:
            hasta = desde + (j - i) * _SEGUNDOS_POR_FRASE_NUEVA
        paso = (hasta - desde) / (j - i)
        for k in range(i, j):
            segmentos[k]["inicio"] = round(desde + paso * (k - i), 2)
            segmentos[k]["fin"] = round(desde + paso * (k - i + 1), 2)
        i = j


def segmentos_desde_texto(
    texto: str, previos: list[dict], duracion_total: float = 0.0
) -> list[dict]:
    """Rearma los segmentos desde el texto plano, conservando los minutos.

    Lo que no cambió mantiene su tiempo exacto; lo nuevo reparte el hueco
    entre sus vecinas. Así se puede reescribir la transcripción entera sin
    perder el trabajo de haberla sincronizada, que es lo que hace que un clic
    lleve al segundo justo.
    """
    filas = _parsear(texto)
    viejos_txt = [str(s.get("texto") or "").strip() for s in previos]
    nuevos_txt = [t for _h, t in filas]

    nuevos: list[dict] = [{"texto": t} for t in nuevos_txt]
    for bloque in SequenceMatcher(None, viejos_txt, nuevos_txt).get_matching_blocks():
        for k in range(bloque.size):
            viejo = previos[bloque.a + k]
            destino = nuevos[bloque.b + k]
            destino["inicio"] = float(viejo.get("inicio") or 0.0)
            destino["fin"] = float(viejo.get("fin") or destino["inicio"])
            if viejo.get("anclado"):
                destino["anclado"] = True

    _interpolar(nuevos, duracion_total)
    # strict: `nuevos` se arma a partir de `filas`, así que un desajuste sería
    # un error de este módulo. Sin el strict, la voz se le pegaría a la frase
    # equivocada y saldría así en el informe.
    for fila, seg in zip(filas, nuevos, strict=True):
        if fila[0] in HABLANTES:
            seg["hablante"] = fila[0]
    return nuevos
