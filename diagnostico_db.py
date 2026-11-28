#!/usr/bin/env python3
"""diagnostico_db.py - Inspeccion y respaldo de diamante.db. NUNCA modifica la base.

Solo usa Python y la biblioteca estandar (no hace falta el programa `sqlite3`).
La base se abre en modo de solo lectura (mode=ro + query_only): aunque haya un
error en este script, SQLite impide escribir en ella.

Subcomandos (todos de solo lectura sobre la base):
  base                       que base usa db.py, version de esquema, indice unico, conteos
  version ID [ID ...]        a que noticia corresponde cada version_id y cuantos hechos tiene
  exportar ID RUTA           guarda el texto_limpio de la version en un archivo NUEVO
                             (para pasarselo al extractor con --input: es el texto exacto)
  hechos ID [--limite N]     muestra los hechos guardados de esa version (contenido real)
  auditar ID [ID ...]        revisa hechos: duplicados, citas que no estan en el texto
                             de la version, estados contradictorios. Codigo 1 si algo falla
  backup RUTA                copia consistente (VACUUM INTO) a un archivo NUEVO y la verifica

Opcion global: --db RUTA  (por defecto la que usa db.py; sirve para inspeccionar un backup).
Codigos de salida: 0 ok | 1 hallazgo o fallo de verificacion | 2 uso incorrecto.
"""
import argparse
import hashlib
import os
import sqlite3
import sys
from pathlib import Path

from extractor_json import normalizar_texto   # la MISMA normalizacion que usa el Guardian

NOMBRE_INDICE_HECHOS = "ux_hechos_identidad"
VERSION_VACUUM_INTO = (3, 27, 0)


def abrir_solo_lectura(ruta, query_only=True):
    """mode=ro impide escribir en el archivo de la base. query_only=False solo se usa para
    el backup: VACUUM INTO necesita escribir el archivo NUEVO, y query_only lo bloquea."""
    ruta = Path(ruta).expanduser().resolve()
    if not ruta.is_file():
        raise FileNotFoundError(f"no existe la base: {ruta}")
    conn = sqlite3.connect(ruta.as_uri() + "?mode=ro", uri=True, timeout=30,
                           isolation_level=None)   # autocommit: sin transacciones implicitas
    conn.row_factory = sqlite3.Row
    if query_only:
        conn.execute("PRAGMA query_only=ON")
    return conn, ruta


def _tablas(conn):
    return [f[0] for f in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def _indice_ok(conn):
    return any(f[1] == NOMBRE_INDICE_HECHOS and f[2] == 1
               for f in conn.execute("PRAGMA index_list(hechos)"))


def _db_por_defecto():
    import db   # import perezoso: solo para saber DB_PATH; no abre conexion
    return db.DB_PATH


# ------------------------------------------------------------------- base
def cmd_base(conn, ruta, out):
    uv = conn.execute("PRAGMA user_version").fetchone()[0]
    out(f"Base usada: {ruta}")
    out(f"  tamano: {ruta.stat().st_size} bytes")
    for suf in ("-wal", "-shm"):
        p = Path(str(ruta) + suf)
        out(f"  {p.name}: " + (f"{p.stat().st_size} bytes" if p.exists() else "no existe"))
    out(f"  SQLite {sqlite3.sqlite_version} | user_version={uv} | "
        f"journal_mode={conn.execute('PRAGMA journal_mode').fetchone()[0]}")
    tablas = _tablas(conn)
    out("  filas por tabla: " + ", ".join(
        f"{t}={conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}" for t in tablas))
    if "hechos" in tablas:
        out(f"  indice unico {NOMBRE_INDICE_HECHOS}: " + ("PRESENTE" if _indice_ok(conn) else "FALTA (ejecutar db_setup.py)"))
        por_estado = conn.execute("SELECT estado, COUNT(*) FROM hechos GROUP BY estado ORDER BY estado").fetchall()
        out("  hechos por estado: " + (", ".join(f"{e}={n}" for e, n in por_estado) or "(ninguno)"))
    home = Path.home()
    otras = sorted({str(p.resolve()) for patron in ("diamante*.db*", "*/diamante*.db*")
                    for p in home.glob(patron) if p.is_file()} - {str(ruta), str(ruta) + "-wal", str(ruta) + "-shm"})
    if otras:
        out("  OJO, otros archivos diamante*.db* en el HOME (no son los que usa db.py):")
        for o in otras:
            out(f"    {o}")
    return 0


# ---------------------------------------------------------------- version
def _info_version(conn, vid):
    return conn.execute(
        "SELECT v.id, v.documento_id, v.hash_texto, LENGTH(v.texto_limpio) AS chars, v.fecha_captura, "
        "       d.url_canonica, d.fuente, d.titulo, d.fecha_publicacion "
        "FROM versiones v JOIN documentos d ON d.id = v.documento_id WHERE v.id = ?", (vid,)).fetchone()


def cmd_version(conn, ids, out):
    rc = 0
    for vid in ids:
        f = _info_version(conn, vid)
        if f is None:
            out(f"version_id={vid}: NO EXISTE")
            rc = 1
            continue
        out(f"version_id={f['id']} (documento {f['documento_id']}) fuente={f['fuente']}")
        out(f"  titulo: {f['titulo']}")
        out(f"  url: {f['url_canonica']}")
        out(f"  publicada: {f['fecha_publicacion']} | capturada: {f['fecha_captura']} | texto: {f['chars']} caracteres")
        out(f"  hash_texto: {f['hash_texto']}")
        texto = conn.execute("SELECT texto_limpio FROM versiones WHERE id = ?", (vid,)).fetchone()[0]
        out("  inicio del texto: " + " ".join(texto.split())[:160])
        est = conn.execute("SELECT estado, COUNT(*) FROM hechos WHERE version_id = ? GROUP BY estado", (vid,)).fetchall()
        out("  hechos ya guardados: " + (", ".join(f"{e}={n}" for e, n in est) or "0"))
    return rc


# --------------------------------------------------------------- exportar
def cmd_exportar(conn, vid, destino, out):
    fila = conn.execute("SELECT texto_limpio FROM versiones WHERE id = ?", (vid,)).fetchone()
    if fila is None:
        out(f"version_id={vid}: NO EXISTE")
        return 1
    destino = Path(destino).expanduser()
    try:
        with open(destino, "x", encoding="utf-8") as f:   # 'x': jamas pisa un archivo existente
            f.write(fila[0])
    except FileExistsError:
        out(f"ERROR: ya existe {destino}; elige otro nombre (no se sobrescribe nada).")
        return 1
    huella = hashlib.sha256(normalizar_texto(fila[0]).encode("utf-8")).hexdigest()[:16]
    out(f"Texto de version_id={vid} guardado en {destino} ({len(fila[0])} caracteres, huella {huella})")
    return 0


# ----------------------------------------------------------------- hechos
def cmd_hechos(conn, vid, limite, out):
    filas = conn.execute(
        "SELECT id, estado, tipo, sujeto, accion, objeto, cita_literal, motivo_rechazo, fecha_creacion "
        "FROM hechos WHERE version_id = ? ORDER BY id LIMIT ?", (vid, limite)).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM hechos WHERE version_id = ?", (vid,)).fetchone()[0]
    out(f"version_id={vid}: mostrando {len(filas)} de {total} hechos")
    for f in filas:
        out(f"[{f['id']}] {f['estado']}/{f['tipo']} creado={f['fecha_creacion']}")
        out(f"    {f['sujeto']} | {f['accion']} | {f['objeto']}")
        out(f"    cita: {f['cita_literal'][:200]!r}")
        if f["motivo_rechazo"]:
            out(f"    motivo: {f['motivo_rechazo']}")
    return 0


# ---------------------------------------------------------------- auditar
def auditar_version(conn, vid):
    """Devuelve (lineas, problemas:int) para una version."""
    lineas, problemas = [], 0
    fila = conn.execute("SELECT texto_limpio FROM versiones WHERE id = ?", (vid,)).fetchone()
    if fila is None:
        return [f"version_id={vid}: NO EXISTE"], 1
    texto_n = normalizar_texto(fila[0])
    por = conn.execute("SELECT estado, tipo, COUNT(*) FROM hechos WHERE version_id = ? "
                       "GROUP BY estado, tipo ORDER BY estado, tipo", (vid,)).fetchall()
    total = sum(n for _, _, n in por)
    lineas.append(f"version_id={vid}: {total} hechos en total: " +
                  (", ".join(f"{e}/{t}={n}" for e, t, n in por) or "ninguno"))

    dup = conn.execute(
        "SELECT tipo, estado, COUNT(*) AS n, GROUP_CONCAT(id) FROM hechos WHERE version_id = ? "
        "GROUP BY tipo, estado, COALESCE(sujeto,''), COALESCE(accion,''), COALESCE(objeto,''), cita_literal "
        "HAVING COUNT(*) > 1", (vid,)).fetchall()
    if dup:
        problemas += len(dup)
        for tipo, estado, n, ids in dup:
            lineas.append(f"  DUPLICADO: {tipo}/{estado} x{n} ids={ids}")
    else:
        lineas.append("  duplicados: 0")

    huerfanas = [(r["id"], r["cita_literal"]) for r in conn.execute(
        "SELECT id, cita_literal FROM hechos WHERE version_id = ? AND estado = 'validado'", (vid,))
        if normalizar_texto(r["cita_literal"]) not in texto_n]
    if huerfanas:
        problemas += len(huerfanas)
        for hid, cita in huerfanas[:10]:
            lineas.append(f"  CITA VALIDADA NO ESTA EN EL TEXTO DE LA VERSION: hecho id={hid}: {cita[:80]!r}")
    else:
        lineas.append("  citas validadas ausentes del texto de la version: 0")

    contra = conn.execute(
        "SELECT GROUP_CONCAT(id), COUNT(DISTINCT estado) AS e FROM hechos WHERE version_id = ? "
        "GROUP BY tipo, COALESCE(sujeto,''), COALESCE(accion,''), COALESCE(objeto,''), cita_literal "
        "HAVING e > 1", (vid,)).fetchall()
    if contra:
        problemas += len(contra)
        for ids, _ in contra:
            lineas.append(f"  ESTADOS CONTRADICTORIOS (misma cita validada y rechazada) ids={ids}")
    else:
        lineas.append("  hechos con estados contradictorios: 0")

    largos = [len(r[0]) for r in conn.execute(
        "SELECT cita_literal FROM hechos WHERE version_id = ? AND estado = 'validado'", (vid,))]
    if largos:
        largos.sort()
        lineas.append(f"  largo de cita_literal validada: min={largos[0]} p50={largos[len(largos)//2]} max={largos[-1]}")
    return lineas, problemas


def cmd_auditar(conn, ids, out):
    total = 0
    for vid in ids:
        lineas, p = auditar_version(conn, vid)
        for l in lineas:
            out(l)
        total += p
    out("AUDITORIA: " + ("sin problemas" if total == 0 else f"{total} problema(s)"))
    return 0 if total == 0 else 1


# ----------------------------------------------------------------- backup
def _contar(conn):
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in _tablas(conn)}


def cmd_backup(conn, ruta_origen, destino, out):
    if tuple(int(x) for x in sqlite3.sqlite_version.split(".")[:3]) < VERSION_VACUUM_INTO:
        out(f"ERROR: SQLite {sqlite3.sqlite_version} no soporta VACUUM INTO (hace falta >= 3.27).")
        return 1
    destino = Path(destino).expanduser().resolve()
    if destino.exists():
        out(f"ERROR: ya existe {destino}; no se sobrescribe. Elige otro nombre.")
        return 1
    if destino == ruta_origen:
        out("ERROR: el destino no puede ser la propia base.")
        return 1
    antes = _contar(conn)
    uv = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.execute("VACUUM INTO ?", (str(destino),))    # copia consistente: incluye lo que aun esta en el -wal
    os.chmod(destino, 0o600)
    copia, _ = abrir_solo_lectura(destino)
    try:
        integridad = copia.execute("PRAGMA integrity_check").fetchone()[0]
        despues = _contar(copia)
        uv_copia = copia.execute("PRAGMA user_version").fetchone()[0]
    finally:
        copia.close()
    sha = hashlib.sha256(destino.read_bytes()).hexdigest()
    ok = integridad == "ok" and antes == despues and uv == uv_copia
    out(f"Backup: {destino} ({destino.stat().st_size} bytes)")
    out(f"  sha256: {sha}")
    out(f"  integrity_check de la copia: {integridad} | user_version: origen={uv} copia={uv_copia}")
    out(f"  filas por tabla (origen): {antes}")
    out(f"  filas por tabla (copia):  {despues}")
    out("  VERIFICACION: " + ("OK, la copia es identica en contenido" if ok else "FALLO: la copia NO coincide; no la uses"))
    out("  Recuerda copiarla FUERA del telefono (el backup en el mismo equipo no protege de perderlo).")
    return 0 if ok else 1


# -------------------------------------------------------------------- CLI
def construir_parser():
    p = argparse.ArgumentParser(description="Inspeccion y respaldo de diamante.db (nunca escribe en la base).")
    p.add_argument("--db", help="ruta de la base (por defecto, la que usa db.py)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("base")
    for nombre in ("version", "auditar"):
        s = sub.add_parser(nombre)
        s.add_argument("ids", type=int, nargs="+")
    s = sub.add_parser("hechos")
    s.add_argument("id", type=int)
    s.add_argument("--limite", type=int, default=50)
    s = sub.add_parser("exportar")
    s.add_argument("id", type=int)
    s.add_argument("ruta")
    s = sub.add_parser("backup")
    s.add_argument("ruta")
    return p


def main(argv=None, out=print):
    args = construir_parser().parse_args(argv)
    try:
        conn, ruta = abrir_solo_lectura(args.db or _db_por_defecto(), query_only=(args.cmd != "backup"))
    except (OSError, sqlite3.Error) as e:
        out(f"ERROR: no se pudo abrir la base: {e}")
        return 1
    try:
        if args.cmd == "base":
            return cmd_base(conn, ruta, out)
        if args.cmd == "version":
            return cmd_version(conn, args.ids, out)
        if args.cmd == "hechos":
            return cmd_hechos(conn, args.id, args.limite, out)
        if args.cmd == "exportar":
            return cmd_exportar(conn, args.id, args.ruta, out)
        if args.cmd == "auditar":
            return cmd_auditar(conn, args.ids, out)
        return cmd_backup(conn, ruta, args.ruta, out)
    except sqlite3.Error as e:
        out(f"ERROR de SQLite: {e}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
