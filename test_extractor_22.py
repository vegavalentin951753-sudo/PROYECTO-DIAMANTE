"""Pruebas del Modulo 2.2 (Bug A: salida cortada / control; Bug B: sujeto fuera de cita).
Solo unittest. Ninguna prueba usa el modelo real."""
import json
import unittest

import extractor_json as ex

FRAG = (
    "El Ministerio de Economia anuncio el lunes un decreto que reduce el "
    "arancel de importacion al 5% para maquinaria agricola. Un dirigente "
    "empresarial dijo que la medida es insuficiente."
)
CITA_OK = ("El Ministerio de Economia anuncio el lunes un decreto que reduce "
           "el arancel de importacion al 5% para maquinaria agricola")


def hecho(**cambios):
    h = {"sujeto": "Ministerio de Economia", "accion": "anunciar",
         "objeto": "decreto que reduce el arancel al 5%",
         "cita_literal": CITA_OK, "tipo": "hecho"}
    h.update(cambios)
    return h


def cortada(hechos_completos, cola):
    """Salida como la de Bug A: hechos completos + un hecho cortado en `cola`."""
    base = json.dumps({"hechos": hechos_completos}, ensure_ascii=False)
    return base[:-2] + ", " + cola      # quita ']}' y deja el array abierto


COLA_REAL = ('{"sujeto": "ANH", "accion": "informar", "objeto": "x", '
             '"cita_literal": "La Agencia Nacional\n\n')


class TestBugACaracterDeControl(unittest.TestCase):
    def test_json_con_caracter_de_control_se_parsea(self):
        crudo = ('{"hechos": [{"sujeto": "Ministerio de Economia", "accion": "anunciar", '
                 '"objeto": "decreto", "cita_literal": "' + CITA_OK + '\n", "tipo": "hecho"}]}')
        lista, err = ex.extraer_hechos_de_salida(crudo)
        self.assertIsNone(err)
        self.assertEqual(len(lista), 1)

    def test_salida_cortada_recupera_hechos_completos(self):
        crudo = cortada([hecho(), hecho(sujeto="Otro")], '{"sujeto": "Mini')
        lista, err = ex.extraer_hechos_de_salida(crudo)
        self.assertIsNone(err)
        self.assertEqual([h["sujeto"] for h in lista], ["Ministerio de Economia", "Otro"])

    def test_salida_real_cortada_con_saltos_al_final(self):
        # Forma exacta observada en el telefono (pos 1299: \n dentro de un string sin cerrar).
        crudo = cortada([hecho(), hecho(sujeto="Otro")], COLA_REAL)
        lista, err = ex.extraer_hechos_de_salida(crudo)
        self.assertIsNone(err)
        self.assertEqual(len(lista), 2)

    def test_cortada_sin_hechos_completos_sigue_siendo_error(self):
        crudo = '{"hechos": [' + COLA_REAL
        lista, err = ex.extraer_hechos_de_salida(crudo)
        self.assertEqual(lista, [])
        self.assertTrue(err.startswith("json_invalido"), err)

    def test_recuperacion_respeta_el_tope_de_hechos(self):
        crudo = cortada([hecho()] * 8, COLA_REAL)
        lista, _ = ex.extraer_hechos_de_salida(crudo)
        self.assertEqual(len(lista), ex.MAX_HECHOS_POR_FRAGMENTO)


def _runner(salida, **extra):
    def _r(prompt, **kw):
        d = {"ok": True, "salida": salida, "timeout": False, "err": "",
             "perf": {"gen_tokens": 384, "gen_tps": 9.5}}   # forma REAL de llm_runner
        d.update(extra)
        return d
    return _r


class TestProcesarSalidaCortada(unittest.TestCase):
    def test_fragmento_con_salida_cortada_no_es_error(self):
        crudo = cortada([hecho()], COLA_REAL)
        res = ex.procesar_fragmento(FRAG, runner=_runner(crudo))
        self.assertIsNone(res["error"])
        self.assertEqual(len(res["aceptados"]), 1)
        self.assertTrue(res["meta"].get("salida_recuperada"))

    def test_hechos_rescatados_pasan_por_el_guardian(self):
        malo = hecho(cita_literal=CITA_OK.replace("reduce", "sube"))
        crudo = cortada([hecho(), malo], COLA_REAL)
        res = ex.procesar_fragmento(FRAG, runner=_runner(crudo))
        self.assertEqual(len(res["aceptados"]), 1)
        self.assertEqual([r["motivo"] for r in res["rechazados"]], ["cita_no_encontrada"])

    def test_meta_lee_perf_anidado_del_runner_real(self):
        crudo = json.dumps({"hechos": [hecho()]}, ensure_ascii=False)
        res = ex.procesar_fragmento(FRAG, runner=_runner(crudo))
        self.assertEqual(res["meta"], {"gen_tokens": 384, "gen_tps": 9.5})


class TestBugBSujetoFueraDeCita(unittest.TestCase):
    def test_guardian_rechaza_sujeto_fuera_de_cita_parcial(self):
        # Caso real v243 frag 3: la cita no contiene "Marka".
        frag = ("El secretario ejecutivo de la Federacion de Choferes Chuquiago "
                "Marka, Santos Escalante, agradecio las gestiones de la entidad "
                "reguladora y senalo que las decisiones permitiran mejorar el servicio.")
        h = {"sujeto": "Marka", "accion": "agradeció",
             "objeto": "gestiones de la entidad reguladora",
             "cita_literal": "agradecio las gestiones de la entidad reguladora",
             "tipo": "hecho"}
        self.assertEqual(ex.validar_hecho(h, frag), (False, "sujeto_no_en_cita"))


if __name__ == "__main__":
    unittest.main()
