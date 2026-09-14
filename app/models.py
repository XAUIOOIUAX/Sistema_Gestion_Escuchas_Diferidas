"""Estructuras de dominio (dataclasses) compartidas entre capas.

No son ORM: son objetos de transferencia ligeros entre el parser, el importador
y la capa de datos / UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class EstadoRegistro(str, Enum):
    """Estado de emparejamiento TXT/audio de un registro (BUG-06)."""

    COMPLETO = "completo"
    AUDIO_FALTANTE = "audio_faltante"
    TRANSCRIPCION_FALTANTE = "transcripcion_faltante"


@dataclass
class RegistroParseado:
    """Datos de un registro extraídos de un TXT (o de un audio huérfano).

    Espejo de los campos de la tabla Registro relevantes en importación.
    `fecha_inicio_texto` se conserva EXACTO; `fecha_inicio_dt` es derivado.
    """

    estado: EstadoRegistro
    tipo: str = "llamada"  # 'llamada' | 'sms'
    cd: str = ""
    direccion: str = ""
    origen: str = ""
    destino: str = ""
    origen_crudo: str = ""
    destino_crudo: str = ""
    interesado: str = ""
    interlocutor: str = ""
    corresponde_a: str = ""
    fecha_inicio_texto: str = ""
    fecha_fin_texto: str = ""
    fecha_inicio_dt: datetime | None = None
    antenas: str = ""
    tecnologia: str = ""
    calle: str = ""
    numero_calle: str = ""
    localidad: str = ""
    provincia: str = ""
    latitud: str = ""
    longitud: str = ""
    azimuth: str = ""
    radio: str = ""
    contexto: str = ""
    transcripcion: str = ""
    archivo_audio: str = ""
    archivo_txt: str | None = None
    clave_dedup: str = ""


@dataclass
class ItemPreview:
    """Un archivo (o par) detectado durante el escaneo previo a importar."""

    estado: EstadoRegistro
    nombre_base: str
    path_txt: str | None = None
    path_audio: str | None = None
    clave_dedup: str = ""
    # Resumen mínimo para mostrar en la UI antes de confirmar.
    origen: str = ""
    destino: str = ""
    fecha_inicio_texto: str = ""
    motivo_error: str = ""
    # Abonado intervenido deducido de la carpeta (la línea pinchada).
    abonado_intervenido: str = ""


@dataclass
class ResumenPreview:
    """Resultado del escaneo previo: clasificación de lo encontrado."""

    nuevos: list[ItemPreview] = field(default_factory=list)
    existentes: list[ItemPreview] = field(default_factory=list)
    con_error: list[ItemPreview] = field(default_factory=list)
    sms: int = 0  # cantidad de mensajes SMS detectados en carpetas SMS/

    @property
    def conteo_audio_faltante(self) -> int:
        return sum(
            1 for i in self.nuevos if i.estado is EstadoRegistro.AUDIO_FALTANTE
        )

    @property
    def conteo_txt_faltante(self) -> int:
        return sum(
            1
            for i in self.nuevos
            if i.estado is EstadoRegistro.TRANSCRIPCION_FALTANTE
        )

    @property
    def conteo_completos(self) -> int:
        return sum(1 for i in self.nuevos if i.estado is EstadoRegistro.COMPLETO)

    def resumen_texto(self) -> str:
        """Línea de resumen para la UI, p.ej. la del pseudocódigo 3.1."""
        sms_txt = f" / {self.sms} SMS" if self.sms else ""
        return (
            f"{len(self.nuevos)} nuevos "
            f"({self.conteo_audio_faltante} sin audio, "
            f"{self.conteo_txt_faltante} sin transcripción) / "
            f"{len(self.existentes)} existentes / "
            f"{len(self.con_error)} con error"
            f"{sms_txt}"
        )
