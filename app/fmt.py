"""Formatting shared by the app's pages: escaping, percents, dollars and the verdict names and chips."""
import html


def _esc(value) -> str:
    return html.escape(str(value))


def _pct(value: float) -> str:
    """APR as a percent with 1–2 decimals, e.g. 11.0%, 15.9%, 15.99%."""
    text = f"{float(value):.2f}".rstrip("0")
    if text.endswith("."):
        text += "0"
    return text + "%"


def _usd(value: float, cents: bool = False) -> str:
    return f"${abs(float(value)):,.2f}" if cents else f"${abs(float(value)):,.0f}"


FLAG_TEXT = {
    "typical": ("Typical", "mc-flag-typical", ""),
    "high": ("High", "mc-flag-high",
             "Ask for the buy rate and compare it with a second offer before you sign."),
    "likely marked up": ("Well above similar loans", "mc-flag-marked",
                         "Ask for the buy rate and get a second offer before you sign. A dealer markup is one "
                         "possible reason; risk the data can't see is another. In our repayment test, loans priced "
                         "above 90% of similar loans went on to be late or charged off more often, clearly at Santander "
                         "and Ally and only slightly at CarMax."),
}


def percentile_text(p: float) -> str:
    """The model's grid stops at its 5% and 95% points, so an APR beyond them is "over 95%" or "under 5%",
    not a made-up exact figure such as 98%."""
    p = float(p)
    return "over 95%" if p >= 97.5 else "under 5%" if p <= 2.5 else f"{p:.0f}%"


CHIP_TEXT = {"typical": "Typical", "high": "High", "likely marked up": "Well above"}  # short, so tables fit a phone


def _flag_chip(flag) -> str:
    css_class = FLAG_TEXT.get(str(flag), ("", "mc-flag-high", ""))[1]
    return f'<span class="mc-chip {css_class}">{_esc(CHIP_TEXT.get(str(flag), str(flag).capitalize()))}</span>'
