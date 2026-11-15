"""Checks for i18n.py: every rendered result and every fixed UI string has a complete Spanish version.
Run: .venv/bin/python app/test_i18n.py (also works under pytest). Needs the trained model in app/model/.
"""

import collections
import datetime
import html
import json
import os
import re
import shutil
import sys
import tempfile
from html.parser import HTMLParser

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)

import app  # noqa: E402
import gradio as gr  # noqa: E402
import charts  # noqa: E402
import explore  # noqa: E402
import finance  # noqa: E402
import i18n  # noqa: E402
import markupcheck_model  # noqa: E402
import tabs  # noqa: E402

TEMPLATE = os.path.join(APP_DIR, "batch_template.csv")
HEADER = "credit_score,new_or_used,model_year,vehicle_price,amount_financed,term_months,apr,lender"
SAM_PROFILE = (760, "used", 2022, 24000, 25000)
EM_DASH = "\u2014"
DISCLAIMER_ES = "Este proyecto es un prototipo y no es asesoramiento financiero."

# Names and identifiers that stay in English on the Spanish page (proper names, user input, CSV column names).
ALLOWED = ("CarMax Auto Finance", "FICO Auto Score", "Santander Consumer", "Toyota Financial Services",
           "American Honda Finance", "Hyundai Capital America", "Nissan Motor Acceptance", "Ford Credit",
           "GM Financial", "Capital One", "Chrysler Capital", "Some Credit Union", "S&P Global",
           "Hugging Face", "Google Sheets", "VantageScore", "MarkupCheck", "AdmitPath", "Gradio", "CarMax",
           "Santander", "Ally", "NCUA", "SEC", "FICO", "GAP", "Excel", "Rhode Island", "(buy rate)",
           "typical_apr, range_low, range_high, percentile, verdict", '"new"', '"used"')
# The brief's stop-list (matched on the text padded with spaces) ...
STOP = (" the ", " and ", " your ", " you ", " loans ", " similar ", " typical ", " with ", " than ", " this ",
        " from ", " over ", " months", " rate ", " payment ", "What ", "How ", "Why ", "Your ", "Typical",
        "Credit score", " of ", " is ", " are ", " to ", " for ", " in ", " on ", " at ", "Offer", "Month ",
        " no data", " mo ", " points")
# ... and whole English words that are never Spanish words (Spanish ones such as "no", "total" or "final" are out).
ENGLISH = set("""
the and your you yours loan loans similar typical with than this that these those from over month months rate
rates payment payments what how why of is are to for in on at by it its we our they them be was were have can
could would should will if or not about more less lower higher above below inside offer offers lender lenders
credit score scores car cars used new data check checks checked points point year years average interest enter
choose please ask high well which each every any all some there here only also after before between most when
where who into out up down per such as an then show shows compared versus vs gap gaps state states row rows
file verdict chance holds outline dashed solid mo jan aug dec january february march april june july august
september october november december monthly term terms amount financed price add ons optional dealer union
unions bank banks buy get got pay paid save much many few same other next own my result results try example
fair cheapest keep mind left value worth owe still now current already see tell know part risk markup marked
deals filed prices removing treasury combined effects detail details step steps scale starts zero curve common
spread shaded sits median tier range placeholder numbers stub reason take print copy link questions question
borrowing typically cost costs because without lowest highest largest confirmed pays chance
""".split())

_OUTPUTS = {}
_TEMP_PATHS = []


def _scratch_csv(text: str = None, data: bytes = None) -> str:
    path = os.path.join(tempfile.mkdtemp(prefix="test_i18n_"), "upload.csv")
    with open(path, "wb") as f:
        f.write(data if data is not None else text.encode("utf-8"))
    _TEMP_PATHS.append(path)
    return path


def _batch(src):
    out, path = tabs.batch_check(src)
    if path:
        _TEMP_PATHS.append(path)
    return out


def _jordan(**changes):
    keys = ("score", "kind", "year", "price", "financed", "term", "apr", "lender", "payment", "addons")
    values = dict(zip(keys, (*app.jordan_example(), "", "")))
    values.update(changes)
    return tuple(values[k] for k in keys)


def outputs() -> dict:
    """Every English output the Spanish page can show, rendered by the real code with the trained model."""
    if _OUTPUTS:
        return _OUTPUTS
    o = _OUTPUTS
    # Main check
    o["jordan"] = app.check_offer(*app.jordan_example(), "", "")
    o["sam"] = app.check_offer(*app.sam_example(), "", "")
    o["sam_santander"] = app.check_offer(*app.sam_example()[:7], "Santander", "", "")
    o["unknown_lender"] = app.check_offer(*_jordan(lender="Some Credit Union"))
    o["new_2019_90_chrysler"] = app.check_offer(700, "new", 2019, 30000, 32000, 90, 9.9, "Chrysler Capital", "", "")
    o["payment_only"] = app.check_offer(*_jordan(apr="", payment="400.28"))
    o["payment_above_apr"] = app.check_offer(*_jordan(apr=15.9, payment="440.28"))
    o["payment_matches_apr"] = app.check_offer(*_jordan(apr=15.9, payment="400.28"))
    o["payment_below_apr"] = app.check_offer(*_jordan(apr=15.9, payment="300"))
    o["addons"] = app.check_offer(*_jordan(addons="2500"))
    o["err_score_950"] = app.check_offer(*_jordan(score=950))
    o["err_all_blank"] = app.check_offer("", None, "", "", "", "", "", "", "", "")
    o["err_apr_45"] = app.check_offer(*_jordan(apr=45))
    o["err_addons_above_amount"] = app.check_offer(*_jordan(addons="20000"))
    o["err_apr_0"] = app.check_offer(*_jordan(apr=0))
    o["err_year_old"] = app.check_offer(*_jordan(year=1950))
    o["err_year_future"] = app.check_offer(*_jordan(year=datetime.date.today().year + 2))
    o["err_term_100"] = app.check_offer(*_jordan(term=100))
    o["err_payment_text"] = app.check_offer(*_jordan(payment="abc", addons="-5"))
    o["err_payment_fits_no_apr"] = app.check_offer(*_jordan(apr="", payment="10"))
    o["err_server"] = app.render_errors([(None, "Something went wrong on our side, not with your entries. They are "
                                                "still in the form, so press Check my rate to try again.")],
                                        heading="We couldn't check this offer", ref="ab12cd34")
    o["empty"] = app.render_empty()
    o["same_lender_table"] = app._same_lender({"lender": "Ally", "typical_pct": 9.1, "difference_pts": -0.4,
                                               "n_loans": 65372}, "Ally")
    o["same_lender_missing"] = app._same_lender(None, "Some Credit Union")
    o["verdict_high"] = app.check_offer(*_jordan(apr=26))
    o["at_credit_union_rate"] = app.check_offer(*_jordan(apr=markupcheck_model.predict(
        app._prepare(*_jordan())[0])["credit_union"]["credit_union_pct"]))
    o["financed_below_price"] = app.check_offer(700, "new", 2026, 32000, 30000, 60, 7.5, "Ally", "", "")
    # An APR within a few cents of the typical one over the loan: "That's about the same as the typical APR".
    offer, _, _, _, _ = app._prepare(*_jordan())
    first = markupcheck_model.predict(offer, detail=False)
    per_point = finance.cost_per_point(offer["amount_financed"], first["typical_pct"], offer["term_months"])
    typical = first["typical_pct"] - (markupcheck_model.predict({**offer, "offered_apr_pct": first["typical_pct"]},
                                                                detail=False)["extra_cost_usd"] / per_point)
    o["at_typical_apr"] = app.check_offer(*_jordan(apr=f"{typical:.4f}"))
    o["rare_inputs"] = app.check_offer(300, "new", 2010, 150000, 250000, 96, 3.0, "", "", "")
    o["same_lender_higher"] = app._same_lender({"lender": "Santander Consumer", "typical_pct": 14.4,
                                                "difference_pts": 5.6, "n_loans": 157201}, "Santander")
    original, extras = markupcheck_model.predict, markupcheck_model._load().get("extras")
    markupcheck_model.predict = lambda offer, detail=True: markupcheck_model._stub(offer)
    try:
        o["stub"] = app.check_offer(*app.jordan_example(), "", "")
        o["stub_compare"] = tabs.compare_offers(*SAM_PROFILE, [("", "15", "60"), ("", "9", "60")])
    finally:
        markupcheck_model.predict = original
    markupcheck_model._CACHE["extras"] = None  # model files without src/build_extras.py output
    try:
        o["no_extras"] = app.check_offer(*app.jordan_example(), "", "")
        o["no_extras_lender"] = app.check_offer(*app.sam_example()[:7], "Ally", "", "")
        o["no_extras_states"] = explore.states_html()
        o["no_extras_tracker"] = explore.tracker_html("prime", "used")
    finally:
        markupcheck_model._CACHE["extras"] = extras

    def broken(offer, detail=True):
        raise RuntimeError("test")
    markupcheck_model.predict = broken
    try:
        o["batch_server_error"] = _batch(TEMPLATE)
    finally:
        markupcheck_model.predict = original
    # Chart edge cases the result pages can reach: no data, and lines of different lengths.
    o["charts_empty"] = "".join([
        charts.distribution_svg([], None, None, None, None, "e1"), charts.timeline_svg([], "e2"),
        charts.tracker_svg([], [], "e3", y_label="Median APR"), charts.waterfall_svg("Start", None, [], "End", None, "e4"),
        charts.tile_map_svg({}, "e5", "")])
    o["chart_paid_off"] = charts.timeline_svg([("Your offer", [10.0, 20.0, 30.0]), ("Typical", [12.0, None])], "p1",
                                              highlight="Your offer")
    # Compare offers
    o["compare_terms_differ"] = tabs.compare_offers(*SAM_PROFILE, [("", "15.0", "60"), ("", "9.0", "60"),
                                                                    ("", "12%", "72")])
    o["compare_named"] = tabs.compare_offers(*SAM_PROFILE, [("Concesionario", "15.0", "60"), ("Cooperativa", "6.5", "60"),
                                                             None])
    o["compare_same_cost"] = tabs.compare_offers(*SAM_PROFILE, [("", "9", "60"), ("", "9", "60")])
    o["compare_err_fields"] = tabs.compare_offers(*SAM_PROFILE, [("A", "15", "60"), ("B", "", "60"), ("C", "12", "")])
    o["compare_err_profile"] = tabs.compare_offers(950, "used", 2022, 24000, 25000, [("A", "15", "60"), ("B", "9", "60")])
    o["compare_err_too_few"] = tabs.compare_offers(*SAM_PROFILE, [])
    o["compare_err_apr"] = tabs.compare_offers(*SAM_PROFILE, [("A", "15", "60"), ("B", "45", "60"), ("C", "0", "100")])
    # Refinance
    o["refi"] = tabs.refinance_check("700", "2020", "$15,000", "14.5%", "40", "16,000")
    o["refi_pays_more"] = tabs.refinance_check("700", "2020", "15000", "3.0", "40", "")
    o["refi_short"] = tabs.refinance_check("700", "2020", "5000", "14.5", "6", "7000")
    o["refi_one_month"] = tabs.refinance_check("700", "2020", "5000", "14.5", "1", "7000")
    o["refi_err"] = tabs.refinance_check("950", "", "800", "45", "0", "-5")
    o["refi_err_blank"] = tabs.refinance_check("", "", "", "", "", "")
    o["refi_offered"] = tabs.refinance_check("700", "2020", "15000", "14.5", "40", "", "9.5")
    o["refi_offered_err"] = tabs.refinance_check("700", "2020", "15000", "14.5", "40", "", "abc")
    # Contract box check
    o["tila_ok"] = tabs.contract_box_check("18500", "10320.24", "28820.24", "72", "15.9")
    o["tila_apr_off"] = tabs.contract_box_check("18500", "10320.24", "28820.24", "72", "13.9")
    o["tila_sum_off"] = tabs.contract_box_check("18500", "9000", "28820.24", "72", "15.9")
    o["tila_impossible"] = tabs.contract_box_check("18500", "0", "100", "72", "15.9")
    o["tila_err"] = tabs.contract_box_check("", "-1", "x", "0", "99")
    # Batch check
    o["batch_template"] = _batch(TEMPLATE)
    o["batch_row_errors"] = _batch(_scratch_csv(
        " Credit_Score , NEW_OR_USED,Model_Year,vehicle_price,amount_financed,term_months, APR \n"
        "950,used,2019,17500,18500,72,15.9\n760,used,2022,$24,000,25000,60,15.0\n"
        "760,used,2022,\"$24,000\",25000,60,15.0\n"))
    o["batch_one_row"] = _batch(_scratch_csv(HEADER + "\n660,used,2019,17500,18500,72,15.9,\n"))
    o["batch_capped"] = _batch(_scratch_csv(HEADER + "\n" + "660,used,2019,17500,18500,72,15.9,\n" * 501))
    o["batch_missing_columns"] = _batch(_scratch_csv("credit_score,new_or_used,vehicle_price\n660,used,17500\n"))
    o["batch_unreadable"] = _batch(_scratch_csv(data=bytes(range(256)) * 40))
    o["batch_empty"] = _batch(_scratch_csv(data=b""))
    o["batch_header_only"] = _batch(_scratch_csv(HEADER + "\n"))
    o["batch_no_file"] = _batch(None)
    o["batch_choose_first"] = "<div class='mc-result'><p class='mc-note'>Choose a CSV file first.</p></div>"
    # Explore the data
    o["states"] = explore.states_html()
    for tier in explore.TIER_LABELS:
        for kind in ("used", "new"):
            o[f"tracker_{tier}_{kind}"] = explore.tracker_html(tier, kind)
    for path in _TEMP_PATHS:
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)
    return o


def static_strings() -> list:
    """Every fixed string on the page: labels, info lines, placeholders, buttons, tabs, choices, HTML blocks."""
    found = [app.TITLE, app.DESCRIPTION, app.DISCLAIMER, app.API_DOCS, "Link copied.",
             re.search(r"content:'([^']*)'", app.HEAD).group(1)]
    for block in app.demo.blocks.values():
        kind = type(block).__name__
        if kind in ("Api", "State"):
            continue
        for attr in ("label", "info", "placeholder"):
            value = getattr(block, attr, None)
            if isinstance(value, str) and value:
                found.append(value)
        if kind in ("Button", "HTML") and isinstance(block.value, str) and block.value:
            found.append(block.value)
        for choice in getattr(block, "choices", None) or []:
            found.append(choice[0] if isinstance(choice, (list, tuple)) else choice)
    return list(dict.fromkeys(found))


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.text, self.skip = collections.Counter(), [], 0

    def handle_starttag(self, tag, attrs):
        self.tags["<" + tag] += 1
        if tag in ("pre", "code"):
            self.skip += 1
        for name, value in attrs:
            if name in ("aria-label", "aria-valuetext", "title") and value:
                self.text.append(value)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.tags["<" + tag] -= 1
        self.tags["<" + tag + "/>"] += 1

    def handle_endtag(self, tag):
        self.tags["</" + tag] += 1
        if tag in ("pre", "code"):
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.text.append(data)


def _parse(markup: str) -> _Tags:
    parser = _Tags()
    parser.feed(markup)
    parser.close()
    return parser


def _numbers(markup: str) -> collections.Counter:
    # Trailing sentence punctuation is dropped: "November 15, 2026" becomes "15 de noviembre de 2026", which is
    # the only place a number moves next to different punctuation.
    return collections.Counter(n.rstrip(".,") for n in re.findall(r"\d[\d,.]*", html.unescape(markup)))


def _leftovers(markup: str) -> list:
    """English left in the visible text and the aria-label / aria-valuetext / title attributes."""
    text = " ".join(" ".join(_parse(markup).text).split())
    for name in ALLOWED:
        text = text.replace(name, " ")
    padded = f" {text} "
    found = [s.strip() for s in STOP if s in padded]
    words = re.findall(r"(?<!\w)[A-Za-z]+(?!\w)", text)
    found += sorted({w for w in words if w.lower() in ENGLISH and not w.isupper()})  # IN, OR, MO: state codes
    if found:
        # Show where: the shortest text pieces that still contain an English word.
        pieces = [p for p in _parse(markup).text if any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", p) or
                                                         (w in p and " " in w) for w in found)]
        return found + ["in: " + " | ".join(dict.fromkeys(p.strip() for p in pieces))[:600]]
    return []


def test_outputs_translate_completely():
    problems = []
    for name, english in outputs().items():
        spanish = i18n.translate_html(english, "es")
        before, after = _parse(english), _parse(spanish)
        if before.tags != after.tags:
            problems.append(f"{name}: tags changed {dict((before.tags - after.tags) + (after.tags - before.tags))}")
        if _numbers(english) != _numbers(spanish):
            lost, added = _numbers(english) - _numbers(spanish), _numbers(spanish) - _numbers(english)
            problems.append(f"{name}: numbers changed, lost {dict(lost)}, added {dict(added)}")
        left = _leftovers(spanish)
        if left:
            problems.append(f"{name}: English left {left}")
        if EM_DASH in spanish:
            problems.append(f"{name}: em dash")
    assert not problems, "\n".join(problems)


def test_ids_classes_and_share_link_kept():
    english = outputs()["jordan"]
    spanish = i18n.translate_html(english, "es")
    for pattern in (r'\bid="[^"]*"', r"\bid='[^']*'", r'\bclass="[^"]*"', r"\bclass='[^']*'", r'data-share="[^"]*"'):
        assert re.findall(pattern, english) == re.findall(pattern, spanish), pattern


def test_whatif_labels_and_invalid_fields():
    spanish = i18n.translate_html(outputs()["jordan"], "es")
    raw = re.search(r'data-whatif="([^"]*)"', spanish).group(1)
    data = json.loads(html.unescape(raw))
    assert data["labels"] == {"typical": "Típica", "high": "Alta", "likely marked up": "Muy por encima"}, data["labels"]
    english_data = json.loads(html.unescape(re.search(r'data-whatif="([^"]*)"', outputs()["jordan"]).group(1)))
    assert {k: v for k, v in data.items() if k != "labels"} == {k: v for k, v in english_data.items() if k != "labels"}

    spanish = i18n.translate_html(outputs()["err_all_blank"], "es")
    fields = html.unescape(re.search(r'data-invalid="([^"]*)"', spanish).group(1)).split("|")
    english = html.unescape(re.search(r'data-invalid="([^"]*)"', outputs()["err_all_blank"]).group(1)).split("|")
    assert fields == [i18n.STATIC[f] for f in english], fields
    assert fields[0] == i18n.t(app.L_SCORE, "es") == "Puntaje de crédito"


def test_static_strings_all_translated():
    problems = []
    for text in static_strings():
        if text in i18n.STATIC:  # a few are the same in Spanish, e.g. "Prime (661–780)"
            spanish = i18n.t(text, "es")
        else:  # a result rendered into the page at build time (the empty panel, the explore tab)
            spanish = i18n.translate_html(text, "es")
        if spanish == text and text not in i18n.STATIC:
            problems.append(f"untranslated: {text[:80]!r}")
        left = _leftovers(spanish)
        if left:
            problems.append(f"{text[:60]!r}: English left {left}")
    for key, value in i18n.STATIC.items():
        if not value or EM_DASH in value:
            problems.append(f"bad value for {key[:60]!r}")
        if key.startswith("e.g. ") and _numbers(key) != _numbers(value):
            problems.append(f"number changed in {key!r}")
    assert not problems, "\n".join(problems)


def test_language_switch_relabels_every_component():
    """The switch relabels through app._localized (i18n.t), not translate_html, so check that exact path."""
    i18n.MISSES.clear()
    for block in app.demo.blocks.values():
        if isinstance(block, (gr.Textbox, gr.Radio, gr.Dropdown, gr.Button, gr.DownloadButton, gr.File, gr.Tab,
                              gr.Accordion)):
            app._localized(app._english_props(block), "es")
    assert not i18n.MISSES, sorted(i18n.MISSES)


def test_t_and_english_mode():
    for key, value in i18n.STATIC.items():
        assert i18n.t(key, "en") == key
        assert i18n.t(key, "es") == value and value
    for name, english in outputs().items():
        assert i18n.translate_html(english, "en") == english, name
    assert [code for _, code in i18n.LANGS] == ["en", "es"]


def test_misses_empty_after_everything():
    i18n.MISSES.clear()
    for english in outputs().values():
        i18n.translate_html(english, "es")
    for text in static_strings():
        if text in i18n.STATIC:
            i18n.t(text, "es")
        else:
            i18n.translate_html(text, "es")
    for label in (app.L_SCORE, app.L_KIND, app.L_YEAR, app.L_PRICE, app.L_FINANCED, app.L_TERM, app.L_APR,
                  app.L_LENDER, app.L_PAYMENT, app.L_ADDONS):
        i18n.t(label, "es")
    assert not i18n.MISSES, sorted(i18n.MISSES)
    i18n.t("A string nobody translated", "es")
    assert "A string nobody translated" in i18n.MISSES
    i18n.MISSES.clear()


def test_disclaimer_exact():
    assert i18n.t(app.DISCLAIMER, "es") == DISCLAIMER_ES
    assert i18n.t(tabs.DISCLAIMER, "es") == DISCLAIMER_ES
    assert i18n.t(f"<footer><p>{app.DISCLAIMER}</p></footer>", "es") == f"<footer><p>{DISCLAIMER_ES}</p></footer>"
    for name in ("jordan", "sam", "refi", "batch_template", "compare_named"):
        assert f'<p class="mc-disclaimer">{DISCLAIMER_ES}</p>' in i18n.translate_html(outputs()[name], "es"), name


def test_dates_in_spanish():
    spanish = i18n.translate_html(outputs()["jordan"], "es")
    d = datetime.date.today()
    months = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
              "noviembre", "diciembre"]
    assert f"Revisado con MarkupCheck el {d.day} de {months[d.month - 1]} de {d.year}." in spanish
    assert re.search(r"El \d{1,2} de [a-z]+ de \d{4}, las cooperativas de crédito", spanish), spanish
    tracker = i18n.translate_html(outputs()["tracker_prime_used"], "es")
    assert re.search(r"\(\d{4}-\d{2} a \d{4}-\d{2}\)", tracker)  # YYYY-MM codes stay as they are


def test_forward_line_across_two_years_in_spanish():
    f = {"lender": "CarMax", "loans": 1000, "months": "December 2026 to February 2027", "model_mae": 1.5,
         "rule_mae": 2.0, "coverage_pct": 70.0, "below_pct": 20.0}
    es = i18n.translate_html(app._forward_line(f), "es")
    assert "diciembre de 2026 a febrero de 2027" in es and "December" not in es and "newer loans" not in es


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # report every failure, then exit non-zero
            failed += 1
            print(f"FAIL {test.__name__}: {exc!r}"[:6000])
    print(f"{len(tests) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
