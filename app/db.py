"""Capa de base de datos SQLite: esquema, conexión e inicialización.

Implementa la sección 1 del pseudocódigo. El campo ORDEN de la macro original
deja de ser frágil (BUG-03): la clave real es el id autoincremental nativo de
SQLite; `orden` queda como correlativo visual.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app import config

# --------------------------------------------------------------------------
# Esquema (DDL)
# --------------------------------------------------------------------------
SCHEMA: str = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS Caso (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre          TEXT NOT NULL,
    fecha_creacion  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    notas           TEXT
);

CREATE TABLE IF NOT EXISTS HistorialImportacion (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    caso_id                 INTEGER NOT NULL REFERENCES Caso(id) ON DELETE CASCADE,
    ruta_usada              TEXT,
    fecha                   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    archivos_nuevos         INTEGER DEFAULT 0,
    archivos_existentes     INTEGER DEFAULT 0,
    archivos_error          INTEGER DEFAULT 0,
    archivos_audio_faltante INTEGER DEFAULT 0,
    archivos_txt_faltante   INTEGER DEFAULT 0,
    tipo_importacion        TEXT CHECK (tipo_importacion IN ('txt','xlsx','db'))
);

-- Una causa no recibe "un CD" sino una serie de entregas, cada una con su
-- número, su identificador, su fecha y las líneas que estaban intervenidas ese
-- día. Todo eso lo declara el DatosCausa.txt de la entrega; se guarda acá para
-- que el informe judicial no dependa de que el analista lo recuerde y lo tipee.
CREATE TABLE IF NOT EXISTS CD (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    caso_id             INTEGER NOT NULL REFERENCES Caso(id) ON DELETE CASCADE,
    numero              TEXT,      -- "4", como lo nombra el juzgado
    identificador       TEXT,      -- "700000002", el Id del CD
    fecha               TEXT,      -- fecha declarada de las comunicaciones
    fecha_recepcion     TEXT,      -- la que suministra el Magistrado
    abonados_declarados TEXT,      -- JSON con las líneas intervenidas ese día
    ruta                TEXT,
    UNIQUE(caso_id, numero, identificador)
);
CREATE INDEX IF NOT EXISTS ix_cd_caso ON CD(caso_id);

CREATE TABLE IF NOT EXISTS Abonado (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    caso_id             INTEGER NOT NULL REFERENCES Caso(id) ON DELETE CASCADE,
    numero_normalizado  TEXT NOT NULL,
    pertenece_a         TEXT,
    color_hex           TEXT,
    observaciones       TEXT,
    intervenido         INTEGER NOT NULL DEFAULT 0,
    UNIQUE(caso_id, numero_normalizado)
);
CREATE INDEX IF NOT EXISTS ix_abonado_numero
    ON Abonado(caso_id, numero_normalizado);

CREATE TABLE IF NOT EXISTS AbonadoConocidoGlobal (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_normalizado  TEXT UNIQUE NOT NULL,
    nombre              TEXT,
    fecha_actualizacion TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS AbonadoConocidoPorCaso (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    caso_id             INTEGER NOT NULL REFERENCES Caso(id) ON DELETE CASCADE,
    numero_normalizado  TEXT NOT NULL,
    nombre              TEXT,
    fecha_actualizacion TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(caso_id, numero_normalizado)
);

CREATE TABLE IF NOT EXISTS LoteExportacion (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    caso_id         INTEGER NOT NULL REFERENCES Caso(id) ON DELETE CASCADE,
    tipo            TEXT CHECK (tipo IN ('word_informe','excel','imagen_mapa','imagen_grafo')),
    fecha           TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    usuario         TEXT,
    deshecho        INTEGER NOT NULL DEFAULT 0,
    fecha_deshecho  TEXT
);

CREATE TABLE IF NOT EXISTS Registro (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    caso_id             INTEGER NOT NULL REFERENCES Caso(id) ON DELETE CASCADE,
    orden               INTEGER,
    interesado          TEXT,
    -- La otra punta: con quien hablo la linea intervenida. Se deriva de
    -- origen/destino y se recompone cuando cambia el Indice de abonados.
    interlocutor        TEXT,
    cd                  TEXT,
    direccion           TEXT,
    tipo                TEXT NOT NULL DEFAULT 'llamada'
                        CHECK (tipo IN ('llamada','sms')),
    origen              TEXT,
    destino             TEXT,
    origen_crudo        TEXT,
    destino_crudo       TEXT,
    corresponde_a       TEXT DEFAULT 'NO IDENTIFICADO',
    fecha_inicio_texto  TEXT,
    fecha_fin_texto     TEXT,
    fecha_inicio_dt     TEXT,
    antenas             TEXT,
    tecnologia          TEXT,
    calle               TEXT,
    numero_calle        TEXT,
    localidad           TEXT,
    provincia           TEXT,
    latitud             TEXT,
    longitud            TEXT,
    azimuth             TEXT,
    radio               TEXT,
    contexto            TEXT,
    transcripcion       TEXT,
    -- Tiempos de cada frase, como los devuelve Whisper: JSON
    -- [{"inicio": 0.0, "fin": 4.2, "texto": "..."}]. Es lo que
    -- permite saltar del texto al segundo exacto del audio.
    transcripcion_segmentos TEXT,
    transcripcion_revisada INTEGER NOT NULL DEFAULT 0,
    -- Cuándo y quién dio por desgrabada la comunicación. El 0/1 de arriba
    -- alcanza para saber qué falta, pero no para armar la entrega de una
    -- jornada ni para que Auditoría pueda decir quién firmó cada texto.
    transcripcion_revisada_en  TEXT,
    transcripcion_revisada_por TEXT,
    -- Lo que el analista concluye de esta comunicación, escrito por él
    -- mientras la escucha. NO es la transcripción: la transcripción dice qué
    -- se dijo y esto dice qué significa. En el informe salen separadas y
    -- rotuladas, que es lo que permite leer una como registro y la otra como
    -- opinión del analista sin que se contaminen.
    interpretacion      TEXT,
    -- Mandada a la mesa de trabajo a mano. La cola de Desgrabar se armaba con
    -- "¿la máquina produjo texto?", que es una pregunta de Whisper y no del
    -- analista: un SMS o un intento de comunicación quedaban afuera aunque
    -- fueran lo más importante de la causa. Esta marca la pone una persona.
    en_desgrabar        INTEGER NOT NULL DEFAULT 0,
    escuchado           INTEGER NOT NULL DEFAULT 0,
    duracion_seg        REAL,
    archivo_audio       TEXT,
    archivo_txt         TEXT,
    estado              TEXT NOT NULL DEFAULT 'completo'
                        CHECK (estado IN ('completo','audio_faltante','transcripcion_faltante')),
    -- Binario: la comunicación sirve para el expediente o no. Los valores
    -- viejos (bajo/medio/alto) siguen aceptados para que una base anterior
    -- pueda abrirse antes de que corra la migración que los unifica.
    nivel_interes       TEXT NOT NULL DEFAULT 'ninguno'
                        CHECK (nivel_interes IN
                               ('ninguno','interes','bajo','medio','alto')),
    informada           INTEGER NOT NULL DEFAULT 0,
    lote_exportacion_id INTEGER REFERENCES LoteExportacion(id) ON DELETE SET NULL,
    -- Línea intervenida de la que salió el archivo, según la carpeta.
    -- Es el único dato de pertenencia que tiene un audio sin TXT, que no
    -- trae origen ni destino: sin esto el informe lo agrupa bajo
    -- «Abonado NO IDENTIFICADO» aunque la carpeta sí lo decía.
    abonado_intervenido TEXT,
    -- Segunda grabación de la MISMA comunicación, cuando las dos puntas
    -- estaban intervenidas y la prestadora la entregó desde ambas. Es una
    -- sola comunicación (una sola fila), pero son dos audios distintos y
    -- muchas veces uno se escucha bastante mejor que el otro.
    audio_alternativo   TEXT,
    clave_dedup         TEXT,
    UNIQUE(caso_id, clave_dedup)
);
CREATE INDEX IF NOT EXISTS ix_registro_caso     ON Registro(caso_id);
CREATE INDEX IF NOT EXISTS ix_registro_dedup    ON Registro(caso_id, clave_dedup);
CREATE INDEX IF NOT EXISTS ix_registro_fecha    ON Registro(caso_id, fecha_inicio_dt);

-- Papelera de comunicaciones.
--
-- No es un borrado lógico con una columna "eliminado": 29 consultas distintas
-- leen de Registro y olvidarse de filtrar en una sola haría reaparecer una
-- comunicación borrada en el mapa, en el grafo o —lo grave— en un informe
-- judicial. Acá la fila SALE de Registro y se guarda entera, con sus hijos
-- (historial de cambios, marcas de audio, avisos), de modo que restaurar
-- devuelve exactamente el estado anterior y no restaurar no deja rastros.
CREATE TABLE IF NOT EXISTS Papelera (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    caso_id      INTEGER NOT NULL REFERENCES Caso(id) ON DELETE CASCADE,
    registro_id  INTEGER,            -- el id que tenía, solo como referencia
    orden        INTEGER,
    resumen      TEXT,               -- para leer la papelera sin abrir el JSON
    datos_json   TEXT NOT NULL,      -- la fila completa y sus hijos
    lote         TEXT,               -- agrupa lo borrado en una misma acción
    fecha        TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    usuario      TEXT
);
CREATE INDEX IF NOT EXISTS ix_papelera_caso ON Papelera(caso_id, fecha);

CREATE TABLE IF NOT EXISTS CatalogoContexto (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    caso_id     INTEGER REFERENCES Caso(id) ON DELETE CASCADE,  -- NULL = global
    etiqueta    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS Informe (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    caso_id             INTEGER NOT NULL REFERENCES Caso(id) ON DELETE CASCADE,
    numero_o_nombre     TEXT,
    fecha               TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    analista            TEXT,
    lote_exportacion_id INTEGER REFERENCES LoteExportacion(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS HistorialCambio (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    registro_id         INTEGER NOT NULL REFERENCES Registro(id) ON DELETE CASCADE,
    campo               TEXT,
    valor_anterior      TEXT,
    valor_nuevo         TEXT,
    fecha               TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    usuario             TEXT,
    origen_cambio       TEXT CHECK (origen_cambio IN ('manual','automatico_export','importacion')),
    lote_exportacion_id INTEGER REFERENCES LoteExportacion(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS EventoClave (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    caso_id         INTEGER NOT NULL REFERENCES Caso(id) ON DELETE CASCADE,
    descripcion     TEXT,
    fecha_hora      TEXT,
    ventana_minutos INTEGER NOT NULL DEFAULT 120
);

CREATE TABLE IF NOT EXISTS VinculoDetectado (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    caso_id_a           INTEGER NOT NULL REFERENCES Caso(id) ON DELETE CASCADE,
    caso_id_b           INTEGER NOT NULL REFERENCES Caso(id) ON DELETE CASCADE,
    tipo                TEXT CHECK (tipo IN ('mismo_abonado','misma_antena_cercania_horaria')),
    detalle_json        TEXT,
    confirmado          INTEGER NOT NULL DEFAULT 0,
    fecha_deteccion     TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    fecha_confirmacion  TEXT
);

CREATE TABLE IF NOT EXISTS AvisoValidacion (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    caso_id         INTEGER NOT NULL REFERENCES Caso(id) ON DELETE CASCADE,
    registro_id     INTEGER REFERENCES Registro(id) ON DELETE CASCADE,
    importacion_id  INTEGER REFERENCES HistorialImportacion(id) ON DELETE SET NULL,
    tipo            TEXT CHECK (tipo IN (
                        'audio_faltante','transcripcion_faltante','cd_no_detectado',
                        'fecha_invalida','coordenadas_sospechosas','sin_abonados',
                        'posible_duplicado_parcial')),
    descripcion     TEXT,
    sugerencia      TEXT,
    resuelto        INTEGER NOT NULL DEFAULT 0,
    fecha_creacion  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    fecha_resolucion TEXT,
    resuelto_por    TEXT
);
CREATE INDEX IF NOT EXISTS ix_aviso_caso ON AvisoValidacion(caso_id, resuelto);

CREATE TABLE IF NOT EXISTS MarcaAudio (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    registro_id INTEGER NOT NULL REFERENCES Registro(id) ON DELETE CASCADE,
    segundo     REAL NOT NULL,
    nota        TEXT,
    fecha       TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_marca_registro ON MarcaAudio(registro_id);

CREATE TABLE IF NOT EXISTS LogAuditoria (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    caso_id     INTEGER REFERENCES Caso(id) ON DELETE SET NULL,
    accion      TEXT,
    detalle     TEXT,
    usuario     TEXT,
    fecha       TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""


def conectar(ruta: str | Path | None = None) -> sqlite3.Connection:
    """Abre (creando si hace falta) la base de datos y devuelve la conexión.

    - Activa claves foráneas.
    - Devuelve filas como sqlite3.Row (acceso por nombre de columna).
    - Usa WAL, que aguanta mejor un corte de luz a mitad de una importación.
    """
    if ruta is None:
        ruta = config.RUTA_BASE_DATOS
    ruta = Path(ruta)
    if ruta != Path(":memory:"):
        ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(ruta))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON;")
    if ruta != Path(":memory:"):
        # El modo por defecto (`delete`) reescribe la base y borra el diario:
        # si la máquina se apaga en el medio, lo que queda depende de en qué
        # paso estaba. WAL anota aparte y recupera solo al volver a abrir. Es
        # una causa de meses de trabajo adentro de un archivo, y la importación
        # de un CD escribe miles de filas de una sentada.
        # En memoria no aplica y SQLite lo rechaza, así que ni se pide.
        con.execute("PRAGMA journal_mode = WAL;")
    return con


def inicializar(con: sqlite3.Connection) -> None:
    """Crea el esquema (idempotente) y siembra el catálogo global de contextos."""
    con.executescript(SCHEMA)
    _migrar(con)
    _sembrar_contextos_globales(con)
    con.commit()


def _migrar(con: sqlite3.Connection) -> None:
    """Migraciones aditivas para bases creadas con esquemas anteriores."""
    _unificar_nivel_interes(con)
    columnas = {r["name"] for r in con.execute("PRAGMA table_info(Registro)")}
    if "transcripcion" not in columnas:
        con.execute("ALTER TABLE Registro ADD COLUMN transcripcion TEXT")
    if "escuchado" not in columnas:
        con.execute(
            "ALTER TABLE Registro ADD COLUMN escuchado INTEGER NOT NULL DEFAULT 0"
        )
    if "duracion_seg" not in columnas:
        con.execute("ALTER TABLE Registro ADD COLUMN duracion_seg REAL")
    for col in ("tecnologia", "calle", "numero_calle",
                "origen_crudo", "destino_crudo"):
        if col not in columnas:
            con.execute(f"ALTER TABLE Registro ADD COLUMN {col} TEXT")
    if "tipo" not in columnas:
        con.execute(
            "ALTER TABLE Registro ADD COLUMN tipo TEXT NOT NULL DEFAULT 'llamada'"
        )
    if "audio_alternativo" not in columnas:
        con.execute("ALTER TABLE Registro ADD COLUMN audio_alternativo TEXT")
    if "interlocutor" not in columnas:
        con.execute("ALTER TABLE Registro ADD COLUMN interlocutor TEXT")
    if "abonado_intervenido" not in columnas:
        con.execute("ALTER TABLE Registro ADD COLUMN abonado_intervenido TEXT")
    if "transcripcion_segmentos" not in columnas:
        con.execute("ALTER TABLE Registro ADD COLUMN transcripcion_segmentos TEXT")
    if "transcripcion_revisada" not in columnas:
        con.execute(
            "ALTER TABLE Registro ADD COLUMN transcripcion_revisada "
            "INTEGER NOT NULL DEFAULT 0"
        )
    if "transcripcion_revisada_en" not in columnas:
        con.execute(
            "ALTER TABLE Registro ADD COLUMN transcripcion_revisada_en TEXT"
        )
    if "transcripcion_revisada_por" not in columnas:
        con.execute(
            "ALTER TABLE Registro ADD COLUMN transcripcion_revisada_por TEXT"
        )
    if "interpretacion" not in columnas:
        con.execute("ALTER TABLE Registro ADD COLUMN interpretacion TEXT")
    if "en_desgrabar" not in columnas:
        con.execute(
            "ALTER TABLE Registro ADD COLUMN en_desgrabar "
            "INTEGER NOT NULL DEFAULT 0"
        )
    cols_abonado = {r["name"] for r in con.execute("PRAGMA table_info(Abonado)")}
    if "intervenido" not in cols_abonado:
        con.execute(
            "ALTER TABLE Abonado ADD COLUMN intervenido INTEGER NOT NULL DEFAULT 0"
        )


def _ddl_registro_al_dia() -> str:
    """DDL de Registro tal como lo crea una instalación nueva.

    Se saca de una base en memoria armada con el SCHEMA de este archivo, en vez
    de recortar el texto a mano: así la tabla reconstruida es exactamente la
    misma que la de un equipo recién instalado, sin depender de que un parseo
    siga andando cuando el esquema cambie.
    """
    tmp = sqlite3.connect(":memory:")
    try:
        tmp.executescript(SCHEMA)
        fila = tmp.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='Registro'"
        ).fetchone()
        return fila[0] if fila else ""
    finally:
        tmp.close()


def _unificar_nivel_interes(con: sqlite3.Connection) -> None:
    """Pasa los tres grados viejos a un único "de interés".

    En una causa ya trabajada, bajo/medio/alto significan todos lo mismo para
    lo que se usa el dato: esa comunicación entra al informe.

    No alcanza con un UPDATE. El CHECK de la tabla se fija al crearla y
    `CREATE TABLE IF NOT EXISTS` no lo toca, así que una base anterior tiene
    grabado `CHECK (nivel_interes IN ('ninguno','bajo','medio','alto'))` y
    rechaza el valor nuevo: la aplicación no arrancaba. Hay que rehacer la
    tabla, que es el procedimiento que documenta SQLite para cambiar una
    restricción.

    Se preservan los ids porque los hijos (historial de cambios, marcas de
    audio, avisos) apuntan a ellos.
    """
    fila = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='Registro'"
    ).fetchone()
    if fila is None:
        return                       # base recién creada por el SCHEMA
    if "'interes'" in (fila[0] or ""):
        return                       # ya tiene el CHECK al día

    ddl = _ddl_registro_al_dia()
    if not ddl:
        return
    ddl_nuevo = ddl.replace("Registro", "Registro_migrando", 1)

    viejas = {r["name"] for r in con.execute("PRAGMA table_info(Registro)")}
    tmp = sqlite3.connect(":memory:")
    try:
        tmp.executescript(SCHEMA)
        nuevas = [r[1] for r in tmp.execute("PRAGMA table_info(Registro)")]
    finally:
        tmp.close()
    comunes = [c for c in nuevas if c in viejas]
    columnas = ", ".join(comunes)
    # nivel_interes se traduce al vuelo; el resto se copia tal cual.
    seleccion = ", ".join(
        "CASE WHEN nivel_interes IN ('bajo','medio','alto') THEN 'interes' "
        "ELSE nivel_interes END" if c == "nivel_interes" else c
        for c in comunes
    )

    con.execute("PRAGMA foreign_keys = OFF")
    try:
        con.execute(ddl_nuevo)
        con.execute(
            f"INSERT INTO Registro_migrando ({columnas}) "
            f"SELECT {seleccion} FROM Registro"
        )
        con.execute("DROP TABLE Registro")
        con.execute("ALTER TABLE Registro_migrando RENAME TO Registro")
        # Los índices se fueron con la tabla vieja: el SCHEMA los rehace.
        con.executescript(SCHEMA)
        rotas = con.execute("PRAGMA foreign_key_check").fetchall()
        if rotas:
            raise sqlite3.IntegrityError(
                f"La migración dejó {len(rotas)} referencias rotas"
            )
        con.commit()
    except Exception:
        con.rollback()
        con.execute("DROP TABLE IF EXISTS Registro_migrando")
        con.commit()
        raise
    finally:
        con.execute("PRAGMA foreign_keys = ON")


def _sembrar_contextos_globales(con: sqlite3.Connection) -> None:
    """Inserta los contextos iniciales globales (caso_id NULL) si no existen."""
    existentes = {
        r["etiqueta"]
        for r in con.execute(
            "SELECT etiqueta FROM CatalogoContexto WHERE caso_id IS NULL"
        )
    }
    nuevos = [(c,) for c in config.CONTEXTOS_INICIALES if c not in existentes]
    if nuevos:
        con.executemany(
            "INSERT INTO CatalogoContexto (caso_id, etiqueta) VALUES (NULL, ?)",
            nuevos,
        )


def crear_base(ruta: str | Path | None = None) -> sqlite3.Connection:
    """Atajo: conecta + inicializa en un solo paso."""
    con = conectar(ruta)
    inicializar(con)
    return con
