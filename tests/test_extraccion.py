"""Archivos y extracción simulada: revisión humana, procedencia y continuidad manual."""
from copy import deepcopy
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import json
import base64
import unittest
from unittest.mock import patch

import httpx
from google import genai
from PIL import Image
from pypdf import PdfWriter
from streamlit.testing.v1 import AppTest
import app
from test_ia import CLAVE_FICTICIA, ErrorServicioSimulado


def imagen(formato="PNG"):
    salida = BytesIO()
    Image.new("RGB", (300, 100), "white").save(salida, format=formato)
    return salida.getvalue()


def pdf(paginas=1, cifrado=False):
    escritor = PdfWriter()
    for _ in range(paginas):
        escritor.add_blank_page(width=300, height=400)
    if cifrado:
        escritor.encrypt("contrasena_ficticia")
    salida = BytesIO()
    escritor.write(salida)
    return salida.getvalue()


def vacio(esquema):
    tipo = esquema["type"]
    if isinstance(tipo, list):
        return None
    if tipo == "object":
        return {k: vacio(v) for k, v in esquema["properties"].items()}
    if tipo == "array":
        return []
    if tipo == "boolean":
        return False
    return esquema["enum"][0]


def datos_extraidos():
    esquema = app.esquema_extraccion()
    datos = vacio(esquema)
    linea = vacio(esquema["properties"]["lineas"]["items"])
    linea.update(identificador="VAL-100", producto="Válvula de ejemplo", cantidad="100", unidad="piezas",
                 precio_unitario="10.00", moneda="USD", moq="50", estado_multiplo="Sin múltiplo obligatorio",
                 alcance_precio="Por pedido", base_tramos="Unitario para todas las unidades")
    linea["tramos"] = [
        dict(tipo="Entre dos cantidades", desde="50", hasta="99", precio="10.50", moneda="USD", unidad="piezas"),
        dict(tipo="A partir de", desde="100", hasta=None, precio="10.00", moneda="USD", unidad="piezas"),
    ]
    datos.update(es_cotizacion=True, proveedor="Proveedor ficticio", moneda="USD", lineas=[linea],
                 entrega_dias="30", alcance_lt="Recepción en destino (días calendario)",
                 incoterm="DDP", version_incoterm="2020", lugar_incoterm="Almacén de Ejemplo")
    for k in ("envio", "impuestos"):
        datos[k].update(estado="Incluido en el precio", moneda="USD")
    for gasto in datos["gastos_comprador"].values():
        gasto.update(estado="Incluido en la cotización", moneda="USD")
    datos["referencias"] = [dict(campo="lineas[0].precio_unitario", origen="Página 1, productos", fragmento="VAL-100: 10.00 USD por pieza")]
    return datos


def fuente():
    return dict(archivo="oferta-ficticia.pdf", mime="application/pdf", paginas=1, sha256="hash-ficticio")


class ArchivosYContrato(unittest.TestCase):
    def test_png_jpeg_y_pdf_se_validan_por_contenido(self):
        for nombre, contenido, mime in (("oferta.png", imagen(), "image/png"), ("oferta.jpeg", imagen("JPEG"), "image/jpeg"), ("oferta.PDF", pdf(), "application/pdf")):
            with self.subTest(nombre=nombre):
                dato = app.validar_archivo_cotizacion(nombre, contenido)
                self.assertEqual(dato["mime"], mime)
                self.assertEqual(dato["paginas"], 1)
                self.assertEqual(len(dato["sha256"]), 64)

    def test_vacio_danado_tipo_falso_o_no_admitido_se_rechaza(self):
        for nombre, contenido in (("oferta.pdf", b""), ("oferta.pdf", b"%PDF-roto"), ("oferta.png", b"texto"),
                                  ("oferta.jpg", imagen()), ("oferta.xlsx", imagen()), ("oferta.png", imagen()[:20])):
            with self.subTest(nombre=nombre, tamano=len(contenido)):
                with self.assertRaises(ValueError):
                    app.validar_archivo_cotizacion(nombre, contenido)

    def test_limites_y_pdf_cifrado_se_rechazan_antes_de_la_api(self):
        for contenido in (pdf(paginas=11), pdf(cifrado=True), b"x" * (5 * 1024 * 1024 + 1)):
            with patch("google.genai.Client") as cliente:
                resultado = app.extraer_archivo_ia("oferta.pdf", contenido)
                self.assertFalse(resultado["ok"])
                cliente.assert_not_called()

    def test_contrato_completo_acepta_null_y_cero_como_datos_distintos(self):
        datos = datos_extraidos()
        datos["lineas"][0]["precio_unitario"] = "0"
        self.assertEqual(app.leer_respuesta_extraccion(json.dumps(datos)), datos)

    def test_contrato_incompleto_duplicado_con_numeros_o_campos_ajenos_se_rechaza(self):
        casos = []
        incompleto = datos_extraidos()
        incompleto.pop("moneda")
        casos.append(json.dumps(incompleto))
        numerico = datos_extraidos()
        numerico["lineas"][0]["precio_unitario"] = 10.0
        casos.append(json.dumps(numerico))
        ajeno = datos_extraidos()
        ajeno["confirmar_moq_uno"] = True
        casos.append(json.dumps(ajeno))
        texto = json.dumps(datos_extraidos())
        casos.extend((texto[:-1] + ', "proveedor": "otro"}', "```json\n" + texto + "\n```", "{}", "NaN"))
        for caso in casos:
            with self.subTest(caso=caso[:40]):
                with self.assertRaises(ValueError):
                    app.leer_respuesta_extraccion(caso)

    def test_no_oferta_o_lectura_parcial_no_se_presenta_completa(self):
        for campo, valor in (("es_cotizacion", False), ("excede_limites", True), ("lineas", [])):
            datos = datos_extraidos()
            datos[campo] = valor
            with self.assertRaises(ValueError):
                app.leer_respuesta_extraccion(json.dumps(datos))


class DatosParaRevision(unittest.TestCase):
    def test_limites_contradictorios_no_se_convierten_en_rangos_abiertos(self):
        datos = datos_extraidos()
        datos["lineas"][0]["tramos"][1]["hasta"] = "200"
        campos = app.campos_desde_extraccion(datos, fuente())
        self.assertEqual(len(campos["lineas"][0]["tramos"]), 1)
        self.assertEqual(campos["extraccion"]["datos_origen"]["lineas"][0]["tramos"][1]["hasta"], "200")

    def test_tramos_exactos_y_rangos_se_conservan_sin_confirmar_por_el_usuario(self):
        datos = datos_extraidos()
        datos["lineas"][0]["tramos"][0].update(tipo="Cantidad exacta", desde="50", hasta=None)
        campos = app.campos_desde_extraccion(datos, fuente())
        linea = campos["lineas"][0]
        self.assertEqual(linea["tramos"][0]["tipo"], "Cantidad exacta")
        self.assertEqual(linea["tramos"][1]["tipo"], "A partir de")
        self.assertFalse(linea["precio_todo_pedido"])
        self.assertFalse(linea["confirmar_moq_uno"])

    def test_ausente_no_es_cero_y_moq_uno_requiere_aceptacion(self):
        datos = datos_extraidos()
        datos["lineas"][0].update(moq=None, precio_unitario="0", tramos=[])
        datos["envio"].update(estado="Pendiente de confirmar", importe=None)
        datos["impuestos"].update(estado="Adicional conocido", importe="0")
        campos = app.campos_desde_extraccion(datos, fuente())
        self.assertEqual(campos["envio"], "")
        self.assertEqual(campos["impuestos"], "0")
        self.assertEqual(campos["lineas"][0]["precio_unitario"], "0")
        cotizacion = app.crear_cotizacion_manual(campos)
        self.assertIsNone(cotizacion["lineas"][0]["moq"])
        self.assertIsNone(app.total_original(cotizacion))
        campos["lineas"][0]["confirmar_moq_uno"] = True
        self.assertTrue(app.crear_cotizacion_manual(campos)["lineas"][0]["moq_origen"].startswith("Supuesto"))

    def test_moneda_ambigua_mezclada_y_uom_distinta_no_se_suponen_equivalentes(self):
        datos = datos_extraidos()
        datos["lineas"][0]["moneda"] = "EUR"
        datos["envio"].update(estado="Adicional conocido", importe="20", moneda="EUR")
        campos = app.campos_desde_extraccion(datos, fuente())
        self.assertEqual(campos["lineas"][0]["precio_unitario"], "")
        self.assertEqual(campos["estado_envio"], "Pendiente de confirmar")
        self.assertEqual(campos["extraccion"]["datos_origen"]["envio"]["importe"], "20")
        datos = datos_extraidos()
        datos["lineas"][0]["tramos"][0]["unidad"] = "kg"
        self.assertEqual(len(app.campos_desde_extraccion(datos, fuente())["lineas"][0]["tramos"]), 1)
        datos["moneda"] = "$"
        self.assertEqual(app.campos_desde_extraccion(datos, fuente())["moneda"], "")

    def test_paquetes_y_marginales_se_conservan_para_aclarar_sin_aplicar_tramos(self):
        for base in ("Paquete", "Marginal por bloques", "Por confirmar"):
            datos = datos_extraidos()
            datos["lineas"][0]["base_tramos"] = base
            campos = app.campos_desde_extraccion(datos, fuente())
            self.assertEqual(campos["lineas"][0]["tramos"], [])
            self.assertEqual(len(campos["extraccion"]["datos_origen"]["lineas"][0]["tramos"]), 2)

    def test_datos_invalidos_se_dejan_pendientes_y_se_conserva_su_origen(self):
        datos = datos_extraidos()
        datos["lineas"][0].update(cantidad="-1", precio_unitario="NaN", moq="0")
        campos = app.campos_desde_extraccion(datos, fuente())
        self.assertEqual(campos["lineas"][0]["cantidad"], "")
        self.assertEqual(campos["lineas"][0]["precio_unitario"], "")
        self.assertEqual(campos["lineas"][0]["moq"], "")
        self.assertEqual(campos["extraccion"]["datos_origen"]["lineas"][0]["cantidad"], "-1")

    def test_varias_lineas_y_procedencia_moq_no_se_cruzan_al_corregir(self):
        datos = datos_extraidos()
        segunda = deepcopy(datos["lineas"][0])
        segunda.update(identificador="JUN-200", producto="Junta de ejemplo", moq="100", tramos=[])
        datos["lineas"].append(segunda)
        campos = app.campos_desde_extraccion(datos, fuente())
        campos["lineas"] = [campos["lineas"][1]]
        cotizacion = app.crear_cotizacion_manual(campos)
        self.assertEqual(cotizacion["lineas"][0]["moq"], Decimal("100"))
        self.assertEqual(cotizacion["lineas"][0]["moq_origen"], "Extraído del documento y confirmado por el usuario")
        campos["lineas"][0]["moq"] = "200"
        self.assertEqual(app.crear_cotizacion_manual(campos)["lineas"][0]["moq_origen"], "Indicado por el usuario")


class ServicioYRecorrido(unittest.TestCase):
    def test_sdk_real_serializa_pdf_y_esquema_con_transporte_http_simulado(self):
        contenido_pdf = pdf()
        solicitudes = []

        def responder(request):
            solicitudes.append(request)
            return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(datos_extraidos())}]}, "finishReason": "STOP"}]})

        cliente_real = genai.Client

        def crear_simulado(**kwargs):
            kwargs["http_options"].httpx_client = httpx.Client(transport=httpx.MockTransport(responder))
            return cliente_real(**kwargs)

        with patch.object(app.st, "secrets", {"GEMINI_API_KEY": CLAVE_FICTICIA}), patch("google.genai.Client", side_effect=crear_simulado):
            resultado = app.extraer_archivo_ia("oferta.pdf", contenido_pdf)
        self.assertTrue(resultado["ok"], resultado)
        self.assertEqual(len(solicitudes), 1)
        cuerpo = json.loads(solicitudes[0].content)
        self.assertFalse(cuerpo["generationConfig"]["responseJsonSchema"]["additionalProperties"])
        partes = cuerpo["contents"][0]["parts"]
        adjunto = next(p["inlineData"] for p in partes if "inlineData" in p)
        self.assertEqual(base64.urlsafe_b64decode(adjunto["data"]), contenido_pdf)
        self.assertEqual(adjunto.get("mimeType", adjunto.get("mime_type")), "application/pdf")

    def test_peticion_usa_bytes_y_salida_estructurada_sin_enviar_la_clave_al_modelo(self):
        for nombre, contenido in (("oferta.png", imagen()), ("oferta.pdf", pdf())):
            with patch.object(app.st, "secrets", {"GEMINI_API_KEY": CLAVE_FICTICIA}), patch("google.genai.Client") as crear:
                cliente = crear.return_value.__enter__.return_value
                cliente.models.generate_content.return_value = SimpleNamespace(text=json.dumps(datos_extraidos()), candidates=[])
                resultado = app.extraer_archivo_ia(nombre, contenido)
                self.assertTrue(resultado["ok"])
                peticion = cliente.models.generate_content.call_args.kwargs
                self.assertEqual(peticion["config"].response_mime_type, "application/json")
                self.assertEqual(peticion["contents"][1].inline_data.data, contenido)
                self.assertNotIn(CLAVE_FICTICIA, str(peticion))
                self.assertEqual(crear.call_args.kwargs["http_options"].retry_options.attempts, 1)
                cliente.files.upload.assert_not_called()

    def test_cuota_clave_ausente_y_respuesta_truncada_son_recuperables(self):
        contenido = imagen()
        with patch.object(app.st, "secrets", {}), patch("google.genai.Client") as cliente:
            self.assertFalse(app.extraer_archivo_ia("oferta.png", contenido)["ok"])
            cliente.assert_not_called()
        with patch.object(app.st, "secrets", {"GEMINI_API_KEY": CLAVE_FICTICIA}), patch("google.genai.Client") as crear:
            cliente = crear.return_value.__enter__.return_value
            cliente.models.generate_content.side_effect = ErrorServicioSimulado(429)
            resultado = app.extraer_archivo_ia("oferta.png", contenido)
            self.assertIn("cuota", resultado["mensaje"])
            self.assertNotIn(CLAVE_FICTICIA, str(resultado))
            cliente.models.generate_content.side_effect = None
            cliente.models.generate_content.return_value = SimpleNamespace(text=json.dumps(datos_extraidos()), candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")])
            self.assertFalse(app.extraer_archivo_ia("oferta.png", contenido)["ok"])

    def test_formulario_exige_carga_explicita_revision_y_confirmacion(self):
        archivo = SimpleNamespace(name="oferta.png", getvalue=lambda: imagen())
        with patch("streamlit.file_uploader", return_value=archivo), patch("google.genai.Client") as crear:
            cliente = crear.return_value.__enter__.return_value
            cliente.models.generate_content.return_value = SimpleNamespace(text=json.dumps(datos_extraidos()), candidates=[])
            at = AppTest.from_file(str(Path(app.__file__).resolve()), default_timeout=30)
            at.secrets["GEMINI_API_KEY"] = CLAVE_FICTICIA
            at.run().button("agregar").click().run()
            self.assertTrue(at.button("extraer_archivo_0").disabled)
            cliente.models.generate_content.assert_not_called()
            at.checkbox("aceptar_carga_0").check().run()
            at.button("extraer_archivo_0").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(len(at.session_state["cotizaciones_confirmadas"]), 0)
            self.assertIsNone(at.session_state["borrador"])
            version = at.session_state["version_formulario"]
            self.assertEqual(at.text_input(f"cotizacion_{version}_proveedor").value, "Proveedor ficticio")
            self.assertFalse(at.checkbox(f"cotizacion_{version}_precio_todo_pedido").value)
            next(b for b in at.button if b.label == "Revisar cotización").click().run()
            self.assertEqual(len(at.session_state["cotizaciones_confirmadas"]), 0)
            self.assertIsNotNone(at.session_state["borrador"])
            at.button("confirmar").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(len(at.session_state["cotizaciones_confirmadas"]), 1)
            cotizacion = at.session_state["cotizaciones_confirmadas"][0]
            self.assertEqual(cotizacion["extraccion"]["archivo"], "oferta.png")
            self.assertEqual(cotizacion["lineas"][0]["moq_origen"], "Extraído del documento y confirmado por el usuario")
            cliente.models.generate_content.assert_called_once()

    def test_fallo_no_sustituye_formulario_ni_cotizaciones_confirmadas(self):
        archivo = SimpleNamespace(name="oferta.png", getvalue=lambda: imagen())
        with patch("streamlit.file_uploader", return_value=archivo), patch("google.genai.Client") as crear:
            cliente = crear.return_value.__enter__.return_value
            cliente.models.generate_content.side_effect = ErrorServicioSimulado(429)
            at = AppTest.from_file(str(Path(app.__file__).resolve()), default_timeout=30)
            at.secrets["GEMINI_API_KEY"] = CLAVE_FICTICIA
            at.run().button("cargar_ejemplo").click().run()
            at.button("agregar").click().run()
            at.session_state["campos_formulario"] = {"proveedor": "Borrador previo", "lineas": [{}]}
            at.run()
            at.checkbox("aceptar_carga_0").check().run()
            at.button("extraer_archivo_0").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state["campos_formulario"]["proveedor"], "Borrador previo")
            self.assertEqual(len(at.session_state["cotizaciones_confirmadas"]), 2)
            at.button("cancelar_formulario").click().run()
            next(b for b in at.button if b.label == "Analizar cotizaciones").click().run()
            self.assertFalse(at.exception)
            self.assertIsNotNone(at.session_state["resultado"])


if __name__ == "__main__":
    unittest.main()
