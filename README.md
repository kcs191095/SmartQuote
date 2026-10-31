# SmartQuote

**Enlace a la app:** [Abrir SmartQuote](https://smartquote.streamlit.app/)

**Autor/a:** [kcs191095](https://github.com/kcs191095)

**Repositorio:** [kcs191095/SmartQuote](https://github.com/kcs191095/SmartQuote)

Prototipo académico del Máster en Inteligencia Artificial de OBS Business School. Ayuda a compradores de pequeñas y medianas empresas a registrar, revisar y comparar cotizaciones.

> Documento de trabajo de la entrega final. El pitch se revisará en el punto 4 de la ruta; los prompts y el proceso, en el punto 2; el registro de prueba, en el punto 3; y las capturas, en el punto 5. La prueba de un compañero sigue pendiente del punto 6.

## Pitch

**Borrador para revisar en el punto 4.**

Los compradores de pequeñas y medianas empresas dedican tiempo a ordenar cotizaciones con precios, monedas y condiciones diferentes.
SmartQuote reúne esas ofertas, permite revisarlas y compara escenarios de precio, urgencia, objetivos y ahorro potencial.
La IA interpreta los documentos y explica los resultados que calcula Python, mientras el comprador confirma los datos y decide.
Al probar la lectura de un PDF aprendí que una conexión correcta con Gemini no garantiza que la solicitud de extracción funcione, por lo que ajustamos esa solicitud y comprobamos después la lectura del documento.
Como siguiente paso, probaría la claridad de las recomendaciones con otros compradores usando, por ejemplo, el caso en que pagar 80 USD adicionales permite recibir un pedido 18 días antes.

## El problema

Un comprador de una pequeña o mediana empresa recibe cotizaciones de distintos proveedores en PDF, imágenes, Word o Excel.
Normalmente revisa los documentos y copia los datos a una hoja de cálculo para comparar precios, cantidades, plazos y condiciones.
Las diferencias de moneda, los gastos pendientes y las condiciones de compra pueden hacer que el menor precio unitario no sea la opción más conveniente.
SmartQuote organiza esa información y muestra escenarios con sus condiciones, para que el comprador pueda tomar una decisión con datos comparables.

## Qué hace la app

1. **Agrega una cotización.** Pulsa «Agregar cotización» y completa los campos manualmente o abre «Subir archivo con IA — opcional». Para extraer un archivo, confirma la carga y pulsa «Extraer datos con IA». Puedes combinar ambos métodos entre proveedores.
2. **Revisa las líneas y condiciones.** Comprueba proveedor, producto, cantidad, unidad de medida, precio, moneda, cantidad mínima de compra (MOQ), múltiplos y precios por volumen. Revisa también entrega, pago, Incoterm y gastos. Completa los datos que queden «Por confirmar».
3. **Confirma cada oferta.** Pulsa «Revisar cotización» y comprueba la tabla preliminar. Solo «Confirmar y agregar» incorpora la oferta a las cotizaciones confirmadas. Extraer un archivo no confirma una compra ni una cotización.
4. **Prepara la comparación.** Con al menos dos cotizaciones confirmadas, elige la moneda del análisis e introduce los tipos de cambio necesarios. Confirma qué productos y unidades son equivalentes y qué gastos y plazos cubren el mismo destino.
5. **Añade tus objetivos si los necesitas.** Precio objetivo, presupuesto, plazo de entrega y tolerancia al sobrecosto son opcionales. También puedes indicar precio actual, volumen previsto o forecast, su periodo y un plan de pedidos para evaluar ahorro potencial.
6. **Analiza y revisa los escenarios.** Pulsa «Analizar cotizaciones». La app conserva los importes originales y muestra conversiones, costos disponibles, cumplimiento de objetivos y escenarios de precio y urgencia. Cuando hay información suficiente, añade savings y alternativas de volumen.
7. **Solicita una explicación con IA.** Pulsa «Explicar análisis con IA» para obtener una interpretación de los resultados y de lo que falta confirmar. Si cambias los datos, actualiza el análisis y solicita otra explicación.

### Probarla con un ejemplo

En una sesión vacía, pulsa «Cargar ejemplo ficticio» y después «Analizar cotizaciones».

| Oferta del ejemplo | Costo completo | Plazo de recepción |
|---|---|---|
| Proveedor A | 1.000 USD | 30 días |
| Proveedor B | 1.080 USD | 12 días |

Con presupuesto de 1.100 USD y plazo objetivo de 15 días, A tiene el menor costo y B cumple ambos objetivos: cuesta 80 USD más, un 8 %, y entrega 18 días antes. El ejemplo incluye una tolerancia al sobrecosto del 8 %; esa condición se muestra junto con el resto de los objetivos.

También hay documentos inventados en la [carpeta de ejemplos](https://github.com/kcs191095/SmartQuote/tree/main/ejemplos).

### Condiciones y límites

- Usa únicamente cotizaciones ficticias, sin datos personales reales ni información comercial confidencial.
- Se admiten JPG/JPEG, PNG, PDF, Word `.docx` y Excel `.xlsx`, de hasta 5 MB. Los PDF pueden tener hasta 10 páginas; la extracción admite hasta 20 líneas y 10 tramos de precio por línea.
- Word y Excel se preparan como texto y tablas. Las imágenes y los objetos incrustados requieren revisión o una copia en PDF. Las fórmulas de Excel no se ejecutan; un importe que dependa de ellas necesita confirmación.
- Excel admite hasta 10 hojas, 1.000 filas y 100 columnas por hoja, y 5.000 celdas con contenido. El texto preparado de Word o Excel tiene un límite de 80.000 caracteres.
- Los tipos de cambio los aporta el usuario. Una conversión de moneda no demuestra que dos productos o unidades sean equivalentes.
- Un MOQ es una cantidad mínima, no un múltiplo obligatorio. Si no está indicado, usar 1 requiere aceptar expresamente ese supuesto.
- El forecast no equivale a un único pedido. Un precio por volumen solo se utiliza cuando se cumplen sus cantidades y condiciones.
- Los savings son diferencias o proyecciones de precio sujetas a las condiciones indicadas; no demuestran por sí solos un ahorro neto realizado.
- Un dato ausente no se convierte en cero. Los gastos o plazos incompletos limitan los escenarios que pueden calcularse.
- La app registra el Incoterm, la versión y el lugar convenido; no deduce de ellos importes de transporte o impuestos.
- Las cotizaciones se mantienen en la sesión de uso. La app no ofrece un historial permanente de compras.
- La selección del proveedor, la negociación y la decisión de compra corresponden al comprador.

## La pieza de IA

- **Qué usa:** API de Gemini, con el SDK `google-genai` y el modelo configurado en `MODELO` de `app.py`: `gemini-3.5-flash-lite`.
- **Por qué esa opción:** permite interpretar imágenes y PDF y organizar el texto de Word y Excel sin entrenar un modelo propio. La misma API ayuda a explicar los escenarios que ya calculó el programa.
- **Qué se envía:** al solicitar la extracción, se envía a Gemini la imagen o el PDF; para Word y Excel, se envían el texto y las tablas preparados. Para explicar el análisis, se envían los hechos calculados y la configuración utilizada.
- **Qué hace Python:** valida entradas, calcula importes y conversiones con precisión decimal, comprueba condiciones de compra y determina los resultados de cada escenario. La IA no sustituye esos cálculos.
- **Qué pasa si falla:** las llamadas están protegidas con `try/except`. Si falta la clave, se agota la cuota, falla la conexión, el modelo no está disponible o la respuesta no es válida, aparece un mensaje claro. Las cotizaciones confirmadas y las funciones manuales permanecen disponibles.
- **Dónde está la clave:** en los secretos de Streamlit, con el nombre `GEMINI_API_KEY`, leída mediante `st.secrets`. La clave no se incluye en el código ni en este documento.

El proyecto sigue el requisito de coste cero del curso. El uso de IA depende de la cuota y de la disponibilidad del servicio; las peticiones se realizan solo al pulsar los botones correspondientes. La revisión humana de los datos extraídos y de las explicaciones sigue siendo necesaria.

## Cómo la he construido

- **Herramientas:** Codex como asistente de desarrollo; Python y Streamlit para la app; GitHub para el repositorio; Streamlit Community Cloud para el despliegue; API de Gemini para la extracción y la explicación.
- **Fichero de contexto del agente:** [AGENTS.md](https://github.com/kcs191095/SmartQuote/blob/main/AGENTS.md).
- **Especificación:** [especificacion.md](https://github.com/kcs191095/SmartQuote/blob/main/especificacion.md).
- **Qué delegué al agente:** convertir los requisitos acordados en código, implementar el formulario y los cálculos, integrar la lectura de archivos y preparar las pruebas automáticas y el manejo de errores.
- **Qué revisé a mano:** el flujo de revisión y confirmación, los datos extraídos de las cotizaciones ficticias, el total de 1.240 USD de los ejemplos, la explicación de precio frente a urgencia y el comportamiento al cargar un archivo inválido. También realicé las publicaciones en GitHub y la configuración del secreto en Streamlit.

### Prompts clave

Selección inicial de tres mensajes reales de la conversación, copiados literalmente. Su selección y contexto se revisarán en el punto 2 de la ruta.

**1. Revisión y confirmación de los datos extraídos**

> si la idea es que se pase la imagen y si hay algo ilegible le indique al usuario que ponga los restantes en los espacios. al final que de una tabla con toda la info de esa cotizacion y que pida confirmar si es correcta. y las va acumulando en una tabla de cotizaciones y cuando ya se agregaron todas comience con el analisis

**2. Comparación entre monedas**

> pero esto me da una idea. que pasa si me pasan una cotizacion en dolares y otra en euros? como hago para compararlas. yo podria proveer como usuario el tipo de cambio para poder completar el analisis. como lo podriamos meter en la app? cambiemos todo lo necesario para que se pueda implementar eso

**3. MOQ y precios por volumen**

> Perdon no era UOM era MOQ. al final la IA podria revisar eso y dar una recomendacion para el comprador diciendo que si por ejemplo hay una cotizacion que da un precio mas bajo pero con un MOQ de 500 por ejemplo, y nosotros ocupamos 900. entonces si se hace un cambio en el forecast ese precio podría servir mas. tambien la IA podría obtener de un documento tier pricing proveido por un supplier. porque me pueden decir si les compro 1 cuesta 10, pero si les compro 5 cuesta 8.5. eso deberia ser capaz de verlo la app. Pero no sé si la version 0 sea capaz de ver eso. pero la IA si debe.

Los requisitos se concretaron después en la especificación: MOQ y múltiplo son condiciones distintas, los rangos deben confirmarse y la app conserva el forecast del comprador.

## Prueba y mejora

Registro inicial con las pruebas propias ya realizadas. Se completará en el punto 3 con la revisión del recorrido sin ayuda y, en el punto 6, con la prueba de la app de un compañero y el comentario publicado en el debate.

| Quién la probó | Qué probó | Qué pasó | Qué cambié |
|---|---|---|---|
| Yo, como usuario | Extraer la cotización ficticia en PDF | La conexión básica funcionaba, pero la extracción fue rechazada por Gemini. Después del ajuste pude leer las dos líneas, con total de 1.240 USD. | Con ayuda del agente simplifiqué las restricciones de tamaño del esquema enviado a Gemini, manteniendo la validación local y la confirmación manual. El ajuste permitió continuar; no se certificó la causa exacta del rechazo inicial. |
| Yo, como usuario | Cargar las versiones ficticias Word y Excel | Los datos de las dos líneas y el total de 1.240 USD coincidieron con lo esperado. | Comprobación de los lectores incorporados; sin cambio adicional registrado por esta prueba. |
| Yo, como usuario | Comparar precio frente a urgencia y cambiar el plazo objetivo | Se distinguieron el menor costo y la entrega más rápida. Al reducir el objetivo de 15 a 10 días, ninguna oferta cumplía el plazo; la más rápida seguía siendo la de 12 días. | Comprobación de escenarios y de actualización de la explicación; sin cambio adicional registrado por esta prueba. |
| Yo, como usuario | Cargar un archivo inválido con extensión PDF | Apareció el aviso de archivo dañado o formato incorrecto. Se conservaron dos cotizaciones y pude continuar con el análisis. | Comprobación del manejo de errores ya implementado; sin cambio adicional registrado por esta prueba. |

Además, el 25/10/2026 se registraron **112 pruebas automáticas correctas**, ejecutadas con Python 3.12.14 y Gemini simulado. Cubren el flujo manual, los cálculos, los formatos, la validación de respuestas, la conservación de datos y fallos de clave, cuota, conexión y modelo. Estas simulaciones se distinguen de las peticiones reales que realicé al probar la app.

**Pendiente:** prueba de uso sin ayuda, cierre del registro de prueba y mejora, y prueba de una app de un compañero con feedback útil en Blackboard. No se han añadido comentarios de terceros que no hayan sido recibidos.

## Ejecutar en local (opcional)

Desde la carpeta del proyecto, con Python 3.12 y las dependencias de `requirements.txt`:

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Para utilizar las funciones de Gemini en local, configura `GEMINI_API_KEY` en tu archivo privado `.streamlit/secrets.toml`. En Streamlit Community Cloud se configura en Settings → Secrets. No compartas el valor en el código, el chat, capturas ni archivos del repositorio.

El `.gitignore` del proyecto excluye `.streamlit/secrets.toml`, `.env` y `.env.*`. La entrada manual y el análisis mediante reglas funcionan aunque la clave no esté configurada.

## Capturas

**Pendientes de seleccionar e incorporar en el punto 5.** Cada captura llevará una línea que explique qué se ve y se revisará para que no muestre claves ni datos reales.

1. **La app funcionando:** cotizaciones confirmadas, comparación y explicación del caso principal.
2. **Un caso límite o error:** aviso del archivo PDF inválido, cuya captura ya está disponible para la entrega.
3. **Trabajo con la IA:** un prompt real y la respuesta del agente durante el desarrollo.
4. **La prueba:** el caso que motivó la mejora de lectura del PDF o un comentario real recibido sobre SmartQuote, si lo hay.
