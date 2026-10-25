"""Explicación sobre hechos calculados y vigencia de sesión; Gemini simulado."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import unittest

import httpx
from google import genai
from streamlit.testing.v1 import AppTest
import app
from test_analysis import compra, configuracion, producto
from test_ia import CLAVE_FICTICIA, ErrorServicioSimulado


def analisis(**cambios):
    ofertas = [compra(1), compra(2, "1080", "12")]
    return app.crear_analisis(ofertas, "USD", {}, configuracion(ofertas, **cambios))


def respuesta_valida(contexto):
    return {tema: {"hechos": [next(h["id"] for h in contexto["hechos"] if h["tema"] == tema)],
                   "interpretacion": "La alternativa citada debe evaluarse según tu prioridad y las condiciones confirmadas.",
                   "siguiente_paso": "Revisa las condiciones pendientes antes de seleccionar al proveedor."}
            for tema in app.TEMAS_EXPLICACION}


def responder(**peticion):
    contexto = json.loads(peticion["contents"].split("\n", 1)[1])
    return SimpleNamespace(text=json.dumps(respuesta_valida(contexto)), candidates=[SimpleNamespace(finish_reason="STOP")])


def cliente_simulado(crear):
    cliente = crear.return_value.__enter__.return_value
    cliente.models.generate_content.side_effect = responder
    return cliente


def demo():
    at = AppTest.from_file(str(Path(app.__file__).resolve()), default_timeout=30)
    at.secrets["GEMINI_API_KEY"] = CLAVE_FICTICIA
    at.run().button("cargar_ejemplo").click().run()
    at.button("analizar").click().run()
    return at


class HechosYContrato(unittest.TestCase):
    def test_cifras_y_candidatas_son_las_del_motor_sin_modificar_el_resultado(self):
        resultado = analisis()
        copia = deepcopy(resultado)
        contexto = app.contexto_explicacion(resultado)
        precio = " ".join(h["texto"] for h in contexto["hechos"] if h["tema"] == "precio")
        urgente = " ".join(h["texto"] for h in contexto["hechos"] if h["tema"] == "urgencia")
        self.assertIn("Proveedor 1 ficticio", precio)
        self.assertIn("1.000,00 USD", precio)
        for cifra in ("80,00 USD", "8,00 %", "18 días antes", "Proveedor 2 ficticio"):
            self.assertIn(cifra, urgente)
        self.assertEqual(resultado, copia)

    def test_no_se_envian_archivos_borradores_ni_datos_de_origen(self):
        resultado = analisis()
        for fila in resultado["filas"]:
            fila["cotizacion"]["extraccion"] = {"datos_origen": "CONTENIDO_NO_NECESARIO_FICTICIO"}
            fila["cotizacion"]["entrada_manual"] = {"texto": "BORRADOR_NO_NECESARIO_FICTICIO"}
        contexto = json.dumps(app.contexto_explicacion(resultado))
        self.assertNotIn("CONTENIDO_NO_NECESARIO", contexto)
        self.assertNotIn("BORRADOR_NO_NECESARIO", contexto)
        self.assertNotIn("extraccion", contexto)
        self.assertNotIn("GEMINI_API_KEY", contexto)

    def test_savings_condicionados_moq_y_precision_unitaria_no_se_reinterpretan(self):
        ofertas = [compra(1, "0.005", cantidad="100"), compra(2, "0.006", cantidad="100")]
        datos = configuracion(ofertas)
        producto(datos, ofertas[0], actual="0.010", forecast="900", periodo="Periodo ficticio")
        contexto = app.contexto_explicacion(app.crear_analisis(ofertas, "USD", {}, datos))
        texto = " ".join(h["texto"] for h in contexto["hechos"] if h["tema"] == "ahorro_volumen")
        self.assertIn("0,005 USD", texto)
        self.assertIn("Hipótesis", texto)
        self.assertIn("sin múltiplo obligatorio", texto)
        self.assertIn("forecast 900", texto)
        self.assertIn("no se suman", " ".join(h["texto"] for h in contexto["hechos"]))

    def test_sin_objetivos_empates_y_datos_pendientes_se_conservan(self):
        resultado = analisis(presupuesto="", lt="", tolerancia="")
        texto = json.dumps(app.contexto_explicacion(resultado), ensure_ascii=False)
        self.assertIn("Sin objetivos", texto)
        resultado = analisis(destino="")
        texto = json.dumps(app.contexto_explicacion(resultado), ensure_ascii=False)
        self.assertIn("No hay dos ofertas equivalentes", texto)
        self.assertIn("Cobertura de costos", texto)
        ofertas = [compra(1), compra(2)]
        texto = json.dumps(app.contexto_explicacion(app.crear_analisis(ofertas, "USD", {}, configuracion(ofertas))), ensure_ascii=False)
        self.assertIn("empate", texto)

    def test_ahorro_negativo_base_cero_y_objetivos_incumplidos_se_conservan(self):
        ofertas = [compra(1, "12", cantidad="100"), compra(2, "11", cantidad="100")]
        datos = configuracion(ofertas, presupuesto="1000")
        producto(datos, ofertas[0], actual="10", target="10")
        resultado = app.crear_analisis(ofertas, "USD", {}, datos)
        texto = json.dumps(app.contexto_explicacion(resultado), ensure_ascii=False)
        self.assertIn("ahorro unitario -2 USD", texto)
        self.assertIn("No cumple", texto)
        self.assertIn("Ninguna oferta tiene cumplimiento de todos", texto)
        producto(datos, ofertas[0], actual="0")
        texto = json.dumps(app.contexto_explicacion(app.crear_analisis(ofertas, "USD", {}, datos)), ensure_ascii=False)
        self.assertIn("no calculable con precio actual cero", texto)

    def test_sin_analisis_ampliado_no_se_inventa_costo_hasta_destino(self):
        resultado = app.crear_analisis([compra(1), compra(2)], "USD", {})
        contexto = app.contexto_explicacion(resultado)
        self.assertEqual({h["tema"] for h in contexto["hechos"]}, set(app.TEMAS_EXPLICACION))
        self.assertIn("no demuestra menor costo completo", json.dumps(contexto))

    def test_respuesta_valida_solo_referencia_hechos_del_tema(self):
        contexto = app.contexto_explicacion(analisis())
        respuesta = respuesta_valida(contexto)
        self.assertEqual(app.leer_explicacion_ia(json.dumps(respuesta), contexto), respuesta)

    def test_rechaza_cifras_nuevas_hechos_ajenos_y_contrato_incompleto(self):
        contexto = app.contexto_explicacion(analisis())
        respuesta = respuesta_valida(contexto)
        casos = []
        for cambio in (
            {"interpretacion": "Cuesta 999 USD."}, {"siguiente_paso": "Compra ٩ unidades."},
            {"hechos": ["H999"]}, {"hechos": respuesta["urgencia"]["hechos"]},
            {"hechos": []}, {"hechos": respuesta["precio"]["hechos"] * 2},
            {"interpretacion": ""}, {"interpretacion": "A" * 901}, {"otra_clave": True},
        ):
            caso = deepcopy(respuesta)
            caso["precio"].update(cambio)
            casos.append(json.dumps(caso))
        incompleta = deepcopy(respuesta)
        incompleta.pop("pendientes")
        casos += [json.dumps(incompleta), "{}", "NaN", None, json.dumps(respuesta)[:-1] + ', "precio": {}}']
        for caso in casos:
            with self.subTest(caso=str(caso)[:35]), self.assertRaisesRegex(ValueError, "no se pudo validar"):
                app.leer_explicacion_ia(caso, contexto)


class ServicioDeExplicacion(unittest.TestCase):
    def test_una_solicitud_estructurada_y_acotada_sin_clave_en_el_contexto(self):
        resultado = analisis()
        copia = deepcopy(resultado)
        with patch.object(app.st, "secrets", {"GEMINI_API_KEY": CLAVE_FICTICIA}), patch("google.genai.Client") as crear:
            cliente = cliente_simulado(crear)
            respuesta = app.explicar_analisis_ia(resultado)
            self.assertTrue(respuesta["ok"], respuesta)
            cliente.models.generate_content.assert_called_once()
            peticion = cliente.models.generate_content.call_args.kwargs
            self.assertEqual(peticion["model"], app.MODELO)
            self.assertEqual(crear.call_args.kwargs["http_options"].retry_options.attempts, 1)
            self.assertEqual(crear.call_args.kwargs["http_options"].timeout, 60_000)
            self.assertEqual(peticion["config"].response_mime_type, "application/json")
            self.assertFalse(peticion["config"].response_json_schema["additionalProperties"])
            self.assertNotIn(CLAVE_FICTICIA, str(peticion))
            self.assertIn("no confiable", peticion["config"].system_instruction)
            cliente.files.upload.assert_not_called()
        self.assertEqual(resultado, copia)

    def test_sdk_real_serializa_el_contexto_y_contrato_con_transporte_simulado(self):
        solicitudes = []
        def responder_http(request):
            datos = json.loads(request.content)
            solicitudes.append(datos)
            contexto = json.loads(datos["contents"][0]["parts"][0]["text"].split("\n", 1)[1])
            return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(respuesta_valida(contexto))}]}, "finishReason": "STOP"}]})
        cliente_real = genai.Client
        def crear_simulado(**kwargs):
            kwargs["http_options"].httpx_client = httpx.Client(transport=httpx.MockTransport(responder_http))
            return cliente_real(**kwargs)
        with patch.object(app.st, "secrets", {"GEMINI_API_KEY": CLAVE_FICTICIA}), patch("google.genai.Client", side_effect=crear_simulado):
            respuesta = app.explicar_analisis_ia(analisis())
        self.assertTrue(respuesta["ok"], respuesta)
        self.assertEqual(len(solicitudes), 1)
        self.assertNotIn("maxItems", json.dumps(solicitudes[0]["generationConfig"]["responseJsonSchema"]))

    def test_contexto_excesivo_o_clave_ausente_no_llaman_a_gemini(self):
        with patch.object(app, "MAX_CONTEXTO_EXPLICACION", 10), patch("google.genai.Client") as crear:
            self.assertIn("extenso", app.explicar_analisis_ia(analisis())["mensaje"])
            crear.assert_not_called()
        with patch.object(app.st, "secrets", {}), patch("google.genai.Client") as crear:
            self.assertIn("Falta GEMINI_API_KEY", app.explicar_analisis_ia(analisis())["mensaje"])
            crear.assert_not_called()

    def test_errores_de_servicio_sin_filtracion_y_resultados_conservados(self):
        resultado = analisis()
        copia = deepcopy(resultado)
        for error, esperado in ((ErrorServicioSimulado(429), "cuota"), (ErrorServicioSimulado(403), "acceso"),
                                (ErrorServicioSimulado(404), "modelo"), (httpx.ReadTimeout(CLAVE_FICTICIA), "tardó")):
            with self.subTest(error=type(error).__name__), patch.object(app.st, "secrets", {"GEMINI_API_KEY": CLAVE_FICTICIA}), patch("google.genai.Client") as crear:
                cliente_simulado(crear).models.generate_content.side_effect = error
                respuesta = app.explicar_analisis_ia(resultado)
                self.assertFalse(respuesta["ok"])
                self.assertIn(esperado, respuesta["mensaje"])
                self.assertNotIn(CLAVE_FICTICIA, str(respuesta))
        self.assertEqual(resultado, copia)

    def test_respuesta_truncada_o_no_validada_no_se_muestra_como_explicacion(self):
        for respuesta in (SimpleNamespace(text="{}", candidates=[]),
                          SimpleNamespace(text="contenido incompleto", candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")])):
            with patch.object(app.st, "secrets", {"GEMINI_API_KEY": CLAVE_FICTICIA}), patch("google.genai.Client") as crear:
                cliente = crear.return_value.__enter__.return_value
                cliente.models.generate_content.return_value = respuesta
                self.assertFalse(app.explicar_analisis_ia(analisis())["ok"])


class InterfazYVigencia(unittest.TestCase):
    def test_no_hay_llamada_automatica_y_las_cifras_visibles_son_del_motor(self):
        with patch("google.genai.Client") as crear:
            cliente = cliente_simulado(crear)
            at = demo()
            self.assertFalse(at.exception)
            cliente.models.generate_content.assert_not_called()
            at.button("explicar_analisis_ia").click().run()
            self.assertFalse(at.exception)
            self.assertIsNotNone(at.session_state["explicacion_ia"])
            texto = " ".join(elemento.value for elemento in at.text)
            for cifra in ("80,00 USD", "8,00 %", "18 días antes"):
                self.assertIn(cifra, texto)
            at.run()
            cliente.models.generate_content.assert_called_once()

    def test_cambiar_objetivo_oculta_explicacion_y_exige_actualizar_y_solicitar(self):
        with patch("google.genai.Client") as crear:
            cliente = cliente_simulado(crear)
            at = demo()
            at.button("explicar_analisis_ia").click().run()
            at.text_input("objetivo_presupuesto").set_value("1000").run()
            self.assertIsNone(at.session_state["explicacion_ia"])
            self.assertTrue(at.button("explicar_analisis_ia").disabled)
            self.assertFalse(any("La alternativa citada" in e.value for e in at.text))
            at.text_input("objetivo_presupuesto").set_value("1100").run()
            self.assertIsNone(at.session_state["explicacion_ia"])
            at.button("analizar").click().run()
            self.assertFalse(at.button("explicar_analisis_ia").disabled)
            self.assertIsNone(at.session_state["explicacion_ia"])
            at.button("explicar_analisis_ia").click().run()
            self.assertFalse(at.exception)
            self.assertIsNotNone(at.session_state["explicacion_ia"])
            self.assertEqual(cliente.models.generate_content.call_count, 2)

    def test_cambiar_moneda_o_forecast_invalida_explicacion(self):
        for cambio in ("moneda", "forecast"):
            with self.subTest(cambio=cambio), patch("google.genai.Client") as crear:
                cliente_simulado(crear)
                at = demo()
                at.button("explicar_analisis_ia").click().run()
                if cambio == "moneda":
                    at.text_input("moneda_analisis").set_value("EUR").run()
                else:
                    clave = app.id_producto(at.session_state["cotizaciones_confirmadas"][0]["lineas"][0])
                    at.text_input(f"p_{clave}_forecast").set_value("900").run()
                self.assertFalse(at.exception)
                self.assertIsNone(at.session_state["explicacion_ia"])
                self.assertTrue(at.button("explicar_analisis_ia").disabled)

    def test_fallo_de_ia_conserva_analisis_y_no_repite_la_llamada(self):
        with patch("google.genai.Client") as crear:
            cliente = cliente_simulado(crear)
            cliente.models.generate_content.side_effect = ErrorServicioSimulado(429)
            at = demo()
            anterior = deepcopy(at.session_state["resultado"])
            at.button("explicar_analisis_ia").click().run()
            self.assertFalse(at.exception)
            self.assertTrue(any("cuota" in w.value for w in at.warning))
            self.assertIsNone(at.session_state["explicacion_ia"])
            self.assertEqual(at.session_state["resultado"], anterior)
            self.assertEqual(len(at.session_state["cotizaciones_confirmadas"]), 2)
            at.run()
            cliente.models.generate_content.assert_called_once()

    def test_cambiar_una_cotizacion_confirmada_invalida_su_explicacion(self):
        with patch("google.genai.Client") as crear:
            cliente = cliente_simulado(crear)
            at = demo()
            at.button("explicar_analisis_ia").click().run()
            cotizaciones = deepcopy(at.session_state["cotizaciones_confirmadas"])
            cotizaciones[0]["condiciones_pago"] = "Pago al recibir, ejemplo ficticio"
            at.session_state["cotizaciones_confirmadas"] = cotizaciones
            at.run()
            self.assertFalse(at.exception)
            self.assertIsNone(at.session_state["explicacion_ia"])
            self.assertTrue(at.button("explicar_analisis_ia").disabled)
            cliente.models.generate_content.assert_called_once()

    def test_otra_sesion_no_hereda_la_explicacion(self):
        with patch("google.genai.Client") as crear:
            cliente_simulado(crear)
            primera = demo()
            primera.button("explicar_analisis_ia").click().run()
            segunda = AppTest.from_file(str(Path(app.__file__).resolve()), default_timeout=30).run()
            self.assertFalse(segunda.exception)
            self.assertIsNone(segunda.session_state["explicacion_ia"])
            self.assertIsNone(segunda.session_state["resultado"])


if __name__ == "__main__":
    unittest.main()
