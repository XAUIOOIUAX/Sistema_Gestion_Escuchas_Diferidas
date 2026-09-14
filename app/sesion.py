"""Identidad del analista que opera la sesión.

Todo lo que la aplicación anota para dejar rastro —el log de auditoría, el
historial de cambios de cada registro, los lotes de exportación y la
resolución de avisos— tiene una columna `usuario`. Hasta ahora esa columna
quedaba siempre vacía: las firmas la traían con default `""` y ningún llamador
la completaba, así que el expediente registraba *qué* se hizo pero nunca
*quién* lo hizo.

Este módulo guarda ese nombre una sola vez y lo resuelve en el momento de
escribir. Las funciones que anotan reciben ahora `usuario: str | None = None`
y llaman a `sesion.o_analista(usuario)`: pasar un nombre explícito lo respeta
(las pruebas lo usan), y no pasar nada toma el de la sesión. Así un llamador
nuevo no puede olvidarse de firmar.

El nombre se persiste en `datos/perfil.json` (no en QSettings) para que el
módulo no dependa de Qt y pueda usarse desde los servicios y las pruebas.
"""

from __future__ import annotations

import getpass
import json
from pathlib import Path

from app import config

RUTA_PERFIL: Path = config.DIR_DATOS / "perfil.json"

# None = todavía no se leyó del disco en esta ejecución.
_analista: str | None = None


def _del_sistema() -> str:
    """Nombre de la cuenta del sistema operativo, como sugerencia inicial."""
    try:
        return (getpass.getuser() or "").strip()
    except (OSError, KeyError):  # sin variables de entorno de usuario
        return ""


def _cargar() -> dict:
    """Contenido de perfil.json, o {} si no existe o está roto."""
    try:
        datos = json.loads(RUTA_PERFIL.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


def _guardar(cambios: dict) -> None:
    """Mezcla `cambios` en perfil.json sin pisar lo que ya había.

    Perder la persistencia no puede voltear la aplicación: si el disco no deja
    escribir, la sesión en curso sigue con lo que tiene en memoria.
    """
    datos = _cargar()
    datos.update(cambios)
    try:
        RUTA_PERFIL.parent.mkdir(parents=True, exist_ok=True)
        RUTA_PERFIL.write_text(
            json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def _leer_perfil() -> str:
    nombre = _cargar().get("analista")
    return nombre.strip() if isinstance(nombre, str) else ""


def preferencia(clave: str, defecto: str = "") -> str:
    """Preferencia guardada en el equipo (el tema visual, por ejemplo).

    Vive en el mismo perfil.json que el nombre del analista: son las dos cosas
    que se eligen una vez por puesto de trabajo y se esperan igual al día
    siguiente.
    """
    valor = _cargar().get(clave)
    return valor if isinstance(valor, str) and valor else defecto


def set_preferencia(clave: str, valor: str) -> None:
    _guardar({clave: valor})


# --------------------------- dónde quedé --------------------------------
#
# Preferencia y lugar son dos cosas distintas y conviene no mezclarlas: una
# preferencia se elige (el tema, la salida de audio) y un lugar se acumula solo
# (la causa abierta, la comunicación que se estaba corrigiendo, el segundo del
# audio). Las dos viven en el mismo perfil.json, pero se leen y se escriben por
# separado para que borrar el rastro de trabajo no borre lo que se configuró.
_CLAVE_LUGAR = "ultimo_lugar"


def lugar() -> dict:
    """Dónde estaba trabajando la última vez que se cerró el programa."""
    guardado = _cargar().get(_CLAVE_LUGAR)
    return dict(guardado) if isinstance(guardado, dict) else {}


def recordar_lugar(**campos) -> None:
    """Anota parte del lugar sin pisar lo demás.

    Se llama seguido —al cambiar de pantalla, al cerrar— así que cada llamador
    manda solo lo suyo: la ventana no tiene por qué saber en qué segundo del
    audio iba la pantalla Corregir.
    """
    actual = lugar()
    actual.update({k: v for k, v in campos.items() if v is not None})
    _guardar({_CLAVE_LUGAR: actual})


def olvidar_lugar() -> None:
    """Borra el rastro de trabajo, dejando intactas las preferencias."""
    _guardar({_CLAVE_LUGAR: {}})


def analista() -> str:
    """Nombre con el que se firman las anotaciones de esta sesión.

    Si nadie lo definió todavía, cae en la cuenta del sistema operativo: es
    menos preciso que el nombre real del analista, pero deja rastro igual.
    """
    global _analista
    if _analista is None:
        _analista = _leer_perfil() or _del_sistema()
    return _analista


def hay_perfil_guardado() -> bool:
    """True si el analista ya se identificó alguna vez en este equipo."""
    return bool(_leer_perfil())


def set_analista(nombre: str, *, persistir: bool = True) -> str:
    """Define el analista de la sesión y (por defecto) lo recuerda en disco."""
    global _analista
    _analista = (nombre or "").strip()
    if persistir:
        _guardar({"analista": _analista})
    return _analista


def o_analista(usuario: str | None) -> str:
    """Resuelve el firmante: el explícito si lo hay, si no el de la sesión."""
    return analista() if usuario is None else usuario


def olvidar() -> None:
    """Descarta el nombre cacheado (para pruebas)."""
    global _analista
    _analista = None
