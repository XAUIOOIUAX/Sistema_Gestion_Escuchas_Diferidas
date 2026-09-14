"""Captura de errores no manejados y aviso al usuario.

Sin esto, cualquier excepción fuera de un try quedaba muda: el traceback iba a
stderr (que el analista no ve, y menos aún si la app corre empaquetada) y la
pantalla se quedaba a medio hacer sin explicar nada. Este módulo instala un
excepthook que deja constancia en un archivo y avisa en pantalla, sin cerrar la
aplicación: el trabajo en curso no debería perderse por un error de una
pantalla.
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path
from types import TracebackType

from PySide6.QtWidgets import QApplication, QMessageBox

from app import config

_NOMBRE_LOG = "errores.log"
_NOMBRE_LOG_VIEJO = "errores.1.log"
# Pasado esto el archivo se archiva y se empieza uno nuevo. No es por espacio
# —un traceback pesa nada— sino porque un log de veinte megas no lo abre nadie,
# y el que hay que leer es siempre el último.
_MAXIMO_BYTES = 1_000_000

# Un mismo fallo dentro de un repaint se repite en cada frame; sin esto el
# usuario recibiría una cascada de diálogos imposible de cerrar.
_ya_avisado: set[str] = set()


def ruta_log() -> Path:
    return config.DIR_DATOS / _NOMBRE_LOG


def contexto() -> str:
    """Dónde y con qué estaba trabajando el programa cuando se rompió.

    El traceback dice qué línea falló; esto dice sobre qué. Con el programa
    instalado en varias máquinas, «se rompió» y «se rompió en la causa X,
    registro #730, pantalla Desgrabar, versión 1.0» son la diferencia entre
    poder reproducirlo y no.

    Nunca lanza: es código que corre mientras algo ya salió mal, y tapar el
    error original con uno propio sería el peor resultado posible.
    """
    lineas = [f"Versión: {getattr(config, 'VERSION', '?')}"]
    try:
        from PySide6 import __version__ as version_pyside

        lineas.append(
            f"Python {sys.version.split()[0]} · PySide6 {version_pyside} · "
            f"{sys.platform}"
        )
    except Exception:      # noqa: BLE001 (nada puede voltear al manejador)
        pass
    try:
        from app import sesion

        analista = sesion.analista()
        if analista:
            lineas.append(f"Analista: {analista}")
        lugar = sesion.lugar()
        if lugar:
            partes = [
                f"{clave}={lugar[clave]}"
                for clave in ("pantalla", "caso_id", "registro_id", "segundo")
                if lugar.get(clave) is not None
            ]
            if partes:
                lineas.append("Dónde estaba: " + " · ".join(partes))
    except Exception:      # noqa: BLE001
        pass
    return "\n".join(lineas)


def _archivar_si_crecio(destino: Path) -> None:
    """Si el log pasó el tope, lo corre a `errores.1.log` y arranca uno nuevo."""
    try:
        if destino.exists() and destino.stat().st_size > _MAXIMO_BYTES:
            viejo = destino.with_name(_NOMBRE_LOG_VIEJO)
            viejo.unlink(missing_ok=True)
            destino.rename(viejo)
    except OSError:
        pass               # si no se puede rotar, se sigue escribiendo igual


def registrar(texto: str) -> Path | None:
    """Agrega una entrada al log de errores. Devuelve la ruta, o None si falló."""
    destino = ruta_log()
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        _archivar_si_crecio(destino)
        with destino.open("a", encoding="utf-8") as fh:
            fh.write(
                f"\n{'=' * 70}\n{datetime.now():%Y-%m-%d %H:%M:%S}\n"
                f"{contexto()}\n\n{texto}"
            )
        return destino
    except OSError:
        # Si ni siquiera se puede escribir el log, no hay que tapar el error
        # original con uno nuevo.
        return None


def _firma(exc_type: type[BaseException], tb: TracebackType | None) -> str:
    ultimo = traceback.extract_tb(tb)[-1] if tb else None
    if ultimo is None:
        return exc_type.__name__
    return f"{exc_type.__name__}:{ultimo.filename}:{ultimo.lineno}"


def manejar_excepcion(
    exc_type: type[BaseException],
    exc: BaseException,
    tb: TracebackType | None,
) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return

    detalle = "".join(traceback.format_exception(exc_type, exc, tb))
    destino = registrar(detalle)
    sys.__excepthook__(exc_type, exc, tb)

    firma = _firma(exc_type, tb)
    if firma in _ya_avisado:
        return
    _ya_avisado.add(firma)

    if QApplication.instance() is None:
        return
    caja = QMessageBox()
    caja.setIcon(QMessageBox.Warning)
    caja.setWindowTitle("Error inesperado")
    caja.setText(
        "Ocurrió un error inesperado y la operación no se completó.\n\n"
        "La aplicación sigue abierta: revisá que el último cambio se haya "
        "guardado antes de continuar."
    )
    pie = f"{exc_type.__name__}: {exc}"
    if destino is not None:
        pie += f"\n\nDetalle guardado en:\n{destino}"
    caja.setInformativeText(pie)
    caja.setDetailedText(f"{contexto()}\n\n{detalle}")

    # Mostrar la ruta como texto no alcanza: nadie va a ir a buscar el archivo
    # a mano. Con el botón, el analista lo tiene en pantalla y lo puede mandar.
    if destino is not None:
        boton = caja.addButton("Abrir la carpeta", QMessageBox.ActionRole)
        caja.addButton("Cerrar", QMessageBox.AcceptRole)
        caja.exec()
        if caja.clickedButton() is boton:
            try:
                from app.ui.dialogos import abrir_carpeta

                abrir_carpeta(destino)
            except Exception:      # noqa: BLE001 (ni esto puede voltearlo)
                pass
        return
    caja.exec()


def instalar() -> None:
    """Instala el excepthook global. Idempotente."""
    if sys.excepthook is not manejar_excepcion:
        sys.excepthook = manejar_excepcion
