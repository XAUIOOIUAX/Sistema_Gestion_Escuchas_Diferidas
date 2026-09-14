"""Importador de SMS (carpetas SMS/ del CD de intervención).

Los mensajes de texto vienen en archivos `SMS-fecha.txt` con formato pipe:

    Dirección|Origen|Destino|Fecha|Tecnología|Calle Celda|Número|Localidad|
    Provincia|Latitud|Longitud|Azimuth|Radio Cobertura|Contenido

Cada SMS se convierte en un RegistroParseado de tipo 'sms': sin audio, con el
contenido del mensaje en el campo transcripción y la misma información de celda
que una llamada (para que participe del mapa y del grafo).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.config import CONTEXTO_DEFAULT, VALOR_NO_IDENTIFICADO
from app.core.direccion import sanear_direccion
from app.core.fechas import parsear_fecha_hora_ar
from app.core.normalizers import normalizar_numero, titulo_case, valor_seguro
from app.core.interesado import componer_interesado
from app.core.interlocutor import componer_interlocutor, nombres_de_las_puntas
from app.importadores.txt_parser import leer_archivo_texto
from app.models import EstadoRegistro, RegistroParseado

# Orden de columnas del formato pipe de la prestadora.
_COLS = (
    "direccion", "origen", "destino", "fecha", "tecnologia", "calle",
    "numero", "localidad", "provincia", "latitud", "longitud", "azimuth",
    "radio", "contenido",
)


def _clave_dedup_sms(origen: str, destino: str, fecha: str, contenido: str) -> str:
    base = f"SMS|{origen}|{destino}|{fecha}|{contenido}".lower()
    return "SMS:" + hashlib.sha256(base.encode("utf-8")).hexdigest()[:28]


def _es_encabezado(linea: str) -> bool:
    l = linea.lower()
    return "origen" in l and "destino" in l and "contenido" in l


def parsear_sms(
    path_sms: str | Path,
    resolver_interesado=None,
    resolver_corresponde_a=None,
    abonado_intervenido: str = "",
) -> list[RegistroParseado]:
    """Lee un archivo SMS-*.txt y devuelve un RegistroParseado por mensaje."""
    contenido = leer_archivo_texto(path_sms)
    if not contenido:
        return []

    registros: list[RegistroParseado] = []
    for linea in contenido.splitlines():
        linea = linea.rstrip("\n")
        if "|" not in linea or _es_encabezado(linea):
            continue
        partes = linea.split("|")
        if len(partes) < len(_COLS):
            continue
        # Sin strict a propósito: el guard de arriba ya asegura que sobren
        # columnas, no que falten, y las de más se descartan.
        d = dict(zip(_COLS, partes))

        origen_crudo = d["origen"].strip()
        destino_crudo = d["destino"].strip()
        origen = normalizar_numero(origen_crudo)
        destino = normalizar_numero(destino_crudo)
        fecha_txt = d["fecha"].strip()
        contenido_sms = d["contenido"].strip()
        calle = d["calle"].strip()
        numero = d["numero"].strip()
        antena = f"{calle} {numero}".strip() if calle or numero else ""
        # Sale a variable porque Interlocutor la necesita: cuando no se sabe de
        # qué línea intervenida salió el archivo, la dirección es lo único que
        # dice cuál de las dos puntas es la de afuera.
        direccion = (
            sanear_direccion(d["direccion"]) or VALOR_NO_IDENTIFICADO
        ).upper()

        registros.append(
            RegistroParseado(
                estado=EstadoRegistro.COMPLETO,
                tipo="sms",
                direccion=direccion,
                origen=origen,
                destino=destino,
                origen_crudo=origen_crudo,
                destino_crudo=destino_crudo,
                fecha_inicio_texto=fecha_txt,
                fecha_fin_texto=fecha_txt,
                fecha_inicio_dt=parsear_fecha_hora_ar(fecha_txt),
                antenas=valor_seguro(antena),
                tecnologia=d["tecnologia"].strip(),
                calle=calle,
                numero_calle=numero,
                localidad=titulo_case(d["localidad"]),
                provincia=titulo_case(d["provincia"]),
                latitud=valor_seguro(d["latitud"].strip()),
                longitud=valor_seguro(d["longitud"].strip()),
                azimuth=valor_seguro(d["azimuth"].strip()),
                radio=valor_seguro(d["radio"].strip()),
                # Los mismos cruces que una llamada: sin esto la columna
                # Interesado quedaba VACÍA solo en los SMS, mientras las
                # llamadas decían NO IDENTIFICADO. Dos huecos distintos para
                # la misma ausencia.
                interesado=componer_interesado(
                    resolver_interesado(origen) if (resolver_interesado and origen) else "",
                    resolver_interesado(destino) if (resolver_interesado and destino) else "",
                    abonado_intervenido,
                    resolver_interesado(abonado_intervenido)
                    if (resolver_interesado and abonado_intervenido) else "",
                ),
                interlocutor=componer_interlocutor(
                    origen, destino, abonado_intervenido, direccion,
                    nombres_de_las_puntas(
                        origen, destino, resolver_interesado, resolver_corresponde_a
                    ),
                ),
                corresponde_a=(
                    (resolver_corresponde_a(origen) or resolver_corresponde_a(destino))
                    if resolver_corresponde_a else ""
                ) or VALOR_NO_IDENTIFICADO,
                contexto=CONTEXTO_DEFAULT,
                transcripcion=contenido_sms,
                archivo_audio="",
                archivo_txt=Path(path_sms).name,
                clave_dedup=_clave_dedup_sms(origen, destino, fecha_txt, contenido_sms),
            )
        )
    return registros


def buscar_archivos_sms(ruta_raiz: str | Path) -> list[Path]:
    """Devuelve todos los archivos SMS-*.txt bajo la carpeta (en subcarpetas SMS/)."""
    encontrados: list[Path] = []
    for p in Path(ruta_raiz).rglob("*.txt"):
        if p.name.lower().startswith("sms"):
            encontrados.append(p)
    return encontrados
