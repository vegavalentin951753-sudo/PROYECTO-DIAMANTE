"""Pruebas del Modulo 2.1 (afinacion del extractor). Solo unittest."""
import unittest

import extractor_json as ex


def _hecho(**kw):
    base = {"sujeto": "Banco Central de Bolivia", "accion": "anuncio",
            "objeto": "nuevas medidas",
            "cita_literal": "El Banco Central de Bolivia anunció ayer nuevas medidas",
            "tipo": "hecho"}
    base.update(kw)
    return base


FRAGMENTO = ("El Banco Central de Bolivia anunció ayer nuevas medidas "
             "cambiarias. El ministro de Economía dijo que seguirá "
             "el diálogo con los exportadores.")


class TestFragmentarAfinado(unittest.TestCase):
    def test_fragmentar_no_corta_palabras(self):
        texto = ("Los comerciantes de la zona informaron que cerraron "
                 "los puestos de venta del mercado durante toda la jornada "
                 "de ayer por falta de abastecimiento")
        max_chars = texto.index("venta") + 4
        frags = ex.fragmentar(texto, max_chars=max_chars)
        self.assertGreater(len(frags), 1)
        palabras = set(texto.split())
        for f in frags:
            self.assertLessEqual(len(f), max_chars)
            self.assertFalse(f.endswith("vent"), f)
            self.assertIn(f.split()[0], palabras, f)
            self.assertIn(f.split()[-1], palabras, f)
        self.assertEqual(" ".join(frags).split(), texto.split())

    def test_fragmentar_respeta_oraciones(self):
        o1 = "El precio del dolar subio en el mercado paralelo."
        o2 = "Los importadores pidieron una reunion con el gobierno."
        o3 = "La Aduana informo que revisara los contenedores."
        frags = ex.fragmentar(f"{o1} {o2} {o3}", max_chars=70)
        self.assertEqual(frags, [o1, o2, o3])

    def test_corte_seguro_no_deja_resto_vacio(self):
        texto = "a" * 60 + "; " + "b" * 20
        frags = ex.fragmentar(texto, max_chars=63)
        self.assertEqual(" ".join(frags).replace(" ", ""), texto.replace(" ", ""))
        for f in frags:
            self.assertLessEqual(len(f), 63)


class TestGuardianSujetos(unittest.TestCase):
    def test_guardian_rechaza_sujeto_generico(self):
        h = _hecho(sujeto="la institución",
                   cita_literal="El Banco Central de Bolivia anunció ayer nuevas medidas")
        self.assertEqual(ex.validar_hecho(h, FRAGMENTO), (False, "sujeto_generico"))

    def test_guardian_rechaza_sujeto_ausente(self):
        h = _hecho(cita_literal="El ministro de Economía dijo que seguirá")
        self.assertEqual(ex.validar_hecho(h, FRAGMENTO), (False, "sujeto_no_en_cita"))

    def test_guardian_acepta_sujeto_en_cita(self):
        self.assertEqual(ex.validar_hecho(_hecho(), FRAGMENTO), (True, None))

    def test_guardian_acepta_sujeto_corto_con_match_parcial(self):
        # Comportamiento conocido: 'Banco' matchea dentro de 'bancos'.
        # Si en el futuro se endurece la regla, actualizar este test.
        h = _hecho(sujeto="Banco",
                   cita_literal="Los bancos comerciales reportaron pérdidas")
        ok, _ = ex.validar_hecho(h, "Los bancos comerciales reportaron pérdidas ayer.")
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
