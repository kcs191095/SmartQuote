"""Casos de aceptación de la versión 0 con cotizaciones ficticias."""

from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest
import app


def campos(**cambios):
    datos = dict(proveedor="Proveedor Alfa", producto="Válvula de acero",
                 cantidad="10", unidad="unidades", precio_unitario="100",
                 moneda="USD", envio="0", impuestos="0", entrega_dias="10",
                 condiciones_pago="Pago a 30 días")
    datos.update(cambios)
    return datos


def oferta(numero=1, **cambios):
    cotizacion = app.crear_cotizacion(campos(**cambios))
    cotizacion["numero"] = numero
    return cotizacion


def revisar_ui(at, datos):
    at.button("agregar").click().run()
    version = at.session_state["version_formulario"]
    for campo, valor in datos.items():
        at.text_input(f"cotizacion_{version}_{campo}").set_value(valor)
    at.text_input(f"cotizacion_{version}_moq").set_value("1")
    at.selectbox(f"cotizacion_{version}_estado_multiplo").select("Sin múltiplo obligatorio")
    at.selectbox(f"cotizacion_{version}_alcance_lt").select("Recepción en destino (días calendario)")
    next(b for b in at.button if b.label == "Revisar cotización").click().run()


def agregar_ui(at, **cambios):
    revisar_ui(at, campos(**cambios))
    at.button("confirmar").click().run()


def linea_manual(**cambios):
    datos = dict(producto="Válvula de acero", identificador="VAL-01", cantidad="900",
                 unidad="piezas", precio_unitario="10", moq="500", multiplo="",
                 estado_multiplo="Sin múltiplo obligatorio", tramos=[], enteros=True)
    datos.update(cambios)
    return datos


def cotizacion_manual(lineas=None, **cambios):
    datos = dict(proveedor="Proveedor ficticio", moneda="USD", envio="20", impuestos="30",
                 estado_envio="Adicional conocido", estado_impuestos="Adicional conocido",
                 entrega_dias="10", condiciones_pago="Pago a 30 días",
                 incoterm="FCA", version_incoterm="2020", lugar_incoterm="Almacén ficticio del proveedor",
                 alcance_lt="Fabricación", lineas=lineas or [linea_manual()])
    datos.update(cambios)
    return app.crear_cotizacion_manual(datos)


class RegistroAmpliado(unittest.TestCase):
    def test_moq_no_se_confunde_con_multiplo(self):
        linea = app.crear_linea(linea_manual(), 1)
        self.assertEqual(linea["cantidad"], Decimal("900"))
        self.assertFalse(linea["avisos_compra"])
        linea = app.crear_linea(linea_manual(multiplo="500", estado_multiplo="Múltiplo indicado"), 1)
        self.assertTrue(any("no es múltiplo" in aviso for aviso in linea["avisos_compra"]))
        self.assertEqual(linea["cantidad"], Decimal("900"))

    def test_moq_uno_es_supuesto_explicito(self):
        pendiente = app.crear_linea(linea_manual(moq=""), 1)
        confirmado = app.crear_linea(linea_manual(moq="", confirmar_moq_uno=True), 1)
        self.assertIsNone(pendiente["moq"])
        self.assertEqual(confirmado["moq"], Decimal("1"))
        self.assertIn("Supuesto", confirmado["moq_origen"])
        self.assertTrue(pendiente["avisos_compra"])
        self.assertFalse(confirmado["avisos_compra"])

    def test_precio_por_tramo_y_cantidad_exacta(self):
        datos = linea_manual(cantidad="5", moq="1", precio_unitario="", alcance_precio="Por pedido",
                             precio_todo_pedido=True,
                             tramos=[dict(tipo="Entre dos cantidades", desde="1", hasta="4", precio="10"),
                                     dict(tipo="A partir de", desde="5", hasta="", precio="8.5")])
        linea = app.crear_linea(datos, 1)
        cotizacion = cotizacion_manual([linea_manual(**{k: v for k, v in datos.items()})], envio="0", impuestos="0")
        self.assertEqual(linea["precio_unitario"], Decimal("8.5"))
        self.assertEqual(app.total_original(cotizacion), Decimal("42.50"))
        self.assertIsNone(linea["precio_declarado"])
        exacta = app.crear_linea({**datos, "tramos": [dict(tipo="Cantidad exacta", desde="5", precio="8.5")]}, 1)
        self.assertIsNone(app.precio_para_cantidad(exacta, Decimal("6")))
        debajo_moq = app.crear_linea({**datos, "moq": "500"}, 1)
        self.assertIsNone(debajo_moq["precio_unitario"])
        self.assertTrue(any("MOQ" in aviso for aviso in debajo_moq["avisos_compra"]))

    def test_no_asume_precio_uniforme_ni_acumulado(self):
        datos = linea_manual(cantidad="5", moq="1", precio_unitario="", alcance_precio="Volumen acumulado en un periodo",
                             precio_todo_pedido=True, tramos=[dict(tipo="A partir de", desde="5", precio="8.5")])
        for cambios in ({}, {"alcance_precio": "Por pedido", "precio_todo_pedido": False},
                        {"alcance_precio": "Por pedido", "tramos": [dict(tipo="Entre dos cantidades", desde="5", hasta="", precio="8.5")]}):
            with self.subTest(cambios=cambios):
                linea = app.crear_linea({**datos, **cambios}, 1)
                self.assertIsNone(linea["precio_unitario"])
                self.assertTrue(linea["avisos_compra"])

    def test_rechaza_superposicion_y_precio_contradictorio(self):
        datos = linea_manual(cantidad="5", moq="1", alcance_precio="Por pedido", precio_todo_pedido=True,
                             tramos=[dict(tipo="A partir de", desde="5", precio="8.5")])
        with self.assertRaisesRegex(ValueError, "no coincide"):
            app.crear_linea(datos, 1)
        with self.assertRaisesRegex(ValueError, "superponen"):
            app.crear_tramos([dict(tipo="Entre dos cantidades", desde="1", hasta="5", precio="10"),
                              dict(tipo="A partir de", desde="5", precio="8.5")])

    def test_valida_enteros_moq_multiplo_y_rangos(self):
        for cambios in ({"moq": "0"}, {"multiplo": "-5"}, {"cantidad": "5.5"},
                        {"multiplo": "5", "estado_multiplo": "Sin múltiplo obligatorio"},
                        {"tramos": [dict(tipo="Entre dos cantidades", desde="5", hasta="1", precio="8")]},
                        {"tramos": [dict(tipo="A partir de", desde="5", precio="NaN")]}):
            with self.subTest(cambios=cambios), self.assertRaises(ValueError):
                app.crear_linea(linea_manual(**cambios), 1)

    def test_multilinea_gastos_compartidos_se_suman_una_vez(self):
        cotizacion = cotizacion_manual([linea_manual(cantidad="10", moq="1", precio_unitario="100"),
                                       linea_manual(producto="Junta", identificador="J-01", cantidad="5", moq="1", precio_unitario="20")])
        self.assertEqual(app.total_original(cotizacion), Decimal("1150.00"))
        self.assertEqual(len(app.filas_lineas(cotizacion)), 2)
        self.assertEqual(cotizacion["producto"], "2 líneas de productos")

    def test_incluido_y_pendiente_no_son_cargos_adicionales(self):
        datos = [linea_manual(cantidad="1", moq="1", precio_unitario="1000")]
        incluido = cotizacion_manual(datos, envio="200", estado_envio="Incluido en el precio", impuestos="50")
        self.assertEqual(app.total_original(incluido), Decimal("1050.00"))
        self.assertEqual(incluido["gastos_cotizados"]["envio"]["importe"], Decimal("200"))
        pendiente = cotizacion_manual(datos, envio="200", estado_envio="Pendiente de confirmar")
        self.assertIsNone(app.total_original(pendiente))
        self.assertEqual(pendiente["gastos_cotizados"]["envio"]["importe"], Decimal("200"))

    def test_precio_cero_y_gasto_no_aplica(self):
        gratis = cotizacion_manual([linea_manual(cantidad="1", moq="1", precio_unitario="0")], envio="0", impuestos="0")
        self.assertEqual(app.total_original(gratis), Decimal("0.00"))
        with self.assertRaisesRegex(ValueError, "por qué no aplica"):
            app.crear_gasto("No aplica", "", "Seguro", comprador=True)
        gasto = app.crear_gasto("No aplica", "", "Seguro", "Servicio sin transporte", comprador=True)
        self.assertEqual(app.importe_gasto(gasto), Decimal("0"))

    def test_no_compara_compra_invalida_ni_promete_recepcion(self):
        a = cotizacion_manual()
        b = cotizacion_manual([linea_manual(multiplo="500", estado_multiplo="Múltiplo indicado")])
        a["numero"], b["numero"] = 1, 2
        self.assertFalse(app.crear_analisis([a, b], "USD", {})["comparaciones"])
        b = deepcopy(a)
        b["numero"] = 2
        resultado = app.crear_analisis([a, b], "USD", {})
        self.assertIn("pendiente", resultado["comparaciones"][0]["entrega"])
        copia = deepcopy(a)
        app.crear_analisis([a, b], "USD", {})
        self.assertEqual(a, copia)


class Calculos(unittest.TestCase):
    def test_total_original(self):
        self.assertEqual(app.total_original(oferta(envio="20", impuestos="30")), Decimal("1050.00"))

    def test_gasto_ausente_no_equivale_a_cero(self):
        self.assertIsNone(app.total_original(oferta(envio="")))
        self.assertEqual(app.total_original(oferta(envio="0")), Decimal("1000.00"))

    def test_numeros_invalidos(self):
        for campo, valor in [("cantidad", "0"), ("cantidad", "-1"),
                             ("precio_unitario", "-10"), ("envio", "-1"),
                             ("impuestos", "-1"), ("precio_unitario", "NaN"),
                             ("precio_unitario", "Infinity"), ("envio", "1.000,00")]:
            with self.subTest(campo=campo, valor=valor), self.assertRaises(ValueError):
                oferta(**{campo: valor})

    def test_conversion_usd_y_originales_conservados(self):
        originales = [oferta(), oferta(2, proveedor="Proveedor Beta", moneda="EUR", precio_unitario="90", entrega_dias="20")]
        copia = deepcopy(originales)
        resultado = app.crear_analisis(originales, "USD", {"EUR": "1,10"})
        self.assertEqual([f["total_convertido"] for f in resultado["filas"]], [Decimal("1000.00"), Decimal("990.00")])
        self.assertIn("10,00 USD menos", resultado["comparaciones"][0]["costo"])
        self.assertIn("10 días después", resultado["comparaciones"][0]["entrega"])
        self.assertEqual(originales, copia)

    def test_conversion_eur_empate(self):
        resultado = app.crear_analisis([oferta(), oferta(2, moneda="EUR", precio_unitario="90")], "EUR", {"USD": "0,90"})
        self.assertEqual([f["total_convertido"] for f in resultado["filas"]], [Decimal("900.00"), Decimal("900.00")])
        self.assertIn("Empate", resultado["comparaciones"][0]["costo"])

    def test_moneda_tercera_y_tipo_compartido(self):
        datos = [oferta(), oferta(2, moneda="EUR"), oferta(3, moneda="EUR")]
        self.assertEqual(app.monedas_requeridas(datos, "CRC"), ["EUR", "USD"])
        resultado = app.crear_analisis(datos, "CRC", {"USD": "500", "EUR": "550"})
        self.assertEqual([f["total_convertido"] for f in resultado["filas"]], [Decimal("500000.00"), Decimal("550000.00"), Decimal("550000.00")])

    def test_misma_moneda_no_necesita_tipo(self):
        resultado = app.crear_analisis([oferta(), oferta(2, precio_unitario="95")], "USD", {})
        self.assertTrue(all(f["tipo"] == Decimal("1") for f in resultado["filas"]))

    def test_moneda_del_analisis_obligatoria(self):
        with self.assertRaises(ValueError):
            app.crear_analisis([oferta(), oferta(2)], "", {})

    def test_tipos_invalidos_y_faltantes(self):
        datos = [oferta(), oferta(2, moneda="EUR")]
        for valor in ("", "0", "-1", "NaN", "Infinity", "abc"):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                app.crear_analisis(datos, "USD", {"EUR": valor})

    def test_producto_cantidad_unidad_no_se_normalizan_por_moneda(self):
        for cambios in ({"producto": "Otro producto"}, {"cantidad": "20"}, {"unidad": "cajas"}):
            with self.subTest(cambios=cambios):
                datos = [oferta(), oferta(2, moneda="EUR", **cambios)]
                resultado = app.crear_analisis(datos, "USD", {"EUR": "1.1"})
                self.assertEqual(resultado["comparaciones"], [])
                self.assertEqual(resultado["sin_comparacion"], [1, 2])

    def test_datos_monetarios_pendientes_no_generan_comparacion(self):
        for cambios in ({"moneda": ""}, {"envio": ""}, {"impuestos": ""}, {"precio_unitario": ""}):
            with self.subTest(cambios=cambios):
                resultado = app.crear_analisis([oferta(), oferta(2, **cambios)], "USD", {})
                self.assertIsNone(resultado["filas"][1]["total_convertido"])
                self.assertFalse(resultado["comparaciones"])

    def test_moneda_ambigua(self):
        with self.assertRaises(ValueError):
            oferta(moneda="$")
        self.assertIsNone(oferta(moneda="")["moneda"])

    def test_precision_tipo_y_redondeo(self):
        self.assertEqual(app.convertir_total(Decimal("12.35"), Decimal("1.234567")), Decimal("15.25"))
        self.assertEqual(app.redondear_importe(Decimal("1.005")), Decimal("1.01"))
        resultado = app.crear_analisis([oferta(cantidad="1", precio_unitario="10.004"), oferta(2, cantidad="1", precio_unitario="10.003")], "USD", {})
        self.assertIn("Empate", resultado["comparaciones"][0]["costo"])

    def test_minimo_dos_confirmadas(self):
        for datos in ([], [oferta()]):
            with self.assertRaises(ValueError):
                app.crear_analisis(datos, "USD", {})


class Interfaz(unittest.TestCase):
    def iniciar(self):
        at = AppTest.from_file(str(Path(app.__file__).resolve()), default_timeout=30).run()
        self.assertFalse(at.exception)
        return at

    def test_inicio_sin_secretos(self):
        at = self.iniciar()
        self.assertEqual(at.session_state["cotizaciones_confirmadas"], [])
        self.assertTrue(at.button("analizar").disabled)
        self.assertIsNone(at.session_state["resultado"])

    def test_revision_correccion_y_confirmacion(self):
        at = self.iniciar()
        revisar_ui(at, campos(envio="20", impuestos="30"))
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["cotizaciones_confirmadas"], [])
        self.assertEqual(app.total_original(at.session_state["borrador"]), Decimal("1050.00"))
        at.button("corregir").click().run()
        version = at.session_state["version_formulario"]
        self.assertEqual(at.text_input(f"cotizacion_{version}_precio_unitario").value, "100")
        at.text_input(f"cotizacion_{version}_precio_unitario").set_value("95")
        next(b for b in at.button if b.label == "Revisar cotización").click().run()
        at.button("confirmar").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.session_state["cotizaciones_confirmadas"]), 1)
        self.assertEqual(at.session_state["cotizaciones_confirmadas"][0]["precio_unitario"], Decimal("95"))
        self.assertIsNone(at.session_state["resultado"])

    def test_formulario_invalido_no_se_confirma(self):
        at = self.iniciar()
        revisar_ui(at, campos(precio_unitario="-10"))
        self.assertFalse(at.exception)
        self.assertTrue(at.error)
        self.assertIsNone(at.session_state["borrador"])
        self.assertFalse(at.session_state["cotizaciones_confirmadas"])

    def test_agregar_quitar_lineas_y_corregir_conserva_datos(self):
        at = self.iniciar()
        at.button("agregar").click().run()
        at.text_input("cotizacion_0_proveedor").set_value("Proveedor ficticio")
        at.text_input("cotizacion_0_producto").set_value("Producto A")
        at.text_input("cotizacion_0_cantidad").set_value("10")
        at.text_input("cotizacion_0_precio_unitario").set_value("100")
        at.text_input("cotizacion_0_moneda").set_value("USD")
        at.text_input("cotizacion_0_envio").set_value("20")
        at.text_input("cotizacion_0_impuestos").set_value("30")
        at.button("agregar_linea").click().run()
        self.assertFalse(at.exception)
        v = at.session_state["version_formulario"]
        self.assertEqual(at.text_input(f"cotizacion_{v}_producto").value, "Producto A")
        at.text_input(f"cotizacion_{v}_linea_1_producto").set_value("Producto B")
        at.text_input(f"cotizacion_{v}_linea_1_cantidad").set_value("5")
        at.text_input(f"cotizacion_{v}_linea_1_precio_unitario").set_value("20")
        next(b for b in at.button if b.label == "Revisar cotización").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(app.total_original(at.session_state["borrador"]), Decimal("1150.00"))
        self.assertFalse(at.session_state["cotizaciones_confirmadas"])
        at.button("corregir").click().run()
        v = at.session_state["version_formulario"]
        self.assertEqual(at.text_input(f"cotizacion_{v}_linea_1_producto").value, "Producto B")
        at.button("quitar_linea_1").click().run()
        v = at.session_state["version_formulario"]
        self.assertEqual(at.text_input(f"cotizacion_{v}_producto").value, "Producto A")
        next(b for b in at.button if b.label == "Revisar cotización").click().run()
        at.button("confirmar").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.session_state["cotizaciones_confirmadas"][0]["lineas"]), 1)
        self.assertIsNone(at.session_state["resultado"])

    def test_tramos_e_incoterm_se_conservan_al_revisar(self):
        at = self.iniciar()
        at.button("agregar").click().run()
        for campo, valor in dict(proveedor="Proveedor ficticio", producto="Pieza", cantidad="5", unidad="piezas",
                                 moneda="USD", envio="0", impuestos="0").items():
            at.text_input(f"cotizacion_0_{campo}").set_value(valor)
        at.checkbox("cotizacion_0_confirmar_moq_uno").check()
        at.selectbox("cotizacion_0_estado_multiplo").select("Sin múltiplo obligatorio")
        at.selectbox("cotizacion_0_alcance_precio").select("Por pedido")
        at.checkbox("cotizacion_0_precio_todo_pedido").check()
        at.selectbox("cotizacion_0_incoterm").select("FCA")
        at.selectbox("cotizacion_0_version_incoterm").select("2020")
        at.text_input("cotizacion_0_lugar_incoterm").set_value("Almacén ficticio")
        at.button("agregar_tramo_0").click().run()
        self.assertFalse(at.exception)
        v = at.session_state["version_formulario"]
        at.selectbox(f"cotizacion_{v}_tramo_0_tipo").select("A partir de")
        at.text_input(f"cotizacion_{v}_tramo_0_desde").set_value("5")
        at.text_input(f"cotizacion_{v}_tramo_0_precio").set_value("8,50")
        next(b for b in at.button if b.label == "Revisar cotización").click().run()
        self.assertFalse(at.exception)
        borrador = at.session_state["borrador"]
        self.assertEqual(app.total_original(borrador), Decimal("42.50"))
        self.assertEqual(borrador["version_incoterm"], "2020")
        self.assertIn("Supuesto", borrador["lineas"][0]["moq_origen"])
        at.button("corregir").click().run()
        v = at.session_state["version_formulario"]
        self.assertEqual(at.text_input(f"cotizacion_{v}_tramo_0_precio").value, "8,50")
        self.assertEqual(at.selectbox(f"cotizacion_{v}_incoterm").value, "FCA")
        at.button("quitar_tramo_0_0").click().run()
        self.assertFalse(at.exception)
        self.assertFalse(at.session_state["campos_formulario"]["lineas"][0]["tramos"])

    def test_recorrido_completo_y_actualizacion(self):
        at = self.iniciar()
        agregar_ui(at)
        agregar_ui(at, proveedor="Proveedor Beta", moneda="EUR", precio_unitario="90", entrega_dias="20")
        self.assertFalse(at.exception)
        self.assertEqual(len(at.session_state["cotizaciones_confirmadas"]), 2)
        self.assertIsNone(at.session_state["resultado"])
        at.text_input("moneda_analisis").set_value("USD").run()
        tipo = next(i for i in at.text_input if i.label.startswith("1 EUR"))
        tipo.set_value("1,10").run()
        self.assertIsNone(at.session_state["resultado"])
        at.button("analizar").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["resultado"]["filas"][1]["total_convertido"], Decimal("990.00"))
        tipo = next(i for i in at.text_input if i.label.startswith("1 EUR"))
        tipo.set_value("1,20").run()
        self.assertTrue(any("Pendiente de actualizar" in w.value for w in at.warning))
        self.assertEqual(at.session_state["resultado"]["filas"][1]["total_convertido"], Decimal("990.00"))
        at.button("analizar").click().run()
        self.assertEqual(at.session_state["resultado"]["filas"][1]["total_convertido"], Decimal("1080.00"))
        at.text_input("moneda_analisis").set_value("EUR").run()
        self.assertEqual(at.session_state["tipos_texto"], {})
        self.assertTrue(any("Pendiente de actualizar" in w.value for w in at.warning))
        tipo = next(i for i in at.text_input if i.label.startswith("1 USD"))
        self.assertEqual(tipo.value, "")
        at.button("analizar").click().run()
        self.assertTrue(at.error)
        tipo = next(i for i in at.text_input if i.label.startswith("1 USD"))
        tipo.set_value("0,90").run()
        at.button("analizar").click().run()
        self.assertFalse(at.exception)
        self.assertIn("Empate", at.session_state["resultado"]["comparaciones"][0]["costo"])
        agregar_ui(at, proveedor="Proveedor Gamma", moneda="CHF")
        self.assertTrue(any("Pendiente de actualizar" in w.value for w in at.warning))
        self.assertTrue(any(i.label.startswith("1 CHF") for i in at.text_input))
        self.assertEqual(len(at.session_state["cotizaciones_confirmadas"]), 3)


if __name__ == "__main__":
    unittest.main()
