"""Capa de acceso a datos (repositorios).

Funciones finas sobre la conexión SQLite que encapsulan las consultas usadas
por los servicios (importación, edición, exportación). Mantienen la lógica de
negocio fuera del SQL crudo y los servicios fuera de los detalles de la base.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Iterable

from app import sesion
from app.core.colores import color_por_indice, normalizar_color_hex
from app.core.interesado import componer_interesado
from app.core.interlocutor import componer_interlocutor
from app.models import RegistroParseado

# Columnas de Registro que se escriben en una inserción de importación.
_COLS_REGISTRO = (
    "caso_id",
    "orden",
    "interesado",
    "interlocutor",
    "tipo",
    "cd",
    "direccion",
    "origen",
    "destino",
    "origen_crudo",
    "destino_crudo",
    "corresponde_a",
    "fecha_inicio_texto",
    "fecha_fin_texto",
    "fecha_inicio_dt",
    "antenas",
    "tecnologia",
    "calle",
    "numero_calle",
    "localidad",
    "provincia",
    "latitud",
    "longitud",
    "azimuth",
    "radio",
    "contexto",
    "transcripcion",
    "archivo_audio",
    "archivo_txt",
    "estado",
    "clave_dedup",
)


# ------------------------------- Casos -------------------------------------
def crear_caso(con: sqlite3.Connection, nombre: str, notas: str = "") -> int:
    cur = con.execute(
        "INSERT INTO Caso (nombre, notas) VALUES (?, ?)", (nombre, notas)
    )
    con.commit()
    return int(cur.lastrowid)


def listar_casos(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT c.*,
               (SELECT COUNT(*) FROM Registro r WHERE r.caso_id = c.id) AS n_registros
        FROM Caso c
        ORDER BY c.fecha_creacion DESC, c.id DESC
        """
    ).fetchall()


def obtener_caso(con: sqlite3.Connection, caso_id: int) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM Caso WHERE id = ?", (caso_id,)).fetchone()


# ------------------------------ Abonados -----------------------------------
def cargar_indice_abonados(con: sqlite3.Connection, caso_id: int) -> dict[str, str]:
    """Devuelve {numero_normalizado: pertenece_a} para el caso (índice INTERESADO)."""
    filas = con.execute(
        "SELECT numero_normalizado, pertenece_a FROM Abonado WHERE caso_id = ?",
        (caso_id,),
    )
    return {r["numero_normalizado"]: (r["pertenece_a"] or "") for r in filas}


def obtener_o_crear_abonado(
    con: sqlite3.Connection,
    caso_id: int,
    numero_normalizado: str,
    intervenido: bool = False,
) -> sqlite3.Row:
    """Devuelve el abonado del caso, creándolo con color automático si no existe.

    Si `intervenido` es True, marca al abonado como línea intervenida (no lo
    desmarca si ya lo estaba).
    """
    fila = con.execute(
        "SELECT * FROM Abonado WHERE caso_id = ? AND numero_normalizado = ?",
        (caso_id, numero_normalizado),
    ).fetchone()
    if fila is not None:
        if intervenido and not fila["intervenido"]:
            con.execute(
                "UPDATE Abonado SET intervenido = 1 WHERE id = ?", (fila["id"],)
            )
            fila = con.execute(
                "SELECT * FROM Abonado WHERE id = ?", (fila["id"],)
            ).fetchone()
        return fila

    n_existentes = con.execute(
        "SELECT COUNT(*) AS n FROM Abonado WHERE caso_id = ?", (caso_id,)
    ).fetchone()["n"]
    color = color_por_indice(n_existentes)
    con.execute(
        "INSERT INTO Abonado (caso_id, numero_normalizado, color_hex, intervenido) "
        "VALUES (?, ?, ?, ?)",
        (caso_id, numero_normalizado, color, 1 if intervenido else 0),
    )
    return con.execute(
        "SELECT * FROM Abonado WHERE caso_id = ? AND numero_normalizado = ?",
        (caso_id, numero_normalizado),
    ).fetchone()


def marcar_abonado_intervenido(
    con: sqlite3.Connection, abonado_id: int, intervenido: bool
) -> None:
    con.execute(
        "UPDATE Abonado SET intervenido = ? WHERE id = ?",
        (1 if intervenido else 0, abonado_id),
    )


def contar_abonados_intervenidos(con: sqlite3.Connection, caso_id: int) -> int:
    return con.execute(
        "SELECT COUNT(*) AS n FROM Abonado WHERE caso_id = ? AND intervenido = 1",
        (caso_id,),
    ).fetchone()["n"]


def listar_abonados(
    con: sqlite3.Connection, caso_id: int, solo_intervenidos: bool = False
) -> list[sqlite3.Row]:
    """Abonados del caso con la cantidad de registros en los que participan.

    Con `solo_intervenidos=True` devuelve únicamente las líneas intervenidas
    (lo que corresponde al Índice de abonados de la causa).
    """
    filtro = "AND a.intervenido = 1" if solo_intervenidos else ""
    return con.execute(
        f"""
        SELECT a.*,
               (SELECT COUNT(*) FROM Registro r
                WHERE r.caso_id = a.caso_id
                  AND (r.origen = a.numero_normalizado
                       OR r.destino = a.numero_normalizado)) AS n_registros
        FROM Abonado a
        WHERE a.caso_id = ? {filtro}
        ORDER BY a.intervenido DESC,
                 a.pertenece_a IS NULL OR a.pertenece_a = '', a.pertenece_a,
                 a.numero_normalizado
        """,
        (caso_id,),
    ).fetchall()


def listar_abonados_por_alta(
    con: sqlite3.Connection, caso_id: int
) -> list[sqlite3.Row]:
    """Abonados del caso en orden de alta (id), como se declararon en el CD.

    El informe judicial respeta este orden (el del DatosCausa.txt), no el
    alfabético que usa la pantalla Índice. Solo incluye líneas intervenidas si
    hay alguna marcada; si no, devuelve todas (compatibilidad con casos viejos).
    """
    intervenidos = con.execute(
        "SELECT * FROM Abonado WHERE caso_id = ? AND intervenido = 1 ORDER BY id",
        (caso_id,),
    ).fetchall()
    if intervenidos:
        return intervenidos
    return con.execute(
        "SELECT * FROM Abonado WHERE caso_id = ? ORDER BY id",
        (caso_id,),
    ).fetchall()


_CAMPOS_ABONADO_EDITABLES = frozenset({"pertenece_a", "observaciones"})


def actualizar_abonado(
    con: sqlite3.Connection, abonado_id: int, campo: str, valor: str
) -> None:
    """Edita un campo de texto permitido del abonado.

    El color no pasa por acá porque necesita validación propia: usar
    `actualizar_color_abonado`.
    """
    if campo not in _CAMPOS_ABONADO_EDITABLES:
        raise ValueError(f"Campo de abonado no editable: {campo}")
    con.execute(f"UPDATE Abonado SET {campo} = ? WHERE id = ?", (valor, abonado_id))


def actualizar_color_abonado(
    con: sqlite3.Connection, abonado_id: int, color_hex: str
) -> str:
    """Fija a mano el color del abonado y devuelve el valor normalizado.

    Al crear el abonado el color sale de la paleta automática; esto permite
    corregirlo sin alterar la asignación del resto. Todas las vistas leen
    color_hex en cada consulta, así que el cambio se propaga solo.
    """
    color = normalizar_color_hex(color_hex)
    con.execute(
        "UPDATE Abonado SET color_hex = ? WHERE id = ?", (color, abonado_id)
    )
    return color


def aplicar_interesado_a_registros(
    con: sqlite3.Connection, caso_id: int, numero_normalizado: str, nombre: str
) -> int:
    """Actualiza el campo interesado de los registros donde participa el número."""
    cur = con.execute(
        """
        UPDATE Registro SET interesado = ?
        WHERE caso_id = ? AND (origen = ? OR destino = ?)
        """,
        (nombre, caso_id, numero_normalizado, numero_normalizado),
    )
    return cur.rowcount


def nombres_conocidos(con: sqlite3.Connection, caso_id: int) -> dict[str, str]:
    """Número -> nombre, con el Índice de la causa arriba de la memoria.

    Son dos directorios distintos y los dos contestan "¿quién es este número?":
    el Índice nombra las líneas de ESTA causa (y les pone color), y la memoria
    «corresponde a» guarda identificaciones que se comparten entre causas. El
    Índice manda porque es lo que el analista cargó mirando este expediente.
    """
    nombres: dict[str, str] = {}
    for tabla in ("AbonadoConocidoGlobal", "AbonadoConocidoPorCaso"):
        cond = "" if tabla == "AbonadoConocidoGlobal" else " WHERE caso_id = ?"
        params = () if tabla == "AbonadoConocidoGlobal" else (caso_id,)
        for fila in con.execute(
            f"SELECT numero_normalizado, nombre FROM {tabla}{cond}", params
        ):
            nombre = (fila["nombre"] or "").strip()
            if nombre:
                nombres[fila["numero_normalizado"]] = nombre
    for fila in con.execute(
        "SELECT numero_normalizado, pertenece_a FROM Abonado WHERE caso_id = ?",
        (caso_id,),
    ):
        nombre = (fila["pertenece_a"] or "").strip()
        if nombre:
            nombres[fila["numero_normalizado"]] = nombre
    return nombres


def recalcular_nombres(con: sqlite3.Connection, caso_id: int) -> int:
    """Recompone Interesado e Interlocutor de toda la causa.

    Devuelve cuántas comunicaciones cambiaron en alguna de las dos columnas.

    Reemplaza al parche que había antes, que al nombrar un abonado hacía un
    UPDATE de `interesado = <ese nombre>` sobre todos los registros donde el
    número apareciera. Eso pisaba los valores compuestos ("ORIGEN: A /
    DESTINO: B") y el resultado dependía del orden en que se hubieran nombrado
    los abonados: dos comunicaciones entre las mismas dos líneas podían quedar
    con textos distintos.

    Acá se recalcula todo desde cero con el Índice actual, así que el resultado
    es el mismo se llame cuando se llame y en el orden que sea. Las dos columnas
    se recomponen juntas porque las dos salen del mismo dato —quién es cada
    número— y dejar una al día y la otra vieja es peor que no tenerlas.
    """
    # Interesado nombra las dos puntas y solo confía en el Índice de la causa:
    # es la columna que ordena el expediente. Interlocutor busca identificar a
    # alguien de afuera, así que además aprovecha la memoria compartida.
    del_indice = {
        fila["numero_normalizado"]: (fila["pertenece_a"] or "").strip()
        for fila in con.execute(
            "SELECT numero_normalizado, pertenece_a FROM Abonado WHERE caso_id = ?",
            (caso_id,),
        )
    }
    todos = nombres_conocidos(con, caso_id)

    cambiados = 0
    for r in con.execute(
        "SELECT id, origen, destino, direccion, abonado_intervenido, "
        "interesado, interlocutor FROM Registro WHERE caso_id = ?",
        (caso_id,),
    ).fetchall():
        linea = r["abonado_intervenido"] or ""
        interesado = componer_interesado(
            del_indice.get(r["origen"] or "", ""),
            del_indice.get(r["destino"] or "", ""),
            linea,
            del_indice.get(linea, ""),
        )
        interlocutor = componer_interlocutor(
            r["origen"] or "", r["destino"] or "", linea, r["direccion"] or "",
            todos,
        )
        if interesado != (r["interesado"] or "") or interlocutor != (
            r["interlocutor"] or ""
        ):
            con.execute(
                "UPDATE Registro SET interesado = ?, interlocutor = ? WHERE id = ?",
                (interesado, interlocutor, r["id"]),
            )
            cambiados += 1
    return cambiados


# Nombre anterior: hubo un tiempo en que solo se recomponía Interesado.
recalcular_interesados = recalcular_nombres


def completar_nombres_faltantes(con: sqlite3.Connection, caso_id: int) -> int:
    """Rellena Interlocutor en las causas importadas antes de que existiera.

    Se llama al abrir una causa. La guarda importa: recalcular es recorrer
    todos los registros y el analista abre y cierra causas todo el día, así que
    solo corre cuando hay algo efectivamente sin completar —o sea, una vez por
    causa vieja y nunca más—.
    """
    faltan = con.execute(
        "SELECT 1 FROM Registro WHERE caso_id = ? AND "
        "(interlocutor IS NULL OR interlocutor = '') LIMIT 1",
        (caso_id,),
    ).fetchone()
    if faltan is None:
        return 0
    cambiados = recalcular_nombres(con, caso_id)
    con.commit()
    return cambiados


# ------------------------- Memoria corresponde_a ---------------------------
def buscar_corresponde_a(
    con: sqlite3.Connection, caso_id: int, numero_normalizado: str
) -> str:
    """Busca el 'corresponde a' primero por caso, luego global; '' si no hay."""
    if not numero_normalizado:
        return ""
    fila = con.execute(
        "SELECT nombre FROM AbonadoConocidoPorCaso WHERE caso_id = ? AND numero_normalizado = ?",
        (caso_id, numero_normalizado),
    ).fetchone()
    if fila and fila["nombre"]:
        return fila["nombre"]
    fila = con.execute(
        "SELECT nombre FROM AbonadoConocidoGlobal WHERE numero_normalizado = ?",
        (numero_normalizado,),
    ).fetchone()
    if fila and fila["nombre"]:
        return fila["nombre"]
    return ""


def guardar_corresponde_a(
    con: sqlite3.Connection,
    caso_id: int,
    numero_normalizado: str,
    nombre: str,
    alcance: str = "caso",
) -> None:
    """Upsert de memoria 'corresponde a' por caso o global (no reescribe el pasado)."""
    if alcance == "global":
        con.execute(
            """
            INSERT INTO AbonadoConocidoGlobal (numero_normalizado, nombre, fecha_actualizacion)
            VALUES (?, ?, datetime('now','localtime'))
            ON CONFLICT(numero_normalizado)
            DO UPDATE SET nombre = excluded.nombre,
                          fecha_actualizacion = excluded.fecha_actualizacion
            """,
            (numero_normalizado, nombre),
        )
    else:
        con.execute(
            """
            INSERT INTO AbonadoConocidoPorCaso (caso_id, numero_normalizado, nombre, fecha_actualizacion)
            VALUES (?, ?, ?, datetime('now','localtime'))
            ON CONFLICT(caso_id, numero_normalizado)
            DO UPDATE SET nombre = excluded.nombre,
                          fecha_actualizacion = excluded.fecha_actualizacion
            """,
            (caso_id, numero_normalizado, nombre),
        )
    con.commit()


def listar_memoria_corresponde(
    con: sqlite3.Connection, caso_id: int | None
) -> list[sqlite3.Row]:
    """Memoria de 'corresponde a': del caso si caso_id, global si None."""
    if caso_id is None:
        return con.execute(
            "SELECT * FROM AbonadoConocidoGlobal ORDER BY nombre, numero_normalizado"
        ).fetchall()
    return con.execute(
        "SELECT * FROM AbonadoConocidoPorCaso WHERE caso_id = ? "
        "ORDER BY nombre, numero_normalizado",
        (caso_id,),
    ).fetchall()


def borrar_memoria_corresponde(
    con: sqlite3.Connection, memoria_id: int, alcance: str
) -> None:
    tabla = "AbonadoConocidoGlobal" if alcance == "global" else "AbonadoConocidoPorCaso"
    con.execute(f"DELETE FROM {tabla} WHERE id = ?", (memoria_id,))


def actualizar_memoria_corresponde(
    con: sqlite3.Connection, memoria_id: int, alcance: str,
    numero: str, nombre: str,
) -> None:
    """Corrige una entrada de memoria ya existente, sin cambiarla de lugar.

    `guardar_corresponde_a` no sirve para esto: hace upsert por número, así que
    corregir un número mal tipeado dejaría la entrada vieja en su lugar y
    crearía una segunda al lado.

    El número es la clave de la entrada. Si el corregido ya lo tiene otra, se
    levanta ValueError en vez de pisarla: son dos identificaciones distintas y
    cuál sobrevive no lo puede decidir la pantalla sola.
    """
    numero = (numero or "").strip()
    nombre = (nombre or "").strip()
    if not numero:
        raise ValueError("La entrada necesita un número.")
    if not nombre:
        raise ValueError("La entrada necesita un nombre. Para sacarla, usá «Quitar».")

    tabla = "AbonadoConocidoGlobal" if alcance == "global" else "AbonadoConocidoPorCaso"
    fila = con.execute(
        f"SELECT * FROM {tabla} WHERE id = ?", (memoria_id,)
    ).fetchone()
    if fila is None:
        raise ValueError("La entrada ya no está en la memoria.")

    if numero != fila["numero_normalizado"]:
        ambito = (
            "" if alcance == "global" else " AND caso_id = ?"
        )
        params: tuple = (
            (numero, memoria_id) if alcance == "global"
            else (numero, memoria_id, fila["caso_id"])
        )
        choque = con.execute(
            f"SELECT nombre FROM {tabla} WHERE numero_normalizado = ? "
            f"AND id <> ?{ambito}",
            params,
        ).fetchone()
        if choque is not None:
            raise ValueError(
                f"El número {numero} ya está en esta memoria, como "
                f"«{choque['nombre']}»."
            )

    con.execute(
        f"UPDATE {tabla} SET numero_normalizado = ?, nombre = ?, "
        "fecha_actualizacion = datetime('now','localtime') WHERE id = ?",
        (numero, nombre, memoria_id),
    )


def vaciar_caso(
    con: sqlite3.Connection, caso_id: int, usuario: str | None = None
) -> dict[str, int]:
    """Borra todos los datos importados del caso (registros, abonados, avisos,
    lotes e historial de importación) dejándolo listo para una carga nueva.

    Conserva el caso en sí, sus notas y la memoria de 'corresponde a'.
    Devuelve un dict con la cantidad de filas borradas por tabla.
    """
    borrados: dict[str, int] = {}
    for tabla in (
        "Registro",
        "AvisoValidacion",
        "HistorialImportacion",
        "LoteExportacion",
        "Abonado",
        "EventoClave",
    ):
        cur = con.execute(f"DELETE FROM {tabla} WHERE caso_id = ?", (caso_id,))
        borrados[tabla] = cur.rowcount
    log_auditoria(
        con,
        "vacio_caso",
        f"Caso vaciado: {borrados['Registro']} registros, "
        f"{borrados['Abonado']} abonados eliminados",
        caso_id,
        usuario,
    )
    con.commit()
    return borrados


# ------------------------------ Registros ----------------------------------
def guardar_audio_alternativo(
    con: sqlite3.Connection, caso_id: int, clave_dedup: str, archivo: str
) -> bool:
    """Anota la segunda grabación de una comunicación ya importada.

    Cuando las dos líneas de una llamada están intervenidas, la prestadora
    entrega la misma comunicación dos veces, con dos archivos de audio
    distintos. La deduplicación guarda una sola fila —que es lo correcto, es
    una sola comunicación— pero antes descartaba el segundo audio sin dejar
    rastro, y cuál sobrevivía dependía del orden en que se escanearan las
    carpetas. Muchas veces una de las dos capturas se escucha mucho mejor.
    """
    fila = con.execute(
        "SELECT id, archivo_audio, audio_alternativo FROM Registro "
        "WHERE caso_id = ? AND clave_dedup = ?",
        (caso_id, clave_dedup),
    ).fetchone()
    if fila is None or not archivo:
        return False
    if archivo in (fila["archivo_audio"] or "", fila["audio_alternativo"] or ""):
        return False
    con.execute(
        "UPDATE Registro SET audio_alternativo = ? WHERE id = ?",
        (archivo, fila["id"]),
    )
    return True


def borrar_registros(
    con: sqlite3.Connection,
    caso_id: int,
    registro_ids: Iterable[int],
    usuario: str | None = None,
) -> int:
    """Borra las comunicaciones indicadas. Devuelve cuántas se eliminaron.

    Es para deshacer una carga equivocada —el mismo día importado dos veces
    desde carpetas distintas, una entrega que no correspondía a la causa—, no
    para depurar material que molesta. Por eso el log de auditoría no guarda
    solo el número: guarda de cada comunicación su orden, sus dos abonados y su
    fecha, que es lo mínimo para reconstruir qué se sacó y poder volver a
    importarlo si hizo falta.

    Los archivos de audio en disco no se tocan.
    """
    ids = [int(i) for i in registro_ids]
    if not ids:
        return 0

    marcadores = ",".join("?" for _ in ids)
    filas = con.execute(
        f"SELECT orden, origen, destino, fecha_inicio_texto, archivo_audio "
        f"FROM Registro WHERE caso_id = ? AND id IN ({marcadores})",
        (caso_id, *ids),
    ).fetchall()
    if not filas:
        return 0

    detalle = "; ".join(
        f"#{f['orden']} {f['origen']}->{f['destino']} {f['fecha_inicio_texto']}"
        + (f" [{f['archivo_audio']}]" if f["archivo_audio"] else "")
        for f in filas
    )
    cur = con.execute(
        f"DELETE FROM Registro WHERE caso_id = ? AND id IN ({marcadores})",
        (caso_id, *ids),
    )
    log_auditoria(
        con,
        "borro_registros",
        f"{cur.rowcount} comunicaciones eliminadas: {detalle}",
        caso_id,
        usuario,
    )
    con.commit()
    return cur.rowcount


def borrar_caso(
    con: sqlite3.Connection, caso_id: int, usuario: str | None = None
) -> dict[str, int]:
    """Elimina la causa entera: registros, abonados, avisos, lotes y memoria.

    A diferencia de `vaciar_caso`, que deja la causa creada y lista para una
    carga nueva, esto la saca del sistema. Las claves foráneas del esquema están
    en CASCADE, así que basta con borrar la fila de Caso.

    Lo único que sobrevive a propósito es el log de auditoría: su `caso_id` está
    en SET NULL, y la línea que deja esta función queda como constancia de que
    la causa existió y de quién la borró. Un expediente en el que se pueda hacer
    desaparecer material sin dejar rastro no sirve como prueba.
    """
    conteos = {
        tabla: con.execute(
            f"SELECT COUNT(*) AS n FROM {tabla} WHERE caso_id = ?", (caso_id,)
        ).fetchone()["n"]
        for tabla in ("Registro", "Abonado", "AvisoValidacion", "LoteExportacion")
    }
    fila = con.execute("SELECT nombre FROM Caso WHERE id = ?", (caso_id,)).fetchone()
    nombre = fila["nombre"] if fila else f"#{caso_id}"

    con.execute("DELETE FROM Caso WHERE id = ?", (caso_id,))
    log_auditoria(
        con,
        "borro_caso",
        f"Causa «{nombre}» (#{caso_id}) eliminada: "
        f"{conteos['Registro']} registros, {conteos['Abonado']} abonados, "
        f"{conteos['AvisoValidacion']} avisos, {conteos['LoteExportacion']} lotes",
        None,
        usuario,
    )
    con.commit()
    return conteos


def claves_dedup_existentes(con: sqlite3.Connection, caso_id: int) -> set[str]:
    """Conjunto de clave_dedup ya presentes en el caso (para el escaneo previo)."""
    return {
        r["clave_dedup"]
        for r in con.execute(
            "SELECT clave_dedup FROM Registro WHERE caso_id = ? AND clave_dedup IS NOT NULL",
            (caso_id,),
        )
    }


def siguiente_orden(con: sqlite3.Connection, caso_id: int) -> int:
    fila = con.execute(
        "SELECT COALESCE(MAX(orden), 0) AS m FROM Registro WHERE caso_id = ?",
        (caso_id,),
    ).fetchone()
    return int(fila["m"]) + 1


def insertar_registro(
    con: sqlite3.Connection, caso_id: int, reg: RegistroParseado, orden: int
) -> int:
    """Inserta un RegistroParseado. Devuelve el id, o -1 si ya existía (dedup)."""
    valores = {
        "caso_id": caso_id,
        "orden": orden,
        "interesado": reg.interesado,
        "interlocutor": reg.interlocutor,
        "tipo": reg.tipo,
        "cd": reg.cd,
        "direccion": reg.direccion,
        "origen": reg.origen,
        "destino": reg.destino,
        "origen_crudo": reg.origen_crudo,
        "destino_crudo": reg.destino_crudo,
        "corresponde_a": reg.corresponde_a,
        "fecha_inicio_texto": reg.fecha_inicio_texto,
        "fecha_fin_texto": reg.fecha_fin_texto,
        "fecha_inicio_dt": reg.fecha_inicio_dt.isoformat(sep=" ")
        if reg.fecha_inicio_dt
        else None,
        "antenas": reg.antenas,
        "tecnologia": reg.tecnologia,
        "calle": reg.calle,
        "numero_calle": reg.numero_calle,
        "localidad": reg.localidad,
        "provincia": reg.provincia,
        "latitud": reg.latitud,
        "longitud": reg.longitud,
        "azimuth": reg.azimuth,
        "radio": reg.radio,
        "contexto": reg.contexto,
        "transcripcion": reg.transcripcion,
        "archivo_audio": reg.archivo_audio,
        "archivo_txt": reg.archivo_txt,
        "estado": reg.estado.value,
        "clave_dedup": reg.clave_dedup,
    }
    placeholders = ", ".join(["?"] * len(_COLS_REGISTRO))
    columnas = ", ".join(_COLS_REGISTRO)
    try:
        cur = con.execute(
            f"INSERT INTO Registro ({columnas}) VALUES ({placeholders})",
            tuple(valores[c] for c in _COLS_REGISTRO),
        )
        return int(cur.lastrowid)
    except sqlite3.IntegrityError:
        return -1  # UNIQUE(caso_id, clave_dedup): ya existe


def listar_registros(con: sqlite3.Connection, caso_id: int) -> list[sqlite3.Row]:
    # El color de la fila = color del abonado INTERVENIDO de la comunicación
    # (la línea pinchada), no el del interlocutor. Se prioriza intervenido=1 y,
    # a igualdad, el abonado más antiguo, para que el color sea determinístico
    # y coherente con la "marca de colores" del libro estándar.
    # Se devuelve además el número de esa línea y si está efectivamente marcada
    # como intervenida: el color por sí solo no dice a quién señala, y cuando
    # ningún abonado del caso está marcado el desempate elige igual a uno, que
    # no sería correcto presentar como "la línea intervenida".
    return con.execute(
        """
        SELECT r.*, (
            SELECT a.color_hex
            FROM Abonado a
            WHERE a.caso_id = r.caso_id
              AND a.numero_normalizado IN (r.origen, r.destino)
            ORDER BY a.intervenido DESC, a.id
            LIMIT 1
        ) AS color_hex, (
            SELECT a.numero_normalizado
            FROM Abonado a
            WHERE a.caso_id = r.caso_id
              AND a.numero_normalizado IN (r.origen, r.destino)
            ORDER BY a.intervenido DESC, a.id
            LIMIT 1
        ) AS linea_color, (
            SELECT a.intervenido
            FROM Abonado a
            WHERE a.caso_id = r.caso_id
              AND a.numero_normalizado IN (r.origen, r.destino)
            ORDER BY a.intervenido DESC, a.id
            LIMIT 1
        ) AS linea_intervenida
        FROM Registro r
        WHERE r.caso_id = ?
        ORDER BY r.orden
        """,
        (caso_id,),
    ).fetchall()


def obtener_registro(con: sqlite3.Connection, registro_id: int) -> sqlite3.Row | None:
    return con.execute(
        "SELECT * FROM Registro WHERE id = ?", (registro_id,)
    ).fetchone()


def actualizar_campo_registro(
    con: sqlite3.Connection, registro_id: int, campo: str, valor: object
) -> None:
    """Actualiza una sola columna de un registro. El campo se valida en la capa
    de servicio (lista blanca); aquí se asume seguro."""
    con.execute(
        f"UPDATE Registro SET {campo} = ? WHERE id = ?",  # noqa: S608 (campo validado en servicio)
        (valor, registro_id),
    )


def registrar_historial_cambio(
    con: sqlite3.Connection,
    registro_id: int,
    campo: str,
    valor_anterior: object,
    valor_nuevo: object,
    origen_cambio: str = "manual",
    usuario: str | None = None,
    lote_exportacion_id: int | None = None,
) -> None:
    usuario = sesion.o_analista(usuario)
    con.execute(
        """
        INSERT INTO HistorialCambio
            (registro_id, campo, valor_anterior, valor_nuevo, origen_cambio,
             usuario, lote_exportacion_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            registro_id,
            campo,
            None if valor_anterior is None else str(valor_anterior),
            None if valor_nuevo is None else str(valor_nuevo),
            origen_cambio,
            usuario,
            lote_exportacion_id,
        ),
    )


def historial_de_registro(
    con: sqlite3.Connection, registro_id: int
) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT * FROM HistorialCambio WHERE registro_id = ? ORDER BY fecha DESC, id DESC",
        (registro_id,),
    ).fetchall()


# ------------------------------ Contextos ----------------------------------
def listar_contextos(con: sqlite3.Connection, caso_id: int) -> list[str]:
    """Etiquetas de contexto disponibles para el caso (globales + propias)."""
    filas = con.execute(
        """
        SELECT etiqueta FROM CatalogoContexto
        WHERE caso_id IS NULL OR caso_id = ?
        ORDER BY (caso_id IS NULL) DESC, etiqueta
        """,
        (caso_id,),
    )
    # Preservar orden y unicidad.
    vistos: dict[str, None] = {}
    for r in filas:
        vistos.setdefault(r["etiqueta"], None)
    return list(vistos.keys())


# --------------------- Lotes de exportación / informes ---------------------
def crear_lote_exportacion(
    con: sqlite3.Connection, caso_id: int, tipo: str, usuario: str | None = None
) -> int:
    usuario = sesion.o_analista(usuario)
    cur = con.execute(
        "INSERT INTO LoteExportacion (caso_id, tipo, usuario) VALUES (?, ?, ?)",
        (caso_id, tipo, usuario),
    )
    return int(cur.lastrowid)


def listar_lotes_exportacion(
    con: sqlite3.Connection, caso_id: int
) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT * FROM LoteExportacion WHERE caso_id = ? ORDER BY fecha DESC, id DESC",
        (caso_id,),
    ).fetchall()


# Columnas que un lote puede revertir: las que alguien edita a mano más la
# marca que pone el propio exportador. Se escribe acá y no se importa de
# `edicion` porque este módulo es la capa de abajo: importar hacia arriba
# ataría la base a un servicio.
_CAMPOS_REVERTIBLES = frozenset(
    {"corresponde_a", "contexto", "nivel_interes", "transcripcion", "informada"}
)


def deshacer_lote_exportacion(
    con: sqlite3.Connection, lote_id: int, usuario: str | None = None
) -> int:
    """Revierte todos los cambios del lote y lo marca como deshecho.

    Devuelve la cantidad de registros revertidos.
    """
    cambios = con.execute(
        "SELECT * FROM HistorialCambio WHERE lote_exportacion_id = ? ORDER BY id",
        (lote_id,),
    ).fetchall()

    revertidos = 0
    for cambio in cambios:
        # El nombre de la columna viaja al SQL, así que se valida acá aunque
        # todo lo que escribe el historial use literales o pase por la lista
        # blanca de `edicion`. Un campo leído de la base no es una constante
        # del programa: entre que se escribió y que se revierte hay un archivo
        # en disco, y un informe judicial no es el lugar para confiar en eso.
        campo = cambio["campo"]
        if campo not in _CAMPOS_REVERTIBLES:
            continue
        con.execute(
            f"UPDATE Registro SET {campo} = ? WHERE id = ?",
            (cambio["valor_anterior"], cambio["registro_id"]),
        )
        revertidos += 1

    # El lote deja de existir a los efectos del expediente: las comunicaciones
    # que lo citaban no pueden seguir apuntando a un informe que se descartó.
    con.execute(
        "UPDATE Registro SET lote_exportacion_id = NULL WHERE lote_exportacion_id = ?",
        (lote_id,),
    )
    con.execute(
        """
        UPDATE LoteExportacion
        SET deshecho = 1, fecha_deshecho = datetime('now','localtime')
        WHERE id = ?
        """,
        (lote_id,),
    )
    log_auditoria(con, "deshizo_exportacion", f"Lote #{lote_id} ({revertidos} cambios revertidos)", usuario=usuario)
    con.commit()
    return revertidos


# ------------------------- Avisos / historial ------------------------------
def crear_aviso(
    con: sqlite3.Connection,
    caso_id: int,
    tipo: str,
    descripcion: str,
    sugerencia: str,
    registro_id: int | None = None,
    importacion_id: int | None = None,
) -> None:
    con.execute(
        """
        INSERT INTO AvisoValidacion
            (caso_id, registro_id, importacion_id, tipo, descripcion, sugerencia)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (caso_id, registro_id, importacion_id, tipo, descripcion, sugerencia),
    )


def contar_avisos_pendientes(con: sqlite3.Connection, caso_id: int) -> int:
    return con.execute(
        "SELECT COUNT(*) AS n FROM AvisoValidacion WHERE caso_id = ? AND resuelto = 0",
        (caso_id,),
    ).fetchone()["n"]


def listar_avisos(
    con: sqlite3.Connection,
    caso_id: int,
    tipo: str | None = None,
    estado: str = "pendientes",
) -> list[sqlite3.Row]:
    """Lista avisos del caso. `estado` ∈ {'pendientes','resueltos','todos'}.

    Incluye el orden del registro asociado (si lo hay) para enlazarlo en la UI.
    """
    where = ["a.caso_id = ?"]
    params: list[object] = [caso_id]
    if estado == "pendientes":
        where.append("a.resuelto = 0")
    elif estado == "resueltos":
        where.append("a.resuelto = 1")
    if tipo:
        where.append("a.tipo = ?")
        params.append(tipo)
    return con.execute(
        f"""
        SELECT a.*, r.orden AS registro_orden
        FROM AvisoValidacion a
        LEFT JOIN Registro r ON r.id = a.registro_id
        WHERE {' AND '.join(where)}
        ORDER BY a.resuelto, a.fecha_creacion DESC, a.id DESC
        """,
        params,
    ).fetchall()


def contar_avisos_por_tipo(
    con: sqlite3.Connection, caso_id: int, solo_pendientes: bool = True
) -> dict[str, int]:
    """Devuelve {tipo: cantidad} de avisos del caso."""
    cond = "AND resuelto = 0" if solo_pendientes else ""
    filas = con.execute(
        f"SELECT tipo, COUNT(*) AS n FROM AvisoValidacion "
        f"WHERE caso_id = ? {cond} GROUP BY tipo",
        (caso_id,),
    )
    return {r["tipo"]: r["n"] for r in filas}


def marcar_aviso_resuelto(
    con: sqlite3.Connection, aviso_id: int, usuario: str | None = None,
    resuelto: bool = True,
) -> None:
    usuario = sesion.o_analista(usuario)
    con.execute(
        """
        UPDATE AvisoValidacion
        SET resuelto = ?,
            fecha_resolucion = CASE WHEN ? THEN datetime('now','localtime') ELSE NULL END,
            resuelto_por = CASE WHEN ? THEN ? ELSE NULL END
        WHERE id = ?
        """,
        (1 if resuelto else 0, resuelto, resuelto, usuario, aviso_id),
    )
    con.commit()


# --------------------------- audio / escucha -------------------------------
def marcar_escuchado(
    con: sqlite3.Connection, registro_id: int, escuchado: bool = True
) -> None:
    con.execute(
        "UPDATE Registro SET escuchado = ? WHERE id = ?",
        (1 if escuchado else 0, registro_id),
    )


def guardar_segmentos_transcripcion(
    con: sqlite3.Connection, registro_id: int, segmentos: list[dict] | None
) -> None:
    """Guarda (como JSON) los tiempos de cada frase de la transcripción."""
    con.execute(
        "UPDATE Registro SET transcripcion_segmentos = ? WHERE id = ?",
        (json.dumps(segmentos, ensure_ascii=False) if segmentos else None, registro_id),
    )


def segmentos_de_registro(registro: sqlite3.Row | str | None) -> list[dict]:
    """Devuelve los segmentos de un registro, o [] si no tiene o están rotos.

    Acepta la fila entera o directamente el texto JSON. Un JSON inválido no
    puede voltear el panel de detalle: se trata como "no hay segmentos" y el
    registro cae en el editor de texto libre.
    """
    if registro is None:
        return []
    if isinstance(registro, str):
        crudo = registro
    elif "transcripcion_segmentos" in registro.keys():
        crudo = registro["transcripcion_segmentos"]
    else:
        # La fila vino de una consulta con columnas explícitas.
        return []
    if not crudo:
        return []
    try:
        datos = json.loads(crudo)
    except (ValueError, TypeError):
        return []
    if not isinstance(datos, list):
        return []
    return [s for s in datos if isinstance(s, dict) and s.get("texto")]


def mandar_a_desgrabar(
    con: sqlite3.Connection, registro_ids: Iterable[int], mandar: bool = True
) -> int:
    """Pone (o saca) comunicaciones en la mesa de trabajo. Devuelve cuántas.

    Es lo que permite trabajar un SMS o un intento de comunicación sin pasar
    por Whisper: no hay audio que transcribir, pero sí hay algo que dejar
    escrito —qué significa esa comunicación— y eso se hace en Desgrabar.

    Mandar algo ya cerrado lo REABRE, y al reabrirlo se borra la constancia de
    quién lo dio por desgrabado y cuándo: esa firma decía que el trabajo estaba
    terminado, y vuelve a no estarlo.
    """
    ids = [int(i) for i in registro_ids]
    if not ids:
        return 0
    marcadores = ",".join("?" * len(ids))
    if mandar:
        con.execute(
            f"UPDATE Registro SET en_desgrabar = 1, transcripcion_revisada = 0, "
            f"transcripcion_revisada_en = NULL, transcripcion_revisada_por = NULL "
            f"WHERE id IN ({marcadores})",
            ids,
        )
    else:
        con.execute(
            f"UPDATE Registro SET en_desgrabar = 0 WHERE id IN ({marcadores})",
            ids,
        )
    return len(ids)


def esta_en_desgrabar(registro: sqlite3.Row) -> bool:
    """Si fue mandada a la mesa de trabajo. Tolera bases sin la columna."""
    try:
        return bool(registro["en_desgrabar"])
    except (IndexError, KeyError):
        return False


def guardar_interpretacion(
    con: sqlite3.Connection, registro_id: int, texto: str
) -> None:
    """Lo que el analista concluye de esta comunicación.

    Se guarda vacía como NULL y no como cadena vacía: así «no escribió nada» y
    «escribió y después borró» son lo mismo, que es lo que corresponde. El
    informe pregunta si hay interpretación, no cuánto mide.
    """
    limpio = (texto or "").strip()
    con.execute(
        "UPDATE Registro SET interpretacion = ? WHERE id = ?",
        (limpio or None, registro_id),
    )


def marcar_transcripcion_revisada(
    con: sqlite3.Connection, registro_id: int, revisada: bool,
    usuario: str | None = None,
) -> None:
    """Da por desgrabada una comunicación, dejando constancia de quién y cuándo.

    La fecha no es decorativa: es lo único que después permite armar la entrega
    de una jornada («exportar lo que desgrabé hoy») sin que el analista tenga
    que acordarse de cuáles fueron. Al desmarcar se borra, porque una fecha de
    revisión sobre algo que volvió a estar pendiente miente.
    """
    if revisada:
        con.execute(
            "UPDATE Registro SET transcripcion_revisada = 1, "
            "transcripcion_revisada_en = datetime('now','localtime'), "
            "transcripcion_revisada_por = ? WHERE id = ?",
            (sesion.o_analista(usuario), registro_id),
        )
    else:
        con.execute(
            "UPDATE Registro SET transcripcion_revisada = 0, "
            "transcripcion_revisada_en = NULL, "
            "transcripcion_revisada_por = NULL WHERE id = ?",
            (registro_id,),
        )


def desgrabadas_sin_informar(
    con: sqlite3.Connection, caso_id: int, *,
    desde: str | None = None, analista: str | None = None,
) -> list[sqlite3.Row]:
    """Lo desgrabado que todavía no salió en ningún informe.

    Es la pila de trabajo terminado y no entregado, que es lo que el analista
    quiere sacar de una sola vez. `desde` la acota por fecha (para «lo de hoy»)
    y `analista` a un firmante, para cuando dos personas comparten la causa.

    Las que ya se informaron quedan afuera a propósito: volver a mandarlas
    duplicaría en el expediente algo que el juzgado ya tiene.
    """
    condiciones = [
        "caso_id = ?", "tipo = 'llamada'", "transcripcion_revisada = 1",
        "informada = 0", "TRIM(COALESCE(transcripcion, '')) <> ''",
    ]
    parametros: list[object] = [caso_id]
    if desde:
        # Las desgrabadas antes de que existiera la columna no tienen fecha;
        # en un recorte por fecha no se pueden afirmar, así que no entran.
        condiciones.append("transcripcion_revisada_en >= ?")
        parametros.append(desde)
    if analista:
        condiciones.append("transcripcion_revisada_por = ?")
        parametros.append(analista)
    return con.execute(
        "SELECT * FROM Registro WHERE " + " AND ".join(condiciones)
        + " ORDER BY orden",
        parametros,
    ).fetchall()


def comienzo_de_hoy() -> str:
    """Medianoche local, en el formato en que SQLite guarda las fechas."""
    return datetime.now().strftime("%Y-%m-%d 00:00:00")


def contar_transcripciones_sin_revisar(
    con: sqlite3.Connection, caso_id: int
) -> int:
    """Registros con transcripción cargada pero sin revisar por el analista.

    Solo cuentan las llamadas (los SMS traen texto de la prestadora, no de IA)."""
    return con.execute(
        """
        SELECT COUNT(*) AS n FROM Registro
        WHERE caso_id = ? AND tipo = 'llamada'
          AND transcripcion IS NOT NULL AND TRIM(transcripcion) != ''
          AND transcripcion_revisada = 0
        """,
        (caso_id,),
    ).fetchone()["n"]


def guardar_duracion(
    con: sqlite3.Connection, registro_id: int, segundos: float
) -> None:
    con.execute(
        "UPDATE Registro SET duracion_seg = ? WHERE id = ?",
        (round(segundos, 2), registro_id),
    )


def progreso_escucha(con: sqlite3.Connection, caso_id: int) -> dict[str, float]:
    """Progreso de escucha del caso: solo cuentan los registros con audio."""
    fila = con.execute(
        """
        SELECT COUNT(*) AS total,
               COALESCE(SUM(escuchado), 0) AS escuchados,
               COALESCE(SUM(duracion_seg), 0) AS segundos
        FROM Registro
        WHERE caso_id = ? AND estado != 'audio_faltante'
              AND archivo_audio IS NOT NULL AND archivo_audio != ''
        """,
        (caso_id,),
    ).fetchone()
    return {
        "total": fila["total"],
        "escuchados": fila["escuchados"],
        "segundos": fila["segundos"],
    }


def guardar_cd(
    con: sqlite3.Connection,
    caso_id: int,
    numero: str,
    identificador: str,
    fecha: str = "",
    abonados_declarados: Iterable[str] = (),
    ruta: str = "",
) -> int:
    """Alta (o actualización) de una entrega. Devuelve su id interno.

    Se reimporta la misma carpeta a menudo; la clave natural es
    (caso, número, identificador), así que la segunda vez se actualizan los
    datos en lugar de duplicar la entrega. La fecha de recepción NO se toca:
    la carga el analista y no viene en ningún archivo.
    """
    con.execute(
        """
        INSERT INTO CD (caso_id, numero, identificador, fecha,
                        abonados_declarados, ruta)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(caso_id, numero, identificador) DO UPDATE SET
            fecha = excluded.fecha,
            abonados_declarados = excluded.abonados_declarados,
            ruta = excluded.ruta
        """,
        (
            caso_id, numero, identificador, fecha,
            json.dumps(list(abonados_declarados), ensure_ascii=False),
            ruta,
        ),
    )
    fila = con.execute(
        "SELECT id FROM CD WHERE caso_id = ? AND numero = ? AND identificador = ?",
        (caso_id, numero, identificador),
    ).fetchone()
    return int(fila["id"]) if fila else -1


def listar_cds(con: sqlite3.Connection, caso_id: int) -> list[sqlite3.Row]:
    """Entregas de la causa, ordenadas por número de CD (numérico, no de texto)."""
    return con.execute(
        """
        SELECT * FROM CD WHERE caso_id = ?
        ORDER BY CAST(NULLIF(numero, '') AS INTEGER), numero, identificador
        """,
        (caso_id,),
    ).fetchall()


def abonados_declarados_de_cd(cd: sqlite3.Row | None) -> list[str]:
    """Lista de líneas intervenidas de una entrega, o [] si el JSON está roto."""
    if cd is None or "abonados_declarados" not in cd.keys():
        return []
    try:
        datos = json.loads(cd["abonados_declarados"] or "[]")
    except (ValueError, TypeError):
        return []
    return [n for n in datos if isinstance(n, str)] if isinstance(datos, list) else []


def set_fecha_recepcion_cd(
    con: sqlite3.Connection, cd_fila_id: int, fecha: str
) -> None:
    """Fecha en que el Magistrado suministró el CD (va en el encabezado)."""
    con.execute("UPDATE CD SET fecha_recepcion = ? WHERE id = ?", (fecha, cd_fila_id))


def resumen_por_cd(con: sqlite3.Connection, caso_id: int) -> list[dict]:
    """Una fila por entrega, con lo que hace falta para decidir por dónde seguir.

    Junta la entrega declarada (número, identificador, fecha, líneas
    intervenidas de ESE día) con lo que se hizo sobre su material. Es la vista
    que faltaba: el CD es la unidad en que llega el material y en que se
    informa, pero hasta ahora no había ningún lugar donde verlos todos.

    Las comunicaciones que no cayeron en ninguna entrega registrada se listan
    al final bajo un CD sin número, para que no desaparezcan de la cuenta.
    """
    por_cd = {
        (r["cd"] or ""): r
        for r in con.execute(
            """
            SELECT cd,
                   COUNT(*)                                    AS registros,
                   COALESCE(SUM(escuchado), 0)                 AS escuchadas,
                   COALESCE(SUM(nivel_interes != 'ninguno'), 0) AS interes,
                   COALESCE(SUM(estado != 'completo'), 0)      AS incompletos,
                   MIN(NULLIF(fecha_inicio_dt, ''))            AS desde,
                   MAX(NULLIF(fecha_inicio_dt, ''))            AS hasta
            FROM Registro WHERE caso_id = ? GROUP BY cd
            """,
            (caso_id,),
        )
    }

    filas: list[dict] = []
    vistos: set[str] = set()
    for cd in listar_cds(con, caso_id):
        numero = cd["numero"] or ""
        vistos.add(numero)
        datos = por_cd.get(numero)
        filas.append({
            "id": cd["id"],
            "numero": numero,
            "identificador": cd["identificador"] or "",
            "fecha": cd["fecha"] or "",
            "declarados": abonados_declarados_de_cd(cd),
            "registros": datos["registros"] if datos else 0,
            "escuchadas": datos["escuchadas"] if datos else 0,
            "interes": datos["interes"] if datos else 0,
            "incompletos": datos["incompletos"] if datos else 0,
        })

    for numero, datos in sorted(por_cd.items()):
        if numero in vistos:
            continue
        filas.append({
            "id": None,
            "numero": numero,
            "identificador": "",
            "fecha": "",
            "declarados": [],
            "registros": datos["registros"],
            "escuchadas": datos["escuchadas"],
            "interes": datos["interes"],
            "incompletos": datos["incompletos"],
        })
    return filas


def vocabulario_causa(con: sqlite3.Connection, caso_id: int) -> str:
    """Nombres y lugares propios de la causa, para orientar la transcripción.

    Son justo las palabras que el modelo no puede adivinar —apellidos, apodos,
    topónimos del norte— y las que más importan en un informe. Se arman solas
    con lo que el analista ya cargó: los nombres del Índice de abonados, la
    memoria de "corresponde a" y las localidades que traen las antenas.
    """
    vistos: dict[str, None] = {}

    def agregar(valor) -> None:
        texto = (valor or "").strip()
        if texto and texto.upper() != "NO IDENTIFICADO":
            vistos.setdefault(texto, None)

    for fila in con.execute(
        "SELECT pertenece_a FROM Abonado WHERE caso_id = ?", (caso_id,)
    ):
        agregar(fila["pertenece_a"])
    for fila in con.execute(
        "SELECT DISTINCT corresponde_a FROM Registro WHERE caso_id = ?", (caso_id,)
    ):
        agregar(fila["corresponde_a"])
    for fila in con.execute(
        "SELECT DISTINCT localidad FROM Registro WHERE caso_id = ?", (caso_id,)
    ):
        agregar(fila["localidad"])
    return ", ".join(vistos)


def resumen_caso(con: sqlite3.Connection, caso_id: int) -> dict:
    """Foto del estado del caso, para responder «¿en qué estaba?» de un vistazo.

    Junta en una sola consulta por tema lo que hasta ahora había que deducir
    filtrando la Tabla TOTAL: cuánto falta escuchar, qué quedó marcado, qué
    archivos faltan, hasta dónde llega el material y cuándo se importó por
    última vez.
    """
    reg = con.execute(
        """
        SELECT
            COUNT(*)                                                   AS total,
            COALESCE(SUM(tipo = 'sms'), 0)                             AS sms,
            COALESCE(SUM(estado = 'completo'), 0)                      AS completos,
            COALESCE(SUM(estado = 'audio_faltante'), 0)                AS audio_faltante,
            COALESCE(SUM(estado = 'transcripcion_faltante'), 0)        AS txt_faltante,
            COALESCE(SUM(nivel_interes != 'ninguno'), 0)               AS de_interes,
            COALESCE(SUM(informada), 0)                                AS informadas,
            COALESCE(SUM(TRIM(COALESCE(transcripcion, '')) != ''), 0)  AS con_transcripcion,
            MIN(NULLIF(fecha_inicio_dt, ''))                           AS desde,
            MAX(NULLIF(fecha_inicio_dt, ''))                           AS hasta
        FROM Registro WHERE caso_id = ?
        """,
        (caso_id,),
    ).fetchone()

    cds = con.execute(
        "SELECT COUNT(DISTINCT cd) AS n FROM Registro "
        "WHERE caso_id = ? AND cd IS NOT NULL AND cd != ''",
        (caso_id,),
    ).fetchone()["n"]

    ultima = con.execute(
        "SELECT fecha, ruta_usada, archivos_nuevos FROM HistorialImportacion "
        "WHERE caso_id = ? ORDER BY id DESC LIMIT 1",
        (caso_id,),
    ).fetchone()

    progreso = progreso_escucha(con, caso_id)
    return {
        "registros": reg["total"],
        "sms": reg["sms"],
        "completos": reg["completos"],
        "audio_faltante": reg["audio_faltante"],
        "transcripcion_faltante": reg["txt_faltante"],
        "de_interes": reg["de_interes"],
        "informadas": reg["informadas"],
        "con_transcripcion": reg["con_transcripcion"],
        "sin_revisar": contar_transcripciones_sin_revisar(con, caso_id),
        "desde": reg["desde"],
        "hasta": reg["hasta"],
        "cds": cds,
        "abonados": len(listar_abonados_por_alta(con, caso_id)),
        "intervenidos": contar_abonados_intervenidos(con, caso_id),
        "avisos_pendientes": contar_avisos_pendientes(con, caso_id),
        "con_audio": progreso["total"],
        "escuchados": progreso["escuchados"],
        "segundos": progreso["segundos"],
        "ultima_importacion": ultima,
    }


def crear_marca_audio(
    con: sqlite3.Connection, registro_id: int, segundo: float, nota: str = ""
) -> int:
    cur = con.execute(
        "INSERT INTO MarcaAudio (registro_id, segundo, nota) VALUES (?, ?, ?)",
        (registro_id, round(segundo, 2), nota),
    )
    return int(cur.lastrowid)


def listar_marcas_audio(
    con: sqlite3.Connection, registro_id: int
) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT * FROM MarcaAudio WHERE registro_id = ? ORDER BY segundo",
        (registro_id,),
    ).fetchall()


def borrar_marca_audio(con: sqlite3.Connection, marca_id: int) -> None:
    con.execute("DELETE FROM MarcaAudio WHERE id = ?", (marca_id,))


def registro_orden_a_id(con: sqlite3.Connection, caso_id: int) -> dict[int, int]:
    """Mapa {orden: registro_id} del caso, para localizar filas desde un aviso."""
    return {
        r["orden"]: r["id"]
        for r in con.execute(
            "SELECT id, orden FROM Registro WHERE caso_id = ?", (caso_id,)
        )
    }


def registrar_importacion(
    con: sqlite3.Connection,
    caso_id: int,
    ruta: str,
    contadores: dict[str, int],
    tipo: str = "txt",
) -> int:
    cur = con.execute(
        """
        INSERT INTO HistorialImportacion
            (caso_id, ruta_usada, archivos_nuevos, archivos_existentes,
             archivos_error, archivos_audio_faltante, archivos_txt_faltante,
             tipo_importacion)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            caso_id,
            ruta,
            contadores.get("nuevos", 0),
            contadores.get("existentes", 0),
            contadores.get("error", 0),
            contadores.get("audio_faltante", 0),
            contadores.get("txt_faltante", 0),
            tipo,
        ),
    )
    return int(cur.lastrowid)


def log_auditoria(
    con: sqlite3.Connection,
    accion: str,
    detalle: str,
    caso_id: int | None = None,
    usuario: str | None = None,
) -> None:
    usuario = sesion.o_analista(usuario)
    con.execute(
        "INSERT INTO LogAuditoria (caso_id, accion, detalle, usuario) VALUES (?, ?, ?, ?)",
        (caso_id, accion, detalle, usuario),
    )


def limpiar_log_auditoria(
    con: sqlite3.Connection, caso_id: int | None = None
) -> int:
    """Borra entradas del log de auditoría. Si caso_id es None, borra TODO el
    log (global); si se pasa, solo las de ese caso. Devuelve cuántas borró."""
    if caso_id is None:
        cur = con.execute("DELETE FROM LogAuditoria")
    else:
        cur = con.execute("DELETE FROM LogAuditoria WHERE caso_id = ?", (caso_id,))
    con.commit()
    return cur.rowcount


def listar_log_auditoria(
    con: sqlite3.Connection,
    caso_id: int | None = None,
    accion: str | None = None,
    limite: int = 200,
) -> list[sqlite3.Row]:
    where: list[str] = []
    params: list[object] = []
    if caso_id is not None:
        where.append("l.caso_id = ?")
        params.append(caso_id)
    if accion:
        where.append("l.accion = ?")
        params.append(accion)
    cond = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(limite)
    return con.execute(
        f"""
        SELECT l.*, c.nombre AS caso_nombre
        FROM LogAuditoria l
        LEFT JOIN Caso c ON c.id = l.caso_id
        {cond}
        ORDER BY l.fecha DESC, l.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
