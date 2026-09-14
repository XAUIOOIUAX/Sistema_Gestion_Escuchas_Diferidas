"""Tema visual de la aplicación: paleta oscura y paleta clara.

Traduce la paleta y tipografía del mockup v2 (mockup_interfaz_v2.html) a una
hoja de estilos Qt (QSS) reutilizable en toda la UI.

Hay dos modos. El oscuro es el original y sigue siendo el de fábrica: es el que
se banca una jornada larga de escucha con la luz baja. El claro existe porque el
material sale de la pantalla: cuando se proyecta el mapa o el grafo en una
reunión, o se muestra la grilla en una oficina con ventana al sol, el oscuro se
vuelve ilegible.

Cómo usarlo: `set_modo("claro")` reescribe los nombres de color de este módulo
y regenera `QSS`. Todo el resto de la UI lee `tema.ALGO` en el momento de
pintar, así que basta con volver a aplicar la hoja y reconstruir las pantallas
(lo hace `VentanaPrincipal.cambiar_tema`).
"""

from __future__ import annotations

MODOS: tuple[str, str] = ("oscuro", "claro")
MODO_POR_DEFECTO = "oscuro"

# Los alfas de la grilla van por paleta y no por token compartido: sobre fondo
# oscuro la fila activa se destaca SUBIENDO el brillo (velo blanco), y sobre
# fondo claro haciendo exactamente lo contrario (velo negro). Usar el mismo
# velo en los dos modos deja la fila activa invisible en uno de ellos.
#
# Nada de la grilla reacciona al mouse a propósito: la única fila resaltada es
# la seleccionada. Un realce que seguía al cursor se lee como si la selección
# se moviera sola, y apoyar el mouse mientras se escucha un audio hacía perder
# de vista cuál era el registro en el que se estaba trabajando.
_PALETAS: dict[str, dict[str, object]] = {
    "oscuro": {
        "BG_DEEP": "#161A20",
        "BG_APP": "#0D1014",
        "PANEL": "#1E242C",
        "PANEL_RAISED": "#252C36",
        "LINE": "#313A46",
        "TEXT_PRIMARY": "#EDEBE5",
        "TEXT_MUTED": "#9AA3B2",
        "TEXT_DIM": "#7A8494",
        "ACCENT": "#D7A53D",
        "ACCENT_DIM": "#8A6A28",
        "ACCENT_RGB": "215,165,61",
        "ACCENT_TEXTO": "#1A1306",
        "ACCENT_HOVER": "#E4B654",
        "DANGER": "#C9605A",
        "DANGER_RGB": "201,96,90",
        "DANGER_HOVER": "#E8837D",
        "TEAL": "#5FA8A0",
        "ROSE": "#C97B84",
        "VIOLET": "#9085C9",
        "SAGE": "#8FAE6B",
        "SAND": "#C9A36A",
        "FILA_ALTERNA": "#1B2028",
        "FILA_SELECCION_BRILLO": (255, 255, 255, 30),
        "FILA_SELECCION": (215, 165, 61, 48),
        "FILA_SELECCION_BORDE": (215, 165, 61, 235),
        "CELDA_ACTUAL_BORDE": (237, 235, 229, 130),
    },
    "claro": {
        # El "papel" es blanco puro solo donde se lee texto largo (tablas,
        # campos); el resto va sobre un crema apagado para que la pantalla no
        # deslumbre en una oficina con ventana.
        "BG_DEEP": "#FFFFFF",
        "BG_APP": "#F2F0EA",
        "PANEL": "#E9E5DC",
        "PANEL_RAISED": "#DFDAD0",
        "LINE": "#C9C2B5",
        "TEXT_PRIMARY": "#1F2329",
        "TEXT_MUTED": "#4E5661",
        "TEXT_DIM": "#6E7785",
        # El dorado del tema oscuro sobre crema da 2,6:1 y no se puede leer en
        # 11px. Se baja a un ocre oscuro que llega a 4,5:1 como texto, y los
        # botones que lo usan de fondo pasan a texto blanco.
        "ACCENT": "#8A5D00",
        "ACCENT_DIM": "#D9C48E",
        "ACCENT_RGB": "138,93,0",
        "ACCENT_TEXTO": "#FFFFFF",
        "ACCENT_HOVER": "#A87209",
        "DANGER": "#A8342D",
        "DANGER_RGB": "168,52,45",
        "DANGER_HOVER": "#8C231D",
        "TEAL": "#1F6F66",
        "ROSE": "#A34A55",
        "VIOLET": "#5E52A0",
        "SAGE": "#5A7A34",
        "SAND": "#8A6528",
        "FILA_ALTERNA": "#F4F1EA",
        "FILA_SELECCION_BRILLO": (0, 0, 0, 16),
        "FILA_SELECCION": (138, 93, 0, 40),
        "FILA_SELECCION_BORDE": (138, 93, 0, 235),
        "CELDA_ACTUAL_BORDE": (31, 35, 41, 150),
    },
}

_modo = ""


def modo() -> str:
    """Modo activo: 'oscuro' o 'claro'."""
    return _modo


def _verificar_paletas() -> None:
    """Todas las paletas tienen que nombrar los mismos colores.

    `globals().update()` solo pisa las claves que trae la paleta nueva: una que
    le faltara se quedaría con el valor de la anterior, así que el modo claro
    heredaría en silencio un color del oscuro y solo se notaría mirando. Un
    color que no existe en los dos modos es un error de programación, y es
    mejor que salte al cambiar el tema que en la pantalla de alguien.
    """
    modos = list(_PALETAS)
    referencia = set(_PALETAS[modos[0]])
    for otro in modos[1:]:
        diferencia = referencia ^ set(_PALETAS[otro])
        if diferencia:
            raise ValueError(
                f"Las paletas {modos[0]} y {otro} no nombran los mismos "
                f"colores: {sorted(diferencia)}"
            )


def set_modo(nombre: str) -> str:
    """Cambia la paleta activa y regenera `QSS`. Devuelve el modo aplicado.

    Reescribe los nombres de color del módulo, de modo que todo lo que dibuja
    leyendo `tema.ALGO` toma los valores nuevos sin cambiar una línea. Un nombre
    desconocido cae en el modo por defecto en lugar de romper el arranque.
    """
    global _modo, QSS, BADGE_DIRECCION
    _modo = nombre if nombre in _PALETAS else MODO_POR_DEFECTO
    _verificar_paletas()
    globals().update(_PALETAS[_modo])
    BADGE_DIRECCION = {
        "ENTRANTE": (f"rgba({_rgb(TEAL)},0.18)", TEAL),
        "SALIENTE": (f"rgba({_rgb(ROSE)},0.18)", ROSE),
        "ENTRE ABONADOS": (f"rgba({_rgb(VIOLET)},0.18)", VIOLET),
        "NO IDENTIFICADO": (f"rgba({_rgb(TEXT_MUTED)},0.14)", TEXT_MUTED),
    }
    QSS = _PLANTILLA.format(**globals())
    return _modo


def _rgb(hex_color: str) -> str:
    """'#5FA8A0' -> '95,168,160', para armar rgba() en la hoja de estilos."""
    h = hex_color.lstrip("#")
    return ",".join(str(int(h[i:i + 2], 16)) for i in (0, 2, 4))


_PLANTILLA = """
* {{
    font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif;
    font-size: 13px;
    color: {TEXT_PRIMARY};
}}
QMainWindow, QWidget#fondo {{ background: {BG_APP}; }}

/* Topbar */
QFrame#topbar {{ background: {PANEL}; border-bottom: 1px solid {LINE}; }}
QLabel#brand {{ font-size: 14px; font-weight: 600; letter-spacing: 1px; }}
QLabel#caseTag {{ color: {ACCENT}; font-family: 'IBM Plex Mono','Consolas',monospace; font-size: 11px; }}
QPushButton#analista {{
    background: transparent;
    border: 1px solid {LINE};
    border-radius: 12px;
    color: {TEXT_MUTED};
    padding: 5px 12px;
    font-size: 11px;
    font-weight: 500;
}}
QPushButton#analista:hover {{ color: {TEXT_PRIMARY}; border-color: {ACCENT_DIM}; }}

/* Sidebar */
QListWidget#sidebar {{
    background: {PANEL};
    border: none;
    border-right: 1px solid {LINE};
    outline: 0;
    padding-top: 8px;
}}
QListWidget#sidebar::item {{
    color: {TEXT_MUTED};
    padding: 10px 16px;
    border-left: 3px solid transparent;
}}
QListWidget#sidebar::item:selected {{
    background: {BG_DEEP};
    color: {TEXT_PRIMARY};
    border-left: 3px solid {ACCENT};
}}
QListWidget#sidebar::item:hover {{ color: {TEXT_PRIMARY}; }}

/* Encabezados de sección de pantalla */
QLabel#titulo {{ font-size: 16px; font-weight: 600; }}
QLabel#subtitulo {{ font-size: 12px; color: {TEXT_DIM}; }}
QLabel#seccion {{ font-size: 10px; color: {TEXT_DIM}; letter-spacing: 2px; }}

/* Botones */
QPushButton {{
    background: {PANEL_RAISED};
    border: 1px solid {LINE};
    border-radius: 6px;
    color: {TEXT_MUTED};
    padding: 8px 14px;
    font-weight: 500;
}}
QPushButton:hover {{ color: {TEXT_PRIMARY}; border-color: {TEXT_DIM}; }}
QPushButton#primary {{
    background: {ACCENT};
    color: {ACCENT_TEXTO};
    border-color: {ACCENT};
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton:disabled {{ color: {TEXT_DIM}; background: {PANEL}; }}

/* ToolButton (menú Exportar): mismo look que los botones */
QToolButton {{
    background: {PANEL_RAISED};
    border: 1px solid {LINE};
    border-radius: 6px;
    color: {TEXT_MUTED};
    padding: 8px 14px;
    font-weight: 500;
}}
QToolButton:hover {{ color: {TEXT_PRIMARY}; border-color: {TEXT_DIM}; }}
QToolButton#primary {{
    background: {ACCENT};
    color: {ACCENT_TEXTO};
    border-color: {ACCENT};
    font-weight: 600;
}}
QToolButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

/* Inputs */
QLineEdit, QTextEdit, QComboBox {{
    background: {BG_DEEP};
    border: 1px solid {LINE};
    border-radius: 6px;
    padding: 7px 10px;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT_DIM};
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {PANEL_RAISED};
    border: 1px solid {LINE};
    selection-background-color: {ACCENT_DIM};
    color: {TEXT_PRIMARY};
}}

/* Barras de progreso (importación, transcripción, avance de escucha) */
QProgressBar {{
    background: {BG_DEEP};
    border: 1px solid {LINE};
    border-radius: 5px;
    text-align: center;
    color: {TEXT_MUTED};
    font-size: 11px;
}}
QProgressBar::chunk {{ background: {TEAL}; border-radius: 4px; }}

/* Tablas */
QTableView, QTableWidget {{
    background: {BG_DEEP};
    alternate-background-color: {FILA_ALTERNA};
    border: none;
    gridline-color: {LINE};
    color: {TEXT_PRIMARY};
    selection-background-color: rgba({ACCENT_RGB},0.12);
    selection-color: {TEXT_PRIMARY};
}}
QHeaderView::section {{
    background: {PANEL};
    color: {TEXT_DIM};
    padding: 9px 12px;
    border: none;
    border-bottom: 1px solid {LINE};
    font-size: 11px;
    text-transform: uppercase;
}}
/* background transparent: deja que el delegado pinte el color del abonado
   debajo. Sin esto QStyleSheetStyle rellena la celda con el fondo del tema y
   tapa la marca de colores (ver _DelegadoColorAbonado en pantalla_total.py). */
QTableView::item, QTableWidget::item {{
    padding: 6px 10px;
    border-bottom: 1px solid {LINE};
    background: transparent;
}}
/* Resaltado de las grillas SIN delegado propio (Índice, Validaciones,
   Auditoría, Exportaciones). En la Tabla TOTAL no llega a aplicarse porque el
   delegado dibuja la banda él mismo y apaga el estado de selección. */
QTableView::item:selected, QTableWidget::item:selected {{
    background: rgba({ACCENT_RGB},0.20);
    color: {TEXT_PRIMARY};
}}
/* Los combos de Contexto e Interés viven dentro de las celdas: sin fondo
   propio, el rayado y la banda de la fila activa no se cortan al pasar por
   esas dos columnas. El borde aparece al pasar el mouse, que es cuando hace
   falta saber que se pueden desplegar. */
QComboBox#celdaCombo {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px 6px;
}}
QComboBox#celdaCombo:hover {{
    background: {PANEL_RAISED};
    border-color: {LINE};
}}
QComboBox#celdaCombo:focus {{ border-color: {ACCENT_DIM}; }}

/* Marca de interlocutor en la transcripción sincronizada: chiquita y discreta
   sin asignar, marcada cuando el analista atribuyó la voz. */
QPushButton#hablante {{
    background: transparent;
    border: 1px solid {LINE};
    border-radius: 4px;
    color: {TEXT_DIM};
    padding: 0;
    font-size: 10px;
    font-weight: 600;
    min-height: 18px;
}}
QPushButton#hablante:hover {{ color: {TEXT_PRIMARY}; border-color: {ACCENT_DIM}; }}

/* Paneles */
QFrame#panel {{ background: {PANEL}; border-left: 1px solid {LINE}; }}
QFrame#card {{ background: {PANEL_RAISED}; border: 1px solid {LINE}; border-radius: 8px; }}

/* Áreas con scroll: sin esto el viewport hereda el fondo blanco del sistema
   y el contenido queda ilegible (texto claro sobre blanco). */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QAbstractScrollArea::corner {{ background: {BG_DEEP}; }}

/* Diálogos y menús del sistema (QMessageBox, QInputDialog, menús contextuales) */
QDialog, QMessageBox, QInputDialog {{ background: {PANEL}; }}
QDialog QLabel, QMessageBox QLabel {{ color: {TEXT_PRIMARY}; }}
QMenu {{
    background: {PANEL_RAISED};
    border: 1px solid {LINE};
    color: {TEXT_PRIMARY};
    padding: 4px;
}}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT_DIM}; }}
QToolTip {{
    background: {PANEL_RAISED};
    color: {TEXT_PRIMARY};
    border: 1px solid {LINE};
    padding: 4px 8px;
}}

/* Checkbox */
QCheckBox {{ color: {TEXT_MUTED}; spacing: 7px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {LINE}; border-radius: 4px;
    background: {BG_DEEP};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

/* Combos y botones dentro de celdas de tabla: compactos y legibles */
QTableWidget QComboBox, QTableView QComboBox {{
    background: {PANEL_RAISED};
    border: 1px solid {LINE};
    border-radius: 5px;
    padding: 3px 8px;
    font-size: 12px;
    color: {TEXT_PRIMARY};
}}
QTableWidget QPushButton {{
    padding: 4px 12px;
    font-size: 12px;
}}

/* Botón de peligro (vaciar caso, etc.) */
QPushButton#danger {{
    background: rgba({DANGER_RGB},0.14);
    color: {DANGER};
    border: 1px solid {DANGER};
}}
QPushButton#danger:hover {{ background: rgba({DANGER_RGB},0.28); color: {DANGER_HOVER}; }}

/* Chip de alerta clickeable */
QPushButton#chipAlerta {{
    background: rgba({DANGER_RGB},0.12);
    color: {DANGER};
    border: 1px solid rgba({DANGER_RGB},0.55);
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 12px;
}}
QPushButton#chipAlerta:hover {{ background: rgba({DANGER_RGB},0.24); }}

/* Búsqueda de la topbar */
QLineEdit#buscador {{
    background: {BG_DEEP};
    border: 1px solid {LINE};
    border-radius: 15px;
    padding: 6px 14px;
    color: {TEXT_PRIMARY};
}}

/* Statusbar */
QStatusBar {{ background: {PANEL}; color: {TEXT_DIM}; border-top: 1px solid {LINE}; }}

/* Scrollbars */
QScrollBar:vertical {{ background: {BG_DEEP}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {TEXT_DIM}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: {BG_DEEP}; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {LINE}; border-radius: 5px; min-width: 30px; }}
"""


# Deja el módulo listo al importarse: `tema.QSS`, `tema.ACCENT` y compañía
# existen desde el arranque, igual que cuando la paleta era fija.
QSS: str = ""
set_modo(MODO_POR_DEFECTO)
