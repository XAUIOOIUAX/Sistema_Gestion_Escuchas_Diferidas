"""Servicio de memoria de 'corresponde a' (módulo 2.2 del pseudocódigo).

Resuelve el nombre asociado a un número (primero por caso, luego global) y
permite persistir asociaciones. Al guardar NO se reescriben automáticamente los
registros pasados; solo aplica hacia adelante, salvo que el analista pida
explícitamente aplicar a los registros existentes.

La segunda mitad del módulo mueve esas identificaciones entre causas. Saber a
quién pertenece una línea es trabajo de investigación: no viene en el CD, sale
de un oficio a la prestadora, de un allanamiento o de la propia escucha. Cuando
el mismo número aparece en otra causa —y aparece, las mismas personas vuelven—
ese trabajo quedaba encerrado en el caso donde se hizo y había que tipearlo de
nuevo, con el riesgo de tipearlo distinto.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from app import repositorios as repo
from app.core.normalizers import normalizar_numero


def buscar(con: sqlite3.Connection, caso_id: int, numero: str) -> str:
    """Devuelve el nombre de memoria para un número (caso > global), o ''."""
    return repo.buscar_corresponde_a(con, caso_id, normalizar_numero(numero))


def guardar(
    con: sqlite3.Connection,
    caso_id: int,
    numero: str,
    nombre: str,
    alcance: str = "caso",
    aplicar_a_existentes: bool = False,
) -> int:
    """Guarda una asociación en memoria. Devuelve cuántos registros existentes
    se actualizaron (0 salvo que aplicar_a_existentes=True)."""
    numero_norm = normalizar_numero(numero)
    repo.guardar_corresponde_a(con, caso_id, numero_norm, nombre, alcance)

    actualizados = 0
    if aplicar_a_existentes:
        cur = con.execute(
            """
            UPDATE Registro SET corresponde_a = ?
            WHERE caso_id = ? AND (origen = ? OR destino = ?)
            """,
            (nombre, caso_id, numero_norm, numero_norm),
        )
        actualizados = cur.rowcount
        repo.log_auditoria(
            con,
            "edito",
            f"Memoria '{nombre}' aplicada a {actualizados} registros existentes "
            f"(número {numero_norm}, alcance {alcance})",
            caso_id,
        )
    con.commit()
    return actualizados


# --------------------------- migrar entre causas ---------------------------
#
# Tres decisiones que vale la pena explicar:
#
# **Migrar es copiar.** Quitar la entrada del origen se pide aparte porque no es
# lo mismo: la memoria del caso manda sobre la global (ver `buscar`), así que
# sacarla puede cambiar en silencio a quién resuelve ese número en la causa de
# origen.
#
# **Un nombre distinto en el destino no se pisa** salvo que se pida
# explícitamente. Dos causas pueden tener motivos para nombrar distinto a la
# misma línea —un alias en una, el nombre real en la otra— y la que uno está
# mirando no tiene por qué ganar.
#
# **Lo que queda en conflicto no se quita del origen**, aunque se haya pedido
# mover. Si no entró en el destino y se borra acá, la identificación se pierde
# entera.


@dataclass(frozen=True)
class Conflicto:
    """El destino ya conocía ese número, con otro nombre."""

    numero: str
    nombre_origen: str
    nombre_destino: str


@dataclass
class ResultadoMigracion:
    migradas: list[str] = field(default_factory=list)
    ya_estaban: list[str] = field(default_factory=list)
    conflictos: list[Conflicto] = field(default_factory=list)
    pisadas: list[Conflicto] = field(default_factory=list)
    quitadas: int = 0

    def __bool__(self) -> bool:  # noqa: D105
        return bool(self.migradas or self.ya_estaban or self.conflictos)


def _tabla(caso_id: int | None) -> str:
    return "AbonadoConocidoGlobal" if caso_id is None else "AbonadoConocidoPorCaso"


def _nombre_en(
    con: sqlite3.Connection, caso_id: int | None, numero: str
) -> str | None:
    """El nombre que el destino ya tiene para ese número, o None si no lo tiene.

    No usa `buscar`: ese cae en la global cuando el caso no sabe, y acá hace
    falta saber si la entrada existe EN ESE LUGAR. Si no, migrar a un caso un
    número que solo estaba en la global se leería como "ya estaba".
    """
    if caso_id is None:
        fila = con.execute(
            "SELECT nombre FROM AbonadoConocidoGlobal WHERE numero_normalizado = ?",
            (numero,),
        ).fetchone()
    else:
        fila = con.execute(
            "SELECT nombre FROM AbonadoConocidoPorCaso "
            "WHERE caso_id = ? AND numero_normalizado = ?",
            (caso_id, numero),
        ).fetchone()
    return fila["nombre"] if fila else None


def entradas(
    con: sqlite3.Connection, ids: list[int], caso_id: int | None
) -> list[sqlite3.Row]:
    """Las entradas pedidas, acotadas al lugar donde se dice que están.

    El filtro por `caso_id` no es decorativo: sin él, un id de otra causa
    entraría igual y se migraría algo que el analista no está viendo.
    """
    if not ids:
        return []
    marcas = ",".join("?" * len(ids))
    if caso_id is None:
        sql = f"SELECT * FROM AbonadoConocidoGlobal WHERE id IN ({marcas})"
        params: list = list(ids)
    else:
        sql = (
            f"SELECT * FROM AbonadoConocidoPorCaso WHERE caso_id = ? "
            f"AND id IN ({marcas})"
        )
        params = [caso_id, *ids]
    return con.execute(sql + " ORDER BY nombre, numero_normalizado", params).fetchall()


def migrar(
    con: sqlite3.Connection,
    ids: list[int],
    *,
    origen: int | None,
    destino: int | None,
    quitar_del_origen: bool = False,
    pisar: bool = False,
    usuario: str | None = None,
) -> ResultadoMigracion:
    """Copia entradas de memoria de un caso a otro, o a la global.

    `origen` y `destino` son el id del caso, o None para la memoria global.
    Devuelve el detalle de qué pasó con cada número: nada se informa como
    migrado si no quedó efectivamente en el destino.
    """
    if origen == destino:
        raise ValueError("El origen y el destino son el mismo lugar.")

    filas = entradas(con, ids, origen)
    resultado = ResultadoMigracion()
    aterrizadas: list[int] = []
    alcance = "global" if destino is None else "caso"

    for fila in filas:
        numero = fila["numero_normalizado"]
        nombre = fila["nombre"] or ""
        actual = _nombre_en(con, destino, numero)

        if actual is None:
            repo.guardar_corresponde_a(con, destino or 0, numero, nombre, alcance)
            resultado.migradas.append(numero)
            aterrizadas.append(fila["id"])
        elif actual == nombre:
            resultado.ya_estaban.append(numero)
            aterrizadas.append(fila["id"])
        elif pisar:
            repo.guardar_corresponde_a(con, destino or 0, numero, nombre, alcance)
            resultado.migradas.append(numero)
            resultado.pisadas.append(Conflicto(numero, nombre, actual))
            aterrizadas.append(fila["id"])
        else:
            resultado.conflictos.append(Conflicto(numero, nombre, actual))

    if quitar_del_origen and aterrizadas:
        marcas = ",".join("?" * len(aterrizadas))
        cur = con.execute(
            f"DELETE FROM {_tabla(origen)} WHERE id IN ({marcas})", aterrizadas
        )
        resultado.quitadas = cur.rowcount

    if resultado.migradas or resultado.quitadas:
        verbo = "Movió" if quitar_del_origen else "Copió"
        repo.log_auditoria(
            con,
            "edito",
            f"Memoria «corresponde a»: {verbo} {len(resultado.migradas)} "
            f"identificación(es) de {_rotulo(con, origen)} "
            f"a {_rotulo(con, destino)}",
            destino,
            usuario,
        )
    con.commit()
    return resultado


def _rotulo(con: sqlite3.Connection, caso_id: int | None) -> str:
    if caso_id is None:
        return "la memoria global"
    caso = repo.obtener_caso(con, caso_id)
    return f"«{caso['nombre']}»" if caso else f"el caso #{caso_id}"
