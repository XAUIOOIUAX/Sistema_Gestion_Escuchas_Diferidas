"""Lectura de DatosCausa.txt (metadatos del CD de intervención).

Port del ParserDatosCausa del Transcriptor Forense. Extrae el número/id del CD,
la fecha y —lo más importante para el índice— la lista de abonados declarados
(las líneas intervenidas). Formato esperado:

    CD 109
    Juzgado:      ...
    Causa:        SA-00000/26
    Descr. Causa: ...
    Fecha:        23-03-2026
    Id del CD:    700000003
    Nº abonados (2):
        3875 550050
        3515 550051
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.core.normalizers import normalizar_numero

_NOMBRES = ("DatosCausa.txt", "datoscausa.txt", "Datos_Causa.txt")
_FORMATOS_FECHA = ("%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y")


@dataclass
class DatosCausa:
    cd_numero: str = ""
    cd_id: str = ""
    causa: str = ""
    descripcion: str = ""
    fecha: str = ""
    abonados_declarados: list[str] = field(default_factory=list)


def buscar_datos_causa(ruta_raiz: str | Path) -> Path | None:
    """Busca DatosCausa.txt en la raíz o en cualquier subcarpeta."""
    raiz = Path(ruta_raiz)
    for nombre in _NOMBRES:
        directo = raiz / nombre
        if directo.is_file():
            return directo
    for encontrado in raiz.rglob("*.txt"):
        if encontrado.name.lower().replace("_", "") == "datoscausa.txt":
            return encontrado
    return None


def _leer(ruta: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return ruta.read_text(encoding=enc)
        except (UnicodeDecodeError, OSError):
            continue
    return ""


def _valor_por_clave(lineas: list[str], clave: str) -> str:
    patron = re.compile(rf"^\s*{re.escape(clave)}\s*:\s*(.*)$", re.IGNORECASE)
    for linea in lineas:
        m = patron.match(linea)
        if m:
            return m.group(1).strip()
    return ""


def parsear(contenido: str) -> DatosCausa:
    datos = DatosCausa()
    lineas = [l.rstrip() for l in (contenido or "").splitlines()]
    if not lineas:
        return datos

    m = re.search(r"\bCD\s+(\d+)\b", lineas[0], flags=re.IGNORECASE)
    if m:
        datos.cd_numero = m.group(1)

    datos.causa = _valor_por_clave(lineas, "Causa")
    datos.descripcion = _valor_por_clave(lineas, "Descr. Causa")
    datos.cd_id = _valor_por_clave(lineas, "Id del CD")

    fecha_raw = _valor_por_clave(lineas, "Fecha").strip()
    for fmt in _FORMATOS_FECHA:
        try:
            datos.fecha = datetime.strptime(fecha_raw, fmt).strftime("%d/%m/%Y")
            break
        except ValueError:
            continue

    datos.abonados_declarados = _extraer_abonados(lineas)
    return datos


def _extraer_abonados(lineas: list[str]) -> list[str]:
    inicio = None
    for i, linea in enumerate(lineas):
        if re.search(r"^\s*N[º°o]?\s*abonados", linea, flags=re.IGNORECASE):
            inicio = i + 1
            break
    if inicio is None:
        return []

    abonados: list[str] = []
    for linea in lineas[inicio:]:
        texto = linea.strip()
        if not texto:
            continue
        # Otra clave "Campo: valor" corta la lista de abonados.
        if ":" in texto and not re.fullmatch(r"[\d\s\-]+", texto):
            break
        digitos = "".join(ch for ch in texto if ch.isdigit())
        if len(digitos) >= 6:
            abonados.append(normalizar_numero(texto))
    return abonados


def leer_datos_causa(ruta_raiz: str | Path) -> DatosCausa:
    """Localiza y parsea DatosCausa.txt bajo la carpeta raíz. Vacío si no está."""
    ruta = buscar_datos_causa(ruta_raiz)
    if ruta is None:
        return DatosCausa()
    return parsear(_leer(ruta))


# ---------------------------------------------------------------------------
# Datos.txt por abonado: manifiesto con duración exacta de cada audio
# ---------------------------------------------------------------------------

# Línea de manifiesto: "23/08/2025 10:46:30;00:00:31;B-...-0159184.wav"
_RE_MANIFIESTO = re.compile(
    r"^\s*(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})\s*;\s*"
    r"(\d{1,2}:\d{2}:\d{2})\s*;\s*(.+\.\w+)\s*$"
)


def _hms_a_segundos(hms: str) -> float:
    partes = hms.split(":")
    try:
        h, m, s = (int(p) for p in partes)
    except (ValueError, TypeError):
        return 0.0
    return float(h * 3600 + m * 60 + s)


def duraciones_desde_datos_txt(ruta_datos_txt: str | Path) -> dict[str, float]:
    """Devuelve {nombre_audio.wav_lower: duracion_seg} leyendo un Datos.txt.

    El manifiesto de cada abonado lista, por audio, su fecha y duración exacta
    provista por la prestadora. Se usa para completar duracion_seg sin decodificar.
    """
    ruta = Path(ruta_datos_txt)
    if not ruta.is_file():
        return {}
    mapa: dict[str, float] = {}
    for linea in _leer(ruta).splitlines():
        m = _RE_MANIFIESTO.match(linea)
        if m:
            nombre = m.group(3).strip().lower()
            mapa[nombre] = _hms_a_segundos(m.group(2))
    return mapa


def duraciones_de_carpeta(ruta_raiz: str | Path) -> dict[str, float]:
    """Une los Datos.txt de todos los abonados de la carpeta en un solo mapa
    {nombre_audio_lower: duracion_seg}."""
    total: dict[str, float] = {}
    for datos in Path(ruta_raiz).rglob("Datos.txt"):
        total.update(duraciones_desde_datos_txt(datos))
    return total


# ---------------------------------------------------------------------------
# Índice de CDs: un DatosCausa.txt por entrega
# ---------------------------------------------------------------------------

class IndiceCDs:
    """Mapa carpeta-de-CD -> DatosCausa, para toda una importación.

    Una causa no trae un CD sino una serie: cada entrega de la prestadora llega
    en su propia carpeta con su propio DatosCausa.txt, que declara su número
    ("CD 1"), su identificador ("Id del CD: 700000001"), su fecha y qué líneas
    estaban intervenidas ESE día —la lista se achica cuando el juzgado levanta
    alguna—.

    Hasta ahora se leía un solo DatosCausa.txt para toda la importación (el
    primero que aparecía) y el número de CD de los registros se adivinaba desde
    la ruta. Eso fallaba de dos maneras: si las carpetas no se llaman "N. CDxxx"
    el número sale de cualquier carpeta numerada del árbol, y los abonados
    declarados quedaban los de una sola entrega.

    Con este índice el CD lo dice el archivo, no la ruta, y los declarados son
    la unión de todas las entregas.
    """

    def __init__(self, ruta_raiz: str | Path) -> None:
        self.raiz = Path(ruta_raiz)
        self.por_carpeta: dict[Path, DatosCausa] = {}
        for archivo in self.raiz.rglob("*.txt"):
            if archivo.name.lower().replace("_", "") == "datoscausa.txt":
                self.por_carpeta[archivo.parent] = parsear(_leer(archivo))

    def __len__(self) -> int:
        return len(self.por_carpeta)

    def datos_para(self, path: str | Path) -> DatosCausa | None:
        """DatosCausa de la entrega a la que pertenece ese archivo.

        Se busca la carpeta con DatosCausa.txt más cercana hacia arriba: si los
        CDs están anidados, gana el más específico.
        """
        actual = Path(path)
        carpetas = [actual] if actual.is_dir() else []
        carpetas.extend(actual.parents)
        for carpeta in carpetas:
            datos = self.por_carpeta.get(carpeta)
            if datos is not None:
                return datos
        return None

    def cd_para(self, path: str | Path) -> str:
        """Número de CD declarado para ese archivo, o '' si no hay DatosCausa.

        Se prefiere el número corto ("1", "2"...) porque es el que el analista
        usa para hablar del material y el que entra en la columna CD; el
        identificador largo queda disponible en `datos_para().cd_id`.
        """
        datos = self.datos_para(path)
        if datos is None:
            return ""
        return datos.cd_numero or datos.cd_id or ""

    def declarados(self) -> set[str]:
        """Unión de los abonados declarados en todas las entregas."""
        numeros: set[str] = set()
        for datos in self.por_carpeta.values():
            numeros.update(datos.abonados_declarados)
        return numeros

    def principal(self) -> DatosCausa:
        """La entrega de menor número, para encabezar informes."""
        if not self.por_carpeta:
            return DatosCausa()

        def orden(d: DatosCausa) -> tuple[int, str]:
            try:
                return (int(d.cd_numero), d.cd_id)
            except (TypeError, ValueError):
                return (10**9, d.cd_id)

        return sorted(self.por_carpeta.values(), key=orden)[0]

    def resumen(self) -> list[DatosCausa]:
        """Las entregas ordenadas por número de CD, para mostrar al analista."""
        def orden(d: DatosCausa) -> tuple[int, str]:
            try:
                return (int(d.cd_numero), d.cd_id)
            except (TypeError, ValueError):
                return (10**9, d.cd_id)

        return sorted(self.por_carpeta.values(), key=orden)
