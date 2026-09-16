"""Genera las claves de habilitación. NO SE DISTRIBUYE.

Esta herramienta y el archivo `clave_privada.txt` que produce se quedan en la
máquina de quien administra las habilitaciones. Si la clave privada se filtra,
cualquiera puede emitir claves y el control se termina: guardarla como se
guarda una credencial.

Primera vez — generar el par
----------------------------
    py herramientas/firmar_licencia.py --generar-par

Escribe `clave_privada.txt` (se queda acá) e imprime la clave PÚBLICA, que hay
que pegar en `app/licencia.py`, en `CLAVE_PUBLICA_B64`. Recién ahí el programa
empieza a pedir habilitación.

Cada vez que alguien pide una habilitación
------------------------------------------
El analista manda la huella que le muestra el programa:

    py herramientas/firmar_licencia.py ABCDE-12345-FGHIJ-67890

Imprime la clave. Se la mandás y la pega una sola vez.

Conviene anotar a quién se le dio cada clave: el programa no lleva ese
registro, y es el dato que sirve el día que haya que saber quién tiene la
herramienta.
"""

from __future__ import annotations

import base64
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.licencia import (  # noqa: E402
    _B, _L, _comprimir, _multiplicar, verificar_firma,
)

RUTA_PRIVADA = Path(__file__).resolve().parent / "clave_privada.txt"


def _expandir(semilla: bytes) -> tuple[int, bytes]:
    h = hashlib.sha512(semilla).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def clave_publica(semilla: bytes) -> bytes:
    a, _ = _expandir(semilla)
    return _comprimir(_multiplicar(_B, a))


def firmar(mensaje: bytes, semilla: bytes) -> bytes:
    a, prefijo = _expandir(semilla)
    publica = _comprimir(_multiplicar(_B, a))
    r = int.from_bytes(
        hashlib.sha512(prefijo + mensaje).digest(), "little"
    ) % _L
    R = _comprimir(_multiplicar(_B, r))
    k = int.from_bytes(
        hashlib.sha512(R + publica + mensaje).digest(), "little"
    ) % _L
    s = (r + k * a) % _L
    return R + int.to_bytes(s, 32, "little")


def _generar_par() -> None:
    if RUTA_PRIVADA.exists():
        print(f"YA EXISTE {RUTA_PRIVADA}")
        print("Generar otro par invalida TODAS las claves ya entregadas.")
        print("Si es lo que querés, borralo a mano primero.")
        raise SystemExit(1)
    import secrets

    semilla = secrets.token_bytes(32)
    RUTA_PRIVADA.write_text(base64.b64encode(semilla).decode(), encoding="utf-8")
    publica = base64.b64encode(clave_publica(semilla)).decode()
    print(f"Clave privada guardada en: {RUTA_PRIVADA}")
    print("   NO la compartas y NO la subas a ningún repositorio.\n")
    print("Pegá esta clave PÚBLICA en app/licencia.py, en CLAVE_PUBLICA_B64:\n")
    print(f'CLAVE_PUBLICA_B64: str = "{publica}"\n')


def normalizar_huella(crudo: str) -> str:
    """Devuelve la huella en la forma EXACTA que firma el programa.

    La firma cubre el texto `XXXXX-XXXXX-XXXXX-XXXXX` tal cual, con guiones y
    en mayúsculas. Si el código llega de otra forma —pegado sin guiones desde
    un chat, en minúsculas, con un rótulo adelante— firmarlo así emite una
    clave perfectamente válida para un texto que no es la huella de nadie: no
    falla acá, falla en el equipo del analista, sin explicación.

    Por eso se reconstruye a partir de los 20 caracteres y no se acepta
    cualquier cosa: es preferible cortar acá con un aviso.
    """
    limpio = re.sub(r"[^0-9A-Za-z]", "", crudo or "").upper()
    if len(limpio) != 20:
        raise ValueError(
            f"El código tiene {len(limpio)} caracteres útiles y tienen que ser "
            f"20 (4 bloques de 5). Revisá que esté completo:\n  {crudo!r}"
        )
    return "-".join(limpio[i:i + 5] for i in range(0, 20, 5))


def _emitir(huella: str) -> None:
    if not RUTA_PRIVADA.exists():
        print("No hay clave privada. Primero: --generar-par")
        raise SystemExit(1)
    semilla = base64.b64decode(RUTA_PRIVADA.read_text(encoding="utf-8").strip())
    try:
        limpia = normalizar_huella(huella)
    except ValueError as exc:
        print(f"\n{exc}\n")
        raise SystemExit(1) from exc
    firma = firmar(limpia.encode("utf-8"), semilla)

    # Base32 y no base64: sin distinguir mayúsculas ni caracteres que se
    # confundan al dictarla por teléfono. En bloques de cinco para poder
    # leerla en voz alta sin perderse.
    texto = base64.b32encode(firma).decode().rstrip("=")
    clave = "-".join(texto[i:i + 5] for i in range(0, len(texto), 5))

    assert verificar_firma(limpia.encode("utf-8"), firma,
                           clave_publica(semilla)), "la firma no verifica"
    print(f"Huella:  {limpia}")
    print("Clave de habilitación:\n")
    print(clave)
    print("\nSirve SOLO en ese equipo. Anotá a quién se la entregaste.")


if __name__ == "__main__":
    # Sin argumentos se PREGUNTA, no se escupe la documentación entera. Se
    # corre de a una vez cada tanto, entre un mensaje del analista y la
    # respuesta: llenar la pantalla de texto en ese momento parece un error.
    if len(sys.argv) < 2:
        print("\n  Emisor de claves de habilitación\n")
        try:
            pedido = input("  Pegá el código del equipo: ").strip()
        except (EOFError, KeyboardInterrupt):
            raise SystemExit(0) from None
        if not pedido:
            print("\n  No pegaste nada.\n")
            raise SystemExit(1)
        _emitir(pedido)
    elif sys.argv[1] == "--generar-par":
        _generar_par()
    elif sys.argv[1] in ("-h", "--help", "/?"):
        print(__doc__)
    else:
        # Todo lo que venga suelto, por si el código se pegó con espacios y la
        # consola lo partió en varios argumentos.
        _emitir(" ".join(sys.argv[1:]))
