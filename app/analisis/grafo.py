"""Armado del grafo de vínculos: quién habla con quién y cuánto.

Un diagrama de vínculos es una figura estándar de este trabajo y es de las que
terminan en el informe. Pero solo sirve si lo que señala es cierto, y el que
había señalaba mal por cuatro motivos que se veían todos juntos en una causa
real de 238 comunicaciones:

**El centro del grafo era un remitente automático.** El nodo más conectado
—el que se dibuja en el medio y con anillo de acento, o sea "el centro de la
causa"— era `1520`, con 127 comunicaciones. Un código de servicio de la
prestadora. Detrás venían `2C7140` y `55110`, iguales. La figura decía que el
eje de la investigación era el correo promocional.

**Los nodos eran números.** El Índice de abonados y la memoria «corresponde a»
tienen los nombres, pero el grafo mostraba `3875550022`. Era la única pantalla
que seguía hablando en números.

**La misma persona aparecía cuatro veces.** Ernesto Ramón Paredes tiene tres
líneas en la causa, cada una su nodo, y además los audios sin metadatos
generaban un nodo suelto rotulado con su NOMBRE, sin una sola arista, flotando
al costado. Dos sistemas de rótulo mezclados en el mismo dibujo.

**El color mentía.** Cada nodo tomaba el color del registro, que es el de la
LÍNEA INTERVENIDA de esa comunicación. Así que un número de afuera quedaba
pintado igual que la línea pinchada con la que habló, y el color —que en la
Tabla TOTAL significa "de qué línea intervenida es esto"— acá no significaba
nada.

Este módulo arma el grafo aparte de la pantalla para poder probarlo contra
datos reales sin abrir una ventana. No importa nada de UI: los colores los
decide quien llama.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, field

VALOR_NO_IDENTIFICADO = "NO IDENTIFICADO"

# Un abonado argentino tiene diez dígitos (código de área + número). Lo que no
# llega a ocho, o trae letras, no es una línea: es un remitente de servicio.
_MINIMO_DIGITOS_ABONADO = 8


@dataclass(frozen=True)
class Opciones:
    """Qué se muestra. Lo que cambia el dibujo se elige, no se decide solo."""

    agrupar_por_persona: bool = True
    ocultar_servicios: bool = True
    peso_minimo: int = 1


@dataclass
class Nodo:
    clave: str
    etiqueta: str
    color: str
    intervenido: bool = False
    numeros: set[str] = field(default_factory=set)
    n_conexiones: int = 0
    n_internas: int = 0      # comunicaciones entre líneas de la misma persona
    n_sin_contraparte: int = 0   # audios sin metadatos: no se sabe con quién
    x: float = 0.0
    y: float = 0.0

    @property
    def nombre(self) -> str:
        """Nombre anterior del campo. Se conserva para no romper lo que lo usa."""
        return self.etiqueta


@dataclass
class Arista:
    origen: str
    destino: str
    peso: int = 0
    color: str = "#888888"


def es_codigo_de_servicio(numero: str) -> bool:
    """True si eso no es una línea telefónica sino un remitente automático.

    Son los `1520`, `55110`, `2C7140` de las prestadoras, los bancos y las
    promociones. Mandan decenas de mensajes, así que sin filtrarlos se llevan
    el centro del grafo y tapan los vínculos que importan.
    """
    numero = (numero or "").strip()
    if not numero or numero == VALOR_NO_IDENTIFICADO:
        return False
    if not numero.isdigit():
        return True
    return len(numero) < _MINIMO_DIGITOS_ABONADO


def _valido(numero: str) -> bool:
    numero = (numero or "").strip()
    return bool(numero) and numero != VALOR_NO_IDENTIFICADO


def construir(
    registros: list[sqlite3.Row],
    *,
    nombres: dict[str, str] | None = None,
    colores: dict[str, str] | None = None,
    intervenidos: set[str] | frozenset[str] = frozenset(),
    color_externo: str = "#888888",
    opciones: Opciones = Opciones(),
) -> tuple[dict[str, Nodo], list[Arista]]:
    """Nodos y aristas de la causa.

    `nombres` y `colores` van por número normalizado; `intervenidos` son las
    líneas pinchadas. El color de un nodo es el de su línea intervenida, igual
    que el de la fila en la Tabla TOTAL; el resto va en `color_externo`, porque
    ahí el color no codifica nada y fingir que sí es lo que hacía antes.
    """
    nombres = nombres or {}
    colores = colores or {}

    def clave_de(numero: str) -> str:
        nombre = (nombres.get(numero) or "").strip()
        if not (opciones.agrupar_por_persona and nombre):
            return numero
        # Sin distinguir mayúsculas: el Índice y la memoria son dos lugares
        # distintos donde se tipea el mismo nombre, y en la causa real la misma
        # persona quedaba partida en dos nodos por "LEMOS" contra "Lemos".
        return nombre.casefold()

    def etiqueta_de(numero: str) -> str:
        return (nombres.get(numero) or "").strip() or numero

    nodos: dict[str, Nodo] = {}

    def asegurar(numero: str) -> Nodo:
        clave = clave_de(numero)
        nodo = nodos.get(clave)
        if nodo is None:
            nodo = Nodo(
                clave=clave,
                etiqueta=etiqueta_de(numero),
                color=colores.get(numero, color_externo)
                if numero in intervenidos else color_externo,
                intervenido=numero in intervenidos,
            )
            nodos[clave] = nodo
        elif numero in intervenidos and not nodo.intervenido:
            # Una persona con una línea pinchada y otra no: manda la pinchada,
            # que es la que le da color y peso en el expediente.
            nodo.intervenido = True
            nodo.color = colores.get(numero, nodo.color)
        nodo.numeros.add(numero)
        return nodo

    # Las líneas intervenidas entran aunque no registren una sola comunicación:
    # están declaradas en la causa, y una línea pinchada que no habló con nadie
    # es justamente de las cosas que hay que poder ver.
    for numero in sorted(intervenidos):
        if _valido(numero):
            asegurar(numero)

    pares: Counter[tuple[str, str]] = Counter()

    for r in registros:
        origen = (r["origen"] or "").strip()
        destino = (r["destino"] or "").strip()
        linea = (r["abonado_intervenido"] or "").strip()

        # Audio sin metadatos: no trae origen ni destino, solo la carpeta de la
        # que salió. Antes inventaba un nodo suelto rotulado con el nombre del
        # interesado, que quedaba flotando sin una sola arista. Ahora se anota
        # en la línea de la que salió, que es todo lo que realmente se sabe.
        if not (_valido(origen) and _valido(destino)):
            if _valido(linea):
                asegurar(linea).n_sin_contraparte += 1
            continue

        if opciones.ocultar_servicios and (
            es_codigo_de_servicio(origen) or es_codigo_de_servicio(destino)
        ):
            continue

        nodo_o, nodo_d = asegurar(origen), asegurar(destino)
        if nodo_o.clave == nodo_d.clave:
            # Dos líneas de la misma persona hablando entre sí. Es un dato
            # —usa dos teléfonos— pero no es un vínculo con nadie.
            nodo_o.n_internas += 1
            continue
        pares[tuple(sorted((nodo_o.clave, nodo_d.clave)))] += 1

    aristas = [
        Arista(
            origen=o, destino=d, peso=peso,
            color=(
                nodos[o].color if nodos[o].intervenido
                else nodos[d].color if nodos[d].intervenido
                else color_externo
            ),
        )
        for (o, d), peso in pares.items()
        if peso >= max(1, opciones.peso_minimo)
    ]

    for arista in aristas:
        nodos[arista.origen].n_conexiones += arista.peso
        nodos[arista.destino].n_conexiones += arista.peso

    # Los que quedaron sin ningún vínculo después de filtrar solo ocupan lugar,
    # salvo las líneas intervenidas: esas están declaradas en la causa y que no
    # registren comunicaciones es en sí mismo algo para ver.
    nodos = {
        clave: nodo for clave, nodo in nodos.items()
        if nodo.n_conexiones or nodo.intervenido or nodo.n_internas
    }
    aristas = [
        a for a in aristas if a.origen in nodos and a.destino in nodos
    ]
    return nodos, aristas


def resumen(nodos: dict[str, Nodo], aristas: list[Arista]) -> str:
    comunicaciones = sum(a.peso for a in aristas)
    interv = sum(1 for n in nodos.values() if n.intervenido)
    return (
        f"{len(nodos)} abonados ({interv} intervenidos) · "
        f"{len(aristas)} vínculos · {comunicaciones} comunicaciones"
    )
