"""Importador de transcripciones TXT + audio.

Implementa la sección 3.1 del pseudocódigo:
  - escanear_carpeta_preview(): escaneo recursivo SIN escribir en la base,
    empareja TXT con audio por nombre base y clasifica cada par en uno de tres
    estados (completo / audio_faltante / transcripcion_faltante, BUG-06).
  - extraer_registro_de_txt(): mapea el diccionario parseado a RegistroParseado.

La escritura efectiva en la base la realiza la capa de servicio (importar_caso),
que consume el ResumenPreview confirmado.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from app.core.archivos import (
    cumple_patron_audio,
    es_extension_audio,
    extension_de,
    nombre_base_archivo,
)
from app.core.cd_extractor import extraer_cd_de_path
from app.core.direccion import inferir_direccion_por_interesado, sanear_direccion
from app.core.interesado import componer_interesado
from app.core.interlocutor import (
    SIN_INTERLOCUTOR,
    componer_interlocutor,
    nombres_de_las_puntas,
)
from app.core.fechas import parsear_fecha_hora_ar
from app.core.normalizers import (
    generar_clave_dedup,
    normalizar_numero,
    titulo_case,
    valor_seguro,
)
from app.config import CD_NO_DETECTADO, CONTEXTO_DEFAULT, VALOR_NO_IDENTIFICADO
from app.importadores.txt_parser import (
    get_val,
    get_val_multi,
    parsear_txt_a_diccionario,
)
from app.models import EstadoRegistro, ItemPreview, RegistroParseado, ResumenPreview

# Claves alternativas para la dirección de la comunicación en el TXT.
_CLAVES_DIRECCION = (
    "direccion",
    "direccion de llamada",
    "sentido",
    "tipo",
    "tipo de llamada",
    "tipo de comunicacion",
)


def _clave_dedup_audio_huerfano(path_audio: str) -> str:
    """Clave de dedup provisional para un audio sin TXT (no hay origen/destino/fecha)."""
    base = nombre_base_archivo(Path(path_audio).name)
    return "AUDIO:" + hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]


# Nombres de carpeta que NO son un abonado (estructura típica del CD).
_CARPETAS_NO_ABONADO = frozenset(
    {"audio", "audios", "sms", "mensajes", "datos", "transcripciones",
     "transcripcion", "txt", "wav", "grabaciones"}
)


def detectar_abonado_intervenido(path: str | Path) -> str:
    """Deduce el abonado intervenido (la línea pinchada) desde la RUTA.

    En un CD de intervención cada línea intervenida tiene su propia carpeta,
    nombrada con su número (p.ej. `CD700000012/3875 550016/Audio/B-...txt`).
    Se sube por las carpetas padre y se devuelve el primer nombre que, tras
    normalizar, sea un número de abonado válido (>= 6 dígitos). '' si no hay.
    """
    p = Path(path)
    partes = list(p.parts[:-1])  # excluye el nombre del archivo
    for nombre in reversed(partes):
        limpio = nombre.strip().lower()
        if not limpio or limpio in _CARPETAS_NO_ABONADO:
            continue
        if limpio.startswith("cd"):  # carpeta raíz del CD, no un abonado
            continue
        solo_digitos = "".join(ch for ch in nombre if ch.isdigit())
        if len(solo_digitos) >= 6:
            # Solo los dígitos: la carpeta suele traer también el titular
            # ("3875 550016 - LEDESMA M") y normalizar el nombre entero
            # devolvía "3875550016LEDESMAM", que no coincide con ningún
            # abonado y dejaba la línea sin marcar como intervenida.
            return normalizar_numero(solo_digitos)
    return ""


def construir_antena(calle: str, numero: str) -> str:
    """Combina calle y número en una sola cadena de antena."""
    calle, numero = (calle or "").strip(), (numero or "").strip()
    if calle and numero:
        return f"{calle} {numero}"
    return calle or ""


def extraer_registro_de_txt(
    path_txt: str | Path,
    dataMap: dict[str, str],
    estado: EstadoRegistro,
    *,
    resolver_interesado=None,
    resolver_corresponde_a=None,
    resolver_cd=None,
    abonado_intervenido: str = "",
    nombre_audio: str | None = None,
) -> RegistroParseado:
    """Mapea un diccionario parseado de TXT a un RegistroParseado.

    `resolver_interesado(numero_normalizado) -> str` y
    `resolver_corresponde_a(numero_normalizado) -> str` son callbacks opcionales
    (inyectados por la capa de datos) para cruzar contra el índice del caso y la
    memoria de "corresponde a". Si no se pasan, esos campos quedan por defecto.

    `resolver_cd(path) -> str` permite que el CD lo diga el DatosCausa.txt de la
    entrega en lugar de adivinarlo desde la ruta. Sin él se cae en la heurística
    de siempre, que sirve cuando las carpetas se llaman "N. CDxxxxx".
    """
    origen_crudo = get_val(dataMap, "origen")
    destino_crudo = get_val(dataMap, "destino")
    origen = normalizar_numero(origen_crudo)
    destino = normalizar_numero(destino_crudo)

    direccion = sanear_direccion(get_val_multi(dataMap, *_CLAVES_DIRECCION))

    i_ori = resolver_interesado(origen) if (resolver_interesado and origen) else ""
    i_des = resolver_interesado(destino) if (resolver_interesado and destino) else ""
    interesado = componer_interesado(
        i_ori, i_des, abonado_intervenido,
        resolver_interesado(abonado_intervenido)
        if (resolver_interesado and abonado_intervenido) else '',
    )

    if direccion in ("", VALOR_NO_IDENTIFICADO):
        direccion = inferir_direccion_por_interesado(i_ori, i_des)

    corresponde_a = VALOR_NO_IDENTIFICADO
    if resolver_corresponde_a:
        corresponde_a = (
            resolver_corresponde_a(origen)
            or resolver_corresponde_a(destino)
            or VALOR_NO_IDENTIFICADO
        )

    # Con quien hablo la linea intervenida. El nombre sale del Indice y, si
    # ahi no esta, de la memoria compartida entre causas; sin nombre queda el
    # numero, que es con lo que el analista trabaja igual.
    interlocutor = componer_interlocutor(
        origen, destino, abonado_intervenido, direccion,
        nombres_de_las_puntas(
            origen, destino, resolver_interesado, resolver_corresponde_a
        ),
    )

    fecha_inicio_texto = get_val(dataMap, "inicio")
    fecha_fin_texto = get_val(dataMap, "fin")
    antena = construir_antena(get_val(dataMap, "calle"), get_val(dataMap, "numero"))

    if estado is EstadoRegistro.COMPLETO:
        archivo_audio = nombre_audio or ""
    else:  # audio_faltante
        archivo_audio = f"{nombre_base_archivo(Path(path_txt).name)} (no encontrado)"

    return RegistroParseado(
        estado=estado,
        cd=_resolver_cd(path_txt, resolver_cd),
        direccion=direccion.upper() if direccion else VALOR_NO_IDENTIFICADO,
        origen=origen,
        destino=destino,
        origen_crudo=origen_crudo,
        destino_crudo=destino_crudo,
        interesado=interesado,
        interlocutor=interlocutor,
        corresponde_a=corresponde_a,
        fecha_inicio_texto=fecha_inicio_texto,
        fecha_fin_texto=fecha_fin_texto,
        fecha_inicio_dt=parsear_fecha_hora_ar(fecha_inicio_texto),
        antenas=valor_seguro(antena),
        tecnologia=get_val(dataMap, "tecnologia"),
        calle=get_val(dataMap, "calle"),
        numero_calle=get_val(dataMap, "numero"),
        localidad=titulo_case(get_val(dataMap, "localidad")),
        provincia=titulo_case(get_val(dataMap, "provincia")),
        latitud=valor_seguro(get_val(dataMap, "latitud")),
        longitud=valor_seguro(get_val(dataMap, "longitud")),
        azimuth=valor_seguro(get_val(dataMap, "azimuth")),
        radio=valor_seguro(get_val_multi(dataMap, "radio cobertura", "radio")),
        contexto=CONTEXTO_DEFAULT,
        archivo_audio=archivo_audio,
        archivo_txt=Path(path_txt).name,
        clave_dedup=generar_clave_dedup(origen, destino, fecha_inicio_texto),
    )


def _resolver_cd(path, resolver_cd) -> str:
    """CD declarado en el DatosCausa.txt de la entrega; si no hay, el de la ruta."""
    if resolver_cd is not None:
        declarado = resolver_cd(path)
        if declarado:
            return declarado
    return extraer_cd_de_path(str(path))


def registro_audio_huerfano(
    path_audio: str | Path, resolver_cd=None, abonado_intervenido: str = "",
    nombre_intervenido: str = "",
) -> RegistroParseado:
    """Construye el registro mínimo para un audio sin transcripción (huérfano)."""
    nombre = Path(path_audio).name
    return RegistroParseado(
        estado=EstadoRegistro.TRANSCRIPCION_FALTANTE,
        cd=_resolver_cd(path_audio, resolver_cd) or CD_NO_DETECTADO,
        direccion=VALOR_NO_IDENTIFICADO,
        origen=VALOR_NO_IDENTIFICADO,
        destino=VALOR_NO_IDENTIFICADO,
        interesado=componer_interesado(
            "", "", abonado_intervenido, nombre_intervenido
        ),
        # Un audio huerfano no trae origen ni destino: no hay otra punta que
        # nombrar, solo la linea de la que salio el archivo.
        interlocutor=SIN_INTERLOCUTOR,
        corresponde_a=VALOR_NO_IDENTIFICADO,
        fecha_inicio_texto="",
        fecha_fin_texto="",
        fecha_inicio_dt=None,
        antenas=VALOR_NO_IDENTIFICADO,
        localidad=VALOR_NO_IDENTIFICADO,
        provincia=VALOR_NO_IDENTIFICADO,
        latitud=VALOR_NO_IDENTIFICADO,
        longitud=VALOR_NO_IDENTIFICADO,
        azimuth=VALOR_NO_IDENTIFICADO,
        radio=VALOR_NO_IDENTIFICADO,
        contexto="",
        archivo_audio=nombre,
        archivo_txt=None,
        clave_dedup=_clave_dedup_audio_huerfano(str(path_audio)),
    )


def _clasificar_carpeta(
    archivos: list[os.DirEntry],
) -> tuple[dict[str, str], dict[str, str]]:
    """Clasifica los archivos de una carpeta en dict_txt y dict_audio por nombre base.

    Devuelve (dict_txt, dict_audio): nombre_base_lower -> path_completo.
    """
    dict_txt: dict[str, str] = {}
    dict_audio: dict[str, str] = {}
    for entrada in archivos:
        nombre = entrada.name
        ext = extension_de(nombre)
        base = nombre_base_archivo(nombre)
        if not cumple_patron_audio(base):
            continue
        clave = base.lower()
        if ext == "txt":
            dict_txt.setdefault(clave, entrada.path)
        elif es_extension_audio(ext):
            dict_audio.setdefault(clave, entrada.path)
    return dict_txt, dict_audio


def escanear_carpeta_preview(
    ruta_raiz: str | Path,
    claves_existentes: set[str] | None = None,
) -> ResumenPreview:
    """Escanea recursivamente y empareja TXT/audio SIN escribir en la base.

    `claves_existentes` es el conjunto de clave_dedup ya presentes en el caso;
    los ítems cuya clave ya existe se clasifican como 'existentes' (se inyecta
    desde la capa de datos para mantener esta función testeable sin DB).
    """
    claves_existentes = claves_existentes or set()
    resumen = ResumenPreview()

    for dir_actual, _subdirs, _archivos in os.walk(str(ruta_raiz)):
        with os.scandir(dir_actual) as it:
            archivos = [e for e in it if e.is_file()]
        dict_txt, dict_audio = _clasificar_carpeta(archivos)

        for base in dict_txt.keys() | dict_audio.keys():
            tiene_txt = base in dict_txt
            tiene_audio = base in dict_audio
            try:
                item = _preview_item(
                    base,
                    dict_txt.get(base),
                    dict_audio.get(base),
                    tiene_txt,
                    tiene_audio,
                )
            except Exception as exc:  # pragma: no cover - defensa ante TXT corruptos
                resumen.con_error.append(
                    ItemPreview(
                        estado=EstadoRegistro.COMPLETO,
                        nombre_base=base,
                        path_txt=dict_txt.get(base),
                        path_audio=dict_audio.get(base),
                        motivo_error=str(exc),
                    )
                )
                continue

            if item is None:
                continue
            if item.clave_dedup and item.clave_dedup in claves_existentes:
                resumen.existentes.append(item)
            else:
                resumen.nuevos.append(item)

    return resumen


def _preview_item(
    base: str,
    path_txt: str | None,
    path_audio: str | None,
    tiene_txt: bool,
    tiene_audio: bool,
) -> ItemPreview | None:
    """Construye el ItemPreview para un nombre base según qué archivos tiene."""
    if tiene_txt and tiene_audio:
        d = parsear_txt_a_diccionario(path_txt)  # type: ignore[arg-type]
        if not d:
            raise ValueError("TXT vacío o sin pares clave:valor")
        item = _item_desde_dict(
            base, EstadoRegistro.COMPLETO, d, path_txt, path_audio
        )
        item.abonado_intervenido = detectar_abonado_intervenido(path_txt)
        return item
    if tiene_txt and not tiene_audio:
        d = parsear_txt_a_diccionario(path_txt)  # type: ignore[arg-type]
        if not d:
            raise ValueError("TXT vacío o sin pares clave:valor")
        item = _item_desde_dict(
            base, EstadoRegistro.AUDIO_FALTANTE, d, path_txt, None
        )
        item.abonado_intervenido = detectar_abonado_intervenido(path_txt)
        return item
    if tiene_audio and not tiene_txt:
        return ItemPreview(
            estado=EstadoRegistro.TRANSCRIPCION_FALTANTE,
            nombre_base=base,
            path_audio=path_audio,
            clave_dedup=_clave_dedup_audio_huerfano(path_audio),  # type: ignore[arg-type]
            abonado_intervenido=detectar_abonado_intervenido(path_audio),  # type: ignore[arg-type]
        )
    return None


def _item_desde_dict(
    base: str,
    estado: EstadoRegistro,
    d: dict[str, str],
    path_txt: str | None,
    path_audio: str | None,
) -> ItemPreview:
    origen = normalizar_numero(get_val(d, "origen"))
    destino = normalizar_numero(get_val(d, "destino"))
    fecha = get_val(d, "inicio")
    return ItemPreview(
        estado=estado,
        nombre_base=base,
        path_txt=path_txt,
        path_audio=path_audio,
        clave_dedup=generar_clave_dedup(origen, destino, fecha),
        origen=origen,
        destino=destino,
        fecha_inicio_texto=fecha,
    )
