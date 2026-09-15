"""Punto de entrada de la aplicación de escritorio.

Uso:
    python main.py
"""

from __future__ import annotations

import os
import sys

# El mapa usa QtWebEngine, cuyo compositor no logra crear contexto GL en equipos
# sin driver 3D utilizable (VM, escritorio remoto, gráficos integrados viejos):
# falla el smoke test de D3D11 y el visor queda completamente en blanco. Forzar
# el rasterizado por software lo hace funcionar en cualquier máquina. Debe
# quedar definido antes de importar QtWebEngine. Se puede sobrescribir desde el
# entorno si el equipo sí tiene GPU y se prefiere aceleración.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

from PySide6.QtWidgets import QApplication

from app import config, sesion
from app.db import crear_base
from app.ui import errores
from app.ui import tema
from app.ui.ventana_principal import VentanaPrincipal


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Escuchas Diferidas")
    # El tema elegido la última vez, antes de construir nada: así la primera
    # pantalla ya sale con la paleta correcta y no parpadea.
    tema.set_modo(sesion.preferencia("tema", tema.MODO_POR_DEFECTO))
    app.setStyleSheet(tema.QSS)
    errores.instalar()

    # Antes que nada: que el equipo esté habilitado. Va acá y no más adelante
    # para no abrir la base ni tocar datos de una causa en un equipo que no
    # debería tener el programa. Si no hay clave pública configurada —el modo
    # de desarrollo— esto no pregunta nada.
    from app.ui.dialogos import pedir_habilitacion

    if not pedir_habilitacion(None):
        return 0

    # Después: saber quién firma. Solo la primera vez en el equipo; después se
    # cambia desde la barra superior.
    if not sesion.hay_perfil_guardado():
        from app.ui.dialogos import pedir_analista
        pedir_analista(None, primera_vez=True)

    con = crear_base(config.RUTA_BASE_DATOS)

    ventana = VentanaPrincipal(con)
    ventana.showMaximized()
    try:
        return app.exec()
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
