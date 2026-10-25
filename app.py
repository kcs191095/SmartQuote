"""SmartQuote: comparación manual y comprobación de conexión con Gemini."""

from collections import defaultdict
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, ROUND_CEILING, localcontext
from hashlib import sha256
from itertools import combinations
import json
import re

import streamlit as st


# Modelo inicial verificado en la documentación de Google el 25/10/2026.
# https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite
MODELO = "gemini-3.5-flash-lite"
TIEMPO_ESPERA_IA_MS = 20_000
CENTAVO = Decimal("0.01")
CAMPOS = (
    "proveedor", "producto", "cantidad", "unidad", "precio_unitario", "moneda",
    "envio", "impuestos", "entrega_dias", "condiciones_pago",
)
ETIQUETAS = {
    "proveedor": "Proveedor", "producto": "Producto o servicio",
    "cantidad": "Cantidad", "unidad": "Unidad", "precio_unitario": "Precio unitario",
    "moneda": "Moneda original", "envio": "Envío total", "impuestos": "Impuestos totales",
    "entrega_dias": "Entrega en días", "condiciones_pago": "Condiciones de pago",
}
PATRON_DECIMAL = re.compile(r"^[+-]?(?:[0-9]+(?:[.,][0-9]*)?|[.,][0-9]+)$")
INCOTERMS = ("Por confirmar", "EXW", "FCA", "CPT", "CIP", "DAP", "DPU", "DDP", "FAS", "FOB", "CFR", "CIF", "No aplica")
ESTADOS_GASTO = ("Pendiente de confirmar", "Adicional conocido", "Incluido en el precio")
ESTADOS_COMPRADOR = ("Pendiente de confirmar", "Adicional conocido", "Incluido en la cotización", "No aplica")
GASTOS_COMPRADOR = {
    "transporte": "Transporte restante", "seguro": "Seguro",
    "aduana": "Despacho y aranceles", "otros": "Otros gastos",
}
ALCANCES_LT = ("Por confirmar", "Recepción en destino (días calendario)", "Fabricación", "Despacho", "Días hábiles u otro alcance")
TIPOS_TRAMO = ("Cantidad exacta", "Entre dos cantidades", "A partir de")
ALCANCES_PRECIO = ("Por confirmar", "Por pedido", "Volumen acumulado en un periodo")
ESTADOS_MULTIPLO = ("Por confirmar", "Sin múltiplo obligatorio", "Múltiplo indicado")
PRIORIDADES = ("Sin preferencia", "Precio", "Urgencia", "Equilibrio")
RIESGO_INCOTERM = {
    "EXW": "Mercancía disponible sin cargar en el lugar pactado.",
    "FCA": "Entrega al transportista del comprador en el punto pactado.",
    "FAS": "Mercancía al costado del buque en el puerto de salida.",
    "FOB": "Mercancía a bordo del buque en el puerto de salida.",
    "CFR": "A bordo en origen; el destino del flete no es el punto de transferencia del riesgo.",
    "CIF": "A bordo en origen; el destino del flete no es el punto de transferencia del riesgo.",
    "CPT": "Entrega al transportista; el destino pagado no es el punto de transferencia del riesgo.",
    "CIP": "Entrega al transportista; el destino pagado no es el punto de transferencia del riesgo.",
    "DAP": "En destino, lista para descargar.",
    "DPU": "En destino, descargada.",
    "DDP": "En destino, lista para descargar, con importación a cargo del vendedor.",
}


def mensaje_error_ia(error):
    """Devuelve mensajes fijos; nunca muestra el contenido de una excepción."""
    codigo = getattr(error, "code", None) or getattr(error, "status_code", None)
    if codigo in (429, "429"):
        return "La cuota de IA se ha agotado o está temporalmente limitada. Inténtalo más tarde; puedes continuar con las funciones manuales."
    if codigo in (401, 403, "401", "403"):
        return "La clave no fue aceptada o no tiene acceso al servicio. Revisa GEMINI_API_KEY en los secretos de Streamlit; puedes continuar manualmente."
    if codigo in (400, "400"):
        return "Gemini rechazó la petición. Revisa la clave y la configuración del proyecto; las funciones manuales siguen disponibles."
    if codigo in (404, "404"):
        return "El modelo configurado no está disponible para este proyecto. Hay que revisar su disponibilidad; puedes continuar manualmente."
    if isinstance(error, TimeoutError) or type(error).__name__ in {
        "TimeoutException", "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout",
    }:
        return "La IA tardó demasiado en responder. Puedes volver a intentarlo más tarde o continuar manualmente."
    if isinstance(error, ConnectionError) or type(error).__name__ in {
        "ConnectError", "NetworkError", "ReadError", "WriteError", "ProxyError",
    }:
        return "No se pudo conectar con la IA. Inténtalo más tarde; tus cotizaciones y las funciones manuales siguen disponibles."
    return "La IA no está disponible en este momento. Inténtalo más tarde; tus cotizaciones y las funciones manuales siguen disponibles."


def probar_conexion_ia():
    """Una solicitud explícita de prueba; solo envía un saludo fijo al servicio."""
    try:
        clave = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        return {"ok": False, "mensaje": "No se pudo leer GEMINI_API_KEY. Revisa los secretos de Streamlit; puedes continuar manualmente."}
    if not isinstance(clave, str) or not clave.strip():
        return {"ok": False, "mensaje": "Falta GEMINI_API_KEY en los secretos de Streamlit. Las funciones manuales siguen disponibles."}

    try:
        from google import genai
        from google.genai import types
    except Exception:
        return {"ok": False, "mensaje": "No se pudo cargar la conexión con Gemini. Revisa la instalación de google-genai; puedes continuar manualmente."}

    try:
        with genai.Client(
            api_key=clave.strip(),
            http_options=types.HttpOptions(
                timeout=TIEMPO_ESPERA_IA_MS,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        ) as cliente:
            respuesta = cliente.models.generate_content(
                model=MODELO,
                contents="Esta es una prueba de conexión. Responde únicamente con SMARTQUOTE_OK, sin explicaciones.",
                config=types.GenerateContentConfig(temperature=0, max_output_tokens=256),
            )
        if not isinstance(respuesta.text, str) or respuesta.text.strip() != "SMARTQUOTE_OK":
            return {"ok": False, "mensaje": "El servicio respondió, pero la prueba no obtuvo la confirmación esperada. Vuelve a intentarlo; puedes continuar manualmente."}
        return {"ok": True, "mensaje": "Conexión con Gemini comprobada correctamente."}
    except Exception as error:
        return {"ok": False, "mensaje": mensaje_error_ia(error)}


def mostrar_conexion_ia():
    with st.expander("Conexión con IA"):
        st.caption("Esta prueba envía únicamente un saludo a Gemini al pulsar el botón.")
        if st.button("Probar conexión con IA", key="probar_conexion_ia"):
            with st.spinner("Comprobando la conexión con IA..."):
                st.session_state.prueba_conexion_ia = probar_conexion_ia()
        resultado = st.session_state.prueba_conexion_ia
        if resultado is not None:
            st.caption("Resultado de la última prueba solicitada en esta sesión.")
            if resultado["ok"]:
                st.success(resultado["mensaje"])
            else:
                st.warning(resultado["mensaje"])


def leer_decimal(texto, etiqueta, positivo=False):
    """Un campo vacío conserva su ausencia; cero es un dato explícito."""
    texto = str(texto).strip() if texto is not None else ""
    if not texto:
        return None
    if len(texto) > 32 or not PATRON_DECIMAL.fullmatch(texto):
        raise ValueError(f"{etiqueta}: escribe un número sin separadores de miles.")
    try:
        valor = Decimal(texto.replace(",", "."))
    except InvalidOperation:
        raise ValueError(f"{etiqueta}: escribe un número válido.") from None
    if not valor.is_finite() or valor < 0 or (positivo and valor == 0):
        regla = "mayor que cero" if positivo else "igual o mayor que cero"
        raise ValueError(f"{etiqueta}: el valor debe ser {regla}.")
    return valor


def leer_moneda(texto, obligatoria=False):
    moneda = str(texto or "").strip().upper()
    if not moneda:
        if obligatoria:
            raise ValueError("Elige la moneda del análisis, por ejemplo USD, EUR o CRC.")
        return None
    if not re.fullmatch(r"[A-Z]{3}", moneda):
        raise ValueError("La moneda debe tener un código de tres letras, como USD o EUR. Si no la conoces, deja el campo vacío.")
    return moneda


def crear_cotizacion(campos):
    cotizacion = {campo: str(campos.get(campo) if campos.get(campo) is not None else "").strip() for campo in CAMPOS}
    if not cotizacion["proveedor"]:
        raise ValueError("Escribe el nombre del proveedor para identificar esta cotización.")
    if not cotizacion["producto"]:
        raise ValueError("Escribe el producto o servicio que estás cotizando.")
    for campo in ("cantidad", "precio_unitario", "envio", "impuestos", "entrega_dias"):
        cotizacion[campo] = leer_decimal(
            cotizacion[campo], ETIQUETAS[campo], positivo=campo == "cantidad"
        )
    cotizacion["moneda"] = leer_moneda(cotizacion["moneda"])
    return cotizacion


def crear_tramos(datos, enteros=False):
    tramos = []
    for posicion, dato in enumerate(datos, 1):
        etiqueta = f"Tramo {posicion}"
        tipo = dato.get("tipo", TIPOS_TRAMO[0])
        if tipo not in TIPOS_TRAMO:
            raise ValueError(f"{etiqueta}: elige una cantidad exacta o un rango.")
        desde = leer_decimal(dato.get("desde"), f"{etiqueta}, cantidad inicial", positivo=True)
        hasta = leer_decimal(dato.get("hasta"), f"{etiqueta}, cantidad final", positivo=True)
        precio = leer_decimal(dato.get("precio"), f"{etiqueta}, precio por unidad")
        if tipo != "Entre dos cantidades" and hasta is not None:
            raise ValueError(f"{etiqueta}: la cantidad final solo se utiliza entre dos cantidades.")
        if tipo == "Cantidad exacta":
            hasta = desde
        if desde is not None and hasta is not None and hasta < desde:
            raise ValueError(f"{etiqueta}: la cantidad final no puede ser menor que la inicial.")
        if enteros and any(v is not None and v != v.to_integral_value() for v in (desde, hasta)):
            raise ValueError(f"{etiqueta}: esta unidad solo admite cantidades enteras.")
        tramos.append({"tipo": tipo, "desde": desde, "hasta": hasta, "precio": precio})
    for a, b in combinations(tramos, 2):
        if a["desde"] is None or b["desde"] is None:
            continue
        if any(t["tipo"] == "Entre dos cantidades" and t["hasta"] is None for t in (a, b)):
            continue
        fin_a = a["hasta"] if a["hasta"] is not None else Decimal("Infinity")
        fin_b = b["hasta"] if b["hasta"] is not None else Decimal("Infinity")
        if max(a["desde"], b["desde"]) <= min(fin_a, fin_b):
            raise ValueError("Los tramos de una línea se superponen. Corrige sus límites antes de revisar.")
    return tramos


def precio_para_cantidad(linea, cantidad):
    """Solo aplica rangos explícitos y precios unitarios para todo el pedido."""
    if cantidad is None:
        return None
    if linea.get("moq") is None or cantidad < linea["moq"]:
        return None
    if linea.get("estado_multiplo") == "Por confirmar":
        return None
    if linea.get("estado_multiplo") == "Múltiplo indicado":
        if linea.get("multiplo") is None:
            return None
        with localcontext() as contexto:
            contexto.prec = 128
            if cantidad % linea["multiplo"] != 0:
                return None
    if not linea.get("tramos"):
        return linea.get("precio_declarado")
    if not linea.get("precio_todo_pedido") or linea.get("alcance_precio") != "Por pedido":
        return None
    if any(t["desde"] is None or t["precio"] is None or (t["tipo"] == "Entre dos cantidades" and t["hasta"] is None)
           for t in linea["tramos"]):
        return None
    for tramo in linea["tramos"]:
        if tramo["desde"] is None or tramo["precio"] is None:
            continue
        if tramo["tipo"] == "Entre dos cantidades" and tramo["hasta"] is None:
            continue
        if cantidad >= tramo["desde"] and (tramo["hasta"] is None or cantidad <= tramo["hasta"]):
            return tramo["precio"]
    return None


def revisar_compra(linea):
    avisos = []
    cantidad = linea["cantidad"]
    if cantidad is None:
        avisos.append("Cantidad por confirmar")
    if linea["moq"] is None:
        avisos.append("MOQ no indicado: se propone 1; confirmar")
    elif cantidad is not None and cantidad < linea["moq"]:
        avisos.append(f"La cantidad no cumple el MOQ de {numero(linea['moq'])}")
    if linea["estado_multiplo"] == "Por confirmar":
        avisos.append("Múltiplo de pedido por confirmar")
    elif linea["estado_multiplo"] == "Múltiplo indicado":
        if linea["multiplo"] is None:
            avisos.append("Falta el múltiplo indicado")
        elif cantidad is not None:
            with localcontext() as contexto:
                contexto.prec = 128
                if cantidad % linea["multiplo"] != 0:
                    avisos.append(f"La cantidad no es múltiplo de {numero(linea['multiplo'])}")
    if not linea["unidad"]:
        avisos.append("Unidad por confirmar")
    if linea["tramos"] and precio_para_cantidad(linea, cantidad) is None:
        avisos.append("No hay un tramo confirmado por pedido aplicable a esta cantidad")
    if linea["precio_unitario"] is None:
        avisos.append("Precio unitario por confirmar")
    return avisos


def crear_linea(datos, posicion):
    linea = {campo: str(datos.get(campo, "") or "").strip()
             for campo in ("identificador", "producto", "unidad", "condiciones_tramos")}
    if not linea["producto"]:
        raise ValueError(f"Línea {posicion}: escribe el producto o servicio.")
    for campo in ("cantidad", "precio_unitario", "moq", "multiplo"):
        linea[campo] = leer_decimal(datos.get(campo), f"Línea {posicion}, {campo.replace('_', ' ')}", positivo=campo != "precio_unitario")
    linea["precio_declarado"] = linea["precio_unitario"]
    linea["moq_origen"] = "Indicado por el usuario" if linea["moq"] is not None else "No indicado"
    if linea["moq"] is None and datos.get("confirmar_moq_uno"):
        linea["moq"] = Decimal("1")
        linea["moq_origen"] = "Supuesto de 1 confirmado por el usuario"
    linea["estado_multiplo"] = datos.get("estado_multiplo", "Por confirmar")
    if linea["estado_multiplo"] not in ESTADOS_MULTIPLO:
        raise ValueError(f"Línea {posicion}: revisa el estado del múltiplo.")
    if linea["multiplo"] is not None and linea["estado_multiplo"] != "Múltiplo indicado":
        raise ValueError(f"Línea {posicion}: si introduces un múltiplo, selecciona «Múltiplo indicado».")
    linea["enteros"] = bool(datos.get("enteros"))
    if linea["enteros"] and any(linea[c] is not None and linea[c] != linea[c].to_integral_value() for c in ("cantidad", "moq", "multiplo")):
        raise ValueError(f"Línea {posicion}: cantidad, MOQ y múltiplo deben ser enteros para esta unidad.")
    linea["alcance_precio"] = datos.get("alcance_precio", "Por confirmar")
    if linea["alcance_precio"] not in ALCANCES_PRECIO:
        raise ValueError(f"Línea {posicion}: revisa el alcance del precio.")
    linea["precio_todo_pedido"] = bool(datos.get("precio_todo_pedido"))
    linea["tramos"] = crear_tramos(datos.get("tramos", []), linea["enteros"])
    precio_tramo = precio_para_cantidad(linea, linea["cantidad"])
    if linea["tramos"] and precio_tramo is not None:
        if linea["precio_declarado"] is not None and linea["precio_declarado"] != precio_tramo:
            raise ValueError(f"Línea {posicion}: el precio unitario no coincide con el tramo de la cantidad cotizada. Revisa ambos valores.")
        linea["precio_unitario"] = precio_tramo
    linea["avisos_compra"] = revisar_compra(linea)
    return linea


def crear_gasto(estado, texto, etiqueta, justificacion="", comprador=False):
    estados = ESTADOS_COMPRADOR if comprador else ESTADOS_GASTO
    if estado not in estados:
        raise ValueError(f"{etiqueta}: revisa si el gasto está incluido, es adicional o está pendiente.")
    valor = leer_decimal(texto, etiqueta)
    justificacion = str(justificacion or "").strip()
    if estado == "No aplica" and not justificacion:
        raise ValueError(f"{etiqueta}: explica brevemente por qué no aplica.")
    return {"estado": estado, "importe": valor, "justificacion": justificacion}


def importe_gasto(gasto):
    if gasto["estado"] in ("Incluido en el precio", "Incluido en la cotización", "No aplica"):
        return Decimal("0")
    return gasto["importe"] if gasto["estado"] == "Adicional conocido" else None


def crear_cotizacion_manual(campos):
    lineas = [crear_linea(datos, i) for i, datos in enumerate(campos.get("lineas", []), 1)]
    if not lineas:
        raise ValueError("Agrega al menos una línea de producto o servicio.")
    base = {**campos, **lineas[0]}
    cotizacion = crear_cotizacion(base)
    cotizacion["lineas"] = lineas
    cotizacion["version_registro"] = 2
    cotizacion["entrada_manual"] = deepcopy(campos)
    cotizacion["gastos_cotizados"] = {}
    for campo in ("envio", "impuestos"):
        gasto = crear_gasto(campos.get(f"estado_{campo}", "Adicional conocido"), campos.get(campo), ETIQUETAS[campo])
        cotizacion["gastos_cotizados"][campo] = gasto
        cotizacion[campo] = importe_gasto(gasto)
    cotizacion["gastos_comprador"] = {}
    for campo, etiqueta in GASTOS_COMPRADOR.items():
        dato = campos.get("gastos_comprador", {}).get(campo, {})
        cotizacion["gastos_comprador"][campo] = crear_gasto(
            dato.get("estado", "Pendiente de confirmar"), dato.get("importe"), etiqueta,
            dato.get("justificacion", ""), comprador=True,
        )
    for campo in ("incoterm", "version_incoterm", "lugar_incoterm", "alcance_lt"):
        cotizacion[campo] = str(campos.get(campo, "Por confirmar") or "Por confirmar").strip()
    if cotizacion["incoterm"] not in INCOTERMS:
        raise ValueError("Selecciona un Incoterm de la lista.")
    if cotizacion["version_incoterm"] not in ("Por confirmar", "2020", "Otra versión"):
        raise ValueError("Selecciona la versión del Incoterm.")
    if cotizacion["alcance_lt"] not in ALCANCES_LT:
        raise ValueError("Selecciona el alcance del plazo de entrega.")
    if len(lineas) > 1:
        cotizacion.update(producto=f"{len(lineas)} líneas de productos", cantidad=None, unidad="", precio_unitario=None)
    return cotizacion


def redondear_importe(valor):
    with localcontext() as contexto:
        contexto.prec = 128
        return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def total_original(cotizacion):
    if cotizacion.get("lineas"):
        if cotizacion.get("moneda") is None or cotizacion.get("envio") is None or cotizacion.get("impuestos") is None:
            return None
        if any(l["cantidad"] is None or l["precio_unitario"] is None for l in cotizacion["lineas"]):
            return None
        with localcontext() as contexto:
            contexto.prec = 128
            subtotal = sum((l["cantidad"] * l["precio_unitario"] for l in cotizacion["lineas"]), Decimal("0"))
            return redondear_importe(subtotal + cotizacion["envio"] + cotizacion["impuestos"])
    necesarios = ("cantidad", "precio_unitario", "envio", "impuestos", "moneda")
    if any(cotizacion.get(campo) is None for campo in necesarios):
        return None
    with localcontext() as contexto:
        contexto.prec = 128
        total = (
            cotizacion["cantidad"] * cotizacion["precio_unitario"]
            + cotizacion["envio"] + cotizacion["impuestos"]
        )
        return redondear_importe(total)


def convertir_total(total, tipo):
    if total is None or tipo is None:
        return None
    with localcontext() as contexto:
        contexto.prec = 128
        return redondear_importe(total * tipo)


def numero(valor, decimales=None):
    if valor is None:
        return "Por confirmar"
    if decimales is None:
        texto = format(valor, "f")
        if "." in texto:
            texto = texto.rstrip("0").rstrip(".")
        return texto.replace(".", ",")
    texto = format(valor, f",.{decimales}f")
    return texto.replace(",", "_").replace(".", ",").replace("_", ".")


def importe(valor, moneda=None):
    if valor is None or not moneda:
        return "Por confirmar"
    return f"{numero(valor, 2)} {moneda}"


def campos_pendientes(cotizacion):
    if cotizacion.get("lineas"):
        pendientes = []
        for i, linea in enumerate(cotizacion["lineas"], 1):
            pendientes.extend(f"Línea {i}: {aviso}" for aviso in linea["avisos_compra"])
        for campo in ("moneda", "envio", "impuestos", "entrega_dias", "condiciones_pago"):
            if cotizacion.get(campo) in (None, ""):
                pendientes.append(ETIQUETAS[campo])
        if cotizacion["incoterm"] != "No aplica":
            for campo in ("incoterm", "version_incoterm", "lugar_incoterm"):
                if cotizacion[campo] == "Por confirmar":
                    pendientes.append(campo.replace("_", " "))
        if cotizacion["alcance_lt"] == "Por confirmar":
            pendientes.append("Alcance del plazo")
        for etiqueta, gasto in cotizacion["gastos_comprador"].items():
            if importe_gasto(gasto) is None:
                pendientes.append(GASTOS_COMPRADOR[etiqueta])
        return pendientes
    return [ETIQUETAS[campo] for campo in CAMPOS if cotizacion.get(campo) in (None, "")]


def clave_comparacion(cotizacion):
    if cotizacion.get("lineas"):
        if any(l["avisos_compra"] for l in cotizacion["lineas"]):
            return None
        return tuple(sorted((
            " ".join(l["producto"].casefold().split()), l["cantidad"],
            " ".join(l["unidad"].casefold().split()), l["identificador"].casefold(),
        ) for l in cotizacion["lineas"]))
    if not cotizacion.get("producto") or not cotizacion.get("unidad") or cotizacion.get("cantidad") is None:
        return None
    return (
        (" ".join(cotizacion["producto"].casefold().split()),
         cotizacion["cantidad"],
         " ".join(cotizacion["unidad"].casefold().split()), ""),
    )


def nombre_oferta(cotizacion):
    return f"{cotizacion['proveedor']} (cotización {cotizacion['numero']})"


def monedas_requeridas(cotizaciones, moneda_analisis):
    return sorted({
        c["moneda"] for c in cotizaciones
        if c.get("moneda") and c["moneda"] != moneda_analisis
    })


def firma_datos(cotizaciones, moneda_analisis, tipos_texto, configuracion=None):
    usados = monedas_requeridas(cotizaciones, moneda_analisis)
    return json.dumps(
        {"cotizaciones": cotizaciones, "moneda": moneda_analisis,
         "tipos": {moneda: tipos_texto.get(moneda, "") for moneda in usados},
         "configuracion": configuracion},
        sort_keys=True, ensure_ascii=False, default=str,
    )


def crear_analisis(cotizaciones, moneda_analisis, tipos_texto, configuracion=None):
    if len(cotizaciones) < 2:
        raise ValueError("Agrega y confirma al menos dos cotizaciones para analizar.")
    moneda_analisis = leer_moneda(moneda_analisis, obligatoria=True)
    tipos = {moneda_analisis: Decimal("1")}
    for origen in monedas_requeridas(cotizaciones, moneda_analisis):
        etiqueta = f"Tipo de cambio de {origen} a {moneda_analisis}"
        tipo = leer_decimal(tipos_texto.get(origen, ""), etiqueta, positivo=True)
        if tipo is None:
            raise ValueError(f"Completa el tipo de cambio: 1 {origen} = ___ {moneda_analisis}.")
        tipos[origen] = tipo

    filas = []
    grupos = defaultdict(list)
    for original in cotizaciones:
        cotizacion = deepcopy(original)
        total = total_original(cotizacion)
        tipo = tipos.get(cotizacion["moneda"])
        convertido = convertir_total(total, tipo)
        fila = {"cotizacion": cotizacion, "total_original": total,
                "tipo": tipo, "total_convertido": convertido}
        filas.append(fila)
        clave = clave_comparacion(cotizacion)
        if clave is not None and convertido is not None:
            grupos[clave].append(fila)

    comparaciones = []
    comparadas = set()
    for grupo in grupos.values():
        for izquierda, derecha in combinations(grupo, 2):
            a, b = izquierda["cotizacion"], derecha["cotizacion"]
            comparadas.update((a["numero"], b["numero"]))
            with localcontext() as contexto:
                contexto.prec = 128
                diferencia = derecha["total_convertido"] - izquierda["total_convertido"]
            if diferencia == 0:
                costo = f"Empate en el total cotizado entre {nombre_oferta(a)} y {nombre_oferta(b)}: {importe(izquierda['total_convertido'], moneda_analisis)} cada una."
            else:
                menor, mayor = (a, b) if diferencia > 0 else (b, a)
                costo = f"{nombre_oferta(menor)} cuesta {importe(diferencia.copy_abs(), moneda_analisis)} menos que {nombre_oferta(mayor)}."
            entrega = "Plazo de entrega pendiente en una o ambas ofertas."
            plazos_completos = all(
                not c.get("lineas") or c.get("alcance_lt") == "Recepción en destino (días calendario)"
                for c in (a, b)
            )
            if plazos_completos and a["entrega_dias"] is not None and b["entrega_dias"] is not None:
                with localcontext() as contexto:
                    contexto.prec = 128
                    dias = b["entrega_dias"] - a["entrega_dias"]
                if dias == 0:
                    entrega = f"Ambas indican entrega en {numero(a['entrega_dias'])} días."
                else:
                    tarde, temprano = (b, a) if dias > 0 else (a, b)
                    entrega = f"{nombre_oferta(tarde)} entrega {numero(dias.copy_abs())} días después de {nombre_oferta(temprano)}."
            comparaciones.append({"producto": a["producto"], "cantidad": a["cantidad"],
                                  "unidad": a["unidad"], "costo": costo, "entrega": entrega,
                                  "pago": f"Pago de {nombre_oferta(a)}: {a['condiciones_pago'] or 'Por confirmar'}. Pago de {nombre_oferta(b)}: {b['condiciones_pago'] or 'Por confirmar'}."})

    resultado = {"moneda_analisis": moneda_analisis, "tipos": tipos, "filas": filas,
            "comparaciones": comparaciones,
            "sin_comparacion": [f["cotizacion"]["numero"] for f in filas
                                if f["cotizacion"]["numero"] not in comparadas]}
    if configuracion is not None:
        with localcontext() as contexto:
            contexto.prec = 128
            resultado["ampliado"] = analizar_objetivos(resultado, configuracion)
    return resultado


def lineas_de(cotizacion):
    if cotizacion.get("lineas"):
        return cotizacion["lineas"]
    return [{**{k: cotizacion.get(k) for k in ("producto", "cantidad", "unidad", "precio_unitario")},
             "identificador": "", "precio_declarado": cotizacion.get("precio_unitario"),
             "moq": None, "estado_multiplo": "Por confirmar", "multiplo": None,
             "tramos": [], "enteros": False, "avisos_compra": ["Condiciones por confirmar"]}]


def id_producto(linea):
    normalizar = lambda t: " ".join(str(t or "").casefold().split())
    identidad = [normalizar(linea.get("identificador") or linea.get("producto")), normalizar(linea.get("unidad"))]
    return sha256(json.dumps(identidad, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def catalogo_productos(cotizaciones):
    productos = {}
    for cotizacion in cotizaciones:
        for i, linea in enumerate(lineas_de(cotizacion)):
            clave = id_producto(linea)
            producto = productos.setdefault(clave, {"producto": linea["producto"], "unidad": linea["unidad"], "enteros": False, "ofertas": []})
            producto["enteros"] = producto["enteros"] or bool(linea.get("enteros"))
            producto["ofertas"].append((cotizacion["numero"], i))
    return productos


def leer_configuracion(datos, catalogo):
    config = {"destino": str(datos.get("destino", "")).strip(),
              "prioridad": datos.get("prioridad", PRIORIDADES[0]),
              "cobertura": deepcopy(datos.get("cobertura", {})),
              "acuerdos": deepcopy(datos.get("acuerdos", {})),
              "vigencias": deepcopy(datos.get("vigencias", {})), "productos": {}}
    if config["prioridad"] not in PRIORIDADES:
        raise ValueError("Selecciona una prioridad de compra válida.")
    for campo, etiqueta, positivo in (("presupuesto", "Presupuesto máximo", True), ("lt", "Plazo máximo", False), ("tolerancia", "Tolerancia de urgencia", False)):
        config[campo] = leer_decimal(datos.get(campo), etiqueta, positivo=positivo)
    if config["lt"] is not None and config["lt"] != config["lt"].to_integral_value():
        raise ValueError("El plazo máximo debe ser un número entero de días calendario.")
    for clave, producto in catalogo.items():
        bruto = datos.get("productos", {}).get(clave, {})
        p = {"equivalente": bool(bruto.get("equivalente")), "base_precio": bool(bruto.get("base_precio")),
             "periodo": str(bruto.get("periodo", "") or "").strip(), "unidad": producto["unidad"]}
        for campo, positivo in (("actual", False), ("target", True), ("necesidad", True), ("forecast", False)):
            p[campo] = leer_decimal(bruto.get(campo), f"{producto['producto']}, {campo}", positivo=positivo)
        if p["forecast"] is not None and not p["periodo"]:
            raise ValueError(f"{producto['producto']}: indica el periodo del forecast.")
        textos_plan = [t.strip() for t in re.split(r"[;\n]+", str(bruto.get("plan", ""))) if t.strip()]
        p["plan"] = [leer_decimal(t, "Cantidad de cada pedido", positivo=True) for t in textos_plan]
        if p["plan"] and p["forecast"] is None:
            raise ValueError(f"{producto['producto']}: indica el forecast para validar el plan de pedidos.")
        if producto["enteros"] and any(v is not None and v != v.to_integral_value() for v in [p["forecast"], p["necesidad"], *p["plan"]]):
            raise ValueError(f"{producto['producto']}: demanda, forecast y pedidos deben ser enteros para esta unidad.")
        with localcontext() as contexto:
            contexto.prec = 128
            if p["plan"] and sum(p["plan"], Decimal("0")) != p["forecast"]:
                raise ValueError(f"{producto['producto']}: la suma del plan debe coincidir con el forecast.")
        config["productos"][clave] = p
    return config


def porcentaje(diferencia, base):
    if base is None or base <= 0 or diferencia is None:
        return None
    with localcontext() as contexto:
        contexto.prec = 128
        return diferencia / base * 100


def condicion_cantidad(linea, cantidad):
    if cantidad is None or cantidad <= 0:
        return "Cantidad pendiente"
    if linea.get("enteros") and cantidad != cantidad.to_integral_value():
        return "La unidad exige cantidades enteras"
    if linea.get("moq") is None:
        return "MOQ por confirmar"
    if cantidad < linea["moq"]:
        return f"No cumple MOQ {numero(linea['moq'])}"
    if linea.get("estado_multiplo") == "Por confirmar":
        return "Múltiplo por confirmar"
    if linea.get("estado_multiplo") == "Múltiplo indicado":
        if linea.get("multiplo") is None or cantidad % linea["multiplo"] != 0:
            return "No cumple el múltiplo indicado"
    return ""


def precio_escenario(linea, cantidad, volumen_acumulado=None):
    motivo = condicion_cantidad(linea, cantidad)
    if motivo:
        return None, motivo
    if not linea.get("tramos"):
        if cantidad != linea.get("cantidad"):
            return None, "Precio de otra cantidad por confirmar: no hay un rango declarado"
        precio = linea.get("precio_declarado")
        return precio, "Precio por confirmar" if precio is None else "Precio de la cantidad cotizada"
    copia = deepcopy(linea)
    alcance = linea.get("alcance_precio")
    if alcance == "Volumen acumulado en un periodo":
        if volumen_acumulado is None:
            return None, "Acuerdo de volumen acumulado por confirmar"
        copia.update(alcance_precio="Por pedido", moq=Decimal("0"), estado_multiplo="Sin múltiplo obligatorio", enteros=False)
        precio = precio_para_cantidad(copia, volumen_acumulado)
    elif alcance == "Por pedido":
        precio = precio_para_cantidad(copia, cantidad)
    else:
        precio = None
    return precio, "Tramo confirmado" if precio is not None else "No hay un tramo confirmado aplicable"


def estado_objetivo(valor, objetivo, base_valida=True):
    if objetivo is None:
        return {"estado": "Sin objetivo", "diferencia": None, "porcentaje": None}
    if valor is None or not base_valida:
        return {"estado": "Por confirmar", "diferencia": None, "porcentaje": None}
    diferencia = valor - objetivo
    return {"estado": "Cumple" if diferencia <= 0 else "No cumple", "diferencia": diferencia,
            "porcentaje": porcentaje(diferencia, objetivo)}


def descripcion_incoterm(cotizacion):
    regla = cotizacion.get("incoterm", "Por confirmar")
    if regla == "No aplica":
        return "No aplica, confirmado por el usuario."
    if regla not in RIESGO_INCOTERM or cotizacion.get("version_incoterm") != "2020" or cotizacion.get("lugar_incoterm") in (None, "", "Por confirmar"):
        return "Regla, versión 2020 o lugar convenido por confirmar; responsabilidades pendientes."
    transporte = "Comprador" if regla in ("EXW", "FCA", "FAS", "FOB") else "Vendedor"
    importacion = "Vendedor" if regla == "DDP" else "Comprador"
    seguro = " El vendedor contrata el seguro previsto por la regla." if regla in ("CIF", "CIP") else ""
    return f"{regla} · {cotizacion['lugar_incoterm']} · 2020. Transporte principal: {transporte}. Despacho de importación: {importacion}. Riesgo: {RIESGO_INCOTERM[regla]}{seguro}"


def costo_y_plazo(fila, config):
    cotizacion = fila["cotizacion"]
    motivos = []
    cobertura = config["cobertura"].get(str(cotizacion["numero"]), {})
    total = fila["total_original"]
    if total is None:
        motivos.append("Total cotizado incompleto")
    gastos = cotizacion.get("gastos_comprador", {})
    valores = [importe_gasto(gastos[c]) if c in gastos else None for c in GASTOS_COMPRADOR]
    if any(v is None for v in valores):
        motivos.append("Gastos adicionales pendientes")
    if not config["destino"] or not cobertura.get("costos"):
        motivos.append("Cobertura de costos hasta el destino por confirmar")
    regla = cotizacion.get("incoterm")
    if regla != "No aplica" and (regla not in RIESGO_INCOTERM or cotizacion.get("version_incoterm") != "2020" or cotizacion.get("lugar_incoterm") in (None, "", "Por confirmar")):
        motivos.append("Incoterm, versión o lugar por confirmar")
    costo_origen = redondear_importe(total + sum(valores, Decimal("0"))) if total is not None and all(v is not None for v in valores) else None
    costo_convertido = convertir_total(costo_origen, fila["tipo"])
    if costo_convertido is None:
        motivos.append("Costo o conversión por confirmar")
    completo = costo_convertido if not motivos else None
    lt = cotizacion.get("entrega_dias") if (config["destino"] and cobertura.get("plazo") and cotizacion.get("alcance_lt") == "Recepción en destino (días calendario)") else None
    return {"completo": completo, "original": costo_origen, "provisional": costo_convertido,
            "motivos": motivos, "lt": lt}


def base_unitaria_valida(cotizacion, producto):
    if not producto["equivalente"] or not producto["base_precio"] or not producto.get("unidad"):
        return False
    return not any(g["estado"] == "Incluido en el precio" and g["importe"] != Decimal("0")
                   for g in cotizacion.get("gastos_cotizados", {}).values())


def calcular_savings_linea(cotizacion, linea, indice, tipo, producto, config):
    cantidad = linea["cantidad"]
    forecast = producto["forecast"]
    acuerdo = config["acuerdos"].get(f"{cotizacion['numero']}:{indice}", False)
    volumen_acumulado = forecast if acuerdo else None
    precio, motivo = precio_escenario(linea, cantidad, volumen_acumulado)
    if linea.get("precio_declarado") is not None and precio is not None and precio != linea["precio_declarado"]:
        precio, motivo = None, "El precio declarado difiere del tramo confirmado; revisar la cotización"
    convertido = precio * tipo if precio is not None and tipo is not None else None
    base = base_unitaria_valida(cotizacion, producto)
    actual = producto["actual"]
    diferencia = actual - convertido if base and actual is not None and convertido is not None else None
    ahorro_cotizado = redondear_importe(diferencia * cantidad) if diferencia is not None else None
    proyectado = None
    estado = "Sin forecast"
    if forecast is not None:
        estado = "Precio actual, base o precio ofertado por confirmar"
        if base and actual is not None and tipo is not None:
            if forecast == 0:
                proyectado, estado = Decimal("0.00"), "Sin compras previstas en el periodo"
            elif producto["plan"]:
                total = Decimal("0")
                for pedido in producto["plan"]:
                    p, razon = precio_escenario(linea, pedido, volumen_acumulado)
                    if p is None:
                        estado = f"Plan pendiente o no válido: {razon}"
                        break
                    total += (actual - p * tipo) * pedido
                else:
                    confirmado = acuerdo or config["vigencias"].get(f"{cotizacion['numero']}:{indice}", False)
                    proyectado = redondear_importe(total)
                    estado = "Proyección de precio con plan y vigencia confirmados" if confirmado else "Hipótesis para el plan: vigencia de los precios durante el periodo por confirmar"
            elif linea.get("alcance_precio") == "Volumen acumulado en un periodo" and acuerdo:
                # El comprador confirma el acuerdo del periodo y que sus pedidos cumplen MOQ y múltiplos.
                if linea.get("moq") is None or linea.get("estado_multiplo") == "Por confirmar" or (linea.get("estado_multiplo") == "Múltiplo indicado" and linea.get("multiplo") is None):
                    estado = "MOQ o múltiplos del acuerdo por confirmar"
                else:
                    copia = deepcopy(linea)
                    copia.update(moq=Decimal("0"), estado_multiplo="Sin múltiplo obligatorio", enteros=False)
                    p, razon = precio_escenario(copia, forecast, forecast)
                    if p is not None:
                        proyectado = redondear_importe((actual - p * tipo) * forecast)
                        estado = "Proyección con acuerdo acumulado y pedidos confirmados"
                    else:
                        estado = razon
            elif diferencia is not None:
                proyectado = redondear_importe(diferencia * forecast)
                estado = "Hipótesis: todas las unidades al precio cotizado; falta confirmar plan y validez"
    return {"cotizacion": cotizacion["numero"], "proveedor": cotizacion["proveedor"], "linea": indice + 1,
            "producto": linea["producto"], "unidad": linea["unidad"], "cantidad": cantidad,
            "moq": linea.get("moq"), "multiplo": linea.get("multiplo"), "precio": convertido,
            "actual": actual, "unitario": diferencia, "porcentaje": porcentaje(diferencia, actual),
            "cotizado": ahorro_cotizado, "forecast": forecast, "periodo": producto["periodo"],
            "proyectado": proyectado, "estado": estado, "motivo_precio": motivo,
            "objetivo": estado_objetivo(convertido, producto["target"], base), "base_valida": base}


def alternativas_volumen(cotizacion, linea, indice, tipo, producto):
    necesidad = producto["necesidad"]
    if necesidad is None or linea.get("moq") is None or linea.get("estado_multiplo") == "Por confirmar":
        return []
    cantidades = {max(necesidad, linea["moq"])}
    cantidades.update(max(necesidad, linea["moq"], t["desde"]) for t in linea.get("tramos", []) if t["desde"] is not None)
    candidatas = set()
    for cantidad in cantidades:
        if linea.get("enteros"):
            cantidad = cantidad.to_integral_value(rounding=ROUND_CEILING)
        if linea.get("estado_multiplo") == "Múltiplo indicado" and linea.get("multiplo") is not None:
            cantidad = (cantidad / linea["multiplo"]).to_integral_value(rounding=ROUND_CEILING) * linea["multiplo"]
        candidatas.add(cantidad)
    filas = []
    for cantidad in sorted(candidatas):
        precio, _ = precio_escenario(linea, cantidad)
        if precio is None or tipo is None:
            continue
        costo = redondear_importe(cantidad * precio * tipo)
        referencia = redondear_importe(necesidad * producto["actual"]) if producto["actual"] is not None and base_unitaria_valida(cotizacion, producto) else None
        filas.append({"cotizacion": cotizacion["numero"], "proveedor": cotizacion["proveedor"], "linea": indice + 1,
                      "producto": linea["producto"], "necesidad": necesidad, "cantidad": cantidad,
                      "excedente": cantidad - necesidad, "precio": precio * tipo, "desembolso": costo,
                      "referencia": referencia, "diferencia": costo - referencia if referencia is not None else None,
                      "nota": "Solo producto. Confirmar gastos y LT del nuevo volumen." if cantidad != linea["cantidad"] else "Solo producto; gastos separados."})
    return filas


def analizar_objetivos(resultado, datos):
    catalogo = catalogo_productos([f["cotizacion"] for f in resultado["filas"]])
    config = leer_configuracion(datos, catalogo)
    savings, volumen, ofertas = [], [], []
    for fila in resultado["filas"]:
        cotizacion = fila["cotizacion"]
        costo = costo_y_plazo(fila, config)
        precios, firma, equivalentes, compra_valida, motivos_compra = [], [], True, True, []
        for i, linea in enumerate(lineas_de(cotizacion)):
            clave = id_producto(linea)
            producto = config["productos"][clave]
            ahorro = calcular_savings_linea(cotizacion, linea, i, fila["tipo"], producto, config)
            savings.append(ahorro)
            volumen.extend(alternativas_volumen(cotizacion, linea, i, fila["tipo"], producto))
            precios.append(ahorro["objetivo"])
            equivalentes = equivalentes and producto["equivalente"] and bool(linea["unidad"])
            motivo = condicion_cantidad(linea, linea["cantidad"])
            if motivo:
                motivos_compra.append(f"Línea {i+1}: {motivo}")
            if ahorro["precio"] is None:
                motivos_compra.append(f"Línea {i+1}: {ahorro['motivo_precio']}")
            demanda_igual = producto["necesidad"] is None or linea["cantidad"] == producto["necesidad"]
            if not demanda_igual:
                motivos_compra.append(f"Línea {i+1}: la cantidad cotizada difiere de la necesidad; revisar escenarios de volumen")
            compra_valida = compra_valida and not motivo and ahorro["precio"] is not None and demanda_igual
            firma.append((clave, numero(linea["cantidad"])))
        presupuesto = estado_objetivo(costo["completo"], config["presupuesto"])
        plazo = estado_objetivo(costo["lt"], config["lt"])
        estados = [e["estado"] for e in [*precios, presupuesto, plazo] if e["estado"] != "Sin objetivo"]
        ofertas.append({"cotizacion": cotizacion, "costo": costo, "precios": precios,
                        "presupuesto": presupuesto, "plazo": plazo,
                        "cumple_todo": bool(estados) and all(e == "Cumple" for e in estados),
                        "tiene_objetivos": bool(estados), "equivalentes": equivalentes, "compra_valida": bool(compra_valida),
                        "motivos_compra": motivos_compra,
                        "firma": tuple(sorted(firma)), "incoterm": descripcion_incoterm(cotizacion)})
    grupos = defaultdict(list)
    for oferta in ofertas:
        grupos[oferta["firma"]].append(oferta)
    escenarios = [escenarios_grupo(grupo, config, resultado["moneda_analisis"]) for grupo in grupos.values()]
    return {"config": config, "ofertas": ofertas, "savings": savings, "volumen": volumen, "escenarios": escenarios}


def escenarios_grupo(grupo, config, moneda):
    validas = [o for o in grupo if o["equivalentes"] and o["compra_valida"] and o["costo"]["completo"] is not None]
    nombre = lambda o: nombre_oferta(o["cotizacion"])
    nombres = lambda lista: ", ".join(nombre(o) for o in lista)
    escenario = {"ofertas": [o["cotizacion"]["numero"] for o in grupo], "precio": [], "urgencia": [], "equilibrio": []}
    if len(validas) < 2:
        aviso = "No hay dos ofertas equivalentes con compra válida y costo completo confirmado hasta el mismo destino. Revisa los datos pendientes."
        for clave in ("precio", "urgencia", "equilibrio"):
            escenario[clave] = [aviso]
        return escenario
    minimo = min(o["costo"]["completo"] for o in validas)
    baratas = [o for o in validas if o["costo"]["completo"] == minimo]
    escenario["precio"].append(f"Menor costo completo: {nombres(baratas)}, {importe(minimo, moneda)}." + (" Hay empate de costo." if len(baratas) > 1 else ""))
    for o in validas:
        if o not in baratas:
            escenario["precio"].append(f"Frente a {nombre(o)}, la diferencia es {importe(o['costo']['completo'] - minimo, moneda)}.")
    for o in baratas:
        escenario["precio"].append(f"{nombre(o)}: presupuesto {o['presupuesto']['estado'].lower()}, plazo {o['plazo']['estado'].lower()}; LT {numero(o['costo']['lt'])} días.")
    conocidas = [o for o in validas if o["costo"]["lt"] is not None]
    if config["lt"] is not None:
        a_tiempo = [o for o in conocidas if o["costo"]["lt"] <= config["lt"]]
        minimo_urgente = min((o["costo"]["completo"] for o in a_tiempo), default=None)
        urgentes = [o for o in a_tiempo if o["costo"]["completo"] == minimo_urgente]
    else:
        lt_min = min((o["costo"]["lt"] for o in conocidas), default=None)
        urgentes = [o for o in conocidas if o["costo"]["lt"] == lt_min]
    if urgentes:
        escenario["urgencia"].append(("Menor costo entre quienes cumplen el plazo: " if config["lt"] is not None else "Más rápida entre ofertas con plazo confirmado, sin target LT definido: ") + nombres(urgentes) + ".")
        for o in urgentes:
            sobrecosto = o["costo"]["completo"] - minimo
            pct = porcentaje(sobrecosto, minimo)
            base = baratas[0] if len(baratas) == 1 else None
            dias = base["costo"]["lt"] - o["costo"]["lt"] if base and base["costo"]["lt"] is not None else None
            texto = f"{nombre(o)}: {importe(o['costo']['completo'], moneda)}, LT {numero(o['costo']['lt'])} días; diferencia frente al menor costo {importe(sobrecosto, moneda)}"
            texto += f" ({numero(pct, 2)} %)" if pct is not None else " (porcentaje no calculable con base cero)"
            texto += f"; permite recibir {numero(dias)} días antes" if dias is not None and dias > 0 else "; ahorro de días frente al menor costo no confirmado o no positivo"
            if dias is not None and dias > 0 and config["tolerancia"] is not None and pct is not None:
                texto += "; " + ("dentro de" if pct <= config["tolerancia"] else "supera") + f" tu tolerancia del {numero(config['tolerancia'])} %"
            texto += f". Presupuesto: {o['presupuesto']['estado'].lower()}."
            escenario["urgencia"].append(texto)
    elif config["lt"] is not None:
        escenario["urgencia"].append("Ninguna oferta tiene cumplimiento del plazo confirmado.")
        if conocidas:
            demora = min(o["costo"]["lt"] for o in conocidas) - config["lt"]
            escenario["urgencia"].append(f"La menor demora conocida es de {numero(demora)} días sobre tu objetivo.")
    else:
        escenario["urgencia"].append("Faltan plazos completos confirmados para identificar la opción más rápida.")
    if any(o["tiene_objetivos"] for o in validas):
        cumplen = [o for o in validas if o["cumple_todo"]]
        menor = min((o["costo"]["completo"] for o in cumplen), default=None)
        ganadoras = [o for o in cumplen if o["costo"]["completo"] == menor]
        escenario["equilibrio"].append(f"Cumple todos tus objetivos con el menor costo: {nombres(ganadoras)}, {importe(menor, moneda)}." if ganadoras else "Ninguna oferta tiene cumplimiento de todos los objetivos confirmado. Revisa el detalle por criterio.")
    else:
        escenario["equilibrio"].append("Sin objetivos de precio, presupuesto o plazo definidos para esta cesta. Puedes completar los que necesites.")
    if len(validas) < len(grupo):
        nota = "Ofertas excluidas o pendientes: " + nombres([o for o in grupo if o not in validas]) + "."
        for clave in ("precio", "urgencia", "equilibrio"):
            escenario[clave].append(nota)
    return escenario


def inicializar_sesion():
    iniciales = {
        "cotizaciones_confirmadas": [], "formulario_abierto": False,
        "borrador": None, "campos_formulario": {}, "version_formulario": 0,
        "moneda_analisis": "", "moneda_anterior": "", "version_tipos": 0,
        "tipos_texto": {}, "resultado": None, "firma_resultado": None,
        "errores_formulario": [], "error_analisis": "", "aviso": "",
        "numero_edicion": None, "configuracion_analisis": {},
        "destino_analisis": "", "objetivo_presupuesto": "", "objetivo_lt": "",
        "tolerancia_texto": "", "prioridad_analisis": "Sin preferencia",
        "prueba_conexion_ia": None,
    }
    for clave, valor in iniciales.items():
        if clave not in st.session_state:
            st.session_state[clave] = deepcopy(valor)


def abrir_formulario():
    st.session_state.formulario_abierto = True
    st.session_state.aviso = ""


def cerrar_formulario():
    st.session_state.formulario_abierto = False
    st.session_state.borrador = None
    st.session_state.campos_formulario = {}
    st.session_state.errores_formulario = []
    st.session_state.version_formulario += 1
    st.session_state.numero_edicion = None


def corregir_borrador():
    st.session_state.borrador = None
    st.session_state.version_formulario += 1


def confirmar_borrador():
    if st.session_state.borrador is None:
        return
    nueva = deepcopy(st.session_state.borrador)
    edicion = st.session_state.numero_edicion
    nueva["numero"] = edicion or len(st.session_state.cotizaciones_confirmadas) + 1
    if edicion is None:
        st.session_state.cotizaciones_confirmadas = [*st.session_state.cotizaciones_confirmadas, nueva]
    else:
        st.session_state.cotizaciones_confirmadas = [nueva if c["numero"] == edicion else c for c in st.session_state.cotizaciones_confirmadas]
    cerrar_formulario()
    st.session_state.error_analisis = ""
    st.session_state.aviso = f"Cotización {nueva['numero']} {'actualizada' if edicion else 'confirmada y agregada'}."


def editar_cotizacion(numero_cotizacion):
    cotizacion = next(c for c in st.session_state.cotizaciones_confirmadas if c["numero"] == numero_cotizacion)
    if cotizacion.get("entrada_manual"):
        campos = deepcopy(cotizacion["entrada_manual"])
    else:
        campos = {c: str(cotizacion[c]) if cotizacion.get(c) is not None else "" for c in CAMPOS}
        campos["lineas"] = []
        for linea in lineas_de(cotizacion):
            dato = {k: str(linea.get(k)) if linea.get(k) is not None else "" for k in ("identificador", "producto", "cantidad", "unidad", "precio_unitario", "moq", "multiplo", "condiciones_tramos")}
            for k in ("estado_multiplo", "alcance_precio", "precio_todo_pedido", "enteros"):
                if k in linea:
                    dato[k] = linea[k]
            if linea.get("moq_origen", "").startswith("Supuesto"):
                dato["moq"] = ""
                dato["confirmar_moq_uno"] = True
            dato["tramos"] = [{"tipo": t["tipo"], "desde": str(t["desde"]) if t["desde"] is not None else "",
                               "hasta": str(t["hasta"]) if t["tipo"] == "Entre dos cantidades" and t["hasta"] is not None else "",
                               "precio": str(t["precio"]) if t["precio"] is not None else ""} for t in linea.get("tramos", [])]
            campos["lineas"].append(dato)
        for k in ("incoterm", "version_incoterm", "lugar_incoterm", "alcance_lt"):
            campos[k] = cotizacion.get(k, "Por confirmar")
        for k, gasto in cotizacion.get("gastos_cotizados", {}).items():
            campos[f"estado_{k}"] = gasto["estado"]
            campos[k] = str(gasto["importe"]) if gasto["importe"] is not None else ""
        campos["gastos_comprador"] = deepcopy(cotizacion.get("gastos_comprador", {}))
        for gasto in campos["gastos_comprador"].values():
            gasto["importe"] = str(gasto["importe"]) if gasto["importe"] is not None else ""
    st.session_state.campos_formulario = campos
    st.session_state.numero_edicion = numero_cotizacion
    st.session_state.borrador = None
    st.session_state.formulario_abierto = True
    st.session_state.version_formulario += 1
    st.session_state.errores_formulario = []
    st.session_state.aviso = ""


def cambiar_moneda():
    actual = st.session_state.moneda_analisis.strip().upper()
    st.session_state.moneda_analisis = actual
    if actual != st.session_state.moneda_anterior:
        st.session_state.tipos_texto = {}
        st.session_state.version_tipos += 1
        st.session_state.moneda_anterior = actual
        st.session_state.objetivo_presupuesto = ""
        for clave in list(st.session_state):
            if clave.startswith("p_") and clave.endswith(("_actual", "_target")):
                st.session_state[clave] = ""
    st.session_state.error_analisis = ""


def guardar_tipo(origen, clave):
    st.session_state.tipos_texto[origen] = st.session_state[clave].strip()
    st.session_state.error_analisis = ""


def fila_cotizacion(cotizacion):
    moneda = cotizacion["moneda"]
    fila = {
        "N.º": cotizacion["numero"], "Proveedor": cotizacion["proveedor"],
        "Total original": importe(total_original(cotizacion), moneda),
        "Producto o servicio": cotizacion["producto"], "Cantidad": numero(cotizacion["cantidad"]),
        "Unidad": cotizacion["unidad"] or "Por confirmar", "Moneda original": moneda or "Por confirmar",
        "Precio unitario": numero(cotizacion["precio_unitario"]),
        "Envío total": numero(cotizacion["envio"]), "Impuestos totales": numero(cotizacion["impuestos"]),
        "Entrega (días)": numero(cotizacion["entrega_dias"]),
        "Condiciones de pago": cotizacion["condiciones_pago"] or "Por confirmar",
    }
    if cotizacion.get("lineas"):
        fila["Líneas"] = len(cotizacion["lineas"])
        fila["Incoterm"] = cotizacion["incoterm"]
        fila["Versión Incoterm"] = cotizacion["version_incoterm"]
        fila["Lugar convenido"] = cotizacion["lugar_incoterm"]
        fila["Plazo informado (días)"] = fila.pop("Entrega (días)")
        fila["Alcance del plazo"] = cotizacion["alcance_lt"]
        if len(cotizacion["lineas"]) > 1:
            for campo in ("Cantidad", "Unidad", "Precio unitario"):
                fila[campo] = "Ver líneas"
    return fila


def filas_lineas(cotizacion):
    filas = []
    for i, linea in enumerate(cotizacion["lineas"], 1):
        with localcontext() as contexto:
            contexto.prec = 128
            subtotal = (redondear_importe(linea["cantidad"] * linea["precio_unitario"])
                        if linea["cantidad"] is not None and linea["precio_unitario"] is not None else None)
        filas.append({
            "Línea": i, "Código": linea["identificador"] or "Sin código",
            "Producto o servicio": linea["producto"], "Cantidad": numero(linea["cantidad"]),
            "UOM": linea["unidad"] or "Por confirmar", "Precio unitario": numero(linea["precio_unitario"]),
            "Subtotal": importe(subtotal, cotizacion["moneda"]), "MOQ": numero(linea["moq"]),
            "Origen MOQ": linea["moq_origen"], "Múltiplo": numero(linea["multiplo"]),
            "Condición del múltiplo": linea["estado_multiplo"],
            "Estado de compra": "; ".join(linea["avisos_compra"]) or "Cumple las condiciones registradas",
        })
    return filas


def mostrar_detalle_cotizacion(cotizacion):
    st.write("**Líneas de la cotización**")
    st.dataframe(filas_lineas(cotizacion), hide_index=True, width="stretch")
    for i, linea in enumerate(cotizacion["lineas"], 1):
        if not linea["tramos"]:
            continue
        st.write(f"**Precios por volumen · Línea {i}**")
        st.dataframe([
            {"Tipo": t["tipo"], "Desde / cantidad exacta": numero(t["desde"]),
             "Hasta": "Sin límite superior (rango confirmado)" if t["tipo"] == "A partir de" else numero(t["hasta"]),
             "Precio unitario": numero(t["precio"]), "Moneda": cotizacion["moneda"] or "Por confirmar",
             "UOM": linea["unidad"] or "Por confirmar"}
            for t in linea["tramos"]
        ], hide_index=True, width="stretch")
        st.text(f"Alcance: {linea['alcance_precio']}. Precio para todas las unidades: {'confirmado' if linea['precio_todo_pedido'] else 'por confirmar'}.")
        if linea["condiciones_tramos"]:
            st.text(linea["condiciones_tramos"])
    st.write("**Condiciones comerciales**")
    st.dataframe([
        {"Campo": "Proveedor", "Información": cotizacion["proveedor"]},
        {"Campo": "Moneda original", "Información": cotizacion["moneda"] or "Por confirmar"},
        {"Campo": "Incoterm", "Información": cotizacion["incoterm"]},
        {"Campo": "Versión", "Información": cotizacion["version_incoterm"]},
        {"Campo": "Lugar / puerto convenido", "Información": cotizacion["lugar_incoterm"]},
        {"Campo": "Plazo informado", "Información": f"{numero(cotizacion['entrega_dias'])} días"},
        {"Campo": "Alcance del plazo", "Información": cotizacion["alcance_lt"]},
        {"Campo": "Condiciones de pago", "Información": cotizacion["condiciones_pago"] or "Por confirmar"},
    ], hide_index=True, width="stretch")
    gastos = []
    for campo, gasto in cotizacion["gastos_cotizados"].items():
        gastos.append({"Concepto": ETIQUETAS[campo], "Responsable del cargo": "Proveedor",
                       "Estado": gasto["estado"], "Importe informado": numero(gasto["importe"]), "Motivo": ""})
    for campo, gasto in cotizacion["gastos_comprador"].items():
        gastos.append({"Concepto": GASTOS_COMPRADOR[campo], "Responsable del cargo": "Comprador",
                       "Estado": gasto["estado"], "Importe informado": numero(gasto["importe"]), "Motivo": gasto["justificacion"]})
    st.write("**Gastos registrados**")
    st.dataframe(gastos, hide_index=True, width="stretch")
    st.metric("Total cotizado por el proveedor", importe(total_original(cotizacion), cotizacion["moneda"]))
    st.caption("El total cotizado suma las líneas y los cargos adicionales del proveedor una sola vez. Los gastos adicionales del comprador se muestran por separado.")


def mostrar_formulario():
    st.subheader("1. Agrega y revisa una cotización")
    st.caption("Completa los datos del proveedor y sus productos. Puedes añadir varias líneas y precios por volumen. Los datos desconocidos quedan por confirmar.")
    if st.session_state.borrador is not None:
        cotizacion = st.session_state.borrador
        mostrar_detalle_cotizacion(cotizacion)
        pendientes = campos_pendientes(cotizacion)
        if pendientes:
            st.warning("Revisa estos datos: " + "; ".join(pendientes) + ". Puedes conservar la cotización con estas limitaciones o corregirla antes de confirmar.")
        st.write("**¿La información de esta cotización es correcta?**")
        confirmar, corregir, cancelar = st.columns([2, 1, 1])
        confirmar.button("Confirmar cambios" if st.session_state.numero_edicion else "Confirmar y agregar", type="primary", key="confirmar", on_click=confirmar_borrador, width="stretch")
        corregir.button("Corregir datos", key="corregir", on_click=corregir_borrador, width="stretch")
        cancelar.button("Cancelar", key="cancelar_revision", on_click=cerrar_formulario, width="stretch")
        return

    previos = st.session_state.campos_formulario
    version = st.session_state.version_formulario
    accion = None

    def texto(campo, etiqueta, previo, columna=None, ejemplo="", largo=160):
        return (columna or st).text_input(
            etiqueta, value=str(previo.get(campo, "")), placeholder=ejemplo,
            key=f"cotizacion_{version}_{campo}", max_chars=largo,
        )

    def seleccion(campo, etiqueta, opciones, previo, columna=None, defecto=None):
        valor = previo.get(campo, defecto or opciones[0])
        return (columna or st).selectbox(etiqueta, opciones, index=opciones.index(valor) if valor in opciones else 0,
                                         key=f"cotizacion_{version}_{campo}")

    with st.form(f"formulario_cotizacion_{version}", enter_to_submit=False):
        izquierda, derecha = st.columns(2)
        campos = {
            "proveedor": texto("proveedor", "Proveedor *", previos, izquierda, "Ej.: Proveedor Alfa"),
            "moneda": texto("moneda", "Moneda original", previos, derecha, "Ej.: USD, EUR o CRC", 3),
        }
        st.caption("Todos los precios y gastos de esta cotización se registran en su moneda original. Usa coma o punto decimal, sin separadores de miles.")
        campos["lineas"] = []
        for i, anterior in enumerate(previos.get("lineas", [{}])):
            prefijo = "" if i == 0 else f"linea_{i}_"
            anterior_widgets = {prefijo + k: v for k, v in anterior.items()}
            linea = {}
            with st.container(border=True):
                st.write(f"**Línea {i + 1}**")
                a, b = st.columns(2)
                for campo, etiqueta, columna, ejemplo, largo in (
                    ("producto", "Producto o servicio *", a, "Ej.: Válvula de acero", 200),
                    ("identificador", "Código o referencia (opcional)", b, "Ej.: VAL-01", 60),
                    ("cantidad", "Cantidad cotizada", a, "Ej.: 900", 32),
                    ("unidad", "Unidad de medida (UOM)", b, "Ej.: piezas, kg, metros", 40),
                    ("precio_unitario", "Precio por unidad", a, "O completa los tramos de precio", 32),
                ):
                    linea[campo] = texto(prefijo + campo, etiqueta, anterior_widgets, columna, ejemplo, largo)
                linea["enteros"] = st.checkbox("Esta unidad solo admite cantidades enteras", value=bool(anterior.get("enteros")), key=f"cotizacion_{version}_{prefijo}enteros")
                with st.expander(f"MOQ, múltiplos y precios por volumen · Línea {i + 1}", expanded=bool(anterior.get("tramos"))):
                    a, b = st.columns(2)
                    linea["moq"] = texto(prefijo + "moq", "MOQ: cantidad mínima", anterior_widgets, a, "Si no está indicado, se propone 1", 32)
                    linea["confirmar_moq_uno"] = st.checkbox("Si el MOQ no está indicado, confirmo usar 1 como supuesto", value=bool(anterior.get("confirmar_moq_uno")), key=f"cotizacion_{version}_{prefijo}confirmar_moq_uno")
                    a, b = st.columns(2)
                    linea["estado_multiplo"] = seleccion(prefijo + "estado_multiplo", "Condición del múltiplo", ESTADOS_MULTIPLO, anterior_widgets, a)
                    linea["multiplo"] = texto(prefijo + "multiplo", "Múltiplo obligatorio (si existe)", anterior_widgets, b, "Ej.: 500; no es el MOQ", 32)
                    st.caption("MOQ 500 permite comprar 900. Un múltiplo obligatorio de 500 exige cantidades como 500 o 1.000.")
                    linea["alcance_precio"] = seleccion(prefijo + "alcance_precio", "¿Cómo se aplica el precio por volumen?", ALCANCES_PRECIO, anterior_widgets)
                    linea["precio_todo_pedido"] = st.checkbox("Confirmo que cada tramo indica un precio por unidad para todas las unidades del pedido", value=bool(anterior.get("precio_todo_pedido")), key=f"cotizacion_{version}_{prefijo}precio_todo_pedido")
                    linea["tramos"] = []
                    for j, previo_tramo in enumerate(anterior.get("tramos", [])):
                        tramo_prefijo = prefijo + f"tramo_{j}_"
                        widgets_tramo = {tramo_prefijo + k: v for k, v in previo_tramo.items()}
                        st.write(f"Tramo {j + 1}")
                        tramo = {"tipo": seleccion(tramo_prefijo + "tipo", "Tipo de cantidad", TIPOS_TRAMO, widgets_tramo)}
                        a, b, c = st.columns(3)
                        for campo, etiqueta, columna in (("desde", "Desde / cantidad exacta", a), ("hasta", "Hasta (solo intervalo)", b), ("precio", "Precio por unidad del tramo", c)):
                            tramo[campo] = texto(tramo_prefijo + campo, etiqueta, widgets_tramo, columna, largo=32)
                        linea["tramos"].append(tramo)
                        if st.form_submit_button(f"Quitar tramo {j + 1} de la línea {i + 1}", key=f"quitar_tramo_{i}_{j}"):
                            accion = ("quitar_tramo", i, j)
                    if st.form_submit_button(f"Añadir tramo a la línea {i + 1}", key=f"agregar_tramo_{i}"):
                        accion = ("agregar_tramo", i)
                    linea["condiciones_tramos"] = texto(prefijo + "condiciones_tramos", "Condiciones, periodo, vigencia o datos por aclarar", anterior_widgets, largo=500)
                    st.caption("No amplíes una cantidad exacta a «o más» sin confirmación. Los precios por bloques o paquetes ambiguos requieren aclaración.")
                if i > 0 and st.form_submit_button(f"Quitar línea {i + 1}", key=f"quitar_linea_{i}"):
                    accion = ("quitar_linea", i)
            campos["lineas"].append(linea)
        if st.form_submit_button("Agregar otra línea", key="agregar_linea"):
            accion = ("agregar_linea",)

        with st.expander("Entrega, pago e Incoterm", expanded=False):
            a, b = st.columns(2)
            campos["entrega_dias"] = texto("entrega_dias", "Plazo informado (días)", previos, a, "Ej.: 10", 32)
            campos["alcance_lt"] = seleccion("alcance_lt", "¿Qué cubre ese plazo?", ALCANCES_LT, previos, b)
            campos["condiciones_pago"] = texto("condiciones_pago", "Condiciones de pago", previos, ejemplo="Ej.: pago a 30 días")
            campos["incoterm"] = seleccion("incoterm", "Incoterm", INCOTERMS, previos, a)
            campos["version_incoterm"] = seleccion("version_incoterm", "Versión del Incoterm", ("Por confirmar", "2020", "Otra versión"), previos, b)
            campos["lugar_incoterm"] = texto("lugar_incoterm", "Lugar, dirección o puerto convenido", previos, largo=240)
            st.caption("El código y el lugar describen condiciones de entrega; no indican por sí solos cuánto costarán los gastos adicionales.")

        with st.expander("Envío, impuestos y gastos del comprador", expanded=False):
            st.write("**Cargos del proveedor**")
            for campo in ("envio", "impuestos"):
                a, b = st.columns(2)
                campos[f"estado_{campo}"] = seleccion(f"estado_{campo}", f"Estado de {ETIQUETAS[campo].lower()}", ESTADOS_GASTO, previos, a, "Adicional conocido")
                campos[campo] = texto(campo, ETIQUETAS[campo], previos, b, "Importe total; 0 si está confirmado", 32)
            st.write("**Gastos adicionales del comprador**")
            st.caption("Marca lo incluido para no sumarlo de nuevo. Un gasto pendiente no se considera cero.")
            campos["gastos_comprador"] = {}
            for campo, etiqueta in GASTOS_COMPRADOR.items():
                dato = previos.get("gastos_comprador", {}).get(campo, {})
                prefijo = f"gasto_{campo}_"
                widgets = {prefijo + k: v for k, v in dato.items()}
                a, b = st.columns(2)
                campos["gastos_comprador"][campo] = {
                    "estado": seleccion(prefijo + "estado", etiqueta, ESTADOS_COMPRADOR, widgets, a),
                    "importe": texto(prefijo + "importe", f"Importe de {etiqueta.lower()}", widgets, b, largo=32),
                    "justificacion": texto(prefijo + "justificacion", f"Motivo si {etiqueta.lower()} no aplica", widgets, largo=240),
                }
        revisar = st.form_submit_button("Revisar cotización", type="primary", width="stretch")
    if accion:
        if accion[0] == "agregar_linea":
            campos["lineas"].append({})
        elif accion[0] == "quitar_linea":
            campos["lineas"].pop(accion[1])
        elif accion[0] == "agregar_tramo":
            campos["lineas"][accion[1]]["tramos"].append({})
        elif accion[0] == "quitar_tramo":
            campos["lineas"][accion[1]]["tramos"].pop(accion[2])
        st.session_state.campos_formulario = deepcopy(campos)
        st.session_state.version_formulario += 1
        st.session_state.errores_formulario = []
        st.rerun()
    if revisar:
        st.session_state.campos_formulario = deepcopy(campos)
        try:
            st.session_state.borrador = crear_cotizacion_manual(campos)
            st.session_state.errores_formulario = []
            st.rerun()
        except ValueError as error:
            st.session_state.errores_formulario = [str(error)]
    for error in st.session_state.errores_formulario:
        st.error(error)
    st.button("Cancelar cotización", key="cancelar_formulario", on_click=cerrar_formulario)


def contexto_cobertura(destino, cotizacion):
    return sha256((destino + firma_datos([cotizacion], cotizacion.get("moneda"), {})).encode()).hexdigest()[:12]


def contexto_producto(relacionadas):
    return sha256(firma_datos(relacionadas, "", {}).encode()).hexdigest()[:10]


def contexto_vigencia(producto, linea, cotizacion):
    return sha256(json.dumps([producto["forecast"], producto["periodo"], producto["plan"], linea, cotizacion], default=str, sort_keys=True).encode()).hexdigest()[:12]


def cargar_ejemplo():
    cotizaciones = []
    destino = "Almacén del comprador — ejemplo ficticio"
    for numero_cotizacion, proveedor, precio, lt in ((1, "Proveedor A (ficticio)", "10", "30"), (2, "Proveedor B (ficticio)", "10.80", "12")):
        datos = {"proveedor": proveedor, "moneda": "USD", "envio": "0", "impuestos": "0", "entrega_dias": lt,
                 "condiciones_pago": "Pago a 30 días", "alcance_lt": "Recepción en destino (días calendario)",
                 "incoterm": "DDP", "version_incoterm": "2020", "lugar_incoterm": destino,
                 "lineas": [{"producto": "Válvula de ejemplo", "identificador": "VAL-EJEMPLO", "cantidad": "100", "unidad": "piezas",
                             "precio_unitario": precio, "moq": "1", "estado_multiplo": "Sin múltiplo obligatorio", "enteros": True, "tramos": []}],
                 "gastos_comprador": {k: {"estado": "Incluido en la cotización", "importe": "", "justificacion": ""} for k in GASTOS_COMPRADOR}}
        cotizacion = crear_cotizacion_manual(datos)
        cotizacion["numero"] = numero_cotizacion
        cotizaciones.append(cotizacion)
    st.session_state.cotizaciones_confirmadas = cotizaciones
    st.session_state.moneda_analisis = st.session_state.moneda_anterior = "USD"
    st.session_state.destino_analisis = destino
    st.session_state.objetivo_presupuesto = "1100"
    st.session_state.objetivo_lt = "15"
    st.session_state.tolerancia_texto = "8"
    st.session_state.prioridad_analisis = "Urgencia"
    clave = id_producto(cotizaciones[0]["lineas"][0])
    producto = {"actual": "12", "target": "", "necesidad": "100", "forecast": "1000", "periodo": "Periodo ficticio de ejemplo", "plan": ";".join(["100"] * 10)}
    for campo, valor in producto.items():
        st.session_state[f"p_{clave}_{campo}"] = valor
    contexto = contexto_producto(cotizaciones)
    st.session_state[f"p_{clave}_equivalente_{contexto}"] = True
    st.session_state[f"p_{clave}_base_{contexto}"] = True
    for cotizacion in cotizaciones:
        referencia = contexto_cobertura(destino, cotizacion)
        st.session_state[f"cob_costos_{cotizacion['numero']}_{referencia}"] = True
        st.session_state[f"cob_plazo_{cotizacion['numero']}_{referencia}"] = True
        referencia = contexto_vigencia(producto, cotizacion["lineas"][0], cotizacion)
        st.session_state[f"vigencia_{cotizacion['numero']}_0_{referencia}"] = True
    st.session_state.aviso = "Ejemplo ficticio cargado. Puedes cambiar sus objetivos y pulsar «Analizar cotizaciones»."


def mostrar_opciones_analisis(cotizaciones, moneda):
    datos = {"productos": {}, "cobertura": {}, "acuerdos": {}, "vigencias": {}}
    datos["destino"] = st.text_input("Destino final común de comparación", key="destino_analisis", max_chars=240,
                                     placeholder="Ej.: almacén del comprador, dirección…",
                                     help="Necesario para comparar costos completos y plazos de recepción. Puedes consultar información parcial si falta.")
    with st.expander("Confirmar cobertura hasta el destino", expanded=False):
        st.caption("Confirma lo revisado para cada oferta. Los gastos o plazos pendientes seguirán apareciendo como tales. Puedes corregir la oferta desde «Cotizaciones confirmadas».")
        for cotizacion in cotizaciones:
            referencia = contexto_cobertura(datos["destino"], cotizacion)
            st.text(nombre_oferta(cotizacion))
            costos = st.checkbox("Los gastos registrados cubren la llegada a este destino", key=f"cob_costos_{cotizacion['numero']}_{referencia}", disabled=not datos["destino"].strip())
            plazo = st.checkbox("El LT registrado cubre la recepción en este destino desde la confirmación del pedido", key=f"cob_plazo_{cotizacion['numero']}_{referencia}", disabled=not datos["destino"].strip() or cotizacion.get("alcance_lt") != "Recepción en destino (días calendario)")
            datos["cobertura"][str(cotizacion["numero"])] = {"costos": costos, "plazo": plazo}
    with st.expander("Objetivos de la compra — opcional", expanded=False):
        a, b = st.columns(2)
        datos["presupuesto"] = a.text_input(f"Presupuesto máximo por cotización o cesta ({moneda or 'moneda por elegir'})", key="objetivo_presupuesto", max_chars=32, disabled=not moneda)
        datos["lt"] = b.text_input("Plazo máximo hasta recepción (días calendario)", key="objetivo_lt", max_chars=32)
        datos["prioridad"] = a.selectbox("Prioridad principal", PRIORIDADES, key="prioridad_analisis")
        datos["tolerancia"] = b.text_input("Sobrecosto aceptable por urgencia (%)", key="tolerancia_texto", max_chars=32)
        st.caption("Todo es opcional. El presupuesto se contrasta por separado con cada cesta equivalente; no se suman compras distintas. El target price se introduce por producto a continuación.")
    catalogo = catalogo_productos(cotizaciones)
    if catalogo:
        with st.expander("Productos, precio actual, target price y forecast — opcional", expanded=False):
            st.caption("Confirma las equivalencias para los escenarios de decisión. Los importes por unidad usan la moneda del análisis; el precio actual es tu referencia de compra y el target price es tu objetivo.")
            for clave, producto in catalogo.items():
                with st.container(border=True):
                    st.text(f"{producto['producto']} · UOM: {producto['unidad'] or 'por confirmar'}")
                    relacionadas = [next(c for c in cotizaciones if c["numero"] == n) for n, _ in producto["ofertas"]]
                    referencias = ", ".join(f"cotización {n}, línea {i+1}" for n, i in producto["ofertas"])
                    st.caption(referencias)
                    contexto = contexto_producto(relacionadas)
                    p = {
                        "equivalente": st.checkbox("Confirmo que las líneas agrupadas son el mismo producto y unidad", key=f"p_{clave}_equivalente_{contexto}"),
                        "base_precio": st.checkbox("Confirmo que los precios unitarios comparan la misma base del producto, sin gastos logísticos no desglosados", key=f"p_{clave}_base_{contexto}"),
                    }
                    a, b = st.columns(2)
                    p["actual"] = a.text_input(f"Precio actual por unidad ({moneda or 'moneda por elegir'})", key=f"p_{clave}_actual", max_chars=32, disabled=not moneda)
                    p["target"] = b.text_input(f"Target price por unidad ({moneda or 'moneda por elegir'})", key=f"p_{clave}_target", max_chars=32, disabled=not moneda)
                    p["necesidad"] = a.text_input("Cantidad necesaria para el pedido", key=f"p_{clave}_necesidad", max_chars=32)
                    p["forecast"] = b.text_input("Forecast: unidades del periodo", key=f"p_{clave}_forecast", max_chars=32)
                    p["periodo"] = st.text_input("Periodo del forecast", key=f"p_{clave}_periodo", placeholder="Ej.: próximo trimestre o año indicado", max_chars=100)
                    p["plan"] = st.text_area("Plan de pedidos (opcional)", key=f"p_{clave}_plan", placeholder="Ej.: 300;300;300 para tres pedidos. Usa punto y coma o una cantidad por línea.", max_chars=4000)
                    for n, i in producto["ofertas"]:
                        cotizacion = next(c for c in cotizaciones if c["numero"] == n)
                        linea = lineas_de(cotizacion)[i]
                        referencia = contexto_vigencia(p, linea, cotizacion)
                        if linea.get("alcance_precio") == "Volumen acumulado en un periodo":
                            datos["acuerdos"][f"{n}:{i}"] = st.checkbox(
                                f"Cotización {n}, línea {i+1}: confirmo el acuerdo acumulado para este forecast y periodo, y que sus pedidos cumplen MOQ y múltiplos",
                                key=f"acuerdo_{n}_{i}_{referencia}", disabled=not p["forecast"].strip() or not p["periodo"].strip(),
                            )
                        elif p["plan"].strip():
                            datos["vigencias"][f"{n}:{i}"] = st.checkbox(
                                f"Cotización {n}, línea {i+1}: confirmo la vigencia de los precios y condiciones para este plan y periodo",
                                key=f"vigencia_{n}_{i}_{referencia}", disabled=not p["forecast"].strip() or not p["periodo"].strip(),
                            )
                    datos["productos"][clave] = p
    return datos


def mostrar_analisis_ampliado(resultado):
    ampliado = resultado["ampliado"]
    config = ampliado["config"]
    moneda = resultado["moneda_analisis"]
    st.write("**Costo y cumplimiento por oferta**")
    resumen, detalle_objetivos = [], []
    por_numero = {f["cotizacion"]["numero"]: f for f in resultado["filas"]}
    for o in ampliado["ofertas"]:
        c = o["cotizacion"]
        fila = por_numero[c["numero"]]
        resumen.append({"Cotización": c["numero"], "Proveedor": c["proveedor"],
                        "Total original": importe(fila["total_original"], c["moneda"]),
                        "Total cotizado convertido": importe(fila["total_convertido"], moneda),
                        "Costo completo hasta destino": importe(o["costo"]["completo"], moneda),
                        "LT hasta recepción": numero(o["costo"]["lt"]),
                        "Presupuesto": o["presupuesto"]["estado"], "Plazo objetivo": o["plazo"]["estado"],
                        "Compra": "Condiciones confirmadas" if o["compra_valida"] else "Condiciones pendientes o incumplidas",
                        "Equivalencia": "Confirmada" if o["equivalentes"] else "Por confirmar",
                        "Incoterm": c.get("incoterm", "Por confirmar"), "Pendientes": "; ".join([*o["costo"]["motivos"], *o["motivos_compra"]])})
        for nombre, dato, unidad in (("Presupuesto", o["presupuesto"], moneda), ("Plazo", o["plazo"], "días")):
            detalle_objetivos.append({"Cotización": c["numero"], "Criterio": nombre, "Estado": dato["estado"],
                                      "Diferencia vs objetivo": f"{numero(dato['diferencia'])} {unidad}" if dato["diferencia"] is not None else "Por confirmar / sin objetivo",
                                      "Variación (%)": numero(dato["porcentaje"], 2) if nombre == "Presupuesto" else ""})
    primeras = ("Proveedor", "Costo completo hasta destino", "LT hasta recepción", "Presupuesto", "Plazo objetivo")
    resumen = [{**{k: fila[k] for k in primeras}, **{k: v for k, v in fila.items() if k not in primeras}} for fila in resumen]
    st.dataframe(resumen, hide_index=True, width="stretch")
    st.caption("Una diferencia positiva supera el objetivo; una negativa queda por debajo. Los costos incompletos no se usan para elegir la oferta más económica hasta destino.")
    st.write("**Escenarios para decidir**")
    orden = [("Precio", "precio"), ("Urgencia", "urgencia"), ("Equilibrio", "equilibrio")]
    prioridad = config["prioridad"]
    orden.sort(key=lambda par: par[0] != prioridad)
    for grupo in ampliado["escenarios"]:
        st.caption("Cotizaciones de esta cesta: " + ", ".join(map(str, grupo["ofertas"])))
        for titulo, clave in orden:
            with st.container(border=True):
                st.write(f"**{'Tu prioridad · ' if titulo == prioridad else ''}{'Cumplir tus objetivos' if titulo == 'Equilibrio' else 'Si priorizas ' + titulo.lower()}**")
                for texto in grupo[clave]:
                    st.text(texto)
    with st.expander("Ver diferencias frente a cada objetivo y condiciones de entrega"):
        for ahorro in ampliado["savings"]:
            dato = ahorro["objetivo"]
            detalle_objetivos.append({"Cotización": ahorro["cotizacion"], "Criterio": f"Target price · Línea {ahorro['linea']} · {ahorro['producto']}",
                                      "Estado": dato["estado"], "Diferencia vs objetivo": importe(dato["diferencia"], moneda) if dato["diferencia"] is not None else "Por confirmar / sin objetivo",
                                      "Variación (%)": numero(dato["porcentaje"], 2)})
        st.dataframe(detalle_objetivos, hide_index=True, width="stretch")
        for o in ampliado["ofertas"]:
            st.text(nombre_oferta(o["cotizacion"]))
            st.text(o["incoterm"])
            st.text("Pago: " + (o["cotizacion"]["condiciones_pago"] or "Por confirmar"))
        st.caption("Responsabilidades resumidas según Incoterms® 2020; pagos y precios se revisan por separado.")
        st.markdown("[Guía oficial de ICC](https://library.iccwbo.org/clp/clp-incoterms-qa-2020.htm?AGENT=ICC_FIN) · [Reglas para cualquier transporte](https://library.iccwbo.org/content/tfb/BOOKS/BK_0049/BK_0049_04_RulesAny.htm) · [Reglas marítimas](https://library.iccwbo.org/content/tfb/BOOKS/BK_0049/BK_0049_05_RulesSea.htm)")
    st.write("**Savings por línea y proveedor**")
    st.dataframe([
        {"Proveedor": a["proveedor"], "Producto": a["producto"],
         "Savings proyectados": importe(a["proyectado"], moneda) + (" · Condicionado" if a["estado"].startswith("Hipótesis") and a["proyectado"] is not None else ""),
         "Ahorro por unidad": numero(a["unitario"]), "Savings cantidad cotizada": importe(a["cotizado"], moneda),
         "Validez de proyección": a["estado"], "Cotización": a["cotizacion"], "Línea": a["linea"],
         "UOM": a["unidad"] or "Por confirmar", "Cantidad cotizada": numero(a["cantidad"]), "MOQ": numero(a["moq"]),
         "Precio actual": numero(a["actual"]), "Precio ofertado válido": numero(a["precio"]),
         "Ahorro (%)": "No calculable: base cero" if a["actual"] == 0 else numero(a["porcentaje"], 2),
         "Forecast": numero(a["forecast"]), "Periodo": a["periodo"] or "Sin definir",
         "Precio / base": a["motivo_precio"] if a["base_valida"] else "Equivalencia o base del precio por confirmar"}
        for a in ampliado["savings"]
    ], hide_index=True, width="stretch")
    st.caption(f"Precios y savings en {moneda}. Ahorro potencial de precio, sin costos logísticos o de inventario no aportados. Un resultado negativo representa un aumento de costo. Las alternativas y las dos medidas de la misma compra no se suman entre sí.")
    if ampliado["volumen"]:
        st.write("**Escenarios de volumen y desembolso del producto**")
        st.dataframe([
            {"Cotización": a["cotizacion"], "Proveedor": a["proveedor"], "Línea": a["linea"], "Producto": a["producto"],
             "Necesidad": numero(a["necesidad"]), "Compra evaluada": numero(a["cantidad"]), "Unidades adicionales": numero(a["excedente"]),
             "Precio por unidad": numero(a["precio"]), "Desembolso producto": importe(a["desembolso"], moneda),
             "Referencia: comprar lo necesario al precio actual": importe(a["referencia"], moneda),
             "Desembolso adicional / reducción": importe(a["diferencia"], moneda), "Alcance": a["nota"]}
            for a in ampliado["volumen"]
        ], hide_index=True, width="stretch")
    st.caption("La decisión de compra te corresponde. Ningún escenario modifica tu forecast ni emite pedidos.")


def mostrar_resultado(resultado, pendiente):
    moneda = resultado["moneda_analisis"]
    st.subheader("Resultado del análisis")
    if pendiente:
        st.warning("Pendiente de actualizar. Cambiaron las cotizaciones, objetivos o configuración. Pulsa «Analizar cotizaciones» para actualizar el resultado.")
        st.caption(f"Último resultado guardado en {moneda}. Estos valores corresponden a la configuración anterior.")
    else:
        st.success(f"Análisis actualizado en {moneda}.")
    if "ampliado" in resultado:
        st.caption(f"Análisis en {moneda}, con los tipos de cambio proporcionados por ti. Los importes originales se conservan.")
        mostrar_analisis_ampliado(resultado)
        return
    filas = []
    for fila in resultado["filas"]:
        cotizacion = fila["cotizacion"]
        vista = fila_cotizacion(cotizacion)
        vista["Tipo aplicado"] = (
            f"1 {cotizacion['moneda']} = {numero(fila['tipo'])} {moneda}"
            if fila["tipo"] is not None else "Por confirmar"
        )
        vista[f"Total en {moneda}"] = importe(fila["total_convertido"], moneda)
        primeras = ("Proveedor", "Total original", f"Total en {moneda}", "Tipo aplicado", "Moneda original")
        vista = {**{campo: vista[campo] for campo in primeras},
                 **{campo: valor for campo, valor in vista.items() if campo not in primeras}}
        filas.append(vista)
    st.dataframe(filas, hide_index=True, width="stretch")
    st.caption("Conversiones calculadas con los tipos de cambio proporcionados por ti. Los importes originales se conservan.")
    if not resultado["comparaciones"]:
        st.warning("No hay dos totales cotizados comparables con las condiciones de compra confirmadas. Revisa productos, cantidades, unidades, MOQ, múltiplos y datos monetarios pendientes.")
    else:
        st.write("**Diferencias entre totales cotizados comparables**")
        for comparacion in resultado["comparaciones"]:
            with st.container(border=True):
                detalle_cantidad = f" · {numero(comparacion['cantidad'])} {comparacion['unidad']}" if comparacion["cantidad"] is not None else " · Ver detalle de líneas"
                st.text(f"{comparacion['producto']}{detalle_cantidad}")
                st.write(comparacion["costo"])
                st.write(comparacion["entrega"])
                st.write(comparacion["pago"])
        if resultado["sin_comparacion"]:
            numeros = ", ".join(str(n) for n in resultado["sin_comparacion"])
            st.info(f"Cotizaciones sin una oferta equivalente para comparar costos: {numeros}. Revisa producto, cantidad, unidad y datos monetarios pendientes.")
    st.info("Estos importes comparan lo cotizado por el proveedor. El costo hasta destino puede variar por los gastos adicionales del comprador; un total cotizado menor no demuestra un menor costo completo.")
    st.caption("Evalúa también la entrega y las condiciones comerciales. La decisión de compra te corresponde.")


def mostrar_configuracion():
    cotizaciones = st.session_state.cotizaciones_confirmadas
    st.subheader("3. Elige la moneda y analiza")
    st.write("Cuando hayas agregado todas las ofertas, elige la moneda en la que quieres ver la comparación.")
    st.text_input(
        "Moneda del análisis", placeholder="Ej.: USD, EUR o CRC", max_chars=3,
        key="moneda_analisis", on_change=cambiar_moneda,
        help="Código de tres letras. Puedes elegir una moneda distinta de las monedas de tus cotizaciones.",
    )
    moneda = st.session_state.moneda_analisis.strip().upper()
    try:
        moneda_valida = leer_moneda(moneda) if moneda else None
    except ValueError:
        moneda_valida = None
        st.info("Indica un código de moneda de tres letras, por ejemplo USD.")
    if moneda_valida:
        requeridas = monedas_requeridas(cotizaciones, moneda)
        if requeridas:
            st.write("Introduce los tipos de cambio que quieres utilizar. La dirección se indica en cada campo.")
            for origen in requeridas:
                clave = f"tipo_{st.session_state.version_tipos}_{origen}"
                st.text_input(
                    f"1 {origen} = ¿cuántos {moneda}?", key=clave,
                    value=st.session_state.tipos_texto.get(origen, ""),
                    placeholder="Ej.: 1,10", max_chars=32,
                    on_change=guardar_tipo, args=(origen, clave),
                    help="Introduce un número mayor que cero. Usa coma o punto decimal, sin separadores de miles.",
                )
        elif cotizaciones:
            st.caption("Las monedas identificadas ya coinciden con la moneda del análisis: se aplica el factor 1.")
    configuracion = mostrar_opciones_analisis(cotizaciones, moneda_valida)
    st.session_state.configuracion_analisis = deepcopy(configuracion)
    if len(cotizaciones) < 2:
        st.info("Agrega y confirma al menos dos cotizaciones para analizar.")
    if st.button("Analizar cotizaciones", key="analizar", type="primary", disabled=len(cotizaciones) < 2):
        try:
            resultado = crear_analisis(cotizaciones, moneda, st.session_state.tipos_texto, configuracion)
            st.session_state.resultado = resultado
            st.session_state.firma_resultado = firma_datos(cotizaciones, moneda, st.session_state.tipos_texto, configuracion)
            st.session_state.error_analisis = ""
            st.rerun()
        except ValueError as error:
            st.session_state.error_analisis = str(error)
    if st.session_state.error_analisis:
        st.error(st.session_state.error_analisis)
    if st.session_state.resultado is not None:
        actual = firma_datos(cotizaciones, moneda, st.session_state.tipos_texto, configuracion)
        mostrar_resultado(st.session_state.resultado, actual != st.session_state.firma_resultado)


def main():
    st.set_page_config(page_title="SmartQuote · Comparar cotizaciones", page_icon="📋", layout="wide", initial_sidebar_state="collapsed")
    st.markdown("""<style>
        :root {--sq-navy:#163347; --sq-teal:#147d73;}
        .stApp {background:#f5f7fa;}
        .block-container {max-width:1180px; padding-top:4.8rem; padding-bottom:3rem;}
        h1,h2,h3 {color:var(--sq-navy); letter-spacing:-.025em;}
        [data-testid="stSidebar"] {background:#163347;}
        [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] p, [data-testid="stSidebar"] li {color:#edf5f7;}
        [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {color:#bfd0dc;}
        [data-testid="stForm"], [data-testid="stMetric"] {background:white; border-radius:12px;}
        [data-testid="stMetric"] {padding:15px 18px; border:1px solid #e1e7ed;}
        [data-testid="stMetricValue"] {color:var(--sq-navy); font-size:1.7rem;}
        .sq-eyebrow {color:#147d73; font-size:.76rem; letter-spacing:.16em; font-weight:700; margin-bottom:.4rem;}
        .sq-mark {display:inline-block; background:#31b5a3; color:#103244; border-radius:12px; padding:12px 15px; font-size:1.3rem; font-weight:800; margin:8px 0 14px;}
        button[kind="primary"] {background:#147d73; border-color:#147d73;}
        [data-testid="stTextInput"] input {background:#fff;}
        </style>""", unsafe_allow_html=True)
    inicializar_sesion()
    with st.sidebar:
        st.markdown('<div class="sq-mark">SQ</div>', unsafe_allow_html=True)
        st.title("SmartQuote")
        st.write("Una vista clara de tus ofertas.")
        st.divider()
        st.write("**Tu recorrido**")
        st.markdown("1. Registra los datos.\n2. Revisa y confirma.\n3. Elige la moneda.\n4. Compara las ofertas.")
        st.divider()
        st.caption("Usa cotizaciones ficticias para el reto. Los datos se conservan durante esta sesión; al recargar o cerrar la conexión pueden perderse.")
    st.markdown('<div class="sq-eyebrow">COMPARADOR DE COTIZACIONES</div>', unsafe_allow_html=True)
    st.title("Compara tus cotizaciones")
    st.write("Registra las ofertas de tus proveedores, confirma sus datos y compara sus costos en la moneda que elijas.")
    cotizaciones = st.session_state.cotizaciones_confirmadas
    columnas = st.columns(2)
    columnas[0].metric("Confirmadas", len(cotizaciones))
    columnas[1].metric("Monedas", len({c["moneda"] for c in cotizaciones if c["moneda"]}))
    st.write("")
    st.button("Agregar cotización", key="agregar", type="primary", on_click=abrir_formulario, disabled=st.session_state.formulario_abierto)
    if not cotizaciones and not st.session_state.formulario_abierto:
        st.button("Cargar ejemplo ficticio", key="cargar_ejemplo", on_click=cargar_ejemplo,
                  help="Carga dos ofertas inventadas con objetivos y forecast para probar el análisis.")
    if st.session_state.aviso:
        st.success(st.session_state.aviso)
    if st.session_state.formulario_abierto:
        mostrar_formulario()
    st.divider()
    st.subheader("2. Cotizaciones confirmadas")
    if cotizaciones:
        st.dataframe([fila_cotizacion(c) for c in cotizaciones], hide_index=True, width="stretch")
        for cotizacion in cotizaciones:
            if cotizacion.get("lineas"):
                with st.expander(f"Ver líneas y condiciones · Cotización {cotizacion['numero']} · {cotizacion['proveedor']}"):
                    mostrar_detalle_cotizacion(cotizacion)
            st.button(f"Corregir cotización {cotizacion['numero']}", key=f"editar_{cotizacion['numero']}", on_click=editar_cotizacion, args=(cotizacion["numero"],), disabled=st.session_state.formulario_abierto)
        st.caption("Las ofertas se incorporan únicamente después de tu confirmación. Puedes agregar otra antes de analizar.")
    else:
        st.info("Todavía no hay cotizaciones confirmadas. Empieza con «Agregar cotización» y revisa los datos antes de guardarlos.")
    st.divider()
    mostrar_configuracion()
    st.divider()
    mostrar_conexion_ia()
    st.caption("SmartQuote · Registro manual y comparación con reglas. La comprobación de conexión con IA está incorporada; la lectura de archivos y la explicación con IA se añadirán en los siguientes pasos.")


if __name__ == "__main__":
    main()
