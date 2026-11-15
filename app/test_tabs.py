"""Checks for tabs.py with the real trained model in app/model/. Run: .venv/bin/python app/test_tabs.py"""

import csv
import html
import os
import shutil
import sys
import tempfile

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)

import finance  # noqa: E402
import markupcheck_model  # noqa: E402
import tabs  # noqa: E402
from fmt import FLAG_TEXT, _pct, _usd  # noqa: E402

TEMPLATE = os.path.join(APP_DIR, "batch_template.csv")
SAM_PROFILE = (760, "used", 2022, 24000, 25000)
HEADER = "credit_score,new_or_used,model_year,vehicle_price,amount_financed,term_months,apr,lender"
EM_DASH = "\u2014"


def _ok(out: str) -> str:
    """Every output: wrapped in mc-result, no em dash. Returns the text with entities decoded."""
    assert out.startswith('<div class="mc-result">') and out.endswith("</div>"), out[:120]
    assert EM_DASH not in out
    return html.unescape(out)


def _success(out: str) -> str:
    text = _ok(out)
    assert out.endswith(f'<p class="mc-disclaimer">{tabs.DISCLAIMER}</p></div>'), out[-200:]
    assert "Please check" not in out and "Placeholder numbers." not in out
    return text


def _scratch_csv(text: str = None, data: bytes = None) -> str:
    path = os.path.join(tempfile.mkdtemp(prefix="test_tabs_"), "upload.csv")
    with open(path, "wb") as f:
        f.write(data if data is not None else text.encode("utf-8"))
    return path


def _read_results(path: str):
    assert os.path.basename(path) == tabs.RESULTS_NAME
    assert os.path.basename(os.path.dirname(path)).startswith("markupcheck_")
    with open(path, encoding="utf-8-sig", newline="") as f:
        raw = f.read()
    assert EM_DASH not in raw
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def _cleanup(*paths):
    for p in paths:
        if p:
            shutil.rmtree(os.path.dirname(p), ignore_errors=True)


def test_model_is_trained():
    assert markupcheck_model._load() is not None, "these tests need the trained model in app/model/"


def test_compare_ranks_by_total_interest():
    out = tabs.compare_offers(*SAM_PROFILE, [("", "15.0", "60"), ("", "9.0", "60"), ("", "12%", "72")])
    text = _success(out)
    assert "Your offers, cheapest first" in text
    body = out[out.index("<tbody>"):out.index("</tbody>")]
    order = [body.index(name) for name in ("Offer 2", "Offer 3", "Offer 1")]
    assert order == sorted(order), order  # 9%/60 < 12%/72 < 15%/60 by total interest
    first_row = body[:body.index("</tr>")]
    assert "Offer 2" in first_row and "cheapest" in first_row and "mc-row-yours" in first_row
    assert body.count("cheapest") == 1

    interest = {apr: finance.total_paid(25000, apr, term) - 25000 for apr, term in ((15.0, 60), (9.0, 60), (12.0, 72))}
    for apr, term in ((15.0, 60), (9.0, 60), (12.0, 72)):
        assert _usd(interest[apr]) in text, apr
        assert _usd(finance.monthly_payment(25000, apr, term), cents=True) in text, apr
    assert f"Offer 2 costs <strong>{_usd(interest[15.0] - interest[9.0])} less</strong> in interest than Offer 1." in text
    assert f"Offer 2 costs <strong>{_usd(interest[12.0] - interest[9.0])} less</strong> in interest than Offer 3." in text

    sam = markupcheck_model.predict({"credit_score": 760, "new_or_used": "used", "vehicle_model_year": 2022,
                                     "vehicle_price": 24000.0, "amount_financed": 25000.0, "term_months": 60,
                                     "offered_apr_pct": 15.0, "lender": None}, detail=False)
    assert f"Typical {_pct(sam['typical_pct'])}" in text
    assert "Well above" in text and "mc-chip" in out  # 15% is Sam's flagged rate (see test_app.py)
    assert "different terms" in text and "longer term lowers the monthly payment" in text
    cu = sam["credit_union"]
    assert "NCUA" in text and _pct(cu["credit_union_pct"]) in text and "not adjusted for credit score" in text


def test_compare_names_escaped_and_same_terms():
    out = tabs.compare_offers(*SAM_PROFILE, [("<b>Dealer</b>", "15.0", "60"), (" Credit union ", "6.5", "60"), None])
    text = _success(out)
    assert "<b>Dealer</b>" not in out and "&lt;b&gt;Dealer&lt;/b&gt;" in out
    assert text.index("Credit union") < text.index("<b>Dealer</b>")
    assert "Credit union costs" in text
    assert "different terms" not in text


def test_compare_validation_errors():
    out = tabs.compare_offers(*SAM_PROFILE, [("A", "15", "60"), ("B", "", "60"), ("C", "12", "")])
    text = _ok(out)
    assert ('<div class="mc-error" id="mc-error-compare" data-invalid="Offer 2 APR (%)|Offer 3 term (months)" '
            'role="alert"><h3>Please check these entries</h3>') in out
    assert "Offer 2: enter the APR" in text and "Offer 3: enter the loan term" in text
    assert "Offer 1:" not in text and "mc-disclaimer" not in out

    out = tabs.compare_offers(950, "used", 2022, 24000, 25000, [("A", "15", "60"), ("B", "9", "60")])
    assert _ok(out).count("Credit scores are whole numbers") == 1  # a profile error is shown once, not per offer

    for offers in ([("A", "15", "60"), ("Named only", "", ""), ("", " ", None)], [], None):
        out = tabs.compare_offers(*SAM_PROFILE, offers)
        assert "Enter at least two offers" in _ok(out), offers

    out = tabs.compare_offers(*SAM_PROFILE, [("A", "15", "60"), ("B", "45", "60")])
    assert "Offer 2: an APR of 45% is above 40%" in _ok(out)


def test_refinance_happy_path():
    out = tabs.refinance_check("700", "2020", "$15,000", "14.5%", "40", "16,000")
    text = _success(out)
    offer = {"credit_score": 700, "new_or_used": "used", "vehicle_model_year": 2020, "vehicle_price": 16000.0,
             "amount_financed": 15000.0, "term_months": 40, "offered_apr_pct": 14.5, "lender": None}
    result = markupcheck_model.predict(offer, detail=False)
    for value in (result["typical_pct"], result["range_low_pct"], result["range_high_pct"]):
        assert _pct(value) in text, value
    assert FLAG_TEXT[result["flag"]][0].split()[0] in text and "mc-chip" in out
    current = finance.refinance(15000, 40, 14.5, 14.5)["current_payment"]
    assert f"about {_usd(current, cents=True)} a month" in text
    refi = finance.refinance(15000, 40, 14.5, result["typical_pct"])
    assert _usd(refi["new_payment"], cents=True) in text
    word = "You'd save" if refi["total_saving"] > 0.5 else "You'd pay"
    assert f"{word} {_usd(refi['total_saving'])}" in text
    # No saving is computed at the credit-union average: it isn't adjusted for credit score or term.
    assert "Credit-union average<span" not in out
    assert "NCUA" in text and "not adjusted for credit score" in text
    for caveat in ("loans made when people bought their cars", "Refinance loans can be priced differently",
                   "Refinancing can have fees", "payoff amount with your lender"):
        assert caveat in text, caveat
    assert "assumed it is worth" not in text and "at least 12 months" not in text


def test_refinance_offered_rate_and_reminders():
    import datetime
    import urllib.parse
    out = tabs.refinance_check("700", "2020", "15000", "14.5", "40", "", "9.5")
    text = _success(out)
    assert "If approved at the rate you were offered" in text and "9.5%" in text
    assert "The difference assumes you are approved at it." in text
    bad = tabs.refinance_check("700", "2020", "15000", "14.5", "40", "", "abc")
    assert "Enter the rate you were offered as a percent" in bad
    href = out.split("href=\"data:text/calendar;charset=utf-8,")[1].split('"')[0]
    ics = urllib.parse.unquote(href)
    assert ics.count("BEGIN:VEVENT") == 2 and ics.startswith("BEGIN:VCALENDAR")
    assert "15000" not in ics and "14.5" not in ics, "the calendar file must hold no numbers from the check"
    fixed = tabs.reminder_ics(datetime.date(2026, 8, 31))
    assert "DTSTART;VALUE=DATE:20270228" in fixed and "DTSTART;VALUE=DATE:20270831" in fixed


def test_contract_box_check():
    bad = tabs.contract_box_check("", "-1", "18500", "72.5", "")
    assert ('id="mc-error-tila" data-invalid="Amount Financed ($)|Finance Charge ($)|Number of payments|'
            'Annual Percentage Rate (%)"') in bad
    ok = tabs.contract_box_check("18,500", "$10,320.24", "28820.24", "72", "15.9%")
    assert "The box adds up" in ok and "within the federal tolerance" in ok
    apr_off = tabs.contract_box_check("18500", "10320.24", "28820.24", "72", "13.9")
    assert "doesn't add up" in apr_off and "but the box says 13.9%" in apr_off
    sum_off = tabs.contract_box_check("18500", "9000", "28820.24", "72", "15.9")
    assert "a difference of $1,320.24" in sum_off
    # 1/8 of a point is the federal tolerance: 0.1 points off passes, 0.2 doesn't.
    assert "The box adds up" in tabs.contract_box_check("18500", "10320.24", "28820.24", "72", "16.0")
    assert "doesn't add up" in tabs.contract_box_check("18500", "10320.24", "28820.24", "72", "16.1")
    assert "Enter the Amount Financed" in tabs.contract_box_check("", "1", "2", "3", "4")


def test_refinance_pays_more_when_rate_is_already_low():
    out = tabs.refinance_check("700", "2020", "15000", "3.0", "40", "")
    assert "You'd pay" in _success(out)


def test_refinance_blank_car_value():
    out = tabs.refinance_check("700", "2020", "15000", "14.5", "40", "")
    text = _success(out)
    assert "You left the car's value blank, so we assumed it is worth what you owe, $15,000." in text
    out_none = tabs.refinance_check("700", "2020", "15000", "14.5", "40", None)
    assert "assumed it is worth" in _success(out_none)


def test_refinance_short_months_left():
    calls = []
    original = markupcheck_model.predict

    def recorder(offer, detail=True):
        calls.append((dict(offer), detail))
        return original(offer, detail=detail)

    markupcheck_model.predict = recorder
    try:
        out = tabs.refinance_check("700", "2020", "5000", "14.5", "6", "7000")
    finally:
        markupcheck_model.predict = original
    text = _success(out)
    assert calls and calls[0][0]["term_months"] == 12 and calls[0][1] is False
    assert calls[0][0]["new_or_used"] == "used" and calls[0][0]["amount_financed"] == 5000.0
    assert calls[0][0]["vehicle_price"] == 7000.0 and calls[0][0]["offered_apr_pct"] == 14.5
    assert "at least 12 months" in text and "your 6 months left" in text
    refi = finance.refinance(5000, 6, 14.5, original(calls[0][0], detail=False)["typical_pct"])
    assert _usd(refi["new_payment"], cents=True) in text  # the money uses the real 6 months, not 12


def test_refinance_validation():
    out = tabs.refinance_check("950", "", "800", "45", "0", "-5")
    text = _ok(out)
    for message in ("Credit scores are whole numbers from 250 to 900", "Enter the car's model year",
                    "balances over $1,000", "from 0% to 40%", "whole number from 1 to 96", "or leave it blank"):
        assert message in text, message
    assert "mc-disclaimer" not in out
    assert ('id="mc-error-refi" data-invalid="Credit score now|Car&#x27;s model year|Balance left ($)|'
            'Current APR (%)|Months left|Car&#x27;s value now ($, optional)"') in out
    out = tabs.refinance_check("<script>", "2020", "15000", "14.5", "40", "")
    assert "<script>" not in out


def test_batch_round_trip_on_template():
    out, path = tabs.batch_check(TEMPLATE)
    try:
        text = _success(out)
        assert path and os.path.exists(path)
        fields, rows = _read_results(path)
        assert fields == HEADER.split(",") + list(tabs.BATCH_NEW_COLUMNS), fields
        assert len(rows) == 3
        names = {v[0] for v in FLAG_TEXT.values()}
        for row in rows:
            assert row["error"] == "" and row["verdict"] in names, row
            assert float(row["range_low"]) <= float(row["typical_apr"]) <= float(row["range_high"]), row
            assert 0 <= float(row["percentile"]) <= 100
        assert rows[2]["lender"] == "Ally" and rows[0]["apr"] == "15.9"
        jordan = markupcheck_model.predict({"credit_score": 660, "new_or_used": "used", "vehicle_model_year": 2019,
                                            "vehicle_price": 17500.0, "amount_financed": 18500.0, "term_months": 72,
                                            "offered_apr_pct": 15.9, "lender": None}, detail=False)
        assert rows[0]["typical_apr"] == f"{jordan['typical_pct']:.2f}"
        assert rows[0]["verdict"] == FLAG_TEXT[jordan["flag"]][0]
        assert rows[1]["verdict"] == "Well above similar loans"  # Sam
        assert "We checked <strong>3</strong> rows." in text and "All rows" in text and "Couldn't check" in text
        assert out.count("<th scope='row'>") == 4 + 3  # 4 tally rows, 3 preview rows
    finally:
        _cleanup(path)


def test_batch_row_errors_and_messy_header():
    src = _scratch_csv(" Credit_Score , NEW_OR_USED,Model_Year,vehicle_price,amount_financed,term_months, APR \n"
                       "950,used,2019,17500,18500,72,15.9\n"
                       ",,,,,,\n"
                       "760,used,2022,$24,000,25000,60,15.0\n"
                       "760,used,2022,\"$24,000\",25000,60,15.0\n")
    out, path = tabs.batch_check(src)
    try:
        text = _success(out)
        fields, rows = _read_results(path)
        assert "lender" not in [f.strip().lower() for f in fields]
        assert len(rows) == 3  # the blank row is skipped
        assert "Credit scores are whole numbers" in rows[0]["error"] and rows[0]["verdict"] == ""
        assert "more values than there are columns" in rows[1]["error"]
        assert rows[2]["error"] == "" and rows[2]["verdict"] == "Well above similar loans"
        assert "Couldn't check</th><td>2" in out
        assert "colspan='2'" in out and "We checked <strong>3</strong> rows." in text
    finally:
        _cleanup(src, path)


def test_batch_missing_columns():
    src = _scratch_csv("credit_score,new_or_used,vehicle_price,amount_financed,term_months\n660,used,17500,18500,72\n")
    out, path = tabs.batch_check(src)
    try:
        text = _ok(out)
        assert path is None
        assert 'role="alert"' in out and "model_year" in text and "apr" in text
        assert "<code>model_year</code>, <code>apr</code>" in out
    finally:
        _cleanup(src)


def test_batch_garbage_and_empty_files():
    garbage = _scratch_csv(data=bytes(range(256)) * 40)
    empty = _scratch_csv(data=b"")
    header_only = _scratch_csv(HEADER + "\n")
    text_only = _scratch_csv("hello, world\nthis is not the right file\n")
    try:
        for src, expected in ((garbage, "We couldn't read this file"), (empty, "This file is empty"),
                              (header_only, "no rows to check"), (text_only, "These are missing"),
                              (None, "Choose a CSV file"), ("", "Choose a CSV file"),
                              ("/no/such/file.csv", "We couldn't read this file")):
            out, path = tabs.batch_check(src)
            assert path is None, src
            assert expected in _ok(out) and 'role="alert"' in out, (src, out)
    finally:
        _cleanup(garbage, empty, header_only, text_only)


def test_batch_caps_at_500_rows():
    src = _scratch_csv(HEADER + "\n" + "660,used,2019,17500,18500,72,15.9,\n" * 501)
    out, path = tabs.batch_check(src)
    try:
        text = _success(out)
        assert "more than 500 rows, so we checked the first 500" in text
        assert "We checked <strong>500</strong> rows." in text and "First 25 rows" in text
        assert out.count("<th scope='row'>") == 4 + 25
        _, rows = _read_results(path)
        assert len(rows) == 500
    finally:
        _cleanup(src, path)


def test_batch_rereads_its_own_results():
    out, first = tabs.batch_check(TEMPLATE)
    out2, second = tabs.batch_check(first)
    try:
        _success(out2)
        fields, rows = _read_results(second)
        assert fields == HEADER.split(",") + list(tabs.BATCH_NEW_COLUMNS), fields  # old result columns replaced
        assert len(rows) == 3
    finally:
        _cleanup(first, second)


def test_stub_results_say_placeholder():
    original = markupcheck_model.predict
    markupcheck_model.predict = lambda offer, detail=True: markupcheck_model._stub(offer)
    try:
        outs = [tabs.compare_offers(*SAM_PROFILE, [("", "15", "60"), ("", "9", "60")]),
                tabs.refinance_check("700", "2020", "15000", "14.5", "40", ""),
                tabs.batch_check(TEMPLATE)]
    finally:
        markupcheck_model.predict = original
    _cleanup(outs[2][1])
    for out in (outs[0], outs[1], outs[2][0]):
        _ok(out)
        assert "Placeholder numbers." in out and out.endswith(f"{tabs.DISCLAIMER}</p></div>")


def test_batch_results_file_is_removed_after_gradio_copies_it():
    started = []

    class FakeTimer:
        def __init__(self, delay, fn, args=(), kwargs=None):
            started.append((delay, fn, args, kwargs or {}))
            self.daemon = False

        def start(self):
            pass

    real = tabs.threading.Timer
    tabs.threading.Timer = FakeTimer
    try:
        _, path = tabs.batch_check(os.path.join(os.path.dirname(tabs.__file__), "batch_template.csv"))
    finally:
        tabs.threading.Timer = real
    folder = os.path.dirname(path)
    assert len(started) == 1 and started[0][2] == (folder,) and started[0][0] <= 300
    delay, fn, args, kwargs = started[0]
    fn(*args, **kwargs)
    assert not os.path.exists(folder)


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
