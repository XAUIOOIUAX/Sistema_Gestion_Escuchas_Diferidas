"""Habilitación del programa en un equipo, con una clave permanente.

El programa se distribuye en un instalador y no debería quedar circulando sin
control: se habilita equipo por equipo, con una clave que emite quien lo
administra.

Cómo funciona
-------------
1. El programa calcula una **huella** del equipo y la muestra.
2. El analista la manda a quien administra.
3. Esa persona genera la clave con `herramientas/firmar_licencia.py`, que usa
   una **clave privada que nunca sale de su máquina**.
4. El analista la pega una vez y el equipo queda habilitado para siempre.

Por qué firma asimétrica y no una clave secreta compartida
----------------------------------------------------------
Una «clave maestra» guardada adentro del programa la puede extraer cualquiera
que lo descompile, y con eso genera claves para todos los equipos. Con firma
asimétrica el programa sólo lleva la clave PÚBLICA: sirve para verificar, no
para firmar. Sin la privada no se puede fabricar una clave válida ni teniendo
el código fuente entero.

Qué protege y qué no
--------------------
Esto evita que la herramienta circule por descuido —copiar la carpeta a otra
máquina no alcanza— y deja constancia de a quién se habilitó. **No** frena a
alguien con conocimientos que decida quitar la verificación del ejecutable: una
aplicación de escritorio se puede modificar, y prometer lo contrario sería
mentir. La protección de fondo es administrativa; esto es la barrera técnica.

Ed25519 en Python puro
----------------------
Sin dependencias a propósito. Agregar `cryptography` o `PyNaCl` significa una
librería con extensiones compiladas más en el empaquetado, y eso es justo lo
que hizo fallar al motor de transcripción. Verificar una firma una vez por
arranque tarda milisegundos: no hace falta nada rápido.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import subprocess
from pathlib import Path

from app import config

# --------------------------------------------------------------------------
# Ed25519 — verificación (RFC 8032). Implementación de referencia.
# --------------------------------------------------------------------------
_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _recuperar_x(y: int, signo: int) -> int | None:
    if y >= _P:
        return None
    xx = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P)
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = x * _I % _P
    if (x * x - xx) % _P != 0:
        return None
    if x % 2 != signo:
        x = _P - x
    return x


def _sumar(p, q):
    x1, y1, z1, t1 = p
    x2, y2, z2, t2 = q
    a = (y1 - x1) * (y2 - x2) % _P
    b = (y1 + x1) * (y2 + x2) % _P
    c = t1 * 2 * _D * t2 % _P
    dd = z1 * 2 * z2 % _P
    e, f, g, h = b - a, dd - c, dd + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _multiplicar(p, e):
    if e == 0:
        return (0, 1, 1, 0)
    q = _multiplicar(p, e // 2)
    q = _sumar(q, q)
    return _sumar(q, p) if e & 1 else q


_BY = 4 * pow(5, _P - 2, _P) % _P
_BX = _recuperar_x(_BY, 0)
_B = (_BX, _BY, 1, _BX * _BY % _P)


def _comprimir(p) -> bytes:
    x, y, z, _t = p
    zi = pow(z, _P - 2, _P)
    x, y = x * zi % _P, y * zi % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _descomprimir(s: bytes):
    y = int.from_bytes(s, "little") & ((1 << 255) - 1)
    x = _recuperar_x(y, int.from_bytes(s, "little") >> 255)
    return None if x is None else (x, y, 1, x * y % _P)


def verificar_firma(mensaje: bytes, firma: bytes, publica: bytes) -> bool:
    """True si `firma` es una firma Ed25519 válida de `mensaje`."""
    if len(firma) != 64 or len(publica) != 32:
        return False
    a = _descomprimir(publica)
    if a is None:
        return False
    r = _descomprimir(firma[:32])
    if r is None:
        return False
    s = int.from_bytes(firma[32:], "little")
    if s >= _L:
        return False
    h = int.from_bytes(
        hashlib.sha512(firma[:32] + publica + mensaje).digest(), "little"
    ) % _L
    izq = _multiplicar(_B, s)
    der = _sumar(r, _multiplicar(a, h))
    return _comprimir(izq) == _comprimir(der)


# --------------------------------------------------------------------------
# La huella del equipo
# --------------------------------------------------------------------------
#
# No se usa la MAC. Una notebook tiene varias —WiFi, Ethernet, adaptadores de
# VPN—, una base de conexión agrega otra, y Windows ofrece «direcciones de
# hardware aleatorias» para WiFi: una licencia atada a «la MAC» se rompe sola
# el día que el analista enchufa la máquina a la base.
#
# `MachineGuid` lo escribe Windows al instalarse y no cambia hasta que se
# reinstala el sistema. El serial del volumen lo acompaña.

def _valor_del_registro() -> str:
    try:
        import winreg  # noqa: PLC0415 — sólo existe en Windows

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as k:
            return str(winreg.QueryValueEx(k, "MachineGuid")[0])
    except Exception:      # noqa: BLE001 — cualquier falla cae al respaldo
        return ""


def _serial_del_volumen() -> str:
    try:
        salida = subprocess.run(
            ["cmd", "/c", "vol", "C:"], capture_output=True, text=True,
            timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        hallado = re.search(r"([0-9A-F]{4}-[0-9A-F]{4})", salida or "", re.I)
        return hallado.group(1) if hallado else ""
    except Exception:      # noqa: BLE001
        return ""


def huella_del_equipo() -> str:
    """Identificador estable del equipo, en bloques legibles por teléfono.

    Se compone de varias fuentes: si una falla —un equipo sin el registro
    esperado, un disco sin serial— las otras alcanzan. Si fallaran todas queda
    el nombre del equipo, que es débil pero es mejor que no arrancar.
    """
    partes = [
        _valor_del_registro(),
        _serial_del_volumen(),
        os.environ.get("COMPUTERNAME", "") or os.environ.get("HOSTNAME", ""),
    ]
    crudo = "|".join(p for p in partes if p) or "sin-identificar"
    digest = hashlib.sha256(crudo.encode("utf-8")).hexdigest().upper()
    corta = digest[:20]
    return "-".join(corta[i:i + 5] for i in range(0, 20, 5))


# --------------------------------------------------------------------------
# La clave
# --------------------------------------------------------------------------

#: Clave pública de quien administra las habilitaciones. Se reemplaza por la
#: que imprime `herramientas/firmar_licencia.py --generar-par`.
#: Vacía = el programa NO pide clave (modo desarrollo y equipos ya en uso).
CLAVE_PUBLICA_B64: str = "kWClYaafp/sOh2rzhKW/B5YrOBto9hcqByaWVa7o8pY="

_NOMBRE_ARCHIVO = "licencia.clave"


def ruta_licencia() -> Path:
    """Junto a la base de la causa: lo del equipo va con los datos del equipo."""
    return config.DIR_DATOS / _NOMBRE_ARCHIVO


def _limpiar(clave: str) -> str:
    r"""Saca guiones, espacios y saltos: la clave se pega de un correo.

    Saca también el BOM y los caracteres de ancho cero. No es un capricho:
    `licencia.clave` se puede pre-cargar por script para habilitar varios
    equipos de una vez, y `Set-Content -Encoding utf8` de PowerShell 5.1
    escribe un BOM al principio. El BOM no es \s, así que sobrevivía a
    esta limpieza y rompía el base32: la clave CORRECTA se rechazaba con
    «esa clave no habilita este equipo», que manda a buscar el problema
    al lado de donde está. Los de ancho cero vienen del mismo lado:
    copiar la clave de una página en vez de un texto plano.
    """
    return re.sub(r"[\s\-\ufeff\u200b\u200c\u200d\u2060]", "", clave or "")


def clave_valida(clave: str, huella: str | None = None) -> bool:
    """Si la clave habilita a ESTE equipo.

    La firma cubre la huella, así que una clave emitida para otra máquina no
    verifica acá: copiar la carpeta entera no alcanza para llevarse el
    programa habilitado.
    """
    if not CLAVE_PUBLICA_B64:
        return True                      # sin clave pública configurada
    limpia = _limpiar(clave)
    if not limpia:
        return False
    try:
        # El relleno se le quita a la clave al emitirla —un '=' colgando al
        # final invita a que alguien lo borre al copiarla— así que hay que
        # reponerlo acá o base32 rechaza la clave correcta.
        relleno = "=" * ((-len(limpia)) % 8)
        firma = base64.b32decode(limpia + relleno, casefold=True)
        publica = base64.b64decode(CLAVE_PUBLICA_B64)
    except Exception:      # noqa: BLE001 — una clave mal pegada no es un error
        return False
    mensaje = (huella or huella_del_equipo()).encode("utf-8")
    return verificar_firma(mensaje, firma, publica)


def esta_habilitado() -> bool:
    """Si este equipo ya tiene una clave válida guardada."""
    if not CLAVE_PUBLICA_B64:
        return True
    try:
        guardada = ruta_licencia().read_text(encoding="utf-8")
    except OSError:
        return False
    return clave_valida(guardada)


def guardar_clave(clave: str) -> bool:
    """Guarda la clave si es válida. Devuelve si quedó habilitado."""
    if not clave_valida(clave):
        return False
    destino = ruta_licencia()
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(_limpiar(clave), encoding="utf-8")
    except OSError:
        return False
    return True
