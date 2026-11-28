"""Crea, migra o verifica el esquema de diamante.db (v4). Se puede ejecutar varias veces sin riesgo.

v4 (2026-11-27): indice unico ux_hechos_identidad sobre `hechos`, para que reejecutar el
extractor sobre una misma version no multiplique hechos identicos. La migracion v3 -> v4
NO borra ni modifica filas: si ya hay duplicados, se detiene y los lista.
"""
import sqlite3
import sys

from db import DB_PATH, conectar

VERSION_ESQUEMA = 4

ESQUEMA = """
CREATE TABLE IF NOT EXISTS documentos (
    id                 INTEGER PRIMARY KEY,
    url_canonica       TEXT NOT NULL UNIQUE,
    url_original       TEXT NOT NULL,
    fuente             TEXT NOT NULL,
    titulo             TEXT,
    fecha_publicacion  TEXT,                       -- ISO 8601 UTC o NULL
    primera_captura    TEXT NOT NULL,              -- ISO 8601 UTC
    estado             TEXT NOT NULL DEFAULT 'ok'
        CHECK (estado IN ('ok','sin_texto','bloqueado_robots','descarga_fallida')),
    intentos           INTEGER NOT NULL DEFAULT 0,
    ultima_revision    TEXT,                       -- v3: última vez que se intentó
    proxima_revision   TEXT,                       -- v3: cuándo toca volver a mirar (9999-12-31 = abandonado)
    ultimo_error       TEXT                        -- v3: motivo del último fallo
);
CREATE INDEX IF NOT EXISTS idx_documentos_fecha        ON documentos(fecha_publicacion);
CREATE INDEX IF NOT EXISTS idx_documentos_fuente_fecha ON documentos(fuente, fecha_publicacion);
CREATE INDEX IF NOT EXISTS idx_documentos_estado       ON documentos(estado);
CREATE INDEX IF NOT EXISTS idx_documentos_revision     ON documentos(fuente, proxima_revision);

CREATE TABLE IF NOT EXISTS versiones (
    id             INTEGER PRIMARY KEY,
    documento_id   INTEGER NOT NULL REFERENCES documentos(id),
    hash_texto     TEXT NOT NULL,                  -- sha256 del texto normalizado
    texto_limpio   TEXT NOT NULL,
    fecha_captura  TEXT NOT NULL,
    UNIQUE (documento_id, hash_texto)
);
CREATE INDEX IF NOT EXISTS idx_versiones_hash ON versiones(hash_texto);

CREATE TABLE IF NOT EXISTS crudos (                -- HTML original comprimido, aparte para no ensanchar versiones
    version_id  INTEGER PRIMARY KEY REFERENCES versiones(id),
    html_zlib   BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS hechos (
    id                INTEGER PRIMARY KEY,
    version_id        INTEGER NOT NULL REFERENCES versiones(id),
    sujeto            TEXT,
    accion            TEXT,
    objeto            TEXT,
    cita_literal      TEXT NOT NULL,
    tipo              TEXT NOT NULL DEFAULT 'hecho'
        CHECK (tipo IN ('hecho','declaracion','opinion','proyeccion')),
    estado            TEXT NOT NULL DEFAULT 'pendiente_validacion'
        CHECK (estado IN ('pendiente_validacion','validado','rechazado')),
    motivo_rechazo    TEXT,
    fecha_creacion    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hechos_version ON hechos(version_id);
CREATE INDEX IF NOT EXISTS idx_hechos_estado  ON hechos(estado);

CREATE TABLE IF NOT EXISTS tareas (
    id                   INTEGER PRIMARY KEY,
    tipo_tarea           TEXT NOT NULL,
    entidad_id           INTEGER NOT NULL,
    estado               TEXT NOT NULL DEFAULT 'pendiente'
        CHECK (estado IN ('pendiente','running','completed','failed','dead')),
    intentos             INTEGER NOT NULL DEFAULT 0,
    max_intentos         INTEGER NOT NULL DEFAULT 3,
    retry_at             TEXT,
    locked_at            TEXT,
    ultimo_error         TEXT,
    fecha_creacion       TEXT NOT NULL,
    fecha_actualizacion  TEXT NOT NULL,
    UNIQUE (tipo_tarea, entidad_id)
);
CREATE INDEX IF NOT EXISTS idx_tareas_cola ON tareas(estado, retry_at);

CREATE TABLE IF NOT EXISTS ejecuciones (           -- una fila por corrida; sirve de latido (heartbeat)
    id        INTEGER PRIMARY KEY,
    modulo    TEXT NOT NULL,
    inicio    TEXT NOT NULL,
    fin       TEXT,
    estado    TEXT NOT NULL DEFAULT 'running'
        CHECK (estado IN ('running','ok','error','interrumpida')),
    resumen   TEXT
);
CREATE INDEX IF NOT EXISTS idx_ejecuciones_modulo ON ejecuciones(modulo, id);
"""

COLUMNAS_V3 = (("ultima_revision", "TEXT"), ("proxima_revision", "TEXT"), ("ultimo_error", "TEXT"))


def migrar_v2_a_v3(conn):
    """Añade las columnas nuevas a documentos sin tocar los datos. Segura si se repite."""
    existentes = {f[1] for f in conn.execute("PRAGMA table_info(documentos)")}
    for nombre, tipo in COLUMNAS_V3:
        if nombre not in existentes:
            conn.execute(f"ALTER TABLE documentos ADD COLUMN {nombre} {tipo}")
    conn.commit()


NOMBRE_INDICE_HECHOS = "ux_hechos_identidad"

# Identidad de un hecho = version + tipo + estado + sujeto + accion + objeto + cita literal.
# COALESCE: en SQLite un UNIQUE normal NO detecta repetidos si alguna columna es NULL
# (NULL != NULL), y sujeto/accion/objeto admiten NULL. Con COALESCE, NULL y '' son lo mismo.
# `estado` entra en la clave a proposito: si el Guardian cambia, una misma cita puede quedar
# como 'rechazado' (historial) y luego como 'validado' sin pisarse.
SQL_INDICE_HECHOS = f"""
CREATE UNIQUE INDEX IF NOT EXISTS {NOMBRE_INDICE_HECHOS} ON hechos (
    version_id, tipo, estado,
    COALESCE(sujeto, ''), COALESCE(accion, ''), COALESCE(objeto, ''),
    cita_literal
);
"""

SQL_DUPLICADOS_HECHOS = """
SELECT version_id, tipo, estado, COALESCE(sujeto, ''), COALESCE(accion, ''),
       COALESCE(objeto, ''), cita_literal, COUNT(*) AS n, GROUP_CONCAT(id)
FROM hechos
GROUP BY 1, 2, 3, 4, 5, 6, 7
HAVING COUNT(*) > 1
ORDER BY n DESC, version_id
LIMIT ?
"""


class DuplicadosEnHechos(Exception):
    """Ya existen hechos repetidos: no se puede crear el indice unico sin decidir cual conservar."""

    def __init__(self, grupos):
        super().__init__(f"{len(grupos)} grupo(s) de hechos duplicados")
        self.grupos = grupos


class EsquemaDesconocido(Exception):
    def __init__(self, version):
        super().__init__(f"user_version={version}")
        self.version = version


def duplicados_en_hechos(conn, limite=20):
    """Solo lectura. Lista de (version_id, tipo, estado, sujeto, accion, objeto, cita, n, ids)."""
    return [tuple(f) for f in conn.execute(SQL_DUPLICADOS_HECHOS, (limite,))]


def indice_hechos_existe(conn):
    """True si el indice unico de identidad existe y es realmente UNIQUE."""
    return any(f[1] == NOMBRE_INDICE_HECHOS and f[2] == 1
               for f in conn.execute("PRAGMA index_list(hechos)"))


def migrar_v3_a_v4(conn):
    """Crea el indice unico y marca user_version=4, TODO en una transaccion.

    Si hay duplicados, lanza DuplicadosEnHechos sin cambiar nada (ni el indice ni la
    version). Nunca borra filas. Segura si se repite (el indice usa IF NOT EXISTS)."""
    conn.execute("BEGIN IMMEDIATE")      # bloquea escritores: la revision y el CREATE ven lo mismo
    try:
        grupos = duplicados_en_hechos(conn)
        if grupos:
            raise DuplicadosEnHechos(grupos)
        conn.execute(SQL_INDICE_HECHOS)
        conn.execute(f"PRAGMA user_version={VERSION_ESQUEMA}")
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise


def aplicar_esquema(conn):
    """Crea o migra hasta la version actual. Lanza EsquemaDesconocido o DuplicadosEnHechos."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    tablas = {f[0] for f in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    migrado_v2 = False
    if "documentos" in tablas:
        if version == 2:
            migrar_v2_a_v3(conn)
            version, migrado_v2 = 3, True
        elif version not in (3, VERSION_ESQUEMA):
            raise EsquemaDesconocido(version)
    conn.executescript(ESQUEMA)          # solo CREATE ... IF NOT EXISTS; no toca filas
    if version < VERSION_ESQUEMA or not indice_hechos_existe(conn):
        migrar_v3_a_v4(conn)
    return {"version_previa": version, "migrado_v2": migrado_v2}


def main():
    conn = conectar()
    try:
        info = aplicar_esquema(conn)
    except EsquemaDesconocido as e:
        conn.close()
        print("Hay una base con un esquema desconocido (user_version=%d) en: %s" % (e.version, DB_PATH))
        print("Renómbrala y vuelve a ejecutar este script:")
        print("    mv diamante.db diamante_viejo.db")
        return 1
    except DuplicadosEnHechos as e:
        conn.close()
        print("NO se migró a v4: la tabla hechos ya tiene filas repetidas (no se borró ni cambió nada).")
        print("Base:", DB_PATH)
        for v, tipo, estado, suj, acc, obj, cita, n, ids in e.grupos[:10]:
            print("  version_id=%s %s/%s x%d ids=%s | %s | %s" % (v, tipo, estado, n, ids, suj[:40], cita[:60]))
        print("Decide qué filas conservar (con un backup hecho) y vuelve a ejecutar este script.")
        return 1
    if info["migrado_v2"]:
        print("Migrado de esquema v2 a v3 (columnas de revisión añadidas).")
    if info["version_previa"] < VERSION_ESQUEMA:
        print("Migrado a esquema v%d (índice único %s creado; ninguna fila modificada)." % (
            VERSION_ESQUEMA, NOMBRE_INDICE_HECHOS))

    try:
        conn.execute("CREATE VIRTUAL TABLE temp._prueba_fts USING fts5(x)")
        conn.execute("DROP TABLE temp._prueba_fts")
        fts5 = "disponible"
    except sqlite3.Error as e:
        fts5 = f"NO disponible ({e})"

    print("Base de datos:", DB_PATH)
    print("Esquema v%d | journal_mode=%s | integrity_check=%s | FTS5: %s | índice único hechos: %s" % (
        VERSION_ESQUEMA,
        conn.execute("PRAGMA journal_mode").fetchone()[0],
        conn.execute("PRAGMA integrity_check").fetchone()[0],
        fts5,
        "ok" if indice_hechos_existe(conn) else "FALTA",
    ))
    print("Tablas:", ", ".join(sorted(
        f[0] for f in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    )))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
