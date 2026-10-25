"""Conexión de IA y continuidad manual con un servicio simulado, sin claves reales."""
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import builtins
import unittest
from unittest.mock import Mock, patch

import httpx
from streamlit.testing.v1 import AppTest
import app


CLAVE_FICTICIA = "clave_ficticia_sin_validez"


class ErrorServicioSimulado(Exception):
    def __init__(self, codigo):
        super().__init__(CLAVE_FICTICIA)
        self.code = codigo


class ConexionIA(unittest.TestCase):
    def solicitar(self, respuesta="SMARTQUOTE_OK", error=None):
        with patch.object(app.st, "secrets", {"GEMINI_API_KEY": CLAVE_FICTICIA}):
            with patch("google.genai.Client") as crear_cliente:
                cliente = crear_cliente.return_value.__enter__.return_value
                cliente.models.generate_content.return_value = SimpleNamespace(text=respuesta)
                cliente.models.generate_content.side_effect = error
                resultado = app.probar_conexion_ia()
                return resultado, crear_cliente, cliente

    def test_clave_ausente_vacia_o_tipo_invalido_no_hace_peticion(self):
        for secretos in ({}, {"GEMINI_API_KEY": " "}, {"GEMINI_API_KEY": 123}, {"GEMINI_API_KEY": None}):
            with self.subTest(secretos=secretos):
                with patch.object(app.st, "secrets", secretos), patch("google.genai.Client") as cliente:
                    resultado = app.probar_conexion_ia()
                    self.assertFalse(resultado["ok"])
                    self.assertIn("GEMINI_API_KEY", resultado["mensaje"])
                    cliente.assert_not_called()

    def test_secreto_no_legible_no_expone_la_excepcion(self):
        secretos = Mock()
        secretos.get.side_effect = FileNotFoundError(CLAVE_FICTICIA)
        with patch.object(app.st, "secrets", secretos):
            resultado = app.probar_conexion_ia()
        self.assertFalse(resultado["ok"])
        self.assertNotIn(CLAVE_FICTICIA, str(resultado))

    def test_prueba_usa_clave_privada_y_una_peticion_acotada(self):
        resultado, crear, cliente = self.solicitar()
        self.assertTrue(resultado["ok"])
        self.assertEqual(crear.call_args.kwargs["api_key"], CLAVE_FICTICIA)
        opciones = crear.call_args.kwargs["http_options"]
        self.assertGreater(opciones.timeout, 0)
        self.assertLessEqual(opciones.timeout, 30_000)
        self.assertEqual(opciones.retry_options.attempts, 1)
        cliente.models.generate_content.assert_called_once()
        peticion = cliente.models.generate_content.call_args.kwargs
        self.assertEqual(peticion["model"], app.MODELO)
        self.assertIn("SMARTQUOTE_OK", peticion["contents"])
        self.assertNotIn(CLAVE_FICTICIA, peticion["contents"])
        self.assertLessEqual(peticion["config"].max_output_tokens, 256)
        self.assertNotIn(CLAVE_FICTICIA, str(resultado))

    def test_respuesta_vacia_o_inesperada_no_declara_exito(self):
        for respuesta in (None, "", "otro contenido " + CLAVE_FICTICIA):
            with self.subTest(respuesta=respuesta):
                resultado, _, _ = self.solicitar(respuesta=respuesta)
                self.assertFalse(resultado["ok"])
                self.assertIn("confirmación esperada", resultado["mensaje"])
                self.assertNotIn(CLAVE_FICTICIA, str(resultado))

    def test_errores_de_cuota_acceso_modelo_y_servicio_son_claros(self):
        for codigo, esperado in ((429, "cuota"), (401, "clave"), (403, "acceso"), (400, "petición"), (404, "modelo"), (503, "disponible")):
            with self.subTest(codigo=codigo):
                resultado, _, cliente = self.solicitar(error=ErrorServicioSimulado(codigo))
                self.assertFalse(resultado["ok"])
                self.assertIn(esperado, resultado["mensaje"].lower())
                self.assertNotIn(CLAVE_FICTICIA, str(resultado))
                cliente.models.generate_content.assert_called_once()

    def test_tiempo_de_espera_y_conexion_sin_detalles_privados(self):
        for error, esperado in ((httpx.ReadTimeout(CLAVE_FICTICIA), "tardó"), (httpx.ConnectError(CLAVE_FICTICIA), "conectar")):
            with self.subTest(tipo=type(error).__name__):
                resultado, _, _ = self.solicitar(error=error)
                self.assertFalse(resultado["ok"])
                self.assertIn(esperado, resultado["mensaje"])
                self.assertNotIn(CLAVE_FICTICIA, str(resultado))

    def test_error_inesperado_no_revela_el_contenido(self):
        resultado, _, _ = self.solicitar(error=RuntimeError(CLAVE_FICTICIA))
        self.assertFalse(resultado["ok"])
        self.assertNotIn(CLAVE_FICTICIA, str(resultado))

    def test_sdk_ausente_se_informa_sin_bloquear_calculos(self):
        importar = builtins.__import__

        def sin_sdk(nombre, *args, **kwargs):
            if nombre == "google":
                raise ImportError(CLAVE_FICTICIA)
            return importar(nombre, *args, **kwargs)

        with patch.object(app.st, "secrets", {"GEMINI_API_KEY": CLAVE_FICTICIA}), patch("builtins.__import__", side_effect=sin_sdk):
            resultado = app.probar_conexion_ia()
        self.assertFalse(resultado["ok"])
        self.assertIn("google-genai", resultado["mensaje"])
        self.assertNotIn(CLAVE_FICTICIA, str(resultado))
        self.assertEqual(app.convertir_total(Decimal("900"), Decimal("1.10")), Decimal("990.00"))


class RecorridoConexion(unittest.TestCase):
    def nueva_app(self, clave=True):
        at = AppTest.from_file(str(Path(app.__file__).resolve()), default_timeout=30)
        if clave:
            at.secrets["GEMINI_API_KEY"] = CLAVE_FICTICIA
        return at.run()

    def test_arranque_y_registro_manual_no_llaman_a_la_api(self):
        with patch("google.genai.Client") as cliente:
            at = self.nueva_app()
            at.button("agregar").click().run()
            self.assertFalse(at.exception)
            cliente.assert_not_called()

    def test_exito_solo_al_pulsar_y_sin_repetir_por_otros_cambios(self):
        with patch("google.genai.Client") as crear:
            cliente = crear.return_value.__enter__.return_value
            cliente.models.generate_content.return_value = SimpleNamespace(text="SMARTQUOTE_OK")
            at = self.nueva_app()
            cliente.models.generate_content.assert_not_called()
            at.button("probar_conexion_ia").click().run()
            self.assertTrue(at.session_state["prueba_conexion_ia"]["ok"])
            at.text_input("moneda_analisis").set_value("USD").run()
            self.assertFalse(at.exception)
            cliente.models.generate_content.assert_called_once()

    def test_cuota_agotada_conserva_ofertas_y_permite_analizarlas(self):
        with patch("google.genai.Client") as crear:
            cliente = crear.return_value.__enter__.return_value
            cliente.models.generate_content.side_effect = ErrorServicioSimulado(429)
            at = self.nueva_app()
            at.button("cargar_ejemplo").click().run()
            at.button("probar_conexion_ia").click().run()
            self.assertFalse(at.session_state["prueba_conexion_ia"]["ok"])
            self.assertEqual(len(at.session_state["cotizaciones_confirmadas"]), 2)
            next(b for b in at.button if b.label == "Analizar cotizaciones").click().run()
            self.assertFalse(at.exception)
            self.assertIsNotNone(at.session_state["resultado"])
            self.assertEqual(len(at.session_state["cotizaciones_confirmadas"]), 2)
            cliente.models.generate_content.assert_called_once()
            self.assertNotIn(CLAVE_FICTICIA, str([w.value for w in at.warning]))

    def test_sin_clave_la_prueba_no_impide_el_ejemplo_manual(self):
        with patch("google.genai.Client") as cliente:
            at = self.nueva_app(clave=False)
            at.button("probar_conexion_ia").click().run()
            at.button("cargar_ejemplo").click().run()
            next(b for b in at.button if b.label == "Analizar cotizaciones").click().run()
            self.assertFalse(at.exception)
            self.assertIsNotNone(at.session_state["resultado"])
            cliente.assert_not_called()


if __name__ == "__main__":
    unittest.main()
