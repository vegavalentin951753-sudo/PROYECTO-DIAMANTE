"""Pruebas de la migracion de esquema v3 -> v4 (db_setup) y de diagnostico_db.

Solo unittest, sin modelo ni Internet. Todas las bases son archivos temporales;
ninguna prueba toca la base real. Lo que se verifica sobre todo: que la migracion
CONSERVA los datos, que se detiene (sin cambiar nada) si hay duplicados y que la
herramienta de diagnostico no modifica la base.
"""
import contextlib
import hashlib
import io
import os
import sqlite3
import stat
import tempfile
import unittest
from unittest import mock

import db_setup
import diagnostico_db as dg

FECHA = "2026-11-27T12:00:00Z"
TEXTO = ("El Banco Central de Bolivia anuncio ayer nuevas medidas cambiarias. "
         "El ministro de Economia dijo que seguira el dialogo con los exportadores.")
CITA = "El Banco Central de Bolivia anuncio ayer nuevas medidas cambiarias"

INSERT_HECHO = ("INSERT INTO hechos (version_id, sujeto, accion, objeto, cita_literal, tipo, estado, "
                "motivo_rechazo, fecha_creacion) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)")


def volcado(conn):
    """Contenido completo de todas las tablas de datos, para comparar antes/despues."""
    out = {}
    for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        out[t] = conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
    return out


def sembrar(conn, con_hechos=True):
    conn.execute("INSERT INTO documentos (id, url_canonica, url_original, fuente, titulo, primera_captura) "
                 "VALUES (1, 'https://x/1', 'https://x/1', 'LaRazon', 'Titulo uno', ?)", (FECHA,))
    conn.execute("INSERT INTO versiones (id, documento_id, hash_texto, texto_limpio, fecha_captura) "
                 "VALUES (1, 1, 'hash1', ?, ?)", (TEXTO, FECHA))
    conn.execute("INSERT INTO crudos (version_id, html_zlib) VALUES (1, ?)", (b"\x78\x9c\x01",))
    if con_hechos:
        conn.execute(INSERT_HECHO, (1, "Banco Central de Bolivia", "anunciar", None, CITA, "hecho",
                                    "validado", None, FECHA))
        conn.execute(INSERT_HECHO, (1, "ministro de Economia", "decir", "", "xx", "declaracion",
                                    "rechazado", "cita_muy_corta", FECHA))
    conn.commit()


class BaseTemporal(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.ruta = os.path.join(self._dir.name, "t.db")

    def abrir(self):
        c = sqlite3.connect(self.ruta)
        self.addCleanup(c.close)
        return c

    def crear_v3(self, con_hechos=True):
        """Base como la de hoy en el telefono: esquema v3 sin el indice unico."""
        c = self.abrir()
        c.executescript(db_setup.ESQUEMA)
        c.execute("PRAGMA user_version=3")
        sembrar(c, con_hechos)
        return c

    def user_version(self, c):
        return c.execute("PRAGMA user_version").fetchone()[0]

    def tiene_indice(self, c):
        return db_setup.indice_hechos_existe(c)


# ---------------------------------------------------------------- migracion
class TestMigracion(BaseTemporal):
    def test_base_nueva_queda_en_v4_con_indice_unico(self):
        c = self.abrir()
        db_setup.aplicar_esquema(c)
        self.assertEqual(self.user_version(c), 4)
        self.assertTrue(self.tiene_indice(c))

    def test_v3_con_datos_migra_y_conserva_todo(self):
        c = self.crear_v3()
        antes = volcado(c)
        info = db_setup.aplicar_esquema(c)
        self.assertEqual(info["version_previa"], 3)
        self.assertEqual(self.user_version(c), 4)
        self.assertTrue(self.tiene_indice(c))
        self.assertEqual(volcado(c), antes)          # ni una fila ni un campo cambiaron
        self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_v2_migra_a_v4_conservando_datos(self):
        c = self.abrir()
        c.executescript("""
            CREATE TABLE documentos (id INTEGER PRIMARY KEY, url_canonica TEXT NOT NULL UNIQUE,
              url_original TEXT NOT NULL, fuente TEXT NOT NULL, titulo TEXT, fecha_publicacion TEXT,
              primera_captura TEXT NOT NULL, estado TEXT NOT NULL DEFAULT 'ok', intentos INTEGER NOT NULL DEFAULT 0);
            INSERT INTO documentos (id, url_canonica, url_original, fuente, titulo, primera_captura)
              VALUES (7, 'u7', 'u7', 'LaRazon', 'Viejo', '2026-11-20T00:00:00Z');
            PRAGMA user_version=2;
        """)
        c.commit()
        info = db_setup.aplicar_esquema(c)
        self.assertTrue(info["migrado_v2"])
        self.assertEqual(self.user_version(c), 4)
        fila = c.execute("SELECT id, url_canonica, titulo, proxima_revision FROM documentos").fetchone()
        self.assertEqual(fila, (7, "u7", "Viejo", None))
        self.assertTrue(self.tiene_indice(c))

    def test_es_idempotente(self):
        c = self.crear_v3()
        db_setup.aplicar_esquema(c)
        despues_1 = volcado(c)
        db_setup.aplicar_esquema(c)
        db_setup.aplicar_esquema(c)
        self.assertEqual((self.user_version(c), volcado(c)), (4, despues_1))

    def test_tras_migrar_el_indice_es_real(self):
        c = self.crear_v3(con_hechos=False)
        db_setup.aplicar_esquema(c)
        fila = (1, "S", "a", None, "cita larga de prueba", "hecho", "validado", None, FECHA)
        c.execute(INSERT_HECHO, fila)
        c.commit()
        with self.assertRaises(sqlite3.IntegrityError):      # un INSERT normal SI falla (NULL == '')
            c.execute(INSERT_HECHO, (1, "S", "a", "", "cita larga de prueba", "hecho", "validado", None, FECHA))
        c.rollback()
        self.assertEqual(c.execute("SELECT COUNT(*) FROM hechos").fetchone()[0], 1)

    def test_con_duplicados_previos_se_detiene_sin_cambiar_nada(self):
        c = self.crear_v3(con_hechos=False)
        for objeto in (None, ""):                    # NULL y '' cuentan como el mismo hecho
            c.execute(INSERT_HECHO, (1, "S", "a", objeto, "cita larga de prueba", "hecho", "validado", None, FECHA))
        c.commit()
        antes = volcado(c)
        with self.assertRaises(db_setup.DuplicadosEnHechos) as cm:
            db_setup.aplicar_esquema(c)
        self.assertEqual(len(cm.exception.grupos), 1)
        self.assertEqual(cm.exception.grupos[0][7], 2)       # n
        self.assertEqual(cm.exception.grupos[0][8], "1,2")   # ids
        self.assertEqual(self.user_version(c), 3)            # version intacta
        self.assertFalse(self.tiene_indice(c))
        self.assertEqual(volcado(c), antes)                  # nada borrado ni cambiado

    def test_fallo_a_mitad_de_la_migracion_revierte_todo(self):
        c = self.crear_v3()
        antes = volcado(c)
        with mock.patch.object(db_setup, "SQL_INDICE_HECHOS", "CREATE UNIQUE INDEX malo ON no_existe(x)"):
            with self.assertRaises(sqlite3.OperationalError):
                db_setup.migrar_v3_a_v4(c)
        self.assertFalse(c.in_transaction)
        self.assertEqual(self.user_version(c), 3)
        self.assertFalse(self.tiene_indice(c))
        self.assertEqual(volcado(c), antes)
        db_setup.migrar_v3_a_v4(c)                           # y se puede reintentar despues
        self.assertEqual(self.user_version(c), 4)

    def test_fallo_al_confirmar_deja_la_base_como_estaba(self):
        # El indice y user_version=4 ya estan escritos DENTRO de la transaccion cuando el
        # COMMIT falla (disco lleno, I/O...). Debe quedar todo revertido, no a medias.
        class ConexionQueFallaAlConfirmar(sqlite3.Connection):
            def commit(self):
                raise sqlite3.OperationalError("disk I/O error (simulado)")
        self.crear_v3().close()
        c = sqlite3.connect(self.ruta, factory=ConexionQueFallaAlConfirmar)
        self.addCleanup(c.close)
        with self.assertRaises(sqlite3.OperationalError):
            db_setup.migrar_v3_a_v4(c)
        self.assertFalse(c.in_transaction)                    # se hizo ROLLBACK
        self.assertEqual(self.user_version(c), 3)             # visto desde la MISMA conexion
        self.assertFalse(self.tiene_indice(c))
        otra = self.abrir()
        self.assertEqual((self.user_version(otra), self.tiene_indice(otra)), (3, False))
        self.assertEqual(otra.execute("SELECT COUNT(*) FROM hechos").fetchone()[0], 2)

    def test_version_desconocida(self):
        c = self.crear_v3()
        c.execute("PRAGMA user_version=9")
        with self.assertRaises(db_setup.EsquemaDesconocido):
            db_setup.aplicar_esquema(c)

    def test_v4_sin_indice_se_repara(self):
        c = self.crear_v3()
        db_setup.aplicar_esquema(c)
        c.execute(f"DROP INDEX {db_setup.NOMBRE_INDICE_HECHOS}")
        c.commit()
        db_setup.aplicar_esquema(c)
        self.assertTrue(self.tiene_indice(c))

    def test_dos_conexiones_la_migracion_espera_o_falla_limpio(self):
        c = self.crear_v3()
        otra = sqlite3.connect(self.ruta, timeout=0.1)
        self.addCleanup(otra.close)
        otra.execute("BEGIN IMMEDIATE")                      # otro proceso escribiendo
        with self.assertRaises(sqlite3.OperationalError):
            db_setup.migrar_v3_a_v4(c)
        otra.rollback()
        self.assertEqual(self.user_version(c), 3)


class TestMainDbSetup(BaseTemporal):
    def correr(self):
        out = io.StringIO()
        with mock.patch.object(db_setup, "conectar", lambda: sqlite3.connect(self.ruta)), \
                mock.patch.object(db_setup, "DB_PATH", self.ruta), contextlib.redirect_stdout(out):
            codigo = db_setup.main()
        return codigo, out.getvalue()

    def test_main_migra_y_lo_dice(self):
        self.crear_v3()
        codigo, out = self.correr()
        self.assertEqual(codigo, 0)
        self.assertIn("Migrado a esquema v4", out)
        self.assertIn("ninguna fila modificada", out)
        self.assertIn("índice único hechos: ok", out)
        self.assertIn("integrity_check=ok", out)

    def test_main_segunda_vez_no_migra_de_nuevo(self):
        self.crear_v3()
        self.correr()
        codigo, out = self.correr()
        self.assertEqual(codigo, 0)
        self.assertNotIn("Migrado", out)

    def test_main_con_duplicados_devuelve_1_y_explica(self):
        c = self.crear_v3(con_hechos=False)
        for _ in range(2):
            c.execute(INSERT_HECHO, (1, "S", "a", "o", "cita larga de prueba", "hecho", "validado", None, FECHA))
        c.commit()
        codigo, out = self.correr()
        self.assertEqual(codigo, 1)
        self.assertIn("NO se migró a v4", out)
        self.assertIn("no se borró ni cambió nada", out)
        self.assertEqual(self.user_version(c), 3)

    def test_main_version_desconocida(self):
        c = self.crear_v3()
        c.execute("PRAGMA user_version=9")
        c.commit()
        codigo, out = self.correr()
        self.assertEqual(codigo, 1)
        self.assertIn("esquema desconocido", out)


# --------------------------------------------------------------- diagnostico
class BaseDiagnostico(BaseTemporal):
    def setUp(self):
        super().setUp()
        c = self.abrir()
        db_setup.aplicar_esquema(c)
        sembrar(c)
        c.commit()
        c.close()

    def run_dg(self, *argv, db=None):
        salida = []
        codigo = dg.main(["--db", db or self.ruta, *argv], out=salida.append)
        return codigo, "\n".join(salida)

    def sha_archivo(self, ruta=None):
        with open(ruta or self.ruta, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()


class TestDiagnosticoSoloLectura(BaseDiagnostico):
    def test_la_conexion_no_puede_escribir(self):
        conn, _ = dg.abrir_solo_lectura(self.ruta)
        self.addCleanup(conn.close)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("DELETE FROM hechos")
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE intruso (x)")

    def test_ni_siquiera_con_query_only_apagado_se_puede_escribir_en_el_archivo(self):
        conn, _ = dg.abrir_solo_lectura(self.ruta, query_only=False)    # modo del backup
        self.addCleanup(conn.close)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("INSERT INTO ejecuciones (modulo, inicio) VALUES ('x', 'y')")

    def test_los_comandos_de_lectura_no_cambian_la_base(self):
        antes = self.sha_archivo()
        self.run_dg("base")
        self.run_dg("version", "1")
        self.run_dg("auditar", "1")
        self.run_dg("hechos", "1")
        self.run_dg("exportar", "1", os.path.join(self._dir.name, "t1.txt"))
        self.assertEqual(self.sha_archivo(), antes)
        c = self.abrir()
        self.assertEqual(c.execute("SELECT COUNT(*) FROM hechos").fetchone()[0], 2)

    def test_base_inexistente(self):
        codigo, out = self.run_dg("base", db=os.path.join(self._dir.name, "no_hay.db"))
        self.assertEqual(codigo, 1)
        self.assertIn("no se pudo abrir la base", out)


class TestDiagnosticoComandos(BaseDiagnostico):
    def test_base_informa_ruta_version_indice_y_conteos(self):
        codigo, out = self.run_dg("base")
        self.assertEqual(codigo, 0)
        self.assertIn(os.path.realpath(self.ruta), out)
        self.assertIn("user_version=4", out)
        self.assertIn("PRESENTE", out)
        self.assertIn("hechos=2", out)
        self.assertIn("rechazado=1", out)
        self.assertIn("validado=1", out)

    def test_base_avisa_si_falta_el_indice(self):
        c = self.abrir()
        c.execute(f"DROP INDEX {db_setup.NOMBRE_INDICE_HECHOS}")
        c.commit()
        _, out = self.run_dg("base")
        self.assertIn("FALTA", out)

    def test_version_muestra_noticia_y_hechos_existentes(self):
        codigo, out = self.run_dg("version", "1")
        self.assertEqual(codigo, 0)
        for esperado in ("Titulo uno", "https://x/1", "hash1", "El Banco Central de Bolivia anuncio",
                         "rechazado=1", "validado=1"):
            self.assertIn(esperado, out)

    def test_version_inexistente_da_codigo_1(self):
        codigo, out = self.run_dg("version", "1", "999")
        self.assertEqual(codigo, 1)
        self.assertIn("version_id=999: NO EXISTE", out)

    def test_hechos_muestra_el_contenido_guardado(self):
        codigo, out = self.run_dg("hechos", "1")
        self.assertEqual(codigo, 0)
        self.assertIn("mostrando 2 de 2 hechos", out)
        self.assertIn("validado/hecho", out)
        self.assertIn("Banco Central de Bolivia | anunciar", out)
        self.assertIn("motivo: cita_muy_corta", out)
        self.assertIn("mostrando 1 de 2", self.run_dg("hechos", "1", "--limite", "1")[1])

    def test_exportar_escribe_el_texto_exacto_y_no_pisa(self):
        destino = os.path.join(self._dir.name, "v1.txt")
        codigo, out = self.run_dg("exportar", "1", destino)
        self.assertEqual(codigo, 0)
        with open(destino, encoding="utf-8") as f:
            self.assertEqual(f.read(), TEXTO)
        with open(destino, "w", encoding="utf-8") as f:
            f.write("marca")
        codigo, out = self.run_dg("exportar", "1", destino)
        self.assertEqual(codigo, 1)
        self.assertIn("no se sobrescribe", out)
        with open(destino, encoding="utf-8") as f:
            self.assertEqual(f.read(), "marca")

    def test_exportar_version_inexistente(self):
        destino = os.path.join(self._dir.name, "v9.txt")
        self.assertEqual(self.run_dg("exportar", "9", destino)[0], 1)
        self.assertFalse(os.path.exists(destino))


class TestAuditar(BaseDiagnostico):
    def test_base_sana(self):
        codigo, out = self.run_dg("auditar", "1")
        self.assertEqual(codigo, 0)
        self.assertIn("duplicados: 0", out)
        self.assertIn("AUDITORIA: sin problemas", out)

    def test_cita_validada_que_no_esta_en_el_texto_de_la_version(self):
        c = self.abrir()
        c.execute(INSERT_HECHO, (1, "Aduana", "informar", "", "La Aduana informo que revisara contenedores",
                                 "hecho", "validado", None, FECHA))
        c.commit()
        codigo, out = self.run_dg("auditar", "1")
        self.assertEqual(codigo, 1)
        self.assertIn("CITA VALIDADA NO ESTA EN EL TEXTO DE LA VERSION", out)

    def test_cita_rechazada_ausente_no_es_problema(self):
        c = self.abrir()
        c.execute(INSERT_HECHO, (1, "Aduana", "informar", "", "cita inventada por el modelo", "hecho",
                                 "rechazado", "cita_no_encontrada", FECHA))
        c.commit()
        self.assertEqual(self.run_dg("auditar", "1")[0], 0)

    def test_estados_contradictorios(self):
        c = self.abrir()
        c.execute(INSERT_HECHO, (1, "Banco Central de Bolivia", "anunciar", "", CITA, "hecho",
                                 "rechazado", "sujeto_generico", FECHA))
        c.commit()
        codigo, out = self.run_dg("auditar", "1")
        self.assertEqual(codigo, 1)
        self.assertIn("ESTADOS CONTRADICTORIOS", out)

    def test_detecta_duplicados_en_una_base_v3_sin_indice(self):
        c = self.abrir()
        c.execute(f"DROP INDEX {db_setup.NOMBRE_INDICE_HECHOS}")
        c.execute(INSERT_HECHO, (1, "Banco Central de Bolivia", "anunciar", "", CITA, "hecho",
                                 "validado", None, FECHA))
        c.commit()
        codigo, out = self.run_dg("auditar", "1")
        self.assertEqual(codigo, 1)
        self.assertIn("DUPLICADO", out)

    def test_version_inexistente(self):
        self.assertEqual(self.run_dg("auditar", "42")[0], 1)


class TestBackup(BaseDiagnostico):
    def test_backup_consistente_verificado_y_con_permisos_600(self):
        destino = os.path.join(self._dir.name, "copia.db")
        codigo, out = self.run_dg("backup", destino)
        self.assertEqual(codigo, 0, out)
        self.assertIn("VERIFICACION: OK", out)
        self.assertIn("integrity_check de la copia: ok", out)
        self.assertEqual(stat.S_IMODE(os.stat(destino).st_mode), 0o600)
        codigo, out = self.run_dg("base", db=destino)        # la copia es una base usable (restauracion)
        self.assertIn("hechos=2", out)
        self.assertIn("user_version=4", out)

    def test_backup_incluye_lo_que_solo_esta_en_el_wal(self):
        w = self.abrir()
        w.execute("PRAGMA journal_mode=WAL")
        w.execute("PRAGMA wal_autocheckpoint=0")
        w.execute(INSERT_HECHO, (1, "Banco Central de Bolivia", "decir", "x", CITA + " nuevas", "declaracion",
                                 "rechazado", "m", FECHA))
        w.commit()                                           # w sigue abierta: el dato vive en el -wal
        self.assertTrue(os.path.exists(self.ruta + "-wal"))
        destino = os.path.join(self._dir.name, "copia_wal.db")
        codigo, _ = self.run_dg("backup", destino)
        self.assertEqual(codigo, 0)
        c = sqlite3.connect(destino)
        self.addCleanup(c.close)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM hechos").fetchone()[0], 3)

    def test_backup_no_sobrescribe_un_archivo_existente(self):
        destino = os.path.join(self._dir.name, "ya_existe.db")
        with open(destino, "w") as f:
            f.write("importante")
        codigo, out = self.run_dg("backup", destino)
        self.assertEqual(codigo, 1)
        self.assertIn("no se sobrescribe", out)
        with open(destino) as f:
            self.assertEqual(f.read(), "importante")

    def test_backup_no_puede_apuntar_a_la_propia_base(self):
        antes = self.sha_archivo()
        codigo, out = self.run_dg("backup", self.ruta)
        self.assertEqual(codigo, 1)
        self.assertEqual(self.sha_archivo(), antes)

    def test_backup_no_cambia_la_base_origen(self):
        antes = self.sha_archivo()
        self.run_dg("backup", os.path.join(self._dir.name, "c.db"))
        self.assertEqual(self.sha_archivo(), antes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
