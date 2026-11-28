"""Pruebas del Modulo 2.3: persistencia idempotente, conteo real de inserciones,
--input que no confunde rutas con texto, y metricas de la corrida.

Solo unittest. Ninguna prueba usa el modelo real ni Internet. Las bases son
archivos temporales creados con el ESQUEMA REAL (db_setup.aplicar_esquema), no
con una copia minima; ninguna toca la base de verdad.
"""
import contextlib
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest import mock

import db_setup
import extractor_json as ex

FECHA = "2026-11-27T12:00:00Z"
FRAG = ("El Ministerio de Economia anuncio el lunes un decreto que reduce el "
        "arancel de importacion al 5% para maquinaria agricola.")
CITA = ("El Ministerio de Economia anuncio el lunes un decreto que reduce "
        "el arancel de importacion al 5% para maquinaria agricola")


def hecho(**cambios):
    h = {"sujeto": "Ministerio de Economia", "accion": "anunciar",
         "objeto": "decreto que reduce el arancel al 5%", "cita_literal": CITA, "tipo": "hecho"}
    h.update(cambios)
    return h


def resultado(aceptados=(), rechazados=()):
    return {"aceptados": list(aceptados),
            "rechazados": [{"hecho": h, "motivo": m} for h, m in rechazados]}


def salida(hechos):
    return json.dumps({"hechos": hechos}, ensure_ascii=False)


def runner_con(texto_salida, **extra):
    llamadas = []

    def _r(prompt, **kw):
        llamadas.append(prompt)
        d = {"ok": True, "salida": texto_salida, "timeout": False, "err": "",
             "perf": {"gen_tokens": 100, "gen_tps": 9.0}}
        d.update(extra)
        return d
    _r.llamadas = llamadas
    return _r


class BaseConEsquemaReal(unittest.TestCase):
    """BD temporal con el esquema v4 real y una version (id=1) ya cargada."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.ruta = os.path.join(self._dir.name, "prueba.db")
        c = sqlite3.connect(self.ruta)
        db_setup.aplicar_esquema(c)
        c.execute("INSERT INTO documentos (id, url_canonica, url_original, fuente, primera_captura) "
                  "VALUES (1, 'u', 'u', 'prueba', ?)", (FECHA,))
        c.execute("INSERT INTO versiones (id, documento_id, hash_texto, texto_limpio, fecha_captura) "
                  "VALUES (1, 1, 'h', 'texto', ?)", (FECHA,))
        c.commit()
        c.close()
        self.conexiones = 0

        def conectar():
            self.conexiones += 1
            c = sqlite3.connect(self.ruta)
            c.execute("PRAGMA foreign_keys=ON")
            return c
        self.db_falsa = types.SimpleNamespace(conectar=conectar, ahora_utc=lambda: FECHA)

    def conn(self):
        c = sqlite3.connect(self.ruta)
        c.execute("PRAGMA foreign_keys=ON")
        self.addCleanup(c.close)
        return c

    def filas(self, columnas="version_id, tipo, estado, motivo_rechazo, cita_literal"):
        c = sqlite3.connect(self.ruta)
        try:
            return c.execute(f"SELECT {columnas} FROM hechos ORDER BY id").fetchall()
        finally:
            c.close()

    def correr(self, argv, runner):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(sys.modules, {"db": self.db_falsa}), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            codigo = ex.main(argv, runner=runner)
        return codigo, out.getvalue(), err.getvalue()


# --------------------------------------------------- conteo e idempotencia
class TestGuardarResultado(BaseConEsquemaReal):
    def guardar(self, res, version_id=1):
        conn = self.conn()
        return ex.guardar_resultado(conn, version_id, res, FECHA)

    def test_primera_insercion_cuenta_filas_nuevas_reales(self):
        res = resultado([hecho()], [(hecho(cita_literal=CITA.replace("reduce", "sube")), "cita_no_encontrada")])
        c = self.guardar(res)
        self.assertEqual(c, {"validadas_insertadas": 1, "validadas_omitidas": 0,
                             "rechazadas_insertadas": 1, "rechazadas_omitidas": 0, "sin_registro": 0})
        self.assertEqual(len(self.filas()), 2)

    def test_repetir_no_duplica_y_se_cuenta_como_omitida(self):
        res = resultado([hecho()], [(hecho(cita_literal=CITA.replace("reduce", "sube")), "cita_no_encontrada")])
        self.guardar(res)
        c = self.guardar(res)
        self.assertEqual(c["validadas_insertadas"] + c["rechazadas_insertadas"], 0)
        self.assertEqual((c["validadas_omitidas"], c["rechazadas_omitidas"]), (1, 1))
        self.assertEqual(len(self.filas()), 2)

    def test_mismo_hecho_dos_veces_en_el_mismo_fragmento(self):
        c = self.guardar(resultado([hecho(), hecho()]))
        self.assertEqual((c["validadas_insertadas"], c["validadas_omitidas"]), (1, 1))
        self.assertEqual(len(self.filas()), 1)

    def test_objeto_null_previo_y_objeto_vacio_nuevo_son_el_mismo_hecho(self):
        conn = self.conn()
        with conn:
            conn.execute("INSERT INTO hechos (version_id, sujeto, accion, objeto, cita_literal, tipo, "
                         "estado, fecha_creacion) VALUES (1, 'Ministerio de Economia', 'anunciar', NULL, ?, "
                         "'hecho', 'validado', ?)", (CITA, FECHA))
        c = ex.guardar_resultado(conn, 1, resultado([hecho(objeto="")]), FECHA)
        self.assertEqual((c["validadas_insertadas"], c["validadas_omitidas"]), (0, 1))
        self.assertEqual(len(self.filas()), 1)

    def test_otra_version_no_es_duplicado(self):
        conn = self.conn()
        with conn:
            conn.execute("INSERT INTO versiones (id, documento_id, hash_texto, texto_limpio, fecha_captura) "
                         "VALUES (2, 1, 'h2', 'otro', ?)", (FECHA,))
        ex.guardar_resultado(conn, 1, resultado([hecho()]), FECHA)
        c = ex.guardar_resultado(conn, 2, resultado([hecho()]), FECHA)
        self.assertEqual(c["validadas_insertadas"], 1)
        self.assertEqual([f[0] for f in self.filas()], [1, 2])

    def test_decision_misma_cita_con_distinto_estado_convive(self):
        # Si el Guardian cambia, la cita rechazada antes y validada ahora no se pisan.
        self.guardar(resultado(rechazados=[(hecho(), "sujeto_generico")]))
        c = self.guardar(resultado([hecho()]))
        self.assertEqual(c["validadas_insertadas"], 1)
        self.assertEqual([f[2] for f in self.filas()], ["rechazado", "validado"])

    def test_decision_distinto_tipo_se_conserva(self):
        self.guardar(resultado([hecho()]))
        c = self.guardar(resultado([hecho(tipo="declaracion")]))
        self.assertEqual(c["validadas_insertadas"], 1)

    def test_rechazados_sin_estructura_se_cuentan_aparte(self):
        res = resultado([hecho()], [("basura", "estructura_invalida: el hecho no es un objeto")])
        c = self.guardar(res)
        self.assertEqual((c["sin_registro"], c["validadas_insertadas"], c["rechazadas_insertadas"]), (1, 1, 0))

    def test_error_de_la_base_revierte_el_fragmento_y_no_se_oculta(self):
        # el 2.o hecho viola el CHECK de tipo: ON CONFLICT DO NOTHING NO debe silenciarlo
        res = resultado([hecho(), hecho(sujeto="Otro Ministerio", tipo="otro")])
        with self.assertRaises(sqlite3.IntegrityError):
            self.guardar(res)
        self.assertEqual(self.filas(), [])

    def test_version_inexistente_lanza_y_no_deja_filas(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.guardar(resultado([hecho()]), version_id=999)
        self.assertEqual(self.filas(), [])

    def test_rowcount_inesperado_se_trata_como_error(self):
        class Cursor:
            rowcount = -1

        class ConnFalsa:
            revertida = False

            def __enter__(self):
                return self

            def __exit__(self, tipo, valor, tb):
                ConnFalsa.revertida = tipo is not None
                return False

            def execute(self, *a):
                return Cursor()
        with self.assertRaises(RuntimeError):
            ex.guardar_resultado(ConnFalsa(), 1, resultado([hecho()]), FECHA)
        self.assertTrue(ConnFalsa.revertida)

    def test_la_clave_de_unicidad_no_depende_de_la_fecha(self):
        conn = self.conn()
        ex.guardar_resultado(conn, 1, resultado([hecho()]), "2026-11-27T10:00:00Z")
        c = ex.guardar_resultado(conn, 1, resultado([hecho()]), "2026-11-28T10:00:00Z")
        self.assertEqual(c["validadas_omitidas"], 1)
        self.assertEqual(self.filas("fecha_creacion"), [("2026-11-27T10:00:00Z",)])


# ------------------------------------------------------ --guardar de punta a punta
class TestMainGuardar(BaseConEsquemaReal):
    ARGV = ["--input", FRAG, "--guardar", "--version-id", "1"]

    def test_resumen_distingue_insertadas_omitidas_y_veredictos(self):
        r = runner_con(salida([hecho(), hecho(cita_literal=CITA.replace("reduce", "sube"))]))
        codigo, out, _ = self.correr(self.ARGV, r)
        self.assertEqual(codigo, 0)
        self.assertIn("aceptados=1 rechazados=1 errores=0 (proceso=0 guardado=0)", out)
        self.assertIn("filas_insertadas=2 (validadas=1 rechazadas=1)", out)
        self.assertIn("omitidas_por_duplicado=0", out)
        codigo, out, _ = self.correr(self.ARGV, r)          # segunda corrida identica
        self.assertEqual(codigo, 0)
        self.assertIn("aceptados=1 rechazados=1", out)       # el Guardian opina igual...
        self.assertIn("filas_insertadas=0 (validadas=0 rechazadas=0)", out)   # ...pero no se inserta nada
        self.assertIn("omitidas_por_duplicado=2 (validadas=1 rechazadas=1)", out)
        self.assertEqual(len(self.filas()), 2)

    def test_exige_esquema_v4_antes_de_llamar_al_modelo(self):
        c = sqlite3.connect(self.ruta)
        c.execute(f"DROP INDEX {db_setup.NOMBRE_INDICE_HECHOS}")
        c.commit()
        c.close()
        r = runner_con(salida([hecho()]))
        with self.assertLogs("extractor_json", level="ERROR") as logs:
            codigo, out, _ = self.correr(self.ARGV, r)
        self.assertEqual(codigo, 4)
        self.assertEqual(r.llamadas, [])
        self.assertEqual(self.filas(), [])
        self.assertIn("python db_setup.py", "\n".join(logs.output))
        self.assertNotIn("Resumen", out)

    def test_dry_run_no_exige_esquema_ni_conecta(self):
        c = sqlite3.connect(self.ruta)
        c.execute(f"DROP INDEX {db_setup.NOMBRE_INDICE_HECHOS}")
        c.commit()
        c.close()
        codigo, _, _ = self.correr(["--input", FRAG], runner_con(salida([hecho()])))
        self.assertEqual((codigo, self.conexiones), (0, 0))

    def test_version_inexistente_con_esquema_real(self):
        codigo, out, err = self.correr(["--input", FRAG, "--guardar", "--version-id", "999"],
                                       runner_con(salida([hecho()])))
        self.assertEqual(codigo, 3)
        self.assertIn("guardado_fallo", out + err)
        self.assertIn("guardado=1", out)
        self.assertIn("filas_insertadas=0", out)
        self.assertEqual(self.filas(), [])

    def test_fallo_parcial_de_guardado_da_codigo_5_y_conserva_lo_anterior(self):
        texto = "\n".join(f"Linea {i}. " + "x" * 600 for i in (1, 2, 3))
        original = ex.guardar_resultado
        llamadas = {"n": 0}

        def a_veces_falla(conn, vid, res, ahora):
            llamadas["n"] += 1
            if llamadas["n"] == 2:
                raise sqlite3.OperationalError("disk I/O error (simulado)")
            return original(conn, vid, res, ahora)

        def runner(prompt, **kw):
            n = re.search(r"Linea (\d+)\.", prompt).group(1)
            return {"ok": True, "timeout": False, "perf": {},
                    "salida": salida([hecho(sujeto="Linea", accion="anunciar", objeto="",
                                            cita_literal=f"Linea {n}. " + "x" * 40)])}
        with mock.patch.object(ex, "guardar_resultado", a_veces_falla):
            codigo, out, _ = self.correr(["--input", texto, "--guardar", "--version-id", "1"], runner)
        self.assertEqual(codigo, 5)
        self.assertIn("errores=1 (proceso=0 guardado=1)", out)
        self.assertIn("filas_insertadas=2", out)
        self.assertEqual([f[4][:7] for f in self.filas()], ["Linea 1", "Linea 3"])

    def test_corrida_interrumpida_y_reanudada_no_duplica(self):
        texto = "\n".join(f"Linea {i}. " + "x" * 600 for i in (1, 2, 3))

        def hecho_de(prompt):
            n = re.search(r"Linea (\d+)\.", prompt).group(1)
            return {"ok": True, "timeout": False, "perf": {},
                    "salida": salida([hecho(sujeto="Linea", accion="anunciar", objeto="",
                                            cita_literal=f"Linea {n}. " + "x" * 40)])}
        vistos = {"n": 0}

        def interrumpido(prompt, **kw):
            vistos["n"] += 1
            if vistos["n"] == 3:
                raise KeyboardInterrupt()          # Ctrl-C a mitad de la corrida
            return hecho_de(prompt)
        argv = ["--input", texto, "--guardar", "--version-id", "1"]
        with self.assertRaises(KeyboardInterrupt):
            self.correr(argv, interrumpido)
        self.assertEqual(len(self.filas()), 2)      # lo ya guardado se conserva; nada a medias
        codigo, out, _ = self.correr(argv, lambda p, **kw: hecho_de(p))
        self.assertEqual(codigo, 0)
        self.assertIn("filas_insertadas=1", out)                 # solo falta la 3.a
        self.assertIn("omitidas_por_duplicado=2", out)           # las 2 primeras ya estaban
        self.assertEqual(len(self.filas()), 3)
        c = sqlite3.connect(self.ruta)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM (SELECT 1 FROM hechos GROUP BY version_id, tipo, "
                                   "estado, cita_literal HAVING COUNT(*) > 1)").fetchone()[0], 0)
        c.close()

    def test_errores_de_proceso_y_de_guardado_se_separan(self):
        texto = "\n".join(f"Linea {i}. " + "x" * 600 for i in (1, 2))
        respuestas = iter([{"ok": False, "err": "fallo"}, {"ok": True, "salida": salida([]), "perf": {}}])
        codigo, out, _ = self.correr(["--input", texto, "--guardar", "--version-id", "1"],
                                     lambda p, **kw: next(respuestas))
        self.assertEqual(codigo, 0)
        self.assertIn("errores=1 (proceso=1 guardado=0)", out)

    def test_constantes_del_indice_coinciden(self):
        self.assertEqual(ex.INDICE_IDENTIDAD, db_setup.NOMBRE_INDICE_HECHOS)
        self.assertIn(ex.INDICE_IDENTIDAD, db_setup.SQL_INDICE_HECHOS)


# ------------------------------------------------------------------- --input
class TestParecerRuta(unittest.TestCase):
    def test_criterios_documentados(self):
        for v in ("/tmp/x", "./nota", "~/nota", "../nota", "a.txt", "a.MD", "a.json", "a.Html",
                  "carpeta/archivo.txt", "  /tmp/x  "):
            with self.subTest(v=v):
                self.assertTrue(ex.parece_ruta(v))

    def test_texto_literal_no_parece_ruta(self):
        for v in (FRAG, "El dolar subio 5/10 en el mercado", "", "   ", "informe.pdf",
                  "Primera linea\nsegunda linea termina en archivo.txt", "ver la carpeta /tmp\ny luego el .md"):
            with self.subTest(v=v):
                self.assertFalse(ex.parece_ruta(v))


class TestLeerEntrada(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.dir = self._dir.name
        self.archivo = os.path.join(self.dir, "nota.txt")
        with open(self.archivo, "w", encoding="utf-8") as f:
            f.write(FRAG)

    def test_ruta_existente_absoluta(self):
        self.assertEqual(ex.leer_entrada(self.archivo), FRAG)

    def test_ruta_existente_relativa_con_punto_barra(self):
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(self.dir)
        self.assertEqual(ex.leer_entrada("./nota.txt"), FRAG)

    def test_ruta_con_tilde_se_expande(self):
        with mock.patch.dict(os.environ, {"HOME": self.dir}):
            self.assertEqual(ex.leer_entrada("~/nota.txt"), FRAG)

    def test_archivo_existente_sin_pinta_de_ruta_se_sigue_leyendo(self):
        # compatibilidad con el comportamiento anterior (os.path.isfile)
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(self.dir)
        os.rename(self.archivo, os.path.join(self.dir, "nota"))
        self.assertEqual(ex.leer_entrada("nota"), FRAG)

    def test_ruta_inexistente_es_error_claro_por_cada_criterio(self):
        for v in ("/no/existe/nada", "./no_existe.txt", "~/no_existe_xyz", "../no_existe", "no_existe.md",
                  "no_existe.JSON", "no_existe.html", os.path.join(self.dir, "falta.txt")):
            with self.subTest(v=v), self.assertRaises(FileNotFoundError) as cm:
                ex.leer_entrada(v)
            self.assertIn(repr(v), str(cm.exception))
            self.assertIn("no existe", str(cm.exception))

    def test_carpeta_es_error(self):
        with self.assertRaises(IsADirectoryError):
            ex.leer_entrada(self.dir + "/")

    def test_texto_literal_se_acepta_tal_cual(self):
        for v in (FRAG, "El dolar subio 5/10", "Linea uno\nLinea dos termina en .txt", "informe.pdf"):
            with self.subTest(v=v):
                self.assertEqual(ex.leer_entrada(v), v)

    def test_archivo_con_bytes_invalidos_no_rompe(self):
        ruta = os.path.join(self.dir, "raro.txt")
        with open(ruta, "wb") as f:
            f.write(b"hola \xff\xfe mundo")
        self.assertIn("hola", ex.leer_entrada(ruta))


class TestMainInput(BaseConEsquemaReal):
    def test_ruta_inexistente_no_se_procesa_como_texto_ni_llama_al_modelo(self):
        r = runner_con(salida([hecho()]))
        with self.assertLogs("extractor_json", level="ERROR") as logs:
            codigo, out, _ = self.correr(["--input", "/no/existe/noticia.txt"], r)
        self.assertEqual(codigo, 1)
        self.assertEqual(r.llamadas, [])
        self.assertIn("no existe", "\n".join(logs.output))
        self.assertNotIn("Resumen", out)

    def test_ruta_inexistente_con_guardar_no_conecta_a_la_base(self):
        r = runner_con(salida([hecho()]))
        codigo, _, _ = self.correr(["--input", "./falta.md", "--guardar", "--version-id", "1"], r)
        self.assertEqual((codigo, self.conexiones, r.llamadas, self.filas()), (1, 0, [], []))

    def test_texto_literal_sigue_funcionando(self):
        r = runner_con(salida([hecho()]))
        codigo, out, _ = self.correr(["--input", FRAG], r)
        self.assertEqual(codigo, 0)
        self.assertIn("aceptados=1", out)


# ------------------------------------------------------------------- metricas
class TestMetricas(unittest.TestCase):
    def test_procesar_fragmento_registra_orden_de_veredictos(self):
        malo = hecho(cita_literal=CITA.replace("reduce", "sube"))
        res = ex.procesar_fragmento(FRAG, runner=runner_con(salida([hecho(), malo, hecho(sujeto="El")])))
        self.assertEqual(res["orden"], "ARR")

    def test_meta_incluye_tiempos_si_el_runner_los_trae(self):
        r = runner_con(salida([]), segundos=41.5, ram_pico_mb=2048.0)
        r2 = runner_con(salida([]), segundos=41.5, ram_pico_mb=2048.0, perf={"gen_tokens": 7, "prompt_tokens": 300})
        meta = ex.procesar_fragmento(FRAG, runner=r2)["meta"]
        self.assertEqual(meta, {"gen_tokens": 7, "prompt_tokens": 300, "segundos": 41.5, "ram_pico_mb": 2048.0})
        self.assertEqual(ex.procesar_fragmento(FRAG, runner=r)["meta"]["segundos"], 41.5)

    def test_resumen_de_metricas_con_datos_sinteticos(self):
        def r(aceptados, rechazados, orden, gen, **meta):
            return {"fragmento": "f", "aceptados": aceptados,
                    "rechazados": [{"hecho": {}, "motivo": m} for m in rechazados],
                    "error": None, "orden": orden, "meta": dict(gen_tokens=gen, **meta)}
        corto = {"cita_literal": "a" * 50}
        largo = {"cita_literal": "b" * 200}
        resultados = [
            r([corto, largo], ["sujeto_generico"], "AAR", 383, segundos=40.0),
            r([corto], [], "A", 120, segundos=20.0),
            r([], [], "", 50),
            {"fragmento": "f", "aceptados": [], "rechazados": [], "meta": {},
             "error": "json_invalido: x (pos 3)", "orden": ""},
        ]
        texto = "\n".join(ex.resumir_metricas(resultados))
        self.assertIn(f"tope={ex.MAX_TOKENS_LLM} gen_tokens_por_fragmento=[383, 120, 50]", texto)
        self.assertIn("json_invalido=1", texto)
        self.assertIn("segundos_por_fragmento=[40.0, 20.0] total=60.0", texto)
        self.assertIn("hechos_por_fragmento=[3, 1, 0]", texto)
        self.assertIn("#1:2/0, #2:1/0, #3:0/1", texto)
        self.assertIn("n=3 p50=50 p90=200 max=200", texto)
        self.assertIn("motivos_rechazo=sujeto_generico:1", texto)

    def test_sin_resultados_no_imprime_nada(self):
        self.assertEqual(ex.resumir_metricas([]), [])

    def test_main_imprime_metricas_tambien_en_dry_run(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            ex.main(["--input", FRAG], runner=runner_con(salida([hecho()])))
        self.assertIn("Metricas:", out.getvalue())
        self.assertIn("#1:1/0", out.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
