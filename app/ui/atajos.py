"""Atajos de teclado: definición única y ayuda visible.

El bucle real del trabajo es escuchar, juzgar, marcar y pasar al siguiente,
miles de veces. Hacerlo con el mouse cuesta tres clics por registro; con el
teclado, una tecla. Por eso la grilla acepta teclas sin modificador (espacio,
1/2/3, E) mientras tiene el foco: no compiten con la escritura porque los
campos de texto viven en el panel de detalle y en el buscador, que son otros
widgets.

Los atajos con modificador (Ctrl+…) siguen funcionando desde cualquier parte
de la pantalla, incluso escribiendo.

Este módulo es la única fuente de la lista: la grilla arma su despacho de
teclas desde `GRILLA` y el diálogo de ayuda muestra lo mismo, así lo que se
documenta no se despega de lo que hace la aplicación.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui import tema

# (etiqueta visible, tecla Qt, acción, descripción).
# Acción None = la maneja Qt por su cuenta (las flechas ya mueven la selección);
# se lista igual porque el usuario necesita saber que existe.
GRILLA: tuple[tuple[str, object, str | None, str], ...] = (
    ("Espacio", Qt.Key_Space, "reproducir", "Reproducir o pausar el audio"),
    ("I", Qt.Key_I, "interes_alternar",
     "Marcar / desmarcar como DE INTERÉS (es lo que se transcribe y lo que va "
     "al informe)"),
    ("1", Qt.Key_1, "interes_marcar", "Marcar como de interés"),
    ("0", Qt.Key_0, "interes_ninguno", "Quitar la marca de interés"),
    ("E", Qt.Key_E, "escuchado", "Marcar o desmarcar como escuchado"),
    ("D", Qt.Key_D, "a_desgrabar",
     "Mandar a Desgrabar (sirve para SMS e intentos, sin pasar por Whisper)"),
    ("Esc", Qt.Key_Escape, "deseleccionar", "Deseleccionar todo"),
    ("Supr", Qt.Key_Delete, "eliminar", "Enviar lo seleccionado a la papelera"),
    ("↑ / ↓", None, None, "Registro anterior / siguiente"),
    ("Clic en el encabezado", None, None,
     "Ordenar por esa columna (fecha, CD, abonado…)"),
)

GLOBALES: tuple[tuple[str, str], ...] = (
    ("Ctrl+Espacio", "Reproducir o pausar, sin importar dónde esté el foco"),
    ("Alt+↑ / Alt+↓", "Registro anterior / siguiente, salteando los filtrados"),
    ("Ctrl+E", "Marcar o desmarcar como escuchado"),
    ("Ctrl+F", "Ir al buscador de la Tabla TOTAL"),
    ("Ctrl+Z", "Deshacer el último envío a la papelera"),
    ("F1", "Mostrar esta ayuda"),
)

PANEL: tuple[tuple[str, str], ...] = (
    ("Clic en una frase", "Saltar a ese momento del audio"),
    ("Doble clic en una frase", "Corregir el texto de esa frase"),
    ("Clic en la onda", "Saltar a ese punto de la grabación"),
)


class DialogoAtajos(QDialog):
    """Chuleta de atajos. Se abre con F1 o desde el signo de pregunta."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Atajos de teclado")
        self.setModal(True)
        self.setMinimumWidth(520)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(6)

        titulo = QLabel("Atajos de teclado")
        titulo.setObjectName("titulo")
        lay.addWidget(titulo)

        sub = QLabel(
            "Con la grilla enfocada alcanza con una tecla; los Ctrl+… andan "
            "también mientras escribís."
        )
        sub.setObjectName("subtitulo")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        self._seccion(lay, "EN LA GRILLA", [(e, d) for e, _k, _a, d in GRILLA])
        self._seccion(lay, "EN CUALQUIER PARTE", list(GLOBALES))
        self._seccion(lay, "EN EL PANEL DE DETALLE", list(PANEL))

        pie = QHBoxLayout()
        pie.addStretch(1)
        btn = QPushButton("Cerrar")
        btn.setObjectName("primary")
        btn.clicked.connect(self.accept)
        pie.addWidget(btn)
        lay.addLayout(pie)

    def _seccion(self, lay: QVBoxLayout, titulo: str,
                 filas: list[tuple[str, str]]) -> None:
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{tema.LINE};")
        lay.addWidget(sep)

        lbl = QLabel(titulo)
        lbl.setObjectName("seccion")
        lbl.setStyleSheet(f"color:{tema.TEXT_DIM}; margin-top:6px;")
        lay.addWidget(lbl)

        grilla = QGridLayout()
        grilla.setHorizontalSpacing(14)
        grilla.setVerticalSpacing(4)
        grilla.setColumnStretch(1, 1)
        for i, (tecla, descripcion) in enumerate(filas):
            k = QLabel(tecla)
            k.setStyleSheet(
                f"background:{tema.BG_DEEP}; border:1px solid {tema.LINE};"
                f"border-radius:4px; padding:2px 8px; color:{tema.TEXT_PRIMARY};"
                "font-family:'IBM Plex Mono','Consolas',monospace; font-size:11px;"
            )
            grilla.addWidget(k, i, 0)
            d = QLabel(descripcion)
            d.setWordWrap(True)
            d.setStyleSheet(f"color:{tema.TEXT_MUTED};")
            grilla.addWidget(d, i, 1)
        lay.addLayout(grilla)


def mostrar_atajos(parent: QWidget | None) -> None:
    DialogoAtajos(parent).exec()
