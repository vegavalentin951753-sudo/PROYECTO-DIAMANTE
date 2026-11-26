"""Crea, migra o verifica el esquema de diamante.db (v3). Se puede ejecutar varias veces sin riesgo."""
import sqlite3
import sys

from db import DB_PATH, conectar

VERSION_ESQUEMA = 3

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


def main():
    conn = conectar()
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    tablas = {f[0] for f in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    if "documentos" in tablas:
        if version == 2:
            migrar_v2_a_v3(conn)
            print("Migrado de esquema v2 a v3 (columnas de revisión añadidas).")
        elif version != VERSION_ESQUEMA:
            conn.close()
            print("Hay una base con un esquema desconocido (user_version=%d) en: %s" % (version, DB_PATH))
            print("Renómbrala y vuelve a ejecutar este script:")
            print("    mv diamante.db diamante_viejo.db")
            return 1

    conn.executescript(ESQUEMA)
    conn.execute(f"PRAGMA user_version={VERSION_ESQUEMA}")
    conn.commit()

    try:
        conn.execute("CREATE VIRTUAL TABLE temp._prueba_fts USING fts5(x)")
        conn.execute("DROP TABLE temp._prueba_fts")
        fts5 = "disponible"
    except sqlite3.Error as e:
        fts5 = f"NO disponible ({e})"

    print("Base de datos:", DB_PATH)
    print("Esquema v%d | journal_mode=%s | integrity_check=%s | FTS5: %s" % (
        VERSION_ESQUEMA,
        conn.execute("PRAGMA journal_mode").fetchone()[0],
        conn.execute("PRAGMA integrity_check").fetchone()[0],
        fts5,
    ))
    print("Tablas:", ", ".join(sorted(
        f[0] for f in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    )))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
