"""Decisiones, savings y recorrido manual con datos ficticios."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest
import app
from test_app import cotizacion_manual, linea_manual


def compra(numero, precio="1000", dias="30", cantidad="1", moneda="USD", linea=None, **cambios):
    datos = dict(proveedor=f"Proveedor {numero} ficticio", envio="0", impuestos="0", moneda=moneda,
                 entrega_dias=dias, alcance_lt="Recepción en destino (días calendario)",
                 gastos_comprador={k: dict(estado="Incluido en la cotización", importe="") for k in app.GASTOS_COMPRADOR})
    datos.update(cambios)
    cotizacion = cotizacion_manual([linea or linea_manual(cantidad=cantidad, moq="1", precio_unitario=precio)], **datos)
    cotizacion["numero"] = numero
    return cotizacion


def configuracion(cotizaciones, **cambios):
    datos = dict(destino="Almacén ficticio", presupuesto="1100", lt="15", tolerancia="8", prioridad="Urgencia",
                 productos={}, cobertura={str(c["numero"]): dict(costos=True, plazo=True) for c in cotizaciones}, acuerdos={}, vigencias={})
    for c in cotizaciones:
        for i, linea in enumerate(c["lineas"]):
            datos["productos"][app.id_producto(linea)] = dict(equivalente=True, base_precio=True,
                actual="", target="", necesidad="", forecast="", periodo="", plan="")
            datos["vigencias"][f"{c['numero']}:{i}"] = True
    datos.update(cambios)
    return datos


def producto(config, cotizacion, **cambios):
    config["productos"][app.id_producto(cotizacion["lineas"][0])].update(cambios)


class DecisionYSavings(unittest.TestCase):
    def test_precio_urgencia_y_cumplimiento_con_numeros(self):
        ofertas = [compra(1), compra(2, "1080", "12")]
        datos = configuracion(ofertas)
        resultado = app.crear_analisis(ofertas, "USD", {}, datos)["ampliado"]
        escenario = resultado["escenarios"][0]
        self.assertIn("Proveedor 1", escenario["precio"][0])
        urgencia = " ".join(escenario["urgencia"])
        self.assertIn("80,00 USD", urgencia)
        self.assertIn("8,00 %", urgencia)
        self.assertIn("18 días antes", urgencia)
        self.assertIn("dentro de tu tolerancia", urgencia)
        self.assertIn("Proveedor 2", escenario["equilibrio"][0])
        self.assertEqual(resultado["ofertas"][0]["plazo"]["diferencia"], Decimal("15"))
        datos["tolerancia"] = "7"
        self.assertIn("supera tu tolerancia", " ".join(app.crear_analisis(ofertas, "USD", {}, datos)["ampliado"]["escenarios"][0]["urgencia"]))
        datos["tolerancia"] = ""
        self.assertNotIn("tu tolerancia", " ".join(app.crear_analisis(ofertas, "USD", {}, datos)["ampliado"]["escenarios"][0]["urgencia"]))

    def test_ninguna_cumple_presupuesto_y_plazo(self):
        ofertas = [compra(1), compra(2, "1080", "12")]
        resultado = app.crear_analisis(ofertas, "USD", {}, configuracion(ofertas, presupuesto="1000"))["ampliado"]
        self.assertIn("Ninguna", resultado["escenarios"][0]["equilibrio"][0])
        self.assertEqual(resultado["ofertas"][1]["presupuesto"]["diferencia"], Decimal("80.00"))
        self.assertFalse(any(o["cumple_todo"] for o in resultado["ofertas"]))

    def test_objetivos_omitidos_y_empates(self):
        ofertas = [compra(1), compra(2)]
        resultado = app.crear_analisis(ofertas, "USD", {}, configuracion(ofertas, presupuesto="", lt="", tolerancia=""))["ampliado"]
        self.assertIn("empate", resultado["escenarios"][0]["precio"][0])
        self.assertIn("Sin objetivos", resultado["escenarios"][0]["equilibrio"][0])
        self.assertTrue(all(o["presupuesto"]["estado"] == "Sin objetivo" for o in resultado["ofertas"]))

    def test_costos_destino_difieren_de_totales_cotizados(self):
        a, b = compra(1, "900"), compra(2, "1050")
        a["gastos_comprador"]["transporte"] = app.crear_gasto("Adicional conocido", "200", "Transporte", comprador=True)
        datos = configuracion([a, b])
        copia = deepcopy([a, b])
        resultado = app.crear_analisis([a, b], "USD", {}, datos)
        self.assertEqual([f["total_original"] for f in resultado["filas"]], [Decimal("900.00"), Decimal("1050.00")])
        self.assertEqual([o["costo"]["completo"] for o in resultado["ampliado"]["ofertas"]], [Decimal("1100.00"), Decimal("1050.00")])
        self.assertIn("Proveedor 2", resultado["ampliado"]["escenarios"][0]["precio"][0])
        self.assertEqual([a, b], copia)
        a["gastos_comprador"]["transporte"] = app.crear_gasto("Pendiente de confirmar", "", "Transporte", comprador=True)
        self.assertIsNone(app.crear_analisis([a, b], "USD", {}, datos)["ampliado"]["ofertas"][0]["costo"]["completo"])

    def test_equivalencia_destino_y_lt_no_se_suponen(self):
        ofertas = [compra(1), compra(2)]
        datos = configuracion(ofertas, destino="")
        producto(datos, ofertas[0], equivalente=False, target="900", actual="1200")
        resultado = app.crear_analisis(ofertas, "USD", {}, datos)["ampliado"]
        self.assertIsNone(resultado["ofertas"][0]["costo"]["completo"])
        self.assertIsNone(resultado["ofertas"][0]["costo"]["lt"])
        self.assertIsNone(resultado["savings"][0]["unitario"])
        self.assertEqual(resultado["savings"][0]["objetivo"]["estado"], "Por confirmar")
        self.assertIn("No hay dos", resultado["escenarios"][0]["precio"][0])

    def test_target_unitario_y_base_no_desglosada(self):
        ofertas = [compra(1, "12", cantidad="100"), compra(2, "11", cantidad="100")]
        datos = configuracion(ofertas)
        producto(datos, ofertas[0], actual="10", target="10")
        resultado = app.crear_analisis(ofertas, "USD", {}, datos)["ampliado"]
        self.assertEqual(resultado["savings"][0]["objetivo"]["diferencia"], Decimal("2"))
        self.assertEqual(resultado["savings"][0]["objetivo"]["porcentaje"], Decimal("20"))
        self.assertEqual(resultado["savings"][0]["cotizado"], Decimal("-200.00"))
        ofertas[0]["gastos_cotizados"]["envio"] = app.crear_gasto("Incluido en el precio", "50", "Envío")
        self.assertEqual(app.crear_analisis(ofertas, "USD", {}, datos)["ampliado"]["savings"][0]["objetivo"]["estado"], "Por confirmar")

    def test_forecast_no_habilita_pedidos_menores_al_moq(self):
        linea = linea_manual(cantidad="900", moq="500", precio_unitario="9", alcance_precio="Por pedido", precio_todo_pedido=True,
                             tramos=[dict(tipo="A partir de", desde="500", precio="9")])
        ofertas = [compra(1, linea=linea), compra(2, linea=linea)]
        datos = configuracion(ofertas)
        producto(datos, ofertas[0], actual="10", forecast="900", periodo="Año ficticio", plan="300;300;300")
        ahorro = app.crear_analisis(ofertas, "USD", {}, datos)["ampliado"]["savings"][0]
        self.assertEqual(ahorro["cotizado"], Decimal("900.00"))
        self.assertIsNone(ahorro["proyectado"])
        self.assertIn("MOQ", ahorro["estado"])
        producto(datos, ofertas[0], plan="900")
        ahorro = app.crear_analisis(ofertas, "USD", {}, datos)["ampliado"]["savings"][0]
        self.assertEqual(ahorro["proyectado"], Decimal("900.00"))
        self.assertIn("confirmados", ahorro["estado"])

    def test_hipotesis_y_vigencia_se_identifican(self):
        ofertas = [compra(1, "9", cantidad="900"), compra(2, "9", cantidad="900")]
        datos = configuracion(ofertas)
        producto(datos, ofertas[0], actual="10", forecast="1000", periodo="Periodo ficticio")
        ahorro = app.crear_analisis(ofertas, "USD", {}, datos)["ampliado"]["savings"][0]
        self.assertEqual(ahorro["proyectado"], Decimal("1000.00"))
        self.assertIn("Hipótesis", ahorro["estado"])
        producto(datos, ofertas[0], forecast="900", plan="900")
        datos["vigencias"]["1:0"] = False
        self.assertIn("vigencia", app.crear_analisis(ofertas, "USD", {}, datos)["ampliado"]["savings"][0]["estado"])

    def test_acuerdo_acumulado_exige_confirmacion(self):
        linea = linea_manual(cantidad="500", moq="500", precio_unitario="8.5", alcance_precio="Volumen acumulado en un periodo",
                             precio_todo_pedido=True, tramos=[dict(tipo="A partir de", desde="1000", precio="8.5")])
        ofertas = [compra(1, linea=linea), compra(2, linea=linea)]
        datos = configuracion(ofertas)
        producto(datos, ofertas[0], actual="10", forecast="1000", periodo="Año ficticio", plan="500;500")
        self.assertIsNone(app.crear_analisis(ofertas, "USD", {}, datos)["ampliado"]["savings"][0]["proyectado"])
        datos["acuerdos"]["1:0"] = True
        ahorro = app.crear_analisis(ofertas, "USD", {}, datos)["ampliado"]["savings"][0]
        self.assertEqual(ahorro["proyectado"], Decimal("1500.00"))
        self.assertEqual(ahorro["precio"], Decimal("8.5"))

    def test_menor_precio_unitario_puede_exigir_mas_desembolso(self):
        linea = linea_manual(cantidad="4", moq="1", precio_unitario="10", alcance_precio="Por pedido", precio_todo_pedido=True,
                             tramos=[dict(tipo="Entre dos cantidades", desde="1", hasta="4", precio="10"), dict(tipo="A partir de", desde="5", precio="8.5")])
        ofertas = [compra(1, linea=linea), compra(2, linea=linea)]
        copia = deepcopy(ofertas)
        datos = configuracion(ofertas)
        producto(datos, ofertas[0], actual="10", necesidad="4")
        filas = app.crear_analisis(ofertas, "USD", {}, datos)["ampliado"]["volumen"]
        fila = next(f for f in filas if f["cotizacion"] == 1 and f["cantidad"] == 5)
        self.assertEqual(fila["excedente"], Decimal("1"))
        self.assertEqual(fila["desembolso"], Decimal("42.50"))
        self.assertEqual(fila["diferencia"], Decimal("2.50"))
        self.assertEqual(ofertas, copia)

    def test_multiplo_y_necesidad_no_reescriben_la_oferta(self):
        linea = linea_manual(cantidad="1000", moq="500", multiplo="500", estado_multiplo="Múltiplo indicado", precio_unitario="9",
                             alcance_precio="Por pedido", precio_todo_pedido=True, tramos=[dict(tipo="A partir de", desde="500", precio="9")])
        ofertas = [compra(1, linea=linea), compra(2, linea=linea)]
        datos = configuracion(ofertas)
        producto(datos, ofertas[0], actual="10", necesidad="900")
        resultado = app.crear_analisis(ofertas, "USD", {}, datos)["ampliado"]
        self.assertFalse(resultado["ofertas"][0]["compra_valida"])
        self.assertEqual(resultado["volumen"][0]["cantidad"], Decimal("1000"))
        self.assertEqual(resultado["volumen"][0]["excedente"], Decimal("100"))
        self.assertEqual(ofertas[0]["lineas"][0]["cantidad"], Decimal("1000"))

    def test_configuracion_invalida_y_ceros_validos(self):
        ofertas = [compra(1), compra(2)]
        catalogo = app.catalogo_productos(ofertas)
        for cambios in (dict(presupuesto="0"), dict(lt="1.5"), dict(lt="-1"), dict(tolerancia="-1"), dict(tolerancia="NaN")):
            with self.subTest(cambios=cambios), self.assertRaises(ValueError):
                app.leer_configuracion(configuracion(ofertas, **cambios), catalogo)
        for cambios in (dict(forecast="1", periodo=""), dict(forecast="2", periodo="Mes", plan="1"), dict(forecast="1.5", periodo="Mes")):
            datos = configuracion(ofertas)
            producto(datos, ofertas[0], **cambios)
            with self.subTest(cambios=cambios), self.assertRaises(ValueError):
                app.leer_configuracion(datos, catalogo)
        datos = configuracion(ofertas, lt="0", tolerancia="0")
        producto(datos, ofertas[0], actual="0", forecast="0", periodo="Mes ficticio")
        ahorro = app.crear_analisis(ofertas, "USD", {}, datos)["ampliado"]["savings"][0]
        self.assertIsNone(ahorro["porcentaje"])
        self.assertEqual(ahorro["proyectado"], Decimal("0.00"))

    def test_conversion_precisa_en_savings_y_base_cero(self):
        ofertas = [compra(1, "9", cantidad="900", moneda="EUR"), compra(2, "9", cantidad="900")]
        datos = configuracion(ofertas)
        producto(datos, ofertas[0], actual="10", forecast="900", periodo="Mes ficticio", plan="900")
        ahorro = app.crear_analisis(ofertas, "USD", {"EUR": "1.100001"}, datos)["ampliado"]["savings"][0]
        self.assertEqual(ahorro["precio"], Decimal("9.900009"))
        self.assertEqual(ahorro["proyectado"], Decimal("89.99"))
        ceros = [compra(1, "0"), compra(2, "1", "12")]
        resultado = app.crear_analisis(ceros, "USD", {}, configuracion(ceros))["ampliado"]
        self.assertIn("base cero", " ".join(resultado["escenarios"][0]["urgencia"]))

    def test_incoterm_y_firmas_de_actualizacion(self):
        ofertas = [compra(1), compra(2)]
        ofertas[0].update(incoterm="CIP", version_incoterm="2020", lugar_incoterm="Destino ficticio")
        descripcion = app.descripcion_incoterm(ofertas[0])
        self.assertIn("no es el punto", descripcion)
        datos = configuracion(ofertas)
        anterior = app.firma_datos(ofertas, "USD", {}, datos)
        producto(datos, ofertas[0], forecast="900", periodo="Mes ficticio")
        self.assertNotEqual(anterior, app.firma_datos(ofertas, "USD", {}, datos))


class RecorridoAmpliado(unittest.TestCase):
    def iniciar_ejemplo(self):
        at = AppTest.from_file(str(Path(app.__file__).resolve()), default_timeout=30).run()
        at.button("cargar_ejemplo").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.session_state["cotizaciones_confirmadas"]), 2)
        at.button("analizar").click().run()
        self.assertFalse(at.exception)
        return at

    def test_ejemplo_resultados_cambio_objetivos_y_moneda(self):
        at = self.iniciar_ejemplo()
        resultado = at.session_state["resultado"]["ampliado"]
        self.assertEqual(resultado["ofertas"][1]["costo"]["completo"], Decimal("1080.00"))
        self.assertEqual(resultado["savings"][0]["proyectado"], Decimal("2000.00"))
        self.assertIn("confirmados", resultado["savings"][0]["estado"])
        clave = app.id_producto(at.session_state["cotizaciones_confirmadas"][0]["lineas"][0])
        at.text_input("objetivo_lt").set_value("10").run()
        self.assertTrue(any("Pendiente de actualizar" in w.value for w in at.warning))
        at.text_input(f"p_{clave}_target").set_value("11").run()
        at.text_input("moneda_analisis").set_value("EUR").run()
        self.assertEqual(at.text_input(f"p_{clave}_actual").value, "")
        self.assertEqual(at.text_input(f"p_{clave}_target").value, "")
        self.assertEqual(at.text_input("objetivo_presupuesto").value, "")
        self.assertEqual(at.text_input(f"p_{clave}_forecast").value, "1000")
        self.assertEqual(at.text_input("objetivo_lt").value, "10")
        self.assertFalse(at.exception)

    def test_edicion_reemplaza_solo_despues_de_confirmar(self):
        at = self.iniciar_ejemplo()
        at.button("editar_1").click().run()
        v = at.session_state["version_formulario"]
        at.text_input(f"cotizacion_{v}_precio_unitario").set_value("9.50")
        next(b for b in at.button if b.label == "Revisar cotización").click().run()
        self.assertEqual(at.session_state["cotizaciones_confirmadas"][0]["precio_unitario"], Decimal("10"))
        at.button("confirmar").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.session_state["cotizaciones_confirmadas"]), 2)
        self.assertEqual(at.session_state["cotizaciones_confirmadas"][0]["numero"], 1)
        self.assertEqual(at.session_state["cotizaciones_confirmadas"][0]["precio_unitario"], Decimal("9.50"))
        self.assertTrue(any("Pendiente de actualizar" in w.value for w in at.warning))
        self.assertFalse(any(x.value for x in at.checkbox if str(x.key).startswith("cob_costos_1_")))
