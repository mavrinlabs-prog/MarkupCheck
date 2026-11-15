"""Spanish version of MarkupCheck's interface.

t(text, lang) translates one fixed UI string (labels, buttons, tab names, the static gr.HTML blocks).
translate_html(markup, lang) translates a rendered result panel: text nodes, SVG <text>/<title>/<desc>, the
aria-label / aria-valuetext / title attributes, the field labels in data-invalid and the chip labels inside
data-whatif. Markup, ids, classes, data-share and every number are left exactly as they were.

The charts in charts.py lay out their labels with English text widths, so the Spanish chart labels below are
kept no wider than the English ones they replace ("12 m" for "12 mo", "Menos"/"Más" for "Pays less/more").
"""
from __future__ import annotations

import html
import json
import re

LANGS = [("English", "en"), ("Español", "es")]
MISSES: set[str] = set()

DISCLAIMER_EN = "This project is a prototype and is not financial advice."
DISCLAIMER_ES = "Este proyecto es un prototipo y no es asesoramiento financiero."

_MONTHS = {"January": "enero", "February": "febrero", "March": "marzo", "April": "abril", "May": "mayo",
           "June": "junio", "July": "julio", "August": "agosto", "September": "septiembre", "October": "octubre",
           "November": "noviembre", "December": "diciembre"}
_MONTHS_ABBR = {"Jan": "ene", "Feb": "feb", "Mar": "mar", "Apr": "abr", "May": "may", "Jun": "jun", "Jul": "jul",
                "Aug": "ago", "Sep": "sep", "Oct": "oct", "Nov": "nov", "Dec": "dic"}
_ABBR_FULL = dict(zip(_MONTHS_ABBR, _MONTHS.values()))

_STATES = {
    "Alabama": "Alabama", "Alaska": "Alaska", "Arizona": "Arizona", "Arkansas": "Arkansas",
    "California": "California", "Colorado": "Colorado", "Connecticut": "Connecticut", "Delaware": "Delaware",
    "District of Columbia": "Distrito de Columbia", "Florida": "Florida", "Georgia": "Georgia", "Hawaii": "Hawái",
    "Idaho": "Idaho", "Illinois": "Illinois", "Indiana": "Indiana", "Iowa": "Iowa", "Kansas": "Kansas",
    "Kentucky": "Kentucky", "Louisiana": "Luisiana", "Maine": "Maine", "Maryland": "Maryland",
    "Massachusetts": "Massachusetts", "Michigan": "Míchigan", "Minnesota": "Minnesota", "Mississippi": "Misisipi",
    "Missouri": "Misuri", "Montana": "Montana", "Nebraska": "Nebraska", "Nevada": "Nevada",
    "New Hampshire": "Nuevo Hampshire", "New Jersey": "Nueva Jersey", "New Mexico": "Nuevo México",
    "New York": "Nueva York", "North Carolina": "Carolina del Norte", "North Dakota": "Dakota del Norte",
    "Ohio": "Ohio", "Oklahoma": "Oklahoma", "Oregon": "Oregón", "Pennsylvania": "Pensilvania",
    "Rhode Island": "Rhode Island", "South Carolina": "Carolina del Sur", "South Dakota": "Dakota del Sur",
    "Tennessee": "Tennessee", "Texas": "Texas", "Utah": "Utah", "Vermont": "Vermont", "Virginia": "Virginia",
    "Washington": "Washington", "West Virginia": "Virginia Occidental", "Wisconsin": "Wisconsin",
    "Wyoming": "Wyoming",
}

_FLAGS = {"Typical": "Típica", "High": "Alta", "Well above similar loans": "Muy por encima de préstamos similares"}
_CHIPS = {"Typical": "Típica", "High": "Alta", "Well above": "Muy por encima"}
_FLAGS_LOWER = {k.lower(): v.lower() for k, v in _FLAGS.items()}

_TIERS = {"Deep subprime (250–500)": "Subprime profundo (250–500)", "Subprime (501–600)": "Subprime (501–600)",
          "Near-prime (601–660)": "Casi prime (601–660)", "Prime (661–780)": "Prime (661–780)",
          "Super-prime (781–900)": "Superprime (781–900)"}

# ---------------------------------------------------------------- fixed UI strings (t)

_TITLE_EN = "MarkupCheck: is your car-loan rate fair?"
_TITLE_ES = "MarkupCheck: ¿la tasa de tu préstamo de auto es justa?"

_HEADER_EN = (
    "<a class='skip-to-content' href='#mc-main'>Skip to main content</a>"
    "<p class='mc-eyebrow'>Built on public SEC loan data</p>"
    "<h1>MarkupCheck: is your car-loan rate <em>fair?</em></h1>"
    "<p class='mc-lede'>Enter the loan offer from the dealer. MarkupCheck compares its APR with real car loans "
    "that lenders disclosed in public SEC filings, for borrowers with similar credit, cars and loan terms.</p>")
_HEADER_ES = (
    "<a class='skip-to-content' href='#mc-main'>Saltar al contenido principal</a>"
    "<p class='mc-eyebrow'>Hecho con datos públicos de préstamos de la SEC</p>"
    "<h1>MarkupCheck: ¿la tasa de tu préstamo de auto es <em>justa?</em></h1>"
    "<p class='mc-lede'>Escribe la oferta de préstamo del concesionario. MarkupCheck compara su tasa de porcentaje "
    "anual (APR) con préstamos de auto reales que los prestamistas publicaron en registros públicos de la SEC, para "
    "compradores con crédito, autos y plazos parecidos.</p>")

_API_DOCS_EN = (
    "<div class='mc-result'><section class='mc-section mc-first'><h2 class='mc-form-title'>Use MarkupCheck from your own "
    "program</h2><p>The same check is available as an API named <code>check</code>. Send the APR, or leave it empty "
    "and send the monthly payment. You get back JSON with the verdict, the range, the typical APR, each lender, "
    "the checks and the credit-union average.</p>"
    "<h3>Python</h3><pre class='mc-code'><code>pip install gradio_client\n\n"
    "from gradio_client import Client\n"
    "client = Client(\"https://YOUR-SPACE.hf.space\")  # this page's address\n"
    "result = client.predict(660, \"used\", 2019, 17500, 18500, 72, 15.9, \"\", None,\n"
    "                        api_name=\"/check\")\n"
    "print(result[\"verdict\"], result[\"result\"][\"typical_pct\"])</code></pre>"
    "<h3>Any language (two HTTP calls)</h3><pre class='mc-code'><code>curl -X POST https://YOUR-SPACE.hf.space/gradio_api/call/check \\\n"
    "  -H \"Content-Type: application/json\" \\\n"
    "  -d '{\"data\": [660, \"used\", 2019, 17500, 18500, 72, 15.9, \"\", null]}'\n"
    "# returns {\"event_id\": \"...\"}; then read the result:\n"
    "curl -N https://YOUR-SPACE.hf.space/gradio_api/call/check/EVENT_ID</code></pre>"
    "<h3>Inputs, in order</h3><ol class='mc-list'><li>credit score (250 to 900)</li><li>\"new\" or \"used\"</li>"
    "<li>model year</li><li>vehicle price ($)</li><li>amount financed ($)</li><li>term (months, 12 to 96)</li>"
    "<li>APR (%), or empty</li><li>lender name, or empty</li><li>monthly payment ($), or empty</li></ol>"
    "<p class='mc-note'>Limits: 30 checks a minute from one IP address. Nothing you send is stored. The results "
    "come with the same caveats as the page: MarkupCheck is a student prototype, not financial advice.</p>"
    "</section></div>"
)
_API_DOCS_ES = (
    "<div class='mc-result'><section class='mc-section mc-first'><h2 class='mc-form-title'>Usa MarkupCheck desde tu "
    "propio programa</h2><p>La misma revisión está disponible como una API llamada <code>check</code>. Envía la APR, "
    "o déjala vacía y envía el pago mensual. Recibes un JSON con el veredicto, el rango, la APR típica, cada "
    "prestamista, las pruebas y el promedio de las cooperativas de crédito.</p>"
    "<h3>Python</h3><pre class='mc-code'><code>pip install gradio_client\n\n"
    "from gradio_client import Client\n"
    "client = Client(\"https://YOUR-SPACE.hf.space\")  # la dirección de esta página\n"
    "result = client.predict(660, \"used\", 2019, 17500, 18500, 72, 15.9, \"\", None,\n"
    "                        api_name=\"/check\")\n"
    "print(result[\"verdict\"], result[\"result\"][\"typical_pct\"])</code></pre>"
    "<h3>Cualquier lenguaje (dos llamadas HTTP)</h3><pre class='mc-code'><code>curl -X POST https://YOUR-SPACE.hf.space/gradio_api/call/check \\\n"
    "  -H \"Content-Type: application/json\" \\\n"
    "  -d '{\"data\": [660, \"used\", 2019, 17500, 18500, 72, 15.9, \"\", null]}'\n"
    "# devuelve {\"event_id\": \"...\"}; después lee el resultado:\n"
    "curl -N https://YOUR-SPACE.hf.space/gradio_api/call/check/EVENT_ID</code></pre>"
    "<h3>Entradas, en orden</h3><ol class='mc-list'><li>puntaje de crédito (250 a 900)</li><li>\"new\" o \"used\"</li>"
    "<li>año del modelo</li><li>precio del vehículo ($)</li><li>monto financiado ($)</li><li>plazo (meses, 12 a 96)</li>"
    "<li>APR (%), o vacío</li><li>nombre del prestamista, o vacío</li><li>pago mensual ($), o vacío</li></ol>"
    "<p class='mc-note'>Límites: 30 revisiones por minuto desde una misma dirección IP. No se guarda nada de lo que envías. "
    "Los resultados tienen las mismas advertencias que la página: MarkupCheck es un prototipo estudiantil, no "
    "asesoramiento financiero.</p>"
    "</section></div>"
)

STATIC: dict[str, str] = {
    # The language switch names each language in that language, so these stay the same in both.
    "Language / Idioma": "Language / Idioma",
    "English": "English",
    "Español": "Español",
    # page
    _TITLE_EN: _TITLE_ES,
    "Check whether a car-loan APR is fair: MarkupCheck compares it with similar real loans from public SEC filings. "
    "A student prototype, not financial advice.":
        "Revisa si la APR de un préstamo de auto es justa: MarkupCheck la compara con préstamos reales similares de "
        "registros públicos de la SEC. Un prototipo estudiantil, no asesoramiento financiero.",
    "MarkupCheck needs JavaScript to run. Turn it on and reload the page; nothing you typed is stored.":
        "MarkupCheck necesita JavaScript para funcionar. Actívalo y vuelve a cargar la página; no se guarda nada de "
        "lo que escribiste.",
    DISCLAIMER_EN: DISCLAIMER_ES,
    f"<footer><p>{DISCLAIMER_EN}</p></footer>": f"<footer><p>{DISCLAIMER_ES}</p></footer>",
    _HEADER_EN: _HEADER_ES,
    "Link copied.": "Enlace copiado.",
    # tabs
    "Check an offer": "Revisar una oferta",
    "Compare offers": "Comparar ofertas",
    "Refinance": "Refinanciar",
    "Batch check": "Revisión por lotes",
    "Explore the data": "Explorar los datos",
    "Use the API": "Usar la API",
    # check an offer: form (inputs.py L_* labels first)
    "<h2 class='mc-form-title'>Your loan offer</h2>": "<h2 class='mc-form-title'>Tu oferta de préstamo</h2>",
    "Credit score": "Puntaje de crédito",
    "New or used car": "Auto nuevo o usado",
    "Model year": "Año del modelo",
    "Vehicle price ($)": "Precio del vehículo ($)",
    "Amount financed ($)": "Monto financiado ($)",
    "Loan term (months)": "Plazo del préstamo (meses)",
    "Offered APR (%)": "APR ofrecida (%)",
    "Lender (optional)": "Prestamista (opcional)",
    "Monthly payment ($, optional)": "Pago mensual ($, opcional)",
    "Add-ons in the loan ($, optional)": "Productos adicionales en el préstamo ($, opcional)",
    "Auto-lender FICO scores run 250 to 900.": "Los puntajes FICO para préstamos de auto van de 250 a 900.",
    "As listed on the contract.": "Como aparece en el contrato.",
    "On the window sticker or contract.": "En la etiqueta de la ventana o en el contrato.",
    "Agreed price, before taxes and fees.": "Precio acordado, antes de impuestos y cargos.",
    "From the contract, incl. fees and add-ons.": "Del contrato, con cargos y productos adicionales.",
    "How many monthly payments.": "Cuántos pagos mensuales.",
    "The APR, not the payment. Blank if you only know the payment.":
        "La APR, no el pago. En blanco si solo sabes el pago.",
    "Naming one of the 10 lenders in the data gives a sharper check.":
        "Si nombras uno de los 10 prestamistas de los datos, la revisión es más precisa.",
    "From the contract or quote. We check it against the APR.":
        "Del contrato o la cotización. Lo comparamos con la APR.",
    "Warranty, GAP and similar items, if you know them.": "Garantía, GAP y cosas parecidas, si las conoces.",
    "New": "Nuevo",
    "Used": "Usado",
    "Check my rate": "Revisar mi tasa",
    "<p class='mc-examples-label'>Try an example, or enter your own offer below:</p>":
        "<p class='mc-examples-label'>Prueba un ejemplo, o escribe tu propia oferta abajo:</p>",
    "Jordan: a fair rate": "Jordan: una tasa justa",
    "Sam: a rate well above similar loans": "Sam: una tasa muy por encima de préstamos similares",
    # compare offers
    "<h2 class='mc-form-title'>Compare up to three offers</h2><p class='mc-section-intro'>Uses the credit score, car "
    "and amount financed from <strong>Check an offer</strong>. Add each quote you have, for example the dealer's and "
    "a credit union's.</p>":
        "<h2 class='mc-form-title'>Compara hasta tres ofertas</h2><p class='mc-section-intro'>Usa el puntaje de "
        "crédito, el auto y el monto financiado de <strong>Revisar una oferta</strong>. Agrega cada cotización que "
        "tengas, por ejemplo la del concesionario y la de una cooperativa de crédito.</p>",
    # refinance
    "<h2 class='mc-form-title'>Already have a car loan?</h2><p class='mc-section-intro'>See how your current rate "
    "compares with similar loans, and what a lower rate could save.</p>":
        "<h2 class='mc-form-title'>¿Ya tienes un préstamo de auto?</h2><p class='mc-section-intro'>Mira cómo se "
        "compara tu tasa actual con préstamos similares y cuánto podrías ahorrar con una tasa más baja.</p>",
    "Credit score now": "Puntaje de crédito actual",
    "Car's model year": "Año del modelo del auto",
    "Balance left ($)": "Saldo pendiente ($)",
    "Current APR (%)": "APR actual (%)",
    "Months left": "Meses restantes",
    "Car's value now ($, optional)": "Valor actual del auto ($, opcional)",
    "Check refinancing": "Revisar refinanciamiento",
    # batch check
    "<h2 class='mc-form-title'>Check many loans at once</h2><p class='mc-section-intro'>For credit counselors, legal "
    "aid and researchers: upload a CSV with one loan per row (up to 500). Start from the template. Files are used "
    "only for this check and deleted within an hour.</p>":
        "<h2 class='mc-form-title'>Revisa muchos préstamos a la vez</h2><p class='mc-section-intro'>Para asesores de "
        "crédito, asistencia legal e investigadores: sube un CSV con un préstamo por fila (hasta 500). Empieza con la "
        "plantilla. Los archivos se usan solo para esta revisión y se borran en menos de una hora.</p>",
    "Download the CSV template": "Descargar la plantilla CSV",
    "Your CSV file": "Tu archivo CSV",
    "Check every row": "Revisar cada fila",
    "Results (CSV)": "Resultados (CSV)",
    # explore
    "Credit tier": "Nivel de crédito",
    "New or used": "Nuevo o usado",
    **_TIERS,
    # API
    _API_DOCS_EN: _API_DOCS_ES,
}
for _i, _hint in ((1, "Dealer"), (2, "Credit union"), (3, "Bank")):
    STATIC[f"Offer {_i} name"] = f"Nombre de la oferta {_i}"
    STATIC[f"Offer {_i} APR (%)"] = f"APR de la oferta {_i} (%)"
    STATIC[f"Offer {_i} term (months)"] = f"Plazo de la oferta {_i} (meses)"
STATIC.update({"e.g. Dealer": "p. ej. Concesionario", "e.g. Credit union": "p. ej. Cooperativa de crédito",
               "e.g. Bank": "p. ej. Banco", "e.g. Santander": "p. ej. Santander"})
for _v in ("660", "2019", "17500", "18500", "72", "15.9", "400", "2500", "9.5", "11", "60", "680", "2021",
           "14000", "48", "16000", "10320", "28820"):
    STATIC[f"e.g. {_v}"] = f"p. ej. {_v}"


def t(text: str, lang: str) -> str:
    """One fixed UI string in `lang`; an unknown string comes back unchanged and is recorded in MISSES."""
    if lang == "en" or text is None:
        return text
    if text in STATIC:
        return STATIC[text]
    if text in WORDS:  # labels also used inside result HTML live in WORDS; the language switch relabels through t()
        return WORDS[text]
    MISSES.add(text)
    return text


# ---------------------------------------------------------------- result HTML: whole text nodes

WORDS: dict[str, str] = {
    # verdicts and chips
    **_FLAGS, "Well above": "Muy por encima",
    # app.py
    "Please check these entries": "Revisa estos datos",
    "We couldn't check this offer": "No pudimos revisar esta oferta",
    "We couldn't check this": "No pudimos hacer esta revisión",
    "Something went wrong on our side, not with your entries. Try again in a moment.":
        "Algo falló de nuestro lado, no en tus datos. Inténtalo de nuevo en un momento.",
    "Reference code:": "Código de referencia:",
    "Your result will appear here": "Tu resultado aparecerá aquí",
    "Where your rate sits": "Dónde queda tu tasa",
    "Range similar loans mostly got": "Rango que obtuvo la mayoría de préstamos similares",
    "What it costs you": "Cuánto te cuesta",
    "Monthly payment": "Pago mensual",
    "Your offer": "Tu oferta",
    "Typical for similar loans": "Típica para préstamos similares",
    "Loans from the same lender": "Préstamos del mismo prestamista",
    "Lender": "Prestamista",
    "Typical APR at this lender": "APR típica con este prestamista",
    "Versus all lenders": "Frente a todos los prestamistas",
    "Loans from this lender in our data": "Préstamos de este prestamista en nuestros datos",
    "about the same": "casi igual",
    "Your offer at each lender": "Tu oferta con cada prestamista",
    "Range": "Rango",
    "your lender": "tu prestamista",
    "Credit unions and banks": "Cooperativas de crédito y bancos",
    "How sure is this?": "¿Qué tan seguro es esto?",
    "Evidence.": "Evidencia.",
    "Risk.": "Riesgo.",
    "Why this is the typical price": "Por qué este es el precio típico",
    "What to do": "Qué hacer",
    "What the data can't tell you": "Lo que los datos no pueden decirte",
    "Data used:": "Datos usados:",
    "Placeholder numbers.": "Números de ejemplo.",
    # sections.py
    "Your payment": "Tu pago",
    "Add-ons in your loan": "Productos adicionales en tu préstamo",
    "Ways to a lower rate": "Formas de lograr una tasa más baja",
    "All of these together:": "Todo esto junto:",
    "Try it yourself": "Pruébalo tú mismo",
    "Term": "Plazo",
    "Extra down payment": "Pago inicial extra",
    "Take this to the dealer": "Lleva esto al concesionario",
    "Questions to ask:": "Preguntas para hacer:",
    "Print or save as PDF": "Imprimir o guardar como PDF",
    "Copy a link to this check": "Copiar un enlace a esta revisión",
    "Verdict:": "Veredicto:",
    "Cost:": "Costo:",
    "How sure:": "Qué tan seguro:",
    "Data:": "Datos:",
    "This compares my offer with similar loans; it can't show whether a markup was added.":
        "Esto compara mi oferta con préstamos similares; no puede mostrar si se agregó un recargo.",
    "Link to this check:": "Enlace a esta revisión:",
    "If the dealer pushes back": "Si el concesionario insiste",
    "Calm replies you can use at the finance desk:":
        "Respuestas tranquilas que puedes usar en la oficina de financiamiento:",
    "That's the rate the bank approved.": "Esa es la tasa que aprobó el banco.",
    "Can you show me the lender's approval and the buy rate in writing?":
        "¿Me pueden mostrar por escrito la aprobación del prestamista y la tasa de compra (buy rate)?",
    "This rate is only good today.": "Esta tasa solo vale por hoy.",
    "I'd like time to compare it with a pre-approval from a credit union or bank.":
        "Quisiera tiempo para compararla con una preaprobación de una cooperativa de crédito o un banco.",
    "With your credit, this rate is normal.": "Con tu crédito, esta tasa es normal.",
    "Let's just focus on the monthly payment.": "Enfoquémonos solo en el pago mensual.",
    "The warranty or GAP coverage is required for the loan.":
        "La garantía extendida o la cobertura GAP es obligatoria para el préstamo.",
    "Can you show me in writing that the lender requires it? If it's optional, I'd like the price without it.":
        "¿Me pueden mostrar por escrito que el prestamista la exige? Si es opcional, quisiera el precio sin ella.",
    "We can lower your payment with a longer term.": "Podemos bajar tu pago con un plazo más largo.",
    "What would the APR and the total I pay be on the longer term?":
        "¿Cuál sería el APR y el total que pagaría con el plazo más largo?",
    "If nothing moves, you can say \"Thank you, I'll compare my offers and come back.\" Nothing is final until you "
    "sign.": "Si nada cambia, puedes decir \"Gracias, voy a comparar mis ofertas y vuelvo.\" Nada es definitivo "
             "hasta que firmes.",
    "Ask for written offers": "Pide ofertas por escrito",
    "Send this to the dealer and to two or three banks or credit unions, so every APR you compare is for the same "
    "loan:": "Envía esto al concesionario y a dos o tres bancos o cooperativas de crédito, para que cada APR que "
             "compares sea por el mismo préstamo:",
    "Copy this message": "Copiar este mensaje",
    "Jump to": "Ir a",
    "Dealer card": "Tarjeta para el concesionario",
    "If they push back": "Si insisten",
    "Written offers": "Ofertas por escrito",
    "Your state": "Tu estado",
    "State": "Estado",
    "Choose a state": "Elige un estado",
    "Have the contract? Check its Truth-in-Lending box": "¿Tienes el contrato? Revisa su recuadro federal de divulgación",
    "Federal rules require a car-loan contract to group these numbers together, usually in a box near the top. Type "
    "them as printed.": "Las reglas federales exigen que un contrato de préstamo de auto agrupe estos números, "
                         "normalmente en un recuadro cerca del inicio. Escríbelos tal como aparecen.",
    "Amount Financed ($)": "Monto financiado ($)",
    "Finance Charge ($)": "Cargo financiero ($)",
    "Total of Payments ($)": "Total de pagos ($)",
    "Number of payments": "Número de pagos",
    "Annual Percentage Rate (%)": "Tasa de porcentaje anual (%)",
    "Check the box": "Revisar el recuadro",
    "The box adds up": "Las cifras del recuadro cuadran",
    "Something in the box doesn't add up": "Algo en el recuadro no cuadra",
    "Enter the Amount Financed from the box, in dollars.": "Escribe el monto financiado del recuadro, en dólares.",
    "Enter the Finance Charge from the box, in dollars.": "Escribe el cargo financiero del recuadro, en dólares.",
    "Enter the Total of Payments from the box, in dollars.": "Escribe el total de pagos del recuadro, en dólares.",
    "Enter the Annual Percentage Rate from the box, for example 15.9.":
        "Escribe la tasa de porcentaje anual del recuadro, por ejemplo 15.9.",
    "To see whether the APR itself is fair, enter the Amount Financed and the APR in the check above.":
        "Para ver si el APR en sí es justo, escribe el monto financiado y el APR en la revisión de arriba.",
    'For teachers': 'Para docentes',
    'MarkupCheck in the classroom': 'MarkupCheck en el aula',
    'A lesson of about 30 minutes on how car-loan rates are set. Students open four made-up buyers, so nobody types personal information.': 'Una lección de unos 30 minutos sobre cómo se fijan las tasas de los préstamos de auto. Los estudiantes abren cuatro compradores inventados, así que nadie escribe información personal.',
    'Students will be able to': 'Los estudiantes podrán',
    'Read an APR range and say where an offer falls.': 'Leer un rango de APR y decir dónde cae una oferta.',
    'Explain why the same APR can be typical for one buyer and high for another.': 'Explicar por qué el mismo APR puede ser típico para un comprador y alto para otro.',
    'Work out what a higher APR costs over the loan.': 'Calcular lo que cuesta un APR más alto a lo largo del préstamo.',
    'Name reasons a price can be high besides a markup.': 'Nombrar razones por las que un precio puede ser alto además de un recargo.',
    'The buyers': 'Los compradores',
    'Buyer': 'Comprador',
    'Car': 'Auto',
    'Loan': 'Préstamo',
    'Open': 'Abrir',
    "Each link opens the check with that buyer's numbers filled in.": 'Cada enlace abre la revisión con los números de ese comprador.',
    'Worksheet': 'Hoja de trabajo',
    'Print the worksheet': 'Imprimir la hoja de trabajo',
    'Answer key (for teachers)': 'Respuestas (para docentes)',
    "The trained model isn't loaded, so the answers can't be worked out here.": 'El modelo entrenado no está cargado, así que aquí no se pueden calcular las respuestas.',
    "Risk the data can't see (such as the buyer's full credit file), the lender, the state, or a dealer markup. The data can't tell these apart.": 'Un riesgo que los datos no ven (como el historial de crédito completo del comprador), el prestamista, el estado o un recargo del concesionario. Los datos no pueden distinguirlos.',
    "Open Jordan's offer. What range of APRs did similar loans mostly get, and is Jordan's 15.9% inside it?": 'Abre la oferta de Jordan. ¿Qué rango de APR obtuvieron sobre todo los préstamos similares, y está dentro el 15.9% de Jordan?',
    "Sam's APR (14.5%) is lower than Jordan's (15.9%). Why does MarkupCheck rate Sam's offer well above similar loans and Jordan's as typical?": 'El APR de Sam (14.5%) es más bajo que el de Jordan (15.9%). ¿Por qué MarkupCheck califica la oferta de Sam como muy por encima de préstamos similares y la de Jordan como típica?',
    'For Sam, how much more would the loan cost over 60 months than at the typical rate? What is each percentage point worth?': 'Para Sam, ¿cuánto más costaría el préstamo en 60 meses que con la tasa típica? ¿Cuánto vale cada punto porcentual?',
    'Under "Why this is the typical price" for Sam, which detail lowers the typical rate the most?': 'En "Por qué este es el precio típico" para Sam, ¿qué detalle baja más la tasa típica?',
    'Open Alex\'s offer and find "The whole deal". How much will Alex pay in all, and how much of that is interest?': 'Abre la oferta de Alex y busca "El trato completo". ¿Cuánto pagará Alex en total, y cuánto de eso son intereses?',
    "MarkupCheck says it can't show whether a markup was added. Name two other reasons a price can be high.": 'MarkupCheck dice que no puede mostrar si se agregó un recargo. Nombra otras dos razones por las que un precio puede ser alto.',
    "The whole deal": "El trato completo",
    "Car price": "Precio del auto",
    "Financed beyond the price (taxes, fees or add-ons)":
        "Financiado por encima del precio (impuestos, comisiones o productos adicionales)",
    "Paid up front (down payment or trade-in)": "Pagado al inicio (pago inicial o auto a cambio)",
    "Total of your payments": "Total de tus pagos",
    "Taxes and fees paid up front aren't included unless they are in the amount financed.":
        "Los impuestos y comisiones pagados al inicio no se incluyen salvo que estén en el monto financiado.",
    "Rate a lender offered you (%, optional)": "Tasa que te ofreció un prestamista (%, opcional)",
    "If approved at the rate you were offered": "Si te aprueban con la tasa que te ofrecieron",
    "The offered rate is the one a lender quoted you. The difference assumes you are approved at it.":
        "La tasa ofrecida es la que te cotizó un prestamista. La diferencia supone que te aprueban con ella.",
    "Check again later": "Vuelve a revisar más adelante",
    "Rates and credit scores change. Add two reminders to your calendar, 6 and 12 months from today, to check again. "
    "The file holds no numbers from this check.":
        "Las tasas y los puntajes de crédito cambian. Agrega dos recordatorios a tu calendario, dentro de 6 y 12 "
        "meses, para volver a revisar. El archivo no guarda ningún número de esta revisión.",
    "Add reminders to your calendar": "Agregar recordatorios a tu calendario",
    "Find a credit union near you": "Encuentra una cooperativa de crédito cerca de ti",
    "(NCUA's locator).": "(el buscador de la NCUA).",
    "Which credit score should I enter?": "¿Qué puntaje de crédito debo escribir?",
    "The one your lender pulled, if you know it. Car lenders often use a FICO Auto Score, which runs 250 to 900; free "
    "apps often show a different kind of score, and the two can differ. The checks under \"How sure is this?\" show "
    "your verdict with a score 30 points lower and 30 points higher.":
        "El que consultó tu prestamista, si lo sabes. Los prestamistas de autos suelen usar un FICO Auto Score, que va "
        "de 250 a 900; las aplicaciones gratuitas suelen mostrar otro tipo de puntaje, y los dos pueden ser distintos. "
        "Las pruebas de \"¿Qué tan seguro es esto?\" muestran tu veredicto con un puntaje 30 puntos más bajo y 30 "
        "puntos más alto.",
    "Privacy.": "Privacidad.",
    "MarkupCheck doesn't keep your offer: nothing you type is saved on our server or in your browser. A shared link "
    "carries your numbers after the # sign, which browsers don't send to our server. Batch files are deleted within "
    "an hour. To limit misuse, the server counts checks from each IP address for one minute.":
        "MarkupCheck no guarda tu oferta: nada de lo que escribes se guarda en nuestro servidor ni en tu navegador. Un "
        "enlace compartido lleva tus números después del signo #, que los navegadores no envían a nuestro servidor. "
        "Los archivos por lote se borran en menos de una hora. Para limitar el mal uso, el servidor cuenta las "
        "revisiones de cada dirección IP durante un minuto.",
    "Who pays.": "Quién paga.",
    "Nobody. MarkupCheck has no sponsors, ads or referral fees, so nothing pays it to send you to a lender.":
        "Nadie. MarkupCheck no tiene patrocinadores, anuncios ni comisiones por referidos, así que nada le paga por "
        "enviarte a un prestamista.",
    "Accessibility.": "Accesibilidad.",
    "The pages are checked automatically for keyboard use, text contrast of at least 4.5 to 1, 44-pixel touch "
    "targets, and screen-reader labels and announcements, at phone, tablet and desktop widths, in English and "
    "Spanish. They haven't yet been tested by a person using a screen reader.":
        "Las páginas se revisan automáticamente para el uso con teclado, un contraste de texto de al menos 4.5 a 1, "
        "áreas táctiles de 44 píxeles y etiquetas y avisos para lectores de pantalla, en anchos de teléfono, tableta "
        "y computadora, en inglés y español. Todavía no las ha probado una persona que use un lector de pantalla.",
    "Questions about your result": "Preguntas sobre tu resultado",
    "Is my offer marked up?": "¿Mi oferta tiene un recargo?",
    "What is the buy rate, and how do I ask for it?": "¿Qué es la tasa de compra (buy rate) y cómo la pido?",
    "How much would a lower rate save me?": "¿Cuánto me ahorraría una tasa más baja?",
    "Why is the typical rate for me where it is?": "¿Por qué mi tasa típica está donde está?",
    "Where do the numbers come from?": "¿De dónde salen los números?",
    "Is this financial advice?": "¿Esto es asesoramiento financiero?",
    # tabs.py
    "Your offers, cheapest first": "Tus ofertas, de la más barata a la más cara",
    "Offer": "Oferta",
    "Monthly": "Mensual",
    "Total interest": "Interés total",
    "Versus similar loans": "Frente a préstamos similares",
    "cheapest": "la más barata",
    "Your current rate": "Tu tasa actual",
    "If you refinanced": "Si refinanciaras",
    "New rate": "Tasa nueva",
    "New payment": "Pago nuevo",
    "Each month": "Cada mes",
    "About the same": "Casi lo mismo",
    "Credit-union average": "Promedio de cooperativas de crédito",
    "Keep in mind": "Ten en cuenta",
    "Please check this file": "Revisa este archivo",
    "Your file, checked": "Tu archivo, revisado",
    "Rows": "Filas",
    "Couldn't check": "No se pudo revisar",
    "All rows": "Todas las filas",
    "Row": "Fila",
    "Verdict": "Veredicto",
    # explore.py
    "Do some states pay more?": "¿Algunos estados pagan más?",
    "The five lowest and five highest gaps that hold up":
        "Las cinco diferencias más bajas y las cinco más altas que se sostienen",
    "State": "Estado",
    "Gap (points)": "Diferencia (puntos)",
    "95% interval": "Intervalo del 95%",
    "Loans": "Préstamos",
    "Typical APR over time": "APR típica a lo largo del tiempo",
    # charts.py
    "Where your APR sits among similar loans": "Dónde queda tu APR entre préstamos similares",
    "80% range": "Rango 80%",
    "Interest paid over the loan": "Intereses pagados durante el préstamo",
    "What moves the typical rate for a loan like yours": "Qué mueve la tasa típica de un préstamo como el tuyo",
    "Median APR": "APR mediana",
    "Typical APR": "APR típica",
    "Price gap by state, same lender": "Diferencia de precio por estado, mismo prestamista",
    "APR gap by state": "Diferencia de APR por estado",
    "APR gap vs similar loans, in points": "Diferencia de APR frente a préstamos similares, en puntos",
    "Pays less": "Menos",
    "Pays more": "Más",
    "No data": "Sin datos",
    "Solid outline: the gap holds up after testing many states":
        "Borde sólido: la diferencia se sostiene tras probar muchos estados",
    "Dashed outline: the gap could be chance": "Borde punteado: la diferencia podría ser azar",
    "Solid: holds up after testing many states": "Sólido: se sostiene tras probar muchos estados",
    "Dashed: could be chance": "Punteado: podría ser azar",
}

# ---------------------------------------------------------------- result HTML: fixed sentences (substrings)

PHRASES: dict[str, str] = {
    # app.py
    "Something went wrong on our side, not with your entries. They are still in the form, so press Check my rate "
    "to try again.":
        "Algo falló de nuestro lado, no en tus datos. Siguen en el formulario, así que pulsa Revisar mi tasa para "
        "intentarlo de nuevo.",
    "Enter the loan offer and press <strong>Check my rate</strong>, or try an example: <strong>Jordan</strong> "
    "(a fair rate) or <strong>Sam</strong> (a rate well above similar loans).":
        "Escribe la oferta de préstamo y pulsa <strong>Revisar mi tasa</strong>, o prueba un ejemplo: "
        "<strong>Jordan</strong> (una tasa justa) o <strong>Sam</strong> (una tasa muy por encima de préstamos "
        "similares).",
    "The trained model is not connected yet, so every number below is a placeholder, not a real comparison.":
        "El modelo entrenado aún no está conectado, así que cada número de abajo es de ejemplo, no una comparación "
        "real.",
    "The trained model is not connected yet, so every comparison with similar loans below is a placeholder.":
        "El modelo entrenado aún no está conectado, así que cada comparación con préstamos similares de abajo es de "
        "ejemplo.",
    "That's a good rate for a profile like yours.": "Es una buena tasa para un perfil como el tuyo.",
    "Ask for the buy rate and compare it with a second offer before you sign.":
        "Pide la tasa de compra (buy rate) y compárala con una segunda oferta antes de firmar.",
    "Ask for the buy rate and get a second offer before you sign. A dealer markup is one possible reason; risk the "
    "data can't see is another. In our repayment test, loans priced above 90% of similar loans went on to be late or "
    "charged off more often, clearly at Santander and Ally and only slightly at CarMax.":
        "Pide la tasa de compra (buy rate) y consigue una segunda oferta antes de firmar. Un recargo del "
        "concesionario es una razón posible; otra es un riesgo que los datos no ven. En nuestra prueba de pagos, los "
        "préstamos con un precio más alto que el 90% de los préstamos similares se atrasaron o el prestamista los dio por perdidos "
        "más a menudo, claramente en Santander y Ally y solo un poco en CarMax.",
    "Your offer next to each lender's own similar loans. Your lender is marked.":
        "Tu oferta junto a los préstamos similares de cada prestamista. Tu prestamista está marcado.",
    "Your offer next to each lender's own similar loans. Add your lender above to make it the main comparison.":
        "Tu oferta junto a los préstamos similares de cada prestamista. Agrega tu prestamista arriba para que sea la "
        "comparación principal.",
    "Your offer matches the credit-union average.": "Tu oferta es igual al promedio de las cooperativas de crédito.",
    "These are national averages, not adjusted for credit score, so they show where to ask rather than your rate. "
    "A pre-approval from a credit union gives you a real number to compare.":
        "Son promedios nacionales, sin ajustar por puntaje de crédito, así que muestran dónde preguntar, no tu tasa. "
        "Una preaprobación de una cooperativa de crédito te da un número real para comparar.",
    " That's few, so treat the range with care.": " Son pocos, así que toma el rango con cuidado.",
    "Your other details are close to a typical loan in the data, so they barely change the typical rate.":
        "Tus otros datos se parecen a los de un préstamo típico, así que casi no cambian la tasa típica.",
    "Ask for the buy rate.": "Pide la tasa de compra (buy rate).",
    "That is the rate the lender approved you for, before the dealer adds anything. Ask the dealer to bring your "
    "rate down to it.":
        "Es la tasa que el prestamista te aprobó, antes de que el concesionario agregue algo. Pide al concesionario "
        "que baje tu tasa a esa.",
    "Bring a credit-union pre-approval.": "Lleva una preaprobación de una cooperativa de crédito.",
    "A written offer from a credit union or bank gives you a rate to compare and lets you finance somewhere else.":
        "Una oferta por escrito de una cooperativa de crédito o de un banco te da una tasa para comparar y te permite "
        "financiar en otro lugar.",
    "Check the amount financed for add-ons.": "Revisa si el monto financiado incluye productos adicionales.",
    "Extras like an extended warranty or GAP coverage are often added to the loan. Ask what is included and whether "
    "you can drop any of it.":
        "Los extras como una garantía extendida o un seguro GAP a menudo se agregan al préstamo. Pregunta qué incluye "
        "y si puedes quitar algo.",
    # inputs.py and app._prepare
    "Choose whether the car is new or used.": "Elige si el auto es nuevo o usado.",
    "Enter the car's model year, for example 2019.": "Escribe el año del modelo del auto, por ejemplo 2019.",
    "Enter the car's price in dollars (more than $0).": "Escribe el precio del auto en dólares (más de $0).",
    "Enter the amount financed in dollars (more than $1,000, the smallest loans in our data). It's on the loan contract.":
        "Escribe el monto financiado en dólares (más de $1,000, los préstamos más pequeños de nuestros datos). Está en el contrato del préstamo.",
    "Enter the monthly payment in dollars (more than $0), or leave it blank.":
        "Escribe el pago mensual en dólares (más de $0), o déjalo en blanco.",
    "Enter the add-ons in dollars, or leave the field blank.":
        "Escribe los productos adicionales en dólares, o deja el campo en blanco.",
    "The add-ons can't be more than the amount financed, which already includes them.":
        "Los productos adicionales no pueden ser más que el monto financiado, que ya los incluye.",
    # markupcheck_model.py
    "This loan amount is larger than any loan the model learned from.":
        "Este monto es mayor que cualquier préstamo con el que aprendió el modelo.",
    "Very few loans in public bond pools have credit scores this low.":
        "Muy pocos préstamos en los fondos de bonos públicos tienen puntajes de crédito tan bajos.",
    "The loan is much larger than the car's value (often add-ons like warranties or GAP); such loans are rare in "
    "the data.":
        "El préstamo es mucho mayor que el valor del auto (a menudo por productos adicionales como garantías o GAP); "
        "esos préstamos son raros en los datos.",
    "Cars this old are rare in the data.": "Los autos así de viejos son raros en los datos.",
    "Without a lender, this compares with all lenders at once. In our test that was less accurate than a simple rule "
    "of thumb for loans from Hyundai Capital America; naming the lender on the contract fixed it.":
        "Sin un prestamista, esto compara con todos los prestamistas a la vez. En nuestra prueba eso fue menos preciso "
        "que una regla práctica sencilla para los préstamos de Hyundai Capital America; indicar el prestamista del "
        "contrato lo corrigió.",
    "The data has no race, sex or age and no dealer details, so the tool can show how far a price is from similar "
    "loans, but not why.":
        "Los datos no tienen raza, sexo ni edad, ni detalles del concesionario, así que la herramienta puede mostrar "
        "qué tan lejos está un precio de préstamos similares, pero no por qué.",
    "Credit unions and banks that don't sell their loans into public bonds appear only as national averages, not "
    "loan by loan.":
        "Las cooperativas de crédito y los bancos que no venden sus préstamos en bonos públicos aparecen solo como "
        "promedios nacionales, no préstamo por préstamo.",
    "Only loans that lenders sold into public bonds are included; credit unions and many banks aren't.":
        "Solo se incluyen préstamos que los prestamistas vendieron en bonos públicos; las cooperativas de crédito y "
        "muchos bancos no están.",
    "Your credit app may show a VantageScore, while lenders often use FICO; the two can differ.":
        "Tu app de crédito puede mostrar un VantageScore, mientras que los prestamistas suelen usar FICO; los dos "
        "pueden ser distintos.",
    "The data has no race, sex or age, and no information about the dealer, so some price differences can't be "
    "explained.":
        "Los datos no tienen raza, sexo ni edad, ni información del concesionario, así que algunas diferencias de "
        "precio no se pueden explicar.",
    "A high APR can also reflect risk the data doesn't show, not only a markup.":
        "Una APR alta también puede reflejar un riesgo que los datos no muestran, no solo un recargo.",
    "Add the lender named on your contract (if it's one of the 10 lenders in the data) for a sharper same-lender "
    "comparison.":
        "Agrega el prestamista que aparece en tu contrato (si es uno de los 10 prestamistas de los datos) para una "
        "comparación más precisa con el mismo prestamista.",
    "Stub reason 1": "Razón de ejemplo 1",
    "Stub reason 2": "Razón de ejemplo 2",
    "Stub reason 3": "Razón de ejemplo 3",
    "Stub: the real model is not trained yet.": "Ejemplo: el modelo real aún no está entrenado.",
    "Stub: no data loaded.": "Ejemplo: no se cargaron datos.",
    # sections.py
    "Ask what else is in the payment, such as add-ons or fees, and whether the APR and amount on the contract are "
    "final.":
        "Pregunta qué más incluye el pago, como productos adicionales o cargos, y si la APR y el monto del contrato "
        "son finales.",
    "Check that the amount financed and the term match the contract.":
        "Revisa que el monto financiado y el plazo coincidan con el contrato.",
    "Extended warranties, GAP coverage and similar products are usually optional. Ask for each price in writing, "
    "and whether you can buy it later, elsewhere, or not at all.":
        "Las garantías extendidas, el seguro GAP y productos similares suelen ser opcionales. Pide cada precio por "
        "escrito, y pregunta si puedes comprarlo después, en otro lugar o no comprarlo.",
    "How the APRs of similar loans spread out, with the range most of them got shaded.":
        "Cómo se reparten las APR de préstamos similares; el rango que obtuvo la mayoría está sombreado.",
    "Each bar changes one of your details from a typical loan's value to yours; the bars are one-at-a-time "
    "comparisons, not proof of cause.":
        "Cada barra cambia uno de tus datos, del valor de un préstamo típico al tuyo; las barras son comparaciones "
        "de uno en uno, no prueba de causa.",
    "These changes lower the typical rate for a loan like yours the most:":
        "Estos cambios son los que más bajan la tasa típica de un préstamo como el tuyo:",
    "None of these changes moves the typical rate for a loan like yours by much:":
        "Ninguno de estos cambios mueve mucho la tasa típica de un préstamo como el tuyo:",
    "All of these together": "Todo esto junto",
    "What buy rate did the lender approve before any dealer markup?":
        "¿Qué tasa de compra (buy rate) aprobó el prestamista antes de cualquier recargo del concesionario?",
    "What is included in the amount financed, and which items are optional?":
        "¿Qué incluye el monto financiado y qué partes son opcionales?",
    "The link holds your numbers after the # sign, which browsers don't send to our server; anyone you send it to "
    "can see them.":
        "El enlace guarda tus números después del signo #, que los navegadores no envían a nuestro servidor; "
        "cualquiera a quien se lo envíes puede verlos.",
    "It's the rate the lender approved before the dealer adds anything. Ask: \"What buy rate did the lender "
    "approve, and how much is being added?\" Some dealers will tell you; asking shows you know how it works.":
        "Es la tasa que el prestamista aprobó antes de que el concesionario agregue algo. Pregunta: \"¿Qué tasa de "
        "compra (buy rate) aprobó el prestamista y cuánto se está agregando?\" Algunos concesionarios te lo dirán; "
        "preguntar muestra que sabes cómo funciona.",
    "No. MarkupCheck is a student prototype. It shows how your offer compares with real loans; the decision is "
    "yours.":
        "No. MarkupCheck es un prototipo estudiantil. Muestra cómo se compara tu oferta con préstamos reales; la "
        "decisión es tuya.",
    # tabs.py
    "These are national averages, not adjusted for credit score, so your own rate can be higher or lower.":
        "Son promedios nacionales, sin ajustar por puntaje de crédito, así que tu propia tasa puede ser más alta o "
        "más baja.",
    "Enter at least two offers to compare, each with an APR and a loan term.":
        "Escribe al menos dos ofertas para comparar, cada una con una APR y un plazo.",
    "Versus similar loans compares each APR with loans like yours from all lenders in our data, for that offer's "
    "term; Typical is their usual APR.":
        "Frente a préstamos similares compara cada APR con préstamos como el tuyo de todos los prestamistas de "
        "nuestros datos, para el plazo de esa oferta; Típica es su APR habitual.",
    "Your offers have different terms. A longer term lowers the monthly payment, but you usually pay more interest "
    "in total.":
        "Tus ofertas tienen plazos distintos. Un plazo más largo baja el pago mensual, pero normalmente pagas más "
        "interés en total.",
    "Enter what you still owe on the loan, in dollars (more than $1,000).":
        "Escribe lo que aún debes del préstamo, en dólares (más de $1,000).",
    "This check works for balances over $1,000.": "Esta revisión sirve para saldos de más de $1,000.",
    "Enter your current APR, for example 14.5.": "Escribe tu APR actual, por ejemplo 14.5.",
    "Enter how many monthly payments you have left, for example 40.":
        "Escribe cuántos pagos mensuales te quedan, por ejemplo 40.",
    "Enter your car's value in dollars (more than $0), or leave it blank.":
        "Escribe el valor de tu auto en dólares (más de $0), o déjalo en blanco.",
    "Here is the same balance and time at other rates.": "Aquí tienes el mismo saldo y tiempo con otras tasas.",
    "We compared your loan with used-car loans, since a car you already own counts as used.":
        "Comparamos tu préstamo con préstamos de autos usados, porque un auto que ya tienes cuenta como usado.",
    "Our data is loans made when people bought their cars. Refinance loans can be priced differently.":
        "Nuestros datos son préstamos hechos cuando la gente compró su auto. Los préstamos de refinanciamiento pueden "
        "tener otros precios.",
    "Refinancing can have fees, such as a loan or title fee. They aren't included here.":
        "Refinanciar puede tener cargos, como un cargo por préstamo o por título. No se incluyen aquí.",
    "Check the exact payoff amount with your lender. It can differ from the balance on your statement.":
        "Confirma con tu prestamista el monto exacto para liquidar el préstamo. Puede ser distinto del saldo de tu "
        "estado de cuenta.",
    "We couldn't read this file. In Excel or Google Sheets, save it as CSV (UTF-8) and try again. The template shows "
    "the columns it needs.":
        "No pudimos leer este archivo. En Excel o Google Sheets, guárdalo como CSV (UTF-8) e inténtalo de nuevo. La "
        "plantilla muestra las columnas que necesita.",
    "Choose a CSV file to check. The template shows the columns it needs.":
        "Elige un archivo CSV para revisar. La plantilla muestra las columnas que necesita.",
    "This file is empty. Start from the template, which shows the columns it needs.":
        "Este archivo está vacío. Empieza con la plantilla, que muestra las columnas que necesita.",
    "This file has column names but no rows to check.":
        "Este archivo tiene nombres de columnas, pero no filas para revisar.",
    "This row has more values than there are columns. If a number has a comma, like 17,500, remove the comma or put "
    "the number in quotes.":
        "Esta fila tiene más valores que columnas. Si un número tiene coma, como 17,500, quita la coma o pon el número "
        "entre comillas.",
    "Something went wrong on our side while checking this row.": "Algo falló de nuestro lado al revisar esta fila.",
    "Row 1 is the first row under the column names. The results file has every row: your columns plus typical_apr, "
    "range_low, range_high, percentile, verdict and error.":
        "La fila 1 es la primera debajo de los nombres de las columnas. El archivo de resultados tiene todas las "
        "filas: tus columnas más typical_apr, range_low, range_high, percentile, verdict y error.",
    "Rows that name one of the 10 lenders in the data are compared with that lender's own similar loans; the rest "
    "with similar loans from all lenders.":
        "Las filas que nombran a uno de los 10 prestamistas de los datos se comparan con los préstamos similares de "
        "ese prestamista; el resto, con préstamos similares de todos los prestamistas.",
    "Choose a CSV file first.": "Primero elige un archivo CSV.",
    # explore.py
    "Each state's average APR compared with similar loans at the <strong>same lender</strong>, in points.":
        "La APR promedio de cada estado comparada con préstamos similares del <strong>mismo prestamista</strong>, "
        "en puntos.",
    "Positive means borrowers there paid more.": "Un valor positivo significa que los compradores de ahí pagaron más.",
    "The data can't say why a state differs: state law, risk the data doesn't show, or dealer practice. It has no "
    "race, sex or age, so it can't test those groups.":
        "Los datos no pueden decir por qué un estado es distinto: leyes estatales, riesgos que los datos no muestran "
        "o prácticas de los concesionarios. No tienen raza, sexo ni edad, así que no pueden poner a prueba esos "
        "grupos.",
    "These are raw medians, not adjusted for the mix of loans each month, so a jump can mean the lender made "
    "different kinds of loans that month, not only that prices changed.":
        "Son medianas sin ajustar por la mezcla de préstamos de cada mes, así que un salto puede significar que el "
        "prestamista hizo otros tipos de préstamos ese mes, no solo que cambiaron los precios.",
    "The state data isn't built yet (run src/build_extras.py).":
        "Los datos por estado aún no están listos (ejecuta src/build_extras.py).",
    "The tracker data isn't built yet (run src/build_extras.py).":
        "Los datos mensuales aún no están listos (ejecuta src/build_extras.py).",
    # charts.py
    "The curve shows how common each APR is among similar loans.":
        "La curva muestra qué tan común es cada APR entre préstamos similares.",
    "Interest paid so far, by month of the loan.": "Intereses pagados hasta ahora, por mes del préstamo.",
    "Each step changes one detail at a time.": "Cada paso cambia un dato a la vez.",
    "Other and combined effects is what is left, so the steps add up exactly.":
        "Otros efectos combinados es lo que queda, así que los pasos suman exacto.",
    "No APR data to show.": "No hay datos de APR para mostrar.",
    "No interest data to show.": "No hay datos de intereses para mostrar.",
    "No monthly data to show.": "No hay datos mensuales para mostrar.",
    "No rate breakdown to show.": "No hay desglose de la tasa para mostrar.",
    "No state data to show.": "No hay datos de estados para mostrar.",
}

# ---------------------------------------------------------------- result HTML: sentences with numbers or names

_PCT = r"-?\d+(?:\.\d+)?%"
_USD = r"\$[\d,]+(?:\.\d\d)?"
_MON = "|".join(_MONTHS)
_ABBR = "|".join(_MONTHS_ABBR)
_STATE = "|".join(sorted(map(re.escape, _STATES), key=len, reverse=True))


def _date_es(text: str) -> str:
    """'December 26, 2025' -> '26 de diciembre de 2025'; 'January 2026' -> 'enero de 2026'."""
    m = re.fullmatch(rf"({_MON}) (\d{{1,2}}), (\d{{4}})", text.strip())
    if m:
        return f"{m.group(2)} de {_MONTHS[m.group(1)]} de {m.group(3)}"
    m = re.fullmatch(rf"({_MON}) (\d{{4}})", text.strip())
    if m:
        return f"{_MONTHS[m.group(1)]} de {m.group(2)}"
    return text


def _months(n: str, word: str = "months") -> str:
    return f"{n} {'mes' if word == 'month' else 'meses'}"


def _kind(word: str) -> str:
    return {"new": "nuevo", "used": "usado"}.get(word, word)


# Waterfall labels (markupcheck_model._short and charts.waterfall_svg), as (English regex, Spanish template).
_WF = [
    (r"Typical loan in the data", "Préstamo típico"),
    (r"Typical for you", "Típica para ti"),
    (r"Other and combined effects", "Otros efectos combinados"),
    (r"Other detail", "Otro dato"),
    (r"Credit score (\d+)", r"Puntaje de crédito \1"),
    (r"Used car", "Auto usado"),
    (r"New car", "Auto nuevo"),
    (r"This year's model", "Modelo de este año"),
    (r"Car 1 year old", "Auto de 1 año"),
    (r"Car (\d+) years? old", r"Auto de \1 años"),
    (r"Borrowing (\$[\d,]+)", r"Monto de \1"),
    (r"Loan (\d+%) of car value", r"Préstamo \1 del valor"),
    (r"(\d+)-month term", r"Plazo de \1 meses"),
]
_WF_RX = "(?:" + "|".join(re.sub(r"\((?!\?)", "(?:", p) for p, _ in _WF) + ")"  # same labels, no groups


def _wf(label: str) -> str:
    """One waterfall label in Spanish (case-insensitive, so the lower-cased labels in the FAQ match too)."""
    for pattern, spanish in _WF:
        m = re.fullmatch(pattern, label, flags=re.I)
        if m:
            out = m.expand(spanish)
            return out[:1].lower() + out[1:] if label[:1].islower() else out
    return label


# Reason sentences (markupcheck_model._describe).
_SUBJECTS = [
    (r"Your credit score of (\d+)", r"Tu puntaje de crédito de \1"),
    (r"Buying (used|new)", None),
    (r"A car 1 years old", "Un auto de 1 año"),
    (r"A car (\d+) years old", r"Un auto de \1 años"),
    (r"Borrowing (\d+%) of the car's value", r"Pedir prestado el \1 del valor del auto"),
    (r"Borrowing (\$[\d,]+)", r"Pedir prestados \1"),
    (r"A (\d+)-month term", r"Un plazo de \1 meses"),
]
_REFS = [
    (r"a typical credit score of (\d+)", r"un puntaje de crédito típico de \1"),
    (r"buying (used|new)", None),
    (r"a typical 1-year-old car", "un auto típico de 1 año"),
    (r"a typical (\d+)-year-old car", r"un auto típico de \1 años"),
    (r"borrowing a typical (\$[\d,]+)", r"un monto típico de \1"),
    (r"a typical (\d+%) of the car's value", r"el \1 típico del valor del auto"),
    (r"a typical (\d+)-month term", r"un plazo típico de \1 meses"),
]


def _describe(text: str, table) -> str | None:
    for pattern, spanish in table:
        m = re.fullmatch(pattern, text)
        if m:
            if spanish is None:  # buying new / used
                verb = "Comprar" if text[:1].isupper() else "comprar"
                return f"{verb} {_kind(m.group(1))}"
            return m.expand(spanish)
    return None


def _reason(m) -> str:
    subj, ref = _describe(m.group("subj"), _SUBJECTS), _describe(m.group("ref"), _REFS)
    if subj is None or ref is None:
        return m.group(0)
    verb = "sube" if m.group("verb") == "raises" else "baja"
    versus = "frente al " + ref[3:] if ref.startswith("el ") else "frente a " + ref
    return f"{subj} {verb} la tasa típica unos {m.group('x')} puntos {versus}."


def _why(m) -> str:
    parts = []
    for part in m.group(1).split("; "):
        if part == "your details are close to a typical loan's":
            parts.append("tus datos se parecen a los de un préstamo típico")
            continue
        p = re.fullmatch(r"(.+) (adds|takes off) about ([\d.]+) points", part)
        if not p:
            return m.group(0)
        verb = "suma" if p.group(2) == "adds" else "resta"
        parts.append(f"{_wf(p.group(1))} {verb} unos {p.group(3)} puntos")
    return f"Frente a un préstamo típico de los datos, {'; '.join(parts)}."


def _SHARE(share: str) -> str:
    """'over 95%' -> 'más del 95%', 'under 5%' -> 'menos del 5%', '28%' -> '28%'."""
    if share.startswith("over "):
        return "más del " + share[5:]
    if share.startswith("under "):
        return "menos del " + share[6:]
    return share


def _SHARE_ART(share: str) -> str:
    """The article before the share: 'la del 28%', but 'la de más del 95%'."""
    return "de " if share.startswith(("over ", "under ")) else "del "


def _market(m) -> str:
    out = f"Con todos los prestamistas: típica {m.group(1)}, rango {m.group(2)}–{m.group(3)}"
    if m.group(4):
        out += f"; tu APR es más alta que la {_SHARE_ART(m.group(4))}{_SHARE(m.group(4))} de esos préstamos"
    if m.group(5):
        out += f" ({_FLAGS_LOWER.get(m.group(5), m.group(5))})"
    return out + "."


def _credit_union(m) -> str:
    source = ", con datos de S&amp;P Global" if m.group("sp") else ""
    return (f"El {_date_es(m.group('date'))}, las cooperativas de crédito reportaron un promedio de "
            f"<strong>{m.group('cu')}</strong> y los bancos, <strong>{m.group('bank')}</strong>, para un préstamo de "
            f"{m.group('n')} meses para auto {_kind(m.group('kind'))} (NCUA{source}).")


def _distribution_offer(m) -> str:
    out = f"Tu oferta es {m.group('o')}"
    if m.group("where"):
        out += {"below": ", por debajo de ese rango", "above": ", por encima de ese rango",
                "inside": ", dentro de ese rango"}[m.group("where")]
    if m.group("same"):
        out += ", igual que la APR típica"
    elif m.group("gap"):
        side = "por encima" if m.group("side") == "above" else "por debajo"
        out += f", {m.group('gap')} puntos {side} de la APR típica"
    return out + "."


_SERIES = {"Your offer": "Tu oferta", "Typical": "Típica", "Credit-union average": "Cooperativa media"}
_SERIES_OBJ = {"Your offer": "tu oferta", "Typical": "la típica", "Credit-union average": "la cooperativa media"}


def _series(name: str, table=_SERIES) -> str:
    m = re.fullmatch(r"(Loan|Lender) (\d+)", name)
    if m:
        return f"{'Préstamo' if m.group(1) == 'Loan' else 'Prestamista'} {m.group(2)}"
    return table.get(name, name)


def _tracker_desc(m) -> str:
    sentence = f"{m.group('name')}: {m.group('p1')} en {_ABBR_FULL[m.group('m1')]} de {m.group('y1')}"
    if m.group("p2"):
        sentence += f", {m.group('p2')} en {_ABBR_FULL[m.group('m2')]} de {m.group('y2')}"
    if m.group("lo"):
        sentence += f"; mínima {m.group('lo')}, máxima {m.group('hi')}"
    if m.group("gaps"):
        sentence += f"; {_months(m.group('gaps'), m.group('mw'))} sin datos"
    return sentence + "."


def _tier_label(label: str) -> str:
    """'Prime (661–780), used cars' -> 'Prime (661–780), autos usados'."""
    m = re.fullmatch(r"(.+), (used|new) cars", label)
    if not m:
        return label
    return f"{_TIERS.get(m.group(1), m.group(1))}, autos {'usados' if m.group(2) == 'used' else 'nuevos'}"


def _offer_variant(pattern: str, spanish: str):
    """A validation message, plus the 'Offer 2: enter the APR ...' form tabs.compare_offers gives it."""
    lower = pattern[:1].lower() + pattern[1:]
    inner = re.compile(lower)

    def prefixed(m):
        es = inner.sub(spanish, m.group(2), count=1)
        return f"Oferta {m.group(1)}: {es[:1].lower()}{es[1:]}"
    return [(re.compile(rf"Offer (\d+): ({lower})"), prefixed), (re.compile(pattern), spanish)]


def _rules(pairs):
    return [(re.compile(p) if isinstance(p, str) else p, r) for p, r in pairs]


RULES = _rules([
    # app.py: verdict, headline and the whole-market line
    (rf"Your ({_PCT}) is <strong>([\d.]+) points above</strong> the range similar loans got \(([^)<]*)\)\.",
     r"Tu tasa de \1 está <strong>\2 puntos por encima</strong> del rango que obtuvieron los préstamos similares (\3)."),
    (rf"Your ({_PCT}) is <strong>below</strong> the range similar loans got \(([^)<]*)\)\.",
     r"Tu tasa de \1 está <strong>por debajo</strong> del rango que obtuvieron los préstamos similares (\2)."),
    (rf"Your ({_PCT}) is <strong>inside</strong> the range similar loans got \(([^)<]*)\), below the typical ({_PCT})\.",
     r"Tu tasa de \1 está <strong>dentro</strong> del rango que obtuvieron los préstamos similares (\2), por debajo "
     r"de la tasa típica de \3."),
    (rf"Your ({_PCT}) is <strong>inside</strong> the range similar loans got \(([^)<]*)\), above the typical ({_PCT})\.",
     r"Tu tasa de \1 está <strong>dentro</strong> del rango que obtuvieron los préstamos similares (\2), por encima "
     r"de la tasa típica de \3."),
    (r"Your APR is higher than (<span[^>]*>)((?:over |under )?\d+%)(</span>) of similar loans",
     lambda m: f"Tu APR es más alta que la {_SHARE_ART(m.group(2))}{m.group(1)}{_SHARE(m.group(2))}{m.group(3)} "
               "de los préstamos similares"),
    (rf"Across all lenders: typical ({_PCT}), range ({_PCT})–({_PCT})"
     r"(?:; your APR is higher than ((?:over |under )?\d+%) of those loans)?(?: \(([^)<]*)\))?\.", _market),
    (r"Compared with: same lender \(([^)<]*)\)", r"Comparado con: el mismo prestamista (\1)"),
    (r"Compared with: whole market \(all lenders\)", "Comparado con: todo el mercado (todos los prestamistas)"),
    (r"Compared with: placeholder", "Comparado con: ejemplo"),
    (r"Compared with: ", "Comparado con: "),
    (rf"Your offer ({_PCT})\. Similar loans mostly got ({_PCT}) to ({_PCT}); typical ({_PCT})\.",
     r"Tu oferta: \1. La mayoría de los préstamos similares obtuvo de \2 a \3; típica: \4."),
    (r"Similar loans mostly got an APR between (<strong>[^<]*</strong>) and (<strong>[^<]*</strong>)\.",
     r"La mayoría de los préstamos similares obtuvo una APR entre \1 y \2."),
    (r"The range aims to hold 8 in 10 loans; in our test on later loans it held for (\d+)% of buyers like you\.",
     r"El rango busca incluir 8 de cada 10 préstamos; en nuestra prueba con préstamos posteriores, se cumplió para "
     r"el \1% de los compradores como tú."),
    (rf"That's <strong>({_USD}) more</strong> over (\d+) months than at the typical APR\.",
     r"Eso es <strong>\1 más</strong> en \2 meses que con la APR típica."),
    (rf"That's about <strong>({_USD}) less</strong> than a typical loan like yours, over (\d+) months\.",
     r"Eso es unos <strong>\1 menos</strong> que un préstamo típico como el tuyo, en \2 meses."),
    (r"That's about the same as the typical APR over (\d+) months\.",
     r"Es casi lo mismo que con la APR típica en \1 meses."),
    # app.py: lenders, credit unions, checks, evidence, risk
    (r"We don't have loans from ([^<]*?) in our data, so here is your offer next to each lender we do have\.",
     r"No tenemos préstamos de \1 en nuestros datos, así que aquí está tu oferta junto a cada prestamista que sí "
     r"tenemos."),
    (r"We have only ([\d,]+) loans from ([^<]*?), so its typical rate is less certain than for bigger lenders\.",
     r"Solo tenemos \1 préstamos de \2, así que su tasa típica es menos segura que la de prestamistas más grandes."),
    (r"None of the loans from ([^<]*?) fell in our test months, so we couldn't measure how well this check does on "
     r"its loans alone\.",
     r"Ningún préstamo de \1 cayó en nuestros meses de prueba, así que no pudimos medir qué tan bien funciona esta "
     r"revisión solo con sus préstamos."),
    (r"On ([\d,]+) loans from ([^<]*?) held back for testing, the typical rate here was off by ([\d.]+) points on "
     r"average, against ([\d.]+) for the rule of thumb\.",
     r"Con \1 préstamos de \2 reservados para la prueba, la tasa típica de aquí se desvió \3 puntos en promedio, "
     r"frente a \4 de la regla práctica."),
    (r"That test is small, so treat it with care\.", "Esa prueba es pequeña, así que tómala con cuidado."),
    (r"None of the loans from ([^<]*?) fell in our test months, and its later deals hold only promotional loans, "
     r"which aren't market prices, so we couldn't measure how well this check does on its loans\.",
     r"Ningún préstamo de \1 cayó en nuestros meses de prueba, y sus emisiones posteriores solo tienen préstamos "
     r"promocionales, que no son precios de mercado, así que no pudimos medir qué tan bien funciona esta revisión con "
     r"sus préstamos."),
    (r"On ([\d,]+) loans from a later ([^<]*?) deal the model never saw, the typical rate here was off by ([\d.]+) "
     r"points on average, against ([\d.]+) for the rule of thumb\.",
     r"Con \1 préstamos de una emisión posterior de \2 que el modelo nunca vio, la tasa típica de aquí se desvió \3 "
     r"puntos en promedio, frente a \4 de la regla práctica."),
    (r"We don't have enough loans from ([^<]*?) in our data to compare, so the result above uses all lenders\.",
     r"No tenemos suficientes préstamos de \1 en nuestros datos para comparar, así que el resultado de arriba usa "
     r"todos los prestamistas."),
    (r">([\d.]+) points higher<", r">\1 puntos más alta<"),
    (r">([\d.]+) points lower<", r">\1 puntos más baja<"),
    (rf"On (?P<date>[^,<]+ \d{{1,2}}, \d{{4}}), credit unions reported an average of <strong>(?P<cu>{_PCT})</strong> "
     rf"and banks <strong>(?P<bank>{_PCT})</strong> for a (?P<n>\d+)-month (?P<kind>new|used)-car loan "
     r"\(NCUA(?P<sp>, from S&amp;P Global data)?\)\.", _credit_union),
    (r"NCUA reports no (\d+)-month rate, so this compares with its closest term\.",
     r"NCUA no publica una tasa a \1 meses, así que esto se compara con su plazo más cercano."),
    (r"Few loans in the data are like this, so treat it with care\.",
     "Hay pocos préstamos así en los datos, así que tómalo con cuidado."),
    (r"Your offer is ([\d.]+) points above the credit-union average\.",
     r"Tu oferta está \1 puntos por encima del promedio de las cooperativas de crédito."),
    (r"Your offer is ([\d.]+) points below the credit-union average\.",
     r"Tu oferta está \1 puntos por debajo del promedio de las cooperativas de crédito."),
    (r"Your verdict, (<strong>[^<]*</strong>), holds in <strong>all (\d+)</strong> checks below\.",
     r"Tu veredicto, \1, se mantiene en <strong>las \2</strong> pruebas de abajo."),
    (r"Your verdict, (<strong>[^<]*</strong>), changes in <strong>(\d+) of (\d+)</strong> checks below, so treat it "
     r"as less certain\.",
     r"Tu veredicto, \1, cambia en <strong>\2 de \3</strong> pruebas de abajo, así que tómalo como menos seguro."),
    (r"If the score your lender used is (\d+) points lower \((\d+)\)",
     r"Si el puntaje que usó tu prestamista es \1 puntos más bajo (\2)"),
    (r"If the score your lender used is (\d+) points higher \((\d+)\)",
     r"Si el puntaje que usó tu prestamista es \1 puntos más alto (\2)"),
    (r"If this car is really used \(a 'new' car this old is unusual\)",
     "Si este auto en realidad es usado (un auto “nuevo” así de viejo es raro)"),
    (r"If your lender valued the car (\d+%) lower \(for example at invoice, as some lenders report new cars\)",
     r"Si tu prestamista valoró el auto un \1 más bajo (por ejemplo, a precio de factura, como algunos prestamistas "
     r"reportan los autos nuevos)"),
    (rf"If car-loan rates haven't moved since ((?:{_MON}) \d{{4}}) \(we assume they followed the 5-year Treasury, "
     rf"({_PCT}) then and ({_PCT}) in ((?:{_MON}) \d{{4}})\)",
     lambda m: (f"Si las tasas de préstamos de auto no han cambiado desde {_date_es(m.group(1))} (suponemos que "
                f"siguieron al bono del Tesoro a 5 años: {m.group(2)} entonces y {m.group(3)} en "
                f"{_date_es(m.group(4))})")),
    (rf"\btypical ({_PCT}), range ({_PCT})–({_PCT})\. Your offer: ", r"típica \1, rango \2–\3. Tu oferta: "),
    (r"</strong> of the ([\d,]+) loans in the data are like yours \(same new or used, credit score within about "
     r"20 points, term within about 6 months\)\.",
     r"</strong> de los \1 préstamos de los datos se parecen al tuyo (igual de nuevo o usado, puntaje de crédito a "
     r"unos 20 puntos o menos y plazo a unos 6 meses o menos)."),
    (r"Part of the range was capped at the lowest or highest APR seen in the data \(([\d.]+%)–([\d.]+%)\)\.",
     r"Parte del rango se limitó a la APR más baja o más alta de los datos (\1–\2)."),
    (r"Terms longer than (\d+) months are rare in the data\.", r"Los plazos de más de \1 meses son raros en los datos."),
    (r"In our repayment test, loans priced above 90% of similar loans were more often 30 or more days late or charged off "
     r"within about (\d+) months than other loans: ([^<]*?)\. So part of a high price can be risk the data doesn't "
     r"show, not only a markup\.",
     lambda m: (f"En nuestra prueba de pagos, los préstamos con un precio más alto que el 90% de los préstamos similares se "
                f"atrasaron 30 días o más, o el prestamista los dio por perdidos, más a menudo que los demás en unos "
                f"{m.group(1)} meses: {m.group(2).replace(' against ', ' frente a ')}. Así que parte de un precio "
                "alto puede ser un riesgo que los datos no muestran, no solo un recargo.")),
    (r"(?<=<li>)(?P<subj>[^<]+?) (?P<verb>raises|lowers) the typical rate by about (?P<x>[\d.]+) points compared "
     r"with (?P<ref>[^<]+?)\.(?=</li>)", _reason),
    (r"Compared with ([\d,]+) loans from (\d+) SEC-filed bond deals \(([^)<]*)\), originated (\S+) to (\S+?)\.",
     r"Comparado con \1 préstamos de \2 emisiones de bonos registradas ante la SEC (\3), otorgados de \4 a \5."),
    (rf"Prices are compared after removing the 5-year Treasury rate; your offer uses the (\S+) average of ({_PCT})\.",
     r"Los precios se comparan después de quitar la tasa del bono del Tesoro a 5 años; tu oferta usa el promedio "
     r"de \1, que fue de \2."),
    (rf"You're financing ({_USD}) more than the car's price\. Ask what that covers \(taxes and fees, or extras like "
     r"an extended warranty or GAP coverage\) and whether you can drop any of it\.",
     r"Estás financiando \1 más que el precio del auto. Pregunta qué cubre eso (impuestos y cargos, o extras como "
     r"una garantía extendida o un seguro GAP) y si puedes quitar algo."),
    # sections.py: payment, add-ons, cost of a point, charts' captions
    (rf"You entered a payment, not an APR\. A ({_USD}) payment on this loan works out to an APR of "
     rf"<strong>({_PCT})</strong>, so that is what we checked\.",
     r"Escribiste un pago, no una APR. Un pago de \1 en este préstamo equivale a una APR de <strong>\2</strong>, "
     r"así que eso fue lo que revisamos."),
    (rf"Your payment of ({_USD}) matches a ({_PCT}) APR on ({_USD}) over (\d+) months\.",
     r"Tu pago de \1 corresponde a una APR de \2 sobre \3 en \4 meses."),
    (rf"<strong>Your payment is ({_USD}) a month more than the APR explains</strong> \(({_USD}) over the loan\)\. "
     rf"A ({_PCT}) APR on ({_USD}) over (\d+) months should cost ({_USD}) a month\.",
     r"<strong>Tu pago es \1 al mes más de lo que explica la APR</strong> (\2 durante todo el préstamo). Una APR de "
     r"\3 sobre \4 en \5 meses debería costar \6 al mes."),
    (rf" It matches an APR of about <strong>({_PCT})</strong> instead\.",
     r" En cambio, corresponde a una APR de alrededor de <strong>\1</strong>."),
    (rf"Your payment of ({_USD}) is ({_USD}) a month less than a ({_PCT}) APR on ({_USD}) over (\d+) months should "
     rf"cost \(({_USD})\)\.",
     r"Tu pago de \1 es \2 al mes menos de lo que debería costar una APR de \3 sobre \4 en \5 meses (\6)."),
    (rf"The ({_USD}) of add-ons you entered cost <strong>({_USD})</strong> by the end of the loan: ({_USD}) of that "
     rf"is interest, because they are financed at ({_PCT})\. They add ({_USD}) to each payment\.",
     r"Los \1 de productos adicionales que escribiste cuestan <strong>\2</strong> al final del préstamo: \3 de eso "
     r"son intereses, porque se financian al \4. Suman \5 a cada pago."),
    (rf"Each percentage point of APR on this loan is worth about <strong>({_USD})</strong> over (\d+) months, so "
     r"every point you negotiate off saves about that much\.",
     r"Cada punto porcentual de APR en este préstamo vale unos <strong>\1</strong> en \2 meses, así que cada punto "
     r"que logres bajar te ahorra más o menos eso."),
    (rf"Interest paid so far, month by month, on ({_USD}) over (\d+) months\.",
     r"Intereses pagados hasta ahora, mes a mes, sobre \1 en \2 meses."),
    # sections.py: ways to a lower rate and the sliders
    (r"Choose a (\d+)-month term instead of (\d+)", r"Elige un plazo de \1 meses en vez de \2"),
    (rf"Put ({_USD}) more down \((\d+%) of the price\)", r"Da \1 más de pago inicial (\2 del precio)"),
    (r"If your credit score were (\d+) points higher \(paying card balances down can help\)",
     r"Si tu puntaje de crédito fuera \1 puntos más alto (pagar los saldos de tus tarjetas puede ayudar)"),
    (rf"typical ({_PCT}) \((down|up) ([\d.]+) points\), payment ({_USD}), about ({_USD}) (less|more) interest than "
     r"the typical rate for your loan now\.",
     lambda m: (f"típica {m.group(1)} ({'baja' if m.group(2) == 'down' else 'sube'} {m.group(3)} puntos), pago de "
                f"{m.group(4)}, unos {m.group(5)} {'menos' if m.group(6) == 'less' else 'más'} de interés que con la "
                "tasa típica de tu préstamo ahora.")),
    (rf"Typical ({_PCT}), most between ({_PCT}) and ({_PCT})\. Your ({_PCT}) would be (<span[^>]*>[^<]*</span>)\. "
     rf"Payment at the typical rate: ({_USD})\.",
     r"Típica \1, la mayoría entre \2 y \3. Tu tasa de \4 sería \5. Pago con la tasa típica: \6."),
    # sections.py: dealer card and questions
    (rf"<strong>My offer:</strong> ({_PCT}) APR, (\d+) months, ({_USD}) financed, ({_USD}) a month\.",
     r"<strong>Mi oferta:</strong> APR de \1, \2 meses, \3 financiados, \4 al mes."),
    (rf"<strong>Similar real loans \(SEC filings\):</strong> typical ({_PCT}), most between ({_PCT}) and ({_PCT})\.",
     r"<strong>Préstamos reales similares (registros de la SEC):</strong> típica \1, la mayoría entre \2 y \3."),
    (rf"<strong>At ([^<]*?):</strong> typical ({_PCT}) for similar loans\.",
     r"<strong>Con \1:</strong> típica \2 para préstamos similares."),
    (rf"<strong>Credit unions \(NCUA, ([^)<]*)\):</strong> ({_PCT}) average for a (\d+)-month (new|used)-car loan\.",
     lambda m: (f"<strong>Cooperativas de crédito (NCUA, {_date_es(m.group(1))}):</strong> promedio de {m.group(2)} "
                f"para un préstamo de {m.group(3)} meses para auto {_kind(m.group(4))}.")),
    (rf"Can you bring my rate to ({_PCT}), the typical rate for loans like mine\?",
     r"¿Pueden bajar mi tasa a \1, la tasa típica para préstamos como el mío?"),
    (rf"Newer: on ((?:{_MON}) \d{{1,2}}, \d{{4}}), the middle credit union was offering <strong>({_PCT})</strong> on "
     rf"(new|used)-car loans, and half were between ({_PCT}) and ({_PCT}) \(([\d,]+) credit unions reporting to "
     r"NCUA\)\. Each credit union reports one posted rate, not a rate for your credit score\.",
     lambda m: (f"Más reciente: el {m.group(1)}, la cooperativa de crédito del medio ofrecía <strong>{m.group(2)}"
                f"</strong> en préstamos para autos {_kind(m.group(3))}s, y la mitad estaba entre {m.group(4)} y "
                f"{m.group(5)} ({m.group(6)} cooperativas de crédito que informan a la NCUA). Cada cooperativa informa "
                "una tasa publicada, no una tasa para tu puntaje de crédito.")),
    (rf"Banks' average new-car rates \(Federal Reserve G\.19, (\d{{4}}) Q(\d)(, preliminary)?\): ({_PCT}) for 60 months "
     rf"and ({_PCT}) for 72 months; finance companies ({_PCT}) \((\d{{4}}) Q(\d)\)\.",
     lambda m: (f"Tasas promedio de los bancos para autos nuevos (Reserva Federal G.19, T{m.group(2)} {m.group(1)}"
                f"{', preliminar' if m.group(3) else ''}): {m.group(4)} a 60 meses y {m.group(5)} a 72 meses; "
                f"financieras {m.group(6)} (T{m.group(8)} {m.group(7)}).")),
    (rf'<option value="([A-Z]{{2}})">({_STATE})</option>', lambda m: f'<option value="{m.group(1)}">'
                                                                       f'{_STATES[m.group(2)]}</option>'),
    (rf"Choose your state to see how prices there compared at the same lender, and what credit unions based there "
     rf"were offering on ((?:{_MON}) \d{{1,2}}, \d{{4}})\.",
     r"Elige tu estado para ver cómo se compararon allí los precios con el mismo prestamista, y qué ofrecían las "
     r"cooperativas de crédito con sede allí el \1."),
    (r"Enter the number of payments, a whole number from 1 to (\d+)\.",
     r"Escribe el número de pagos, un número entero de 1 a \1."),
    (rf"The Amount Financed plus the Finance Charge equals the Total of Payments \(({_USD})\)\.",
     r"El monto financiado más el cargo financiero es igual al total de pagos (\1)."),
    (rf"The Amount Financed plus the Finance Charge is ({_USD}), but the Total of Payments says ({_USD}), a difference "
     rf"of ({_USD})\. Ask the dealer why they don't add up\.",
     r"El monto financiado más el cargo financiero da \1, pero el total de pagos dice \2, una diferencia de \3. "
     r"Pregunta al concesionario por qué no cuadran."),
    (rf"(\d+) payments of about ({_USD}) can't repay ({_USD}) at any APR from 0% to 60%\. Check the numbers you "
     r"typed\.",
     r"\1 pagos de unos \2 no pueden pagar \3 con ningún APR de 0% a 60%. Revisa los números que escribiste."),
    (rf"(\d+) payments of about ({_USD}) on ({_USD}) works out to an APR of ({_PCT}), which matches the ({_PCT}) in "
     r"the box within the federal tolerance of one eighth of a point\.",
     r"\1 pagos de unos \2 sobre \3 equivalen a un APR de \4, que coincide con el \5 del recuadro dentro de la "
     r"tolerancia federal de un octavo de punto."),
    (rf"(\d+) payments of about ({_USD}) on ({_USD}) works out to an APR of ({_PCT}), but the box says ({_PCT})\. A "
     r"first payment due later than a month after signing can explain a small difference; ask the dealer to show "
     r"how the APR was worked out\.",
     r"\1 pagos de unos \2 sobre \3 equivalen a un APR de \4, pero el recuadro dice \5. Un primer pago que vence "
     r"más de un mes después de firmar puede explicar una diferencia pequeña; pide al concesionario que te muestre "
     r"cómo calculó el APR."),
    (r"<td>(New|Used) (\d{4})</td>", lambda m: f"<td>{'Nuevo' if m.group(1) == 'New' else 'Usado'} {m.group(2)}</td>"),
    (rf"<td>({_USD}) over (\d+) months</td>", r"<td>\1 en \2 meses</td>"),
    (r">Open (Jordan|Sam|Alex|Riley)'s offer</a>", r">Abrir la oferta de \1</a>"),
    (rf"Similar loans mostly got ({_PCT}) to ({_PCT})\. Jordan's 15\.9% is (inside|outside) that range, so it is rated "
     r"(Typical|High|Well above similar loans)\.",
     lambda m: (f"Los préstamos similares obtuvieron sobre todo de {m.group(1)} a {m.group(2)}. El 15.9% de Jordan está "
                f"{'dentro' if m.group(3) == 'inside' else 'fuera'} de ese rango, así que se califica como "
                f"{_FLAGS[m.group(4)]}.")),
    (rf"Sam's 760 score and newer car put the typical rate for loans like Sam's at ({_PCT}); Jordan's 660 score and "
     rf"older car put it at ({_PCT})\. A lower APR can still be far above what similar buyers got\.",
     r"El puntaje de 760 de Sam y su auto más nuevo ponen la tasa típica para préstamos como el de Sam en \1; el puntaje "
     r"de 660 de Jordan y su auto más viejo la ponen en \2. Un APR más bajo puede seguir muy por encima de lo que "
     r"obtuvieron compradores similares."),
    (rf"About ({_USD}) more over 60 months\. Each percentage point is worth about ({_USD})\.",
     r"Unos \1 más en 60 meses. Cada punto porcentual vale unos \2."),
    (rf"({_WF_RX}): it lowers the typical rate by about ([\d.]+) points\.",
     lambda m: f"{_wf(m.group(1))}: baja la tasa típica unos {m.group(2)} puntos."),
    (rf"About ({_USD}) in all, counting the ({_USD}) paid up front; ({_USD}) of it is interest\.",
     r"Unos \1 en total, contando los \2 pagados al inicio; \3 de eso son intereses."),
    (rf"<strong>On newer loans\.</strong> We later tested the same model, unchanged, on ([\d,]+) (CarMax) loans from "
     rf"({_MON})(?: (\d{{4}}))? to ({_MON}) (\d{{4}})\. Its typical price stayed closer than the rule of thumb \(off by ([\d.]+) points "
     r"against ([\d.]+)\), but the range held for only (\d+)% of them, and (\d+)% were cheaper than the range\. So for "
     r"newer loans the range may sit too high, and an offer can look more typical than it is\.",
     lambda m: (f"<strong>Con préstamos más nuevos.</strong> Después probamos el mismo modelo, sin cambios, con "
                f"{m.group(1)} préstamos de {m.group(2)} de {_MONTHS[m.group(3)]}"
                f"{' de ' + m.group(4) if m.group(4) else ''} a {_MONTHS[m.group(5)]} de "
                f"{m.group(6)}. Su precio típico siguió más cerca que la regla práctica (se desvió {m.group(7)} puntos "
                f"frente a {m.group(8)}), pero el rango se cumplió solo para el {m.group(9)}% de ellos, y el "
                f"{m.group(10)}% fue más barato que el rango. Así que, para préstamos más nuevos, el rango puede quedar "
                "demasiado alto y una oferta puede parecer más típica de lo que es.")),
    (rf"This range was updated with ([^<]*?)'s newest filed loans \(({_MON})(?: (\d{{4}}))?(?: to ({_MON}))? "
     rf"(\d{{4}}), ([\d,]+) loans\), because its newer loans were priced (lower|higher) than the model expected\.",
     lambda m: (f"Este rango se actualizó con los préstamos más recientes registrados de {m.group(1)} "
                f"({_MONTHS[m.group(2)]}{' de ' + m.group(3) if m.group(3) else ''}"
                f"{' a ' + _MONTHS[m.group(4)] if m.group(4) else ''} de {m.group(5)}, {m.group(6)} préstamos), porque "
                f"sus préstamos más nuevos tenían precios más {'bajos' if m.group(7) == 'lower' else 'altos'} de lo "
                "que el modelo esperaba.")),
    (r"Download all (\d+) states \(CSV\)", r"Descargar los \1 estados (CSV)"),
    (r"<strong>How to cite:</strong> MarkupCheck, a student project \(2026\)\. State price gaps at the same lender, "
     r"from ([\d,]+ )?car loans in (\d+) SEC Regulation AB II bond deals from (\d+) lenders, originated "
     r"January 2023 to January 2026\. Keep the line above with any number you quote\.",
     r"<strong>Cómo citar:</strong> MarkupCheck, un proyecto estudiantil (2026). Diferencias de precio por estado con "
     r"el mismo prestamista, a partir de \1préstamos de auto en \2 emisiones de bonos registradas ante la SEC "
     r"(Regulation AB II) de \3 prestamistas, originados de enero de 2023 a enero de 2026. Incluye la línea de "
     r"arriba con cualquier número que cites."),
    (rf"Interest over (\d+) months at ({_PCT})", r"Intereses en \1 meses al \2"),
    (rf"All in, this car costs you about <strong>({_USD})</strong>\. At the typical ({_PCT}), the interest would be "
     rf"({_USD})\.",
     r"En total, este auto te cuesta unos <strong>\1</strong>. Con la tasa típica de \2, los intereses serían \3."),
    (r"Enter the rate you were offered as a percent from 0% to (\d+)%, or leave it blank\.",
     r"Escribe la tasa que te ofrecieron como porcentaje de 0% a \1%, o deja el campo en blanco."),
    (r"<strong>Next to a simple rule of thumb\.</strong>", "<strong>Frente a una regla práctica sencilla.</strong>"),
    (rf"A rate table that uses only your credit tier \(({'|'.join(map(re.escape, _TIERS))})\) and new or used would "
     rf"say typical ({_PCT}), range ({_PCT}) to ({_PCT})\.",
     lambda m: (f"Una tabla de tasas que usa solo tu nivel de crédito ({_TIERS[m.group(1)]}) y si es nuevo o usado "
                f"diría típica {m.group(2)}, rango de {m.group(3)} a {m.group(4)}.")),
    (r"MarkupCheck also uses the car's age, the amount, the loan-to-value and the term; its range for you is "
     r"([\d.]+) points wide, the rule's ([\d.]+)\.",
     r"MarkupCheck también usa la edad del auto, el monto, la relación préstamo-valor y el plazo; su rango para ti "
     r"mide \1 puntos, el de la regla \2."),
    (r"In our test on later loans, its typical price was off by ([\d.]+) points on average, against ([\d.]+) for the "
     r"rule\.",
     r"En nuestra prueba con préstamos posteriores, su precio típico se desvió \1 puntos en promedio, frente a \2 "
     r"de la regla."),
    (r"<strong>Verdict:</strong> (Typical|High|Well above similar loans)\.",
     lambda m: f"<strong>Veredicto:</strong> {_FLAGS[m.group(1)]}."),
    (rf"about ({_USD}) (more|less) over (\d+) months than at the typical rate",
     lambda m: f"unos {m.group(1)} {'más' if m.group(2) == 'more' else 'menos'} en {m.group(3)} meses que con la "
               "tasa típica"),
    (r"about the same as at the typical rate over (\d+) months",
     r"más o menos lo mismo que con la tasa típica en \1 meses"),
    (r"([\d,]+) loans in the data are like mine", r"\1 préstamos de los datos se parecen al mío"),
    (rf"real loans up to ((?:{_MON}) \d{{4}}); rates adjusted to the ((?:{_MON}) \d{{4}}) Treasury average\.",
     r"préstamos reales hasta \1; tasas ajustadas al promedio del Tesoro de \2."),
    (rf"Similar loans to mine mostly got ({_PCT}) to ({_PCT}), typical ({_PCT})\. Can you get closer to ({_PCT})\?",
     r"Los préstamos similares al mío obtuvieron sobre todo de \1 a \2, típica \3. ¿Pueden acercarse a \4?"),
    (rf"I'd like to compare the APR and the total I'd pay: ({_USD}) over (\d+) months at ({_PCT}), against ({_USD}) "
     rf"at the typical ({_PCT})\.",
     r"Quisiera comparar el APR y el total que pagaría: \1 en \2 meses al \3, frente a \4 con la tasa típica de \5."),
    (rf"Hello\. I'm buying a (\d{{4}}) (used|new) car for ({_USD}) and want to finance ({_USD}) over (\d+) months\. "
     r"Could you send me your APR for this loan in writing, with any fees and add-ons listed separately\? I'm "
     r"comparing written offers before I sign\.",
     lambda m: (f"Hola. Voy a comprar un auto {'usado' if m.group(2) == 'used' else 'nuevo'} {m.group(1)} por "
                f"{m.group(3)} y quiero financiar {m.group(4)} en {m.group(5)} meses. ¿Me podrían enviar por escrito "
                "su APR para este préstamo, con las comisiones y los productos adicionales por separado? Estoy "
                "comparando ofertas por escrito antes de firmar.")),
    (rf"Newest loans in our data: ((?:{_MON}) \d{{4}}), (\d+) months? before this check\.",
     lambda m: f"Préstamos más recientes en nuestros datos: {m.group(1)}, {m.group(2)} "
               f"{'mes' if m.group(2) == '1' else 'meses'} antes de esta revisión."),
    (rf"Newest loans in our data: ((?:{_MON}) \d{{4}})\.", r"Préstamos más recientes en nuestros datos: \1."),
    (rf"Your offer is compared after adjusting for the ((?:{_MON}) \d{{4}}) Treasury rate\.",
     r"Tu oferta se compara tras ajustar por la tasa del Tesoro de \1."),
    (r"Rates may have moved since; the checks below show how much that could matter\.",
     r"Las tasas pueden haber cambiado desde entonces; las pruebas de abajo muestran cuánto podría importar."),
    (r"Checked with MarkupCheck on ([^.<]+? \d{1,2}, \d{4})\. MarkupCheck is a student prototype, not financial "
     r"advice\.",
     lambda m: (f"Revisado con MarkupCheck el {_date_es(m.group(1))}. MarkupCheck es un prototipo estudiantil, no "
                "asesoramiento financiero.")),
    (rf"We can't tell for one loan\. Your ({_PCT}) is rated (<strong>[^<]*</strong>) next to similar loans \(most got "
     rf"({_PCT}) to ({_PCT})\)\. A price above the range can come from a dealer markup or from risk the data can't "
     r"see, so ask for the buy rate\.",
     r"No podemos saberlo con un solo préstamo. Tu tasa de \1 se califica como \2 frente a préstamos similares (la "
     r"mayoría obtuvo de \3 a \4). Un precio por encima del rango puede venir de un recargo del concesionario o de "
     r"un riesgo que los datos no ven, así que pide la tasa de compra (buy rate)."),
    (rf"About ({_USD}) for every percentage point over (\d+) months\. At the typical ({_PCT}) you'd pay ({_USD}) a "
     r"month\.",
     r"Unos \1 por cada punto porcentual en \2 meses. Con la tasa típica de \3 pagarías \4 al mes."),
    (r"Compared with a typical loan in the data, ([^<]*?)\.(?=<)", _why),
    (r"([\d,]+) loans in the data are like yours", r"\1 préstamos de los datos se parecen al tuyo"),
    (r"The verdict holds in (\d+) of (\d+) checks", r"El veredicto se mantiene en \1 de \2 pruebas"),
    (r"the verdict holds in (\d+) of (\d+) checks", r"el veredicto se mantiene en \1 de \2 pruebas"),
    (r"The range held for (\d+)% of similar buyers in our test",
     r"El rango se cumplió para el \1% de los compradores similares en nuestra prueba"),
    (r"the range held for (\d+)% of similar buyers in our test",
     r"el rango se cumplió para el \1% de los compradores similares en nuestra prueba"),
    # inputs.py and app._prepare (validation)
    (r"Enter your credit score \(a number from (\d+) to (\d+)\)\.",
     r"Escribe tu puntaje de crédito (un número de \1 a \2)."),
    (r"Credit scores are whole numbers from (\d+) to (\d+)\.", r"Los puntajes de crédito son números enteros de \1 a \2."),
    (r"The model year should be a year from (\d+) on, like 2019\.",
     r"El año del modelo debe ser \1 o posterior, como 2019."),
    (r"A (\d+) model year is in the future\. Check the year on the window sticker or contract\.",
     r"Un modelo del año \1 es del futuro. Revisa el año en la etiqueta de la ventana o en el contrato."),
    *_offer_variant(r"Enter the loan term in months, for example (\d+)\.",
                    r"Escribe el plazo del préstamo en meses, por ejemplo \1."),
    *_offer_variant(r"The loan term should be a whole number of months from (\d+) to (\d+)\.",
                    r"El plazo debe ser un número entero de meses de \1 a \2."),
    *_offer_variant(r"Enter the APR you were offered \(for example ([\d.]+)\), or the monthly payment\.",
                    r"Escribe la APR que te ofrecieron (por ejemplo \1), o el pago mensual."),
    *_offer_variant(r"The APR must be more than 0%\. A 0% rate is usually a carmaker promotion, which this tool can't "
                    r"compare\.",
                    "La APR debe ser mayor que 0%. Una tasa de 0% suele ser una promoción del fabricante, que esta "
                    "herramienta no puede comparar."),
    *_offer_variant(r"An APR of ([^<]*?)% is above (\d+)%, which is outside what this tool covers\. Check that you "
                    r"typed the APR, not the payment or the price\.",
                    r"Una APR de \1% está por encima de \2%, fuera de lo que cubre esta herramienta. Revisa que "
                    r"escribiste la APR, no el pago ni el precio."),
    (rf"A ({_USD}) payment doesn't fit ({_USD}) over (\d+) months at any APR from 0% to 60%\. Check the payment, "
     r"amount and term\.",
     r"Un pago de \1 no corresponde a \2 en \3 meses con ninguna APR de 0% a 60%. Revisa el pago, el monto y el "
     r"plazo."),
    # tabs.py: compare
    (rf"(?:(?<=>)|(?<=\. ))([^<>]*?) costs <strong>({_USD}) less</strong> in interest than ([^<>]*?)\.(?=\s|<)",
     r"\1 cuesta <strong>\2 menos</strong> en intereses que \3."),
    (r"(?:(?<=>)|(?<=\. ))([^<>]*?) and ([^<>]*?) cost about the same in interest\.",
     r"\1 y \2 cuestan casi lo mismo en intereses."),
    (rf"Total interest is what you pay on top of the ({_USD}) you borrow, if you make every payment on time\.",
     r"El interés total es lo que pagas además de los \1 que pides prestados, si haces cada pago a tiempo."),
    # tabs.py: refinance
    (r"Your current APR should be from 0% to (\d+)%\.", r"Tu APR actual debe estar entre 0% y \1%."),
    (r"Months left should be a whole number from 1 to (\d+)\.",
     r"Los meses que quedan deben ser un número entero de 1 a \1."),
    (rf"Your current APR of <strong>({_PCT})</strong>, compared with similar loans: ",
     r"Tu APR actual de <strong>\1</strong>, comparada con préstamos similares: "),
    (rf"Similar used-car loans typically got <strong>({_PCT})</strong>, and most got between ({_PCT}) and ({_PCT})\. "
     r"Your APR is higher than ((?:over |under )?\d+%) of them\.",
     lambda m: (f"Los préstamos similares de autos usados obtuvieron normalmente <strong>{m.group(1)}</strong>, y la "
                f"mayoría entre {m.group(2)} y {m.group(3)}. Tu APR es más alta que la "
                f"{_SHARE_ART(m.group(4))}{_SHARE(m.group(4))} de ellos.")),
    (rf"At ({_PCT}), paying off ({_USD}) over (\d+) (months?) works out to about ({_USD}) a month\.",
     lambda m: (f"Al {m.group(1)}, pagar {m.group(2)} en {_months(m.group(3), m.group(4))} sale a unos "
                f"{m.group(5)} al mes.")),
    (r">Over (\d+) (months?)<", lambda m: f">En {_months(m.group(1), m.group(2))}<"),
    (rf"You'd save ({_USD})", r"Ahorrarías \1"),
    (rf"You'd pay ({_USD}) more", r"Pagarías \1 más"),
    (rf"You left the car's value blank, so we assumed it is worth what you owe, ({_USD})\.",
     r"Dejaste en blanco el valor del auto, así que supusimos que vale lo que debes, \1."),
    (r"Loans in our data run at least (\d+) months, so we compared your rate with (\d+)-month loans\. The payments "
     r"above still use your (\d+) (months?) left\.",
     lambda m: (f"Los préstamos de nuestros datos duran al menos {m.group(1)} meses, así que comparamos tu tasa con "
                f"préstamos de {m.group(2)} meses. Los pagos de arriba siguen usando "
                + ("el 1 mes que te queda." if m.group(4) == "month" else f"los {m.group(3)} meses que te quedan."))),
    # tabs.py: batch
    (r"We checked <strong>(\d+)</strong> (rows?)\.",
     lambda m: f"Revisamos <strong>{m.group(1)}</strong> {'fila' if m.group(2) == 'row' else 'filas'}."),
    (r" Your file has more than (\d+) rows, so we checked the first (\d+)\. The results file has only those rows\.",
     r" Tu archivo tiene más de \1 filas, así que revisamos las primeras \2. El archivo de resultados solo tiene "
     r"esas filas."),
    (r">First (\d+) rows<", r">Primeras \1 filas<"),
    (r"The first row must name the columns\. These are missing: ((?:<code>[^<]*</code>(?:, )?)+)\. The template "
     r"shows them all\.",
     r"La primera fila debe tener los nombres de las columnas. Faltan estas: \1. La plantilla las muestra todas."),
    # explore.py
    (r"(\d+) of (\d+) states with enough loans still show a gap after a correction for testing many states at once "
     r"\(solid outline\); the rest could be chance \(dashed outline\)\.",
     r"\1 de \2 estados con suficientes préstamos siguen mostrando una diferencia tras una corrección por probar "
     r"muchos estados a la vez (borde sólido); el resto podría ser azar (borde punteado)."),
    (r">([+−]?[\d.]+) to ([+−]?[\d.]+)<", r">\1 a \2<"),
    (r"None of the lenders made at least (\d+) loans a month for ([^<]*?)\. Try another credit tier\.",
     lambda m: (f"Ninguno de los prestamistas hizo al menos {m.group(1)} préstamos al mes para "
                f"{_tier_label(m.group(2))}. Prueba otro nivel de crédito.")),
    (r"The median APR each month for ([^<]*?), by lender, from the loans in our data \(([^)<]*) to ([^)<]*)\)\. "
     r"Months with fewer than (\d+) loans are left out\.",
     lambda m: (f"La APR mediana de cada mes para {_tier_label(m.group(1))}, por prestamista, con los préstamos de "
                f"nuestros datos ({m.group(2)} a {m.group(3)}). Se omiten los meses con menos de {m.group(4)} "
                "préstamos.")),
    # charts.py: distribution
    (rf"80% of similar loans have an APR between ({_PCT}) and ({_PCT})\.",
     r"El 80% de los préstamos similares tiene una APR entre \1 y \2."),
    (rf"The typical APR is ({_PCT})\.", r"La APR típica es \1."),
    (rf"Your offer is (?P<o>{_PCT})(?:, (?P<where>below|above|inside) that range)?"
     r"(?:(?P<same>, the same as the typical APR)|, (?P<gap>[\d.]+) points (?P<side>above|below) the typical APR)?\.",
     _distribution_offer),
    (rf"80% range: ({_PCT}) to ({_PCT})", r"Rango 80%: \1 a \2"),
    # charts.py: interest timeline
    (rf"(Your offer|Typical|Credit-union average|Loan \d+): ({_USD}) after (\d+) (months?)\.",
     lambda m: f"{_series(m.group(1))}: {m.group(2)} después de {_months(m.group(3), m.group(4))}."),
    (rf"Your offer costs ({_USD}) (more|less) in interest than ([^<.]+?)\.(?=\s|<)",
     lambda m: (f"Tu oferta cuesta {m.group(1)} {'más' if m.group(2) == 'more' else 'menos'} en intereses que "
                f"{_series(m.group(3), _SERIES_OBJ)}.")),
    # charts.py: tracker
    (rf"(Median|Typical) APR by month, ({_ABBR}) (\d{{4}}) to ({_ABBR}) (\d{{4}})\. ",
     lambda m: (f"APR {'mediana' if m.group(1) == 'Median' else 'típica'} por mes, de {_ABBR_FULL[m.group(2)]} de "
                f"{m.group(3)} a {_ABBR_FULL[m.group(4)]} de {m.group(5)}. ")),
    (r"(Median|Typical) APR by month", lambda m: f"APR {'mediana' if m.group(1) == 'Median' else 'típica'} por mes"),
    (rf"(?P<name>[^.<:>]+?): (?P<p1>{_PCT}) in (?P<m1>{_ABBR}) (?P<y1>\d{{4}})"
     rf"(?:, (?P<p2>{_PCT}) in (?P<m2>{_ABBR}) (?P<y2>\d{{4}}))?"
     rf"(?:; lowest (?P<lo>{_PCT}), highest (?P<hi>{_PCT}))?(?:; (?P<gaps>\d+) (?P<mw>months?) without data)?\.",
     _tracker_desc),
    # charts.py: tile map
    (rf"({_STATE}): about the same as similar loans \((holds up|could be chance)\)",
     lambda m: (f"{_STATES[m.group(1)]}: casi igual que préstamos similares "
                f"({'se sostiene' if m.group(2) == 'holds up' else 'podría ser azar'})")),
    (rf"({_STATE}): pays ([\d.]+) points (more|less) than similar loans \((holds up|could be chance)\)",
     lambda m: (f"{_STATES[m.group(1)]}: paga {m.group(2)} puntos {'más' if m.group(3) == 'more' else 'menos'} que "
                f"préstamos similares ({'se sostiene' if m.group(4) == 'holds up' else 'podría ser azar'})")),
    (rf"({_STATE}): no data", lambda m: f"{_STATES[m.group(1)]}: sin datos"),
    (r"APR gap versus similar loans, in points, for (\d+) of 51 states and DC; (\d+) hold up after a "
     r"multiple-testing check\.",
     r"Diferencia de APR frente a préstamos similares, en puntos, para \1 de los 51 estados y DC; \2 se sostienen "
     r"tras una corrección por pruebas múltiples."),
    (r"Largest confirmed gaps where buyers pay (more|less): ([^<]*?)\.(?=\s|<|$)",
     lambda m: (f"Mayores diferencias confirmadas donde los compradores pagan "
                f"{'más' if m.group(1) == 'more' else 'menos'}: "
                f"{re.sub(_STATE, lambda s: _STATES[s.group(0)], m.group(2))}.")),
    (r"No confirmed gaps where buyers pay (more|less)\.",
     lambda m: f"No hay diferencias confirmadas donde los compradores pagan {'más' if m.group(1) == 'more' else 'menos'}."),
    (r" (\d+) have no data\.", r" \1 no tienen datos."),
    # charts.py: waterfall (labels in <tspan>, tooltips and the description)
    (rf"(<tspan[^>]*>)({_WF_RX})(</tspan>)", lambda m: m.group(1) + _wf(m.group(2)) + m.group(3)),
    (rf"({_WF_RX}): ([+−]?[\d.]+) points", lambda m: f"{_wf(m.group(1))}: {m.group(2)} puntos"),
    (rf"({_WF_RX}): ({_PCT})", lambda m: f"{_wf(m.group(1))}: {m.group(2)}"),
    (r"The scale starts at ([\d.]+%), not zero\.", r"La escala empieza en \1, no en cero."),
    # Generic last: "You entered 950." after every message that starts with it.
    (r"You entered ([^<]*?)\.(?=\s|<|$)", r"Escribiste \1."),
])

# After the sentences and the text-node pass: short patterns that would otherwise break the sentence rules.
LATE = _rules([
    (rf"\bTypical \(({_PCT})\)", r"Típica (\1)"),
    (rf"\bYour offer \(({_PCT})\)", r"Tu oferta (\1)"),
    (rf"\bTypical ({_PCT}|{_USD})", r"Típica \1"),
    (rf"\bYour offer ({_PCT}|{_USD})", r"Tu oferta \1"),
    (rf"\bCredit-union average ({_USD})", r"Cooperativa media \1"),
    (r"\b(Your offer|Typical|Credit-union average) paid off(?=,|<)", lambda m: f"{_series(m.group(1))} (ya pagado)"),
    (r"\b(Your offer|Typical|Credit-union average) no data(?=,|<)", lambda m: f"{_series(m.group(1))} sin datos"),
    (r"\bMonth (\d+): ", r"Mes \1: "),
    (r" no data(?=,|<|$)", " sin datos"),
    (r">(\d+) mo<", r">\1 m<"),
    (r"\b1 month\b", "1 mes"),
    (r"\b(\d+) months\b", r"\1 meses"),
    (r">([\d,]+) loans<", r">\1 préstamos<"),
    (r"\bOffer (\d+)\b", r"Oferta \1"),
])
SVG_LATE = _rules([(rf"\b({_ABBR}) (\d{{4}})\b", lambda m: f"{_MONTHS_ABBR[m.group(1)]} {m.group(2)}")])
DATES = _rules([
    (rf"\b({_MON}) (\d{{1,2}}), (\d{{4}})\b", lambda m: _date_es(m.group(0))),
    (rf"\b({_MON}) (\d{{4}})\b", lambda m: _date_es(m.group(0))),
])

_PHRASE_RX = re.compile("|".join(re.escape(k) for k in sorted(PHRASES, key=len, reverse=True)))
_TAG = re.compile(r"(<[^>]*>)")
_SVG = re.compile(r"<svg\b.*?</svg>", re.S)
_ATTR = re.compile(r"""\b(aria-label|aria-valuetext|title)=("[^"]*"|'[^']*')""")
_INVALID = re.compile(r'data-invalid="([^"]*)"')
_WHATIF = re.compile(r'data-whatif="([^"]*)"')


def _apply(rules, text: str) -> str:
    for rx, repl in rules:
        text = rx.sub(repl, text)
    return text


def _normalize(markup: str) -> str:
    """html.escape writes ' and " as entities in text nodes; plain characters there mean the same and let the
    rules match. Tags are left alone, so a quote inside an attribute stays escaped."""
    parts = _TAG.split(markup)
    for i in range(0, len(parts), 2):
        parts[i] = parts[i].replace("&#x27;", "'").replace("&quot;", '"')
    return "".join(parts)


def _word(text: str) -> str:
    core = text.strip()
    if not core:
        return text
    spanish = WORDS.get(core, STATIC.get(core))
    if spanish is None:
        return text
    start = text.index(core)
    return text[:start] + spanish + text[start + len(core):]


def _attr(m) -> str:
    quote, value = m.group(2)[0], m.group(2)[1:-1]
    plain = html.unescape(value)
    spanish = _word(plain)
    if spanish == plain:
        return m.group(0)
    return f"{m.group(1)}={quote}{html.escape(spanish, quote=True)}{quote}"


def _text_nodes(markup: str) -> str:
    parts = _TAG.split(markup)
    for i, part in enumerate(parts):
        parts[i] = _ATTR.sub(_attr, part) if i % 2 else _word(part)
    return "".join(parts)


def _invalid(m) -> str:
    fields = html.unescape(m.group(1)).split("|")
    return 'data-invalid="' + html.escape("|".join(t(f, "es") if f else f for f in fields), quote=True) + '"'


def _whatif(m) -> str:
    try:
        data = json.loads(html.unescape(m.group(1)))
    except ValueError:
        return m.group(0)
    if isinstance(data, dict) and isinstance(data.get("labels"), dict):
        data["labels"] = {k: _CHIPS.get(v, v) for k, v in data["labels"].items()}
    # ensure_ascii=False: "í" escapes would add digits to the attribute and read worse.
    return 'data-whatif="' + html.escape(json.dumps(data, ensure_ascii=False), quote=True) + '"'


def translate_html(markup: str, lang: str) -> str:
    """A rendered result panel (or any static gr.HTML block) in `lang`."""
    if lang == "en" or not markup:
        return markup
    if markup in STATIC:
        return STATIC[markup]
    out = _normalize(markup)
    out = _WHATIF.sub(_whatif, out)
    out = _INVALID.sub(_invalid, out)
    out = _apply(RULES, out)
    out = _PHRASE_RX.sub(lambda m: PHRASES[m.group(0)], out)
    out = _text_nodes(out)
    out = _apply(LATE, out)
    out = _SVG.sub(lambda m: _apply(SVG_LATE, m.group(0)), out)
    out = _apply(DATES, out)
    return out
