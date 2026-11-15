"""Checks for app.py. Run: .venv/bin/python app/test_app.py (also works under pytest)."""

import datetime
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app  # noqa: E402
import markupcheck_model  # noqa: E402

CONTRACT_INPUT_TYPES = {
    "credit_score": int,
    "new_or_used": str,
    "vehicle_model_year": int,
    "vehicle_price": float,
    "amount_financed": float,
    "term_months": int,
    "offered_apr_pct": float,
    "lender": (str, type(None)),
}


# The UI is tested against the contract stub, whatever state app/model/ is in.
STUB = markupcheck_model._stub


def _call_recording(*args):
    """Call the handler while recording every offer passed to predict() (answered by the stub)."""
    calls = []
    original = markupcheck_model.predict

    def recorder(offer):
        calls.append(dict(offer))
        return STUB(offer)

    markupcheck_model.predict = recorder
    try:
        out = app.check_offer(*args)
    finally:
        markupcheck_model.predict = original
    return out, calls


def test_jordan_button_values():
    assert app.jordan_example() == (660, "used", 2019, 17500, 18500, 72, 15.9, "")


def test_jordan_example_with_stub():
    out, calls = _call_recording(*app.jordan_example())
    assert isinstance(out, str) and out.strip()
    assert len(calls) == 1
    offer = calls[0]
    assert set(offer) == set(CONTRACT_INPUT_TYPES), sorted(offer)
    for key, kind in CONTRACT_INPUT_TYPES.items():
        assert isinstance(offer[key], kind), (key, type(offer[key]))
    assert offer == {"credit_score": 660, "new_or_used": "used", "vehicle_model_year": 2019,
                     "vehicle_price": 17500.0, "amount_financed": 18500.0, "term_months": 72,
                     "offered_apr_pct": 15.9, "lender": None}
    result = STUB(offer)
    assert result["stub"] is True
    assert "Placeholder numbers." in out
    assert "Your APR is higher than" in out and f"{result['percentile']:.0f}%" in out
    assert app.DISCLAIMER == "This project is a prototype and is not financial advice."
    assert app.DISCLAIMER in out
    for heading in ("Where your rate sits", "What it costs you", "mc-verdict-name", "Why this is the typical price",
                    "What to do", "What the data can't tell you"):
        assert heading in out, heading
    for text in result["reasons"] + result["weak_spots"] + [result["data_note"]]:
        assert text in out, text
    assert "You're financing $1,000 more than the car's price" in out


def test_invalid_inputs_give_messages():
    future_year = datetime.date.today().year + 2
    cases = [
        ((950, "used", 2019, 17500, 18500, 72, 15.9, ""), "Credit scores are whole numbers from 250 to 900"),
        ((660, "used", 2019, 17500, 18500, 72, 0, ""), "The APR must be more than 0%"),
        ((660, "used", 2019, 17500, 18500, 72, 45, ""), "above 40%"),
        ((660, "used", 2019, 17500, 18500, 120, 15.9, ""), "whole number of months from 12 to 96"),
        ((660, "used", 2019, 17500, 0, 72, 15.9, ""), "Enter the amount financed"),
        ((660, "used", future_year, 17500, 18500, 72, 15.9, ""), "is in the future"),
        ((None, None, None, None, None, None, None, None), "Enter your credit score"),
    ]
    for args, expected in cases:
        out, calls = _call_recording(*args)
        assert isinstance(out, str) and out.strip(), args
        assert expected in out, (args, out)
        assert "Please check these entries" in out
        assert "Your APR is higher than" not in out
        assert calls == [], "predict() must not run on invalid input"


def test_real_model_shape_renders_every_key():
    """A non-stub result (the real model's shape): no banner, every output key visible."""
    fake = {
        "stub": False, "range_low_pct": 7.25, "range_high_pct": 12.75, "typical_pct": 9.5,
        "percentile": 97.0, "flag": "likely marked up",
        "monthly_payment_offer": 403.4, "monthly_payment_typical": 338.12, "extra_cost_usd": 4700.16,
        "reasons": ["Reason alpha", "Reason beta", "Reason gamma"],
        "same_lender": {"lender": "Ally", "typical_pct": 10.1, "difference_pts": -0.4, "n_loans": 1234},
        "view": "whole market", "market": None,
        "weak_spots": ["Weak spot one", "Weak spot two"],
        "data_note": "Data note text",
    }
    original = markupcheck_model.predict
    markupcheck_model.predict = lambda offer: fake
    try:
        out = app.check_offer(660, "used", 2019, 17500, 18500, 72, 15.9, "Ally")
    finally:
        markupcheck_model.predict = original
    assert "Placeholder numbers." not in out
    expected = ["7.25%", "12.75%", "9.5%", "97%", "Well above similar loans", "mc-flag-marked", "$403.40", "$338.12",
                "$4,700 more", "Reason alpha", "Reason beta", "Reason gamma", "Loans from the same lender",
                "Compared with: whole market (all lenders)",
                "Ally", "Typical APR at this lender", "10.1%", "0.40 points lower", "1,234", "Weak spot one", "Weak spot two", "Data note text", app.DISCLAIMER]
    for text in expected:
        assert text in out, text


def test_cheaper_offer_and_one_reason():
    """Offer below typical: negative extra cost shown as 'less' (no minus sign); 1 reason is fine."""
    fake = {
        "stub": False, "range_low_pct": 6.0, "range_high_pct": 10.0, "typical_pct": 8.0,
        "percentile": 4.0, "flag": "typical",
        "monthly_payment_offer": 290.15, "monthly_payment_typical": 315.6, "extra_cost_usd": -1527.0,
        "reasons": ["Your other details are close to a typical loan in the data."],
        "same_lender": None, "weak_spots": ["Weak"], "data_note": "Note",
    }
    original = markupcheck_model.predict
    markupcheck_model.predict = lambda offer: fake
    try:
        out = app.check_offer(760, "new", 2026, 30000, 28000, 60, 5.9, "")
    finally:
        markupcheck_model.predict = original
    assert "about <strong>$1,527 less</strong> than a typical loan like yours" in out
    assert "-$" not in out and "$-" not in out
    assert "$290.15" in out and "$315.60" in out
    assert "Your other details are close to a typical loan in the data." in out
    why = out[out.index("Why this is the typical price"):out.index("What to do")]
    assert why.count("<li>") == 1  # the one reason, nothing padded in


def test_same_lender_view_with_market_line():
    """view = 'same lender: <name>' plus the whole-market dict, as CONTRACT.md describes."""
    fake = {
        "stub": False, "view": "same lender: Santander Consumer",
        "market": {"typical_pct": 13.2, "range_low_pct": 9.8, "range_high_pct": 17.5, "percentile": 71.0,
                   "flag": "typical"},
        "range_low_pct": 12.0, "range_high_pct": 19.0, "typical_pct": 14.05, "percentile": 62.0, "flag": "typical",
        "monthly_payment_offer": 403.4, "monthly_payment_typical": 384.0, "extra_cost_usd": 1396.8,
        "reasons": ["R1", "R2"],
        "same_lender": {"lender": "Santander Consumer", "typical_pct": 14.05, "difference_pts": 0.85,
                        "n_loans": 52000},
        "weak_spots": ["W"], "data_note": "N",
    }
    original = markupcheck_model.predict
    markupcheck_model.predict = lambda offer: fake
    try:
        out = app.check_offer(660, "used", 2019, 17500, 18500, 72, 15.9, "Santander")
    finally:
        markupcheck_model.predict = original
    for text in ["Compared with: same lender (Santander Consumer)",
                 "Across all lenders: typical 13.2%, range 9.8%–17.5%; your APR is higher than 71% of those loans (typical).",
                 "62%", "0.85 points higher", "52,000", "Typical APR at this lender"]:
        assert text in out, text
    assert out.index("Compared with:") < out.index("mc-percent") < out.index("Across all lenders")


def test_live_model_call_never_raises():
    """Whatever state app/model/ is in, the handler returns HTML instead of raising."""
    out = app.check_offer(*app.jordan_example())
    assert isinstance(out, str) and out.strip()


def test_lender_without_data():
    original = markupcheck_model.predict
    markupcheck_model.predict = STUB
    try:
        out = app.check_offer(660, "used", 2019, 17500, 18500, 72, 15.9, "Some Credit Union")
    finally:
        markupcheck_model.predict = original
    assert "don't have enough loans from Some Credit Union" in out


def test_demo_builds():
    assert app.demo is not None


def test_dealer_report_pushback_and_quote():
    out = app.check_offer(*app.SAM[:7], app.SAM[7])
    if "Placeholder numbers." in out:  # stub model: the report lines need the real result
        return
    card = out[out.index("id='mc-card'"):out.index("If the dealer pushes back")]
    for text in ("<strong>Verdict:</strong> Well above similar loans.", "<strong>Cost:</strong> about $4,252 more",
                 "<strong>How sure:</strong> the verdict holds in", "<strong>Data:</strong> real loans up to",
                 "it can't show whether a markup was added", "class='mc-share-url' data-share=\"#s=760"):
        assert text in card, text
    push = out[out.index("If the dealer pushes back"):out.index("Ask for written offers")]
    assert "Can you get closer to 8.87%?" in push and "at the typical 8.87%" in push
    lowered = push.lower()
    for banned in ("overcharg", "markup detected", "guarantee", "you will save", "save $"):
        assert banned not in lowered, banned
    assert "buying a 2022 used car for $24,000 and want to finance $25,000 over 60 months" in out
    # A fair offer gets no "get closer to typical" line.
    fair = app.check_offer(*app.JORDAN[:7], app.JORDAN[7])
    assert "Can you get closer to" not in fair and "If the dealer pushes back" in fair
    assert "Newest loans in our data: January 2026" in out


def test_run_history_is_off():
    # With it on, Gradio keeps each check in the browser at /gradio_api/runs, against the page's "nothing is stored".
    assert app.LAUNCH_KWARGS["run_history"] is False


def test_sam_button_values_and_flag():
    assert app.sam_example() == (760, "used", 2022, 24000, 25000, 60, 14.5, "")
    out = app.check_offer(*app.sam_example())
    if "Placeholder numbers." not in out:  # real model present: Sam is the flagged demo case
        assert "Well above similar loans" in out and "points above</strong>" in out
        assert out.index("mc-verdict-name") < out.index("mc-percent"), "the verdict must come before the numbers"


def test_lender_matching_uses_whole_words():
    import markupcheck_model
    meta = markupcheck_model._load()
    if meta is None:
        return
    meta = meta["meta"]
    for text, key in [("Car Max", "carmax"), ("CARMAX Auto Finance", "carmax"), ("Chrysler Capital", "santander"),
                      ("Ally Bank", "ally"), ("Tally Credit Union", None), ("Finally Auto", None),
                      ("Capital One", "capone"), ("Ford Credit", "ford"), ("Fordham Credit Union", None),
                      ("Lexus Financial Services", "toyota"), ("GM Financial", "gmf"), ("AmeriCredit", None),
                      ("Kia Finance America", "hyundai"), ("Navy Federal Credit Union", None)]:
        assert markupcheck_model._lender_key(meta, text) == key, text


def test_typed_amounts_are_understood():
    for raw, expected in [("$17,500", 17500.0), ("15.9%", 15.9), ("18 500", 18500.0), ("abc", None), ("", None)]:
        assert app._number(raw) == expected, raw
    out = app.check_offer("660", "used", "2019", "$17,500", "18,500", "72", "15.9%", "")
    assert "Please check these entries" not in out and "Your APR is higher than" in out


def test_checks_turn_weak_spots_into_answers():
    """With the trained model: every lender, credit unions, and the checks each weak spot used to describe."""
    if markupcheck_model._load() is None or markupcheck_model._load().get("extras") is None:
        return  # model or src/build_extras.py output not built yet
    sam = html.unescape(app.check_offer(*app.sam_example()))
    for text in ["Your offer at each lender", "Ally", "CarMax Auto Finance", "Santander Consumer",
                 "Credit unions and banks", "NCUA", "5.53%", "7.73%", "How sure is this?",
                 "points lower (730)", "points higher (790)", "haven't moved since January 2026", "Evidence.", "Risk.",
                 "What the data can't tell you", "no race, sex or age"]:
        assert text in sam, text
    for gone in ["Add the lender named on your contract", "VantageScore, while lenders", "Terms longer than 84"]:
        assert gone not in sam, gone
    new_old = html.unescape(app.check_offer(480, "new", 2019, 24000, 25000, 90, 15.0, "Chrysler Capital"))
    for text in ["If this car is really used", "valued the car 5% lower", "your lender", "That's few",
                 "Terms longer than 84 months are rare in the data."]:
        assert text in new_old, text
    unknown = html.unescape(app.check_offer(660, "used", 2019, 17500, 18500, 72, 15.9, "Some Credit Union"))
    assert "We don't have loans from Some Credit Union in our data" in unknown


def test_payment_only_works_out_the_apr():
    out = html.unescape(app.check_offer(660, "used", 2019, 17500, 18500, 72, "", "", "400.28", ""))
    assert "works out to an APR of" in out and "15.9%" in out, out[:400]
    assert "Your payment</h3>" not in out  # no payment check against itself


def test_payment_above_the_apr_is_flagged():
    out = html.unescape(app.check_offer(660, "used", 2019, 17500, 18500, 72, 15.9, "", "440.28", ""))
    assert "$40.00 a month more than the APR explains" in out and "$2,880 over the loan" in out


def test_addons_and_errors():
    out = html.unescape(app.check_offer(660, "used", 2019, 17500, 18500, 72, 15.9, "", "", "2500"))
    assert "Add-ons in your loan" in out and "$3,895" in out  # $2,500 at 15.9% for 72 months
    bad = app.check_offer(660, "used", 2019, 17500, 18500, 72, 15.9, "", "-5", "20000")
    assert "Enter the monthly payment" in bad and "can't be more than the amount financed" in html.unescape(bad)
    neither = app.check_offer(660, "used", 2019, 17500, 18500, 72, "", "", "", "")
    assert "or the monthly payment" in neither


def test_result_has_card_link_and_questions():
    out = html.unescape(app.check_offer(*app.sam_example()))
    for text in ["Take this to the dealer", "Print or save as PDF", "data-share=\"#s=760&k=used&y=2022",
                 "Questions about your result", "Is my offer marked up?", "Each percentage point of APR"]:
        assert text in out, text
    if markupcheck_model._load() is not None:
        for text in ["Ways to a lower rate", "Try it yourself", "data-whatif=", "mc-chart"]:
            assert text in out, text


def test_api_returns_json():
    r = app.check_api(760, "used", 2022, 24000, 25000, 60, 15.0, "", None)
    assert r["verdict"] in ("Typical", "High", "Well above similar loans") and "whatif" not in r["result"]
    assert app.check_api(950, "used", 2022, 24000, 25000, 60, 15.0)["errors"][0]["field"] == app.L_SCORE
    r2 = app.check_api(660, "used", 2019, 17500, 18500, 72, None, "", 400.28)
    assert r2["apr_from_payment"] is True and abs(r2["offer"]["offered_apr_pct"] - 15.9) < 0.01
    assert r["api_version"] == app.API_VERSION and "data_months" in r["result"]
    # Only the documented endpoint is listed; the page's own handlers stay out of the API docs.
    assert list(app.demo.get_api_info()["named_endpoints"]) == ["/check"]


def test_round8_regressions():
    """Fixes from the Nov 15 audit: small loans, comma decimals, badge vs sentence, safe error logs."""
    import contextlib
    import io
    assert "more than $1,000" in html.unescape(app.check_offer(660, "used", 2019, 1000, 1000, 36, 9.0, "", "", ""))
    assert app._number("403,39") == 403.39 and app._number("15,9") == 15.9 and app._number("17,500") == 17500.0
    if markupcheck_model._load() is not None:
        out = html.unescape(app.check_offer(660, "used", 2019, 17500, 18500, 72, 19.56, "Ally", "", ""))
        verdict = out[out.index('<section class="mc-verdict'):]
        verdict = verdict[:verdict.index("</section>")]  # the lender table below has its own badges
        assert ("mc-flag-typical" in verdict) == ("is <strong>inside</strong>" in verdict), "badge and sentence disagree"
        out = html.unescape(app.check_offer(660, "used", 2019, 17500, 18500, 72, 25.47, "", "", ""))
        assert "0.0 points" not in out
        sam = html.unescape(app.check_offer(*app.sam_example(), "", ""))
        assert "over 95%" in sam and "Can you bring my rate" in sam
        jordan = html.unescape(app.check_offer(*app.jordan_example(), "", ""))
        assert "Can you bring my rate" not in jordan  # Jordan's offer is below typical
    original = markupcheck_model.predict

    def boom(offer, *a, **k):
        raise ValueError(f"bad {offer['credit_score']} {offer['amount_financed']}")
    markupcheck_model.predict = boom
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            page = app.check_offer(*app.sam_example(), "", "")
            api = app.check_api(760, "used", 2022, 24000, 25000, 60, 15.0)
    finally:
        markupcheck_model.predict = original
    assert "We couldn't check this offer" in html.unescape(page) and "reference" in api["errors"][0]
    # The timestamp and the random reference can contain "760" by chance, so they are left out of the check.
    logged = " ".join(json.dumps({k: v for k, v in json.loads(line).items() if k not in ("ts", "ref")})
                      for line in err.getvalue().splitlines() if line.strip())
    assert logged and "760" not in logged and "25000" not in logged, "the log quoted the offer"


def test_errors_name_their_fields():
    out = app.check_offer("950", None, "2019", "17500", "", "72", "15.9", "")
    assert f'data-invalid="{app.L_SCORE}|{app.L_KIND}|{app.L_FINANCED}"' in out, out
    assert 'id="mc-error"' in out


def test_security_headers_and_rate_limit():
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    import web_security

    inner = Starlette(routes=[Route("/", lambda r: PlainTextResponse("ok")),
                              Route("/gradio_api/queue/join", lambda r: PlainTextResponse("joined"), methods=["POST"])])
    client = TestClient(web_security.SecurityHeaders(inner, web_security.RateLimiter(limit=3)))
    r = client.get("/")
    for name in ("content-security-policy", "x-content-type-options", "referrer-policy", "permissions-policy",
                 "strict-transport-security"):
        assert name in r.headers, name
    assert "frame-ancestors 'self' https://huggingface.co" in r.headers["content-security-policy"]
    codes = [client.post("/gradio_api/queue/join", headers={"x-forwarded-for": "203.0.113.7, 10.0.0.1"}).status_code
             for _ in range(4)]
    assert codes == [200, 200, 200, 429], codes
    assert client.post("/gradio_api/queue/join", headers={"x-forwarded-for": "203.0.113.8"}).status_code == 200


def test_lender_test_note():
    # The named lender's own held-back test result sits under the headline, with plain warnings when it is thin.
    note = lambda lender: app.check_offer(760, "used", 2022, 24000, 25000, 60, 14.5, lender).split(
        "mc-lender-test'>")[1].split("</p>")[0]
    ford = note("Ford")
    assert ford.startswith("We have only 4,158 loans from Ford Credit")
    assert "On 392 loans from Ford Credit held back for testing" in ford and ford.endswith("treat it with care.")
    assert note("Toyota") == ("On 6,411 loans from a later Toyota Financial Services deal the model never saw, the "
                              "typical rate here was off by 1.07 points on average, against 1.38 for the rule of thumb.")
    assert "On 44,690 loans from a later Capital One deal the model never saw" in note("Capital One")
    nissan = html.unescape(note("Nissan"))
    assert nissan.startswith("We have only 3,265 loans") and "its later deals hold only promotional loans" in nissan
    import i18n
    es = i18n.translate_html(app.check_offer(760, "used", 2022, 24000, 25000, 60, 14.5, "Nissan"), "es")
    assert "sus emisiones posteriores solo tienen préstamos promocionales" in es and "later deals" not in es
    carmax = note("CarMax")
    assert carmax.startswith("On 42,221 loans from CarMax") and "We have only" not in carmax and "care" not in carmax
    assert "mc-lender-test" not in app.check_offer(760, "used", 2022, 24000, 25000, 60, 14.5, "")


def test_offline_banner_script():
    assert app.HEAD.count("window.__mcNet = 1") == 1 and "#mc-offline[hidden]{display:none}" in app.HEAD
    assert "addEventListener('offline'" in app.HEAD and "addEventListener('online'" in app.HEAD


def test_api_numbers_are_plain_json():
    # Gradio's queue stream serializes with orjson and default=str, so a NumPy value would reach clients as a string.
    import orjson
    r = app.check_api(660, "used", 2019, 17500, 18500, 72, 15.9, "Santander", None)
    orjson.dumps(r)  # raises TypeError on any NumPy value
    assert type(r["result"]["same_lender"]["typical_pct"]) is float and type(r["result"]["market"]["typical_pct"]) is float


def test_partner_lookup_is_own_keys_only():
    assert "Object.prototype.hasOwnProperty.call(P, key)" in app.HEAD and "</" not in app.PARTNERS_JSON


def test_cache_is_cleared_within_an_hour():
    frequency, age = app.demo.delete_cache
    assert frequency + age <= 3600


def test_money_figures_agree():
    import re
    for args in [(560, "used", 2019, 18500, 18500, 48, 14.5, "CarMax"), (660, "used", 2019, 17500, 18500, 72, 15.9, ""),
                 (760, "new", 2026, 30000, 28000, 60, 5.9, "Ally")]:
        out = app.check_offer(*args)
        dollars = lambda s: float(s.replace("$", "").replace(",", ""))
        extra = re.search(r"about (\$[\d,]+) (more|less) over \d+ months than at the typical rate", out)
        mine = re.search(r"Interest over \d+ months at [\d.]+%</th><td>(\$[\d,]+)", out)
        typical = re.search(r"the interest would be (\$[\d,]+)", out)
        assert extra and mine and typical, args
        gap = dollars(extra.group(1)) * (1 if extra.group(2) == "more" else -1)
        assert abs(dollars(mine.group(1)) - dollars(typical.group(1)) - gap) <= 1, args
        totals = re.search(r"the total I&#x27;d pay: (\$[\d,]+) over \d+ months at [\d.]+%, against (\$[\d,]+)", out)
        assert totals, args
        assert abs(dollars(totals.group(1)) - dollars(totals.group(2)) - gap) <= 1, args


def test_lender_matching_skips_credit_unions_and_dealers():
    import markupcheck_model
    meta = markupcheck_model._load()["meta"]
    for text, key in [("Honda Federal Credit Union", None), ("Toyota Federal Credit Union", None),
                      ("Ford FCU", None), ("Bill Currie Ford", None), ("Toyota of Sarasota", None),
                      ("Ford", "ford"), ("FORD MOTOR CREDIT COMPANY LLC", "ford"), ("Toyota", "toyota"),
                      ("Toyota Motor Credit Corp", "toyota"), ("Nissan", "nissan"), ("Honda Financial Services", "honda"),
                      ("Hyundai Motor Finance", "hyundai")]:
        assert markupcheck_model._lender_key(meta, text) == key, text


def test_no_lender_is_recalibrated_under_the_preset_band():
    # CarMax's routine reached 77.2%, under the 78-82% band fixed before any recalibration was run (src/recalibrate.py).
    import html as html_mod
    import json
    import markupcheck_model
    assert not markupcheck_model._load()["meta"]["views"]["same_lender"].get("recalibrated")
    rule = json.loads((markupcheck_model.MODEL_DIR.parent.parent / "reports" / "recalibrate.json").read_text())["rule"]
    assert "between 78% and 82%" in rule
    out = html_mod.unescape(app.check_offer(760, "used", 2022, 24000, 25000, 60, 14.5, "CarMax"))
    assert "Newest loans in our data: January 2026" in out and "On newer loans." in out
    assert "This range was updated" not in out


def test_recalibrated_lender_page_is_consistent():
    # The page path for a lender that does pass the rule one day: everything dates from its recalibration months.
    import html as html_mod
    import markupcheck_model
    view = markupcheck_model._load()["meta"]["views"]["same_lender"]
    view["recalibrated"] = {"carmax": {"shift_points": -0.45, "qhat": 0.64, "months": ["2026-07", "2026-08"],
                                       "loans": 25630, "coverage_expected": 0.79}}
    try:
        out = html_mod.unescape(app.check_offer(760, "used", 2022, 24000, 25000, 60, 14.5, "CarMax"))
    finally:
        view["recalibrated"] = {}
    assert "Newest loans in our data: August 2026" in out and "real loans up to August 2026" in out
    assert "moved since August 2026 (we assume they followed the 5-year Treasury, 4.38% then" in out
    assert "On newer loans." not in out and "priced lower than the model expected" in out
    ally = html_mod.unescape(app.check_offer(760, "used", 2022, 24000, 25000, 60, 14.5, "Ally"))
    assert "moved since January 2026" in ally and "On newer loans." in ally


def test_no_lender_gets_the_hyundai_advice():
    import html as html_mod
    blank = html_mod.unescape(app.check_offer(760, "used", 2022, 24000, 25000, 60, 14.5, ""))
    named = html_mod.unescape(app.check_offer(760, "used", 2022, 24000, 25000, 60, 14.5, "Hyundai"))
    advice = "less accurate than a simple rule of thumb for loans from Hyundai Capital America"
    assert advice in blank and advice not in named


def test_recalibrated_line_direction_and_years():
    import i18n
    rc = {"lender": "CarMax Auto Finance", "months": ["2026-12", "2027-01"], "loans": 3000, "shift_points": 0.3}
    line = app._recalibrated_line(rc)
    assert "(December 2026 to January 2027, 3,000 loans)" in line and "priced higher" in line
    es = i18n.translate_html(line, "es")
    assert "diciembre de 2026 a enero de 2027" in es and "más altos" in es and "loans" not in es


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # report every failure, then exit non-zero
            failed += 1
            print(f"FAIL {test.__name__}: {exc!r}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
