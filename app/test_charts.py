"""Checks for charts.py. Run: .venv/bin/python app/test_charts.py (also works under pytest)."""

import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import charts  # noqa: E402

NS = "{http://www.w3.org/2000/svg}"
CARD = "#E8EDF3"
ALLOWED_TEXT = {c.upper() for c in charts.TEXT_COLORS}
NUMBER_WORDS = re.compile(r"(?<![a-z])(nan|inf|infinity)(?![a-z])", re.IGNORECASE)

QUANTILES = [(0.05, 9.4), (0.10, 9.9), (0.15, 10.3), (0.20, 10.7), (0.25, 11.0), (0.30, 11.3), (0.35, 11.6),
             (0.40, 11.9), (0.45, 12.2), (0.50, 12.5), (0.55, 12.8), (0.60, 13.1), (0.65, 13.4), (0.70, 13.8),
             (0.75, 14.2), (0.80, 14.7), (0.85, 15.2), (0.90, 15.9), (0.95, 17.0)]


def _check(svg: str, uid: str, white_ok: bool = False, compact: bool = False) -> ET.Element:
    """Every chart: well-formed, ids from the uid (plus "n" when compact), the fixed root attributes, no
    nan/inf/em dash, and text only in the allowed colours, at 12+ units, inside the viewBox."""
    ident = uid + ("n" if compact else "")
    variant = "mc-chart mc-chart-narrow" if compact else "mc-chart mc-chart-wide"
    assert isinstance(svg, str)
    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="'), svg[:120]
    assert re.match(r'<svg xmlns="http://www\.w3\.org/2000/svg" viewBox="[^"]+" role="img" '
                    rf'aria-labelledby="{re.escape(ident)}-t {re.escape(ident)}-d" class="{variant}"', svg), svg[:200]
    root = ET.fromstring(svg)
    assert root.tag == NS + "svg"
    assert root.get("width") == "100%" and root.get("height") is None
    assert root.get("preserveAspectRatio") == "xMidYMid meet"
    view = [float(v) for v in root.get("viewBox").split()]
    assert len(view) == 4 and view[3] > 0 and view[2] == (340 if compact else 600), view
    title, desc = root.find(NS + "title"), root.find(NS + "desc")
    assert title is not None and title.get("id") == f"{ident}-t" and title.text.strip()
    assert desc is not None and desc.get("id") == f"{ident}-d" and desc.text.strip()
    assert not NUMBER_WORDS.search(svg), NUMBER_WORDS.search(svg)
    assert "\u2014" not in svg
    for text in root.iter(NS + "text"):
        fill = (text.get("fill") or "").upper()
        assert fill in ALLOWED_TEXT or (white_ok and fill == "#FFFFFF"), fill
        assert float(text.get("font-size")) >= 12, text.get("font-size")
        for span in text.iter(NS + "tspan"):
            assert span.get("fill") is None
        for left, right, y in _text_extents(text):
            assert left >= -1 and right <= view[2] + 1, ("".join(text.itertext()), left, right, view[2])
            assert 8 <= y <= view[3], ("".join(text.itertext()), y, view[3])
    return root


def _text_extents(text):
    """(left, right, baseline) of each line of a <text>, from charts' own width estimate."""
    size = float(text.get("font-size"))
    bold = (text.get("font-weight") or "400") >= "600"
    anchor = text.get("text-anchor", "start")
    lines = [(s, s.get("x"), s.get("y")) for s in text.iter(NS + "tspan")] or [(text, text.get("x"),
                                                                               text.get("y"))]
    for node, x, y in lines:
        w = charts._tw("".join(node.itertext()), size, bold)
        x = float(x)
        left = x - w / 2 if anchor == "middle" else x - w if anchor == "end" else x
        yield left, left + w, float(y)


def _texts(root):
    return ["".join(t.itertext()) for t in root.iter(NS + "text")]


def test_text_colours_pass_on_the_card():
    for color in charts.TEXT_COLORS:
        assert charts.contrast(color, CARD) >= 4.5, color
    assert charts.contrast(charts.PALETTE["ACCENT"], CARD) >= 3.0  # marks only
    assert charts.contrast(charts.PALETTE["ACCENT"], CARD) < 4.5   # which is why it never colours text


def test_apr_and_dollar_formats():
    assert [charts._pct(v) for v in (11, 15.9, 15.99, 7.25)] == ["11.0%", "15.9%", "15.99%", "7.25%"]
    assert [charts._signed(v) for v in (0.9, -1.3, 0.0, 0.25)] == ["+0.9", "−1.3", "0.0", "+0.25"]
    assert charts._usd(1234.4) == "$1,234" and charts._usd(4697) == "$4,697"


# ---------------------------------------------------------------- distribution


def test_distribution_typical():
    svg = charts.distribution_svg(QUANTILES, 15.9, 9.9, 15.9, 12.5, "dist-1")
    root = _check(svg, "dist-1")
    texts = _texts(root)
    assert "Your offer 15.9%" in texts and "Typical 12.5%" in texts
    assert root.find(f".//{NS}path[@fill-opacity='0.1']") is not None, "density area"
    band = [r for r in root.iter(NS + "rect") if r.get("fill-opacity") == "0.22"]
    assert len(band) == 1 and band[0].get("stroke") == charts.PALETTE["ACCENT"]
    ticks = [t for t in texts if re.fullmatch(r"\d+(\.\d+)?%", t)]
    assert 4 <= len(ticks) <= 6, ticks
    assert "80% of similar loans have an APR between 9.9% and 15.9%" in svg
    width = float(root.get("viewBox").split()[2])
    assert width == 600


def _label_boxes(root):
    """(y, left, right) of the 'Typical' and 'Your offer' labels, from the width estimate."""
    out = {}
    for t in root.iter(NS + "text"):
        content = "".join(t.itertext())
        if content.startswith(("Typical ", "Your offer ")):
            size = float(t.get("font-size"))
            w = charts._tw(content, size, True)
            x = float(t.get("x"))
            anchor = t.get("text-anchor", "start")
            left = x - w / 2 if anchor == "middle" else x - w if anchor == "end" else x
            out[content.split()[0]] = (float(t.get("y")), left, left + w)
    return out


def test_distribution_labels_never_overlap():
    for offer, typical in [(12.6, 12.5), (12.5, 12.5), (17.4, 17.1), (9.0, 9.2), (15.0, 13.0)]:
        svg = charts.distribution_svg(QUANTILES, offer, 9.9, 15.9, typical, "dist-2")
        boxes = _label_boxes(_check(svg, "dist-2"))
        (y1, l1, r1), (y2, l2, r2) = boxes["Typical"], boxes["Your"]
        assert y1 != y2 or r1 + 8 <= l2 or r2 + 8 <= l1, (offer, typical, boxes)
        for _, left, right in boxes.values():
            assert left >= 0 and right <= 600, (offer, typical, boxes)


def test_distribution_stacks_labels_when_crowded():
    # At the right edge neither label can turn outward, so they go on two rows.
    svg = charts.distribution_svg(QUANTILES, 40.0, 9.9, 15.9, 39.6, "dist-3")
    boxes = _label_boxes(_check(svg, "dist-3"))
    assert boxes["Typical"][0] != boxes["Your"][0], boxes


def test_distribution_offer_outside_extends_axis():
    svg = charts.distribution_svg(QUANTILES, 35.0, 9.9, 15.9, 12.5, "dist-4")
    root = _check(svg, "dist-4")
    marker = root.find(f".//{NS}g[@class='mc-offer']/{NS}line")
    width = float(root.get("viewBox").split()[2])
    assert 0 < float(marker.get("x1")) < width
    assert "Your offer 35.0%" in _texts(root) and "above that range" in svg
    low_offer = charts.distribution_svg(QUANTILES, 2.0, 9.9, 15.9, 12.5, "dist-5")
    root = _check(low_offer, "dist-5")
    assert 0 < float(root.find(f".//{NS}g[@class='mc-offer']/{NS}line").get("x1")) < width
    assert "below that range" in low_offer


def test_distribution_degenerate_inputs():
    cases = [
        ([], 15.9, 9.9, 15.9, 12.5),                              # no quantiles: band and markers only
        ([(0.5, 12.0)], 15.9, 9.9, 15.9, 12.5),                   # a single point
        ([(p, 12.0) for p, _ in QUANTILES], 12.0, 12.0, 12.0, 12.0),  # every value equal
        ([(0.1, 10.0), (0.2, 10.0000001), (0.9, 14.0)], 11.0, 10.0, 14.0, 12.0),  # ΔAPR ~ 0
        (QUANTILES, None, None, None, None),                      # curve only
        ([(0.1, float("nan")), (0.5, float("inf")), ("x", 3)], float("nan"), None, None, None),
        (None, None, None, None, None),
        (QUANTILES, 15.9, 16.0, 9.0, 12.5),                       # low and high swapped
    ]
    for compact in (False, True):
        for k, args in enumerate(cases):
            _check(charts.distribution_svg(*args, uid=f"deg-{k}", compact=compact), f"deg-{k}", compact=compact)


def test_distribution_has_no_needles_from_near_equal_quantiles():
    """A real model output with two near-zero gaps (7.95/7.96 and 8.79/8.8) must not draw spikes."""
    real = [(0.05, 6.0), (0.1, 6.4), (0.15, 6.9), (0.2, 7.2), (0.25, 7.5), (0.3, 7.7), (0.35, 7.95), (0.4, 7.96),
            (0.45, 8.3), (0.5, 8.79), (0.55, 8.8), (0.6, 9.3), (0.65, 9.7), (0.7, 10.1), (0.75, 10.6),
            (0.8, 11.1), (0.85, 11.8), (0.9, 12.6), (0.95, 14.2)]
    for bins in (charts._BINS, charts._BINS_COMPACT):  # wide, compact
        edges, masses = charts._histogram(real, 6.4, 12.6, bins)
        assert len(masses) == bins and abs(sum(masses) - 1) < 1e-9
        assert edges[0] < 6.0 and edges[-1] > 14.2, "tails reach past the outer quantiles"
        assert max(masses) < 0.25, masses
        for k, m in enumerate(masses):
            near = [masses[j] for j in (k - 1, k + 1) if 0 <= j < bins]
            assert m <= 3 * sum(near) / len(near), (bins, k, masses)
        # The drawn curve never rises above the tallest smoothed bin.
        width = edges[1] - edges[0]
        curve = charts._density(real, 6.4, 12.6, bins)
        assert max(v for _, v in curve) <= max(masses) / width + 1e-9
    for compact in (False, True):
        _check(charts.distribution_svg(real, 9.9, 6.4, 12.6, 8.79, "real", compact=compact), "real",
               compact=compact)


def test_uid_is_sanitised_and_ids_unique_per_chart():
    svg = charts.distribution_svg(QUANTILES, 15.9, 9.9, 15.9, 12.5, 'a b"<c>')
    root = ET.fromstring(svg)
    assert root.get("aria-labelledby") == "a-b-c-t a-b-c-d"
    a = charts.timeline_svg([("A", [1, 2])], "one")
    b = charts.timeline_svg([("A", [1, 2])], "two")
    ids = re.findall(r'id="([^"]+)"', a + b)
    assert len(ids) == len(set(ids)) == 4


# ---------------------------------------------------------------- timeline


def _interest(principal, apr, months):
    r = apr / 1200
    pay = principal * r / (1 - (1 + r) ** -months)
    bal, paid, out = principal, 0.0, []
    for _ in range(months):
        paid += bal * r
        bal -= pay - bal * r
        out.append(paid)
    return out


def test_timeline_typical():
    series = [("Your offer", _interest(18500, 15.9, 72)), ("Typical loan", _interest(18500, 12.5, 72)),
              ("Low end", _interest(18500, 9.9, 72))]
    svg = charts.timeline_svg(series, "time-1", highlight="Your offer")
    root = _check(svg, "time-1")
    texts = _texts(root)
    final = charts._usd(series[0][1][-1])
    assert f"Your offer {final}" in texts
    assert {"12 mo", "24 mo", "72 mo"} <= set(texts)
    dollar_ticks = [t for t in texts if re.fullmatch(r"\$[\d,]+", t)]
    assert 3 <= len(dollar_ticks) <= 5, dollar_ticks
    paths = [p for p in root.iter(NS + "path") if p.get("fill") == "none"]
    strong = [p for p in paths if p.get("stroke") == charts.PALETTE["TEXT"]]
    assert len(strong) == 1 and float(strong[0].get("stroke-width")) > 2
    assert any(p.get("stroke-dasharray") for p in paths), "never colour alone"
    assert f"after 72 months" in svg and "more in interest than Typical loan" in svg


def test_timeline_crowded_lines_fall_back_to_a_legend():
    series = [("Your offer", _interest(18500, 15.9, 72)), ("Typical loan", _interest(18500, 15.8, 72)),
              ("Credit union", _interest(18500, 15.7, 72))]
    root = _check(charts.timeline_svg(series, "time-2", highlight="Your offer"), "time-2")
    keys = [ln for ln in root.iter(NS + "line") if ln.get("x2") and
            float(ln.get("x2")) - float(ln.get("x1")) == 24]
    assert len(keys) == 3, "legend keys"


def test_timeline_edge_cases():
    cases = [
        ([("Only month", [42.0])], None),                    # single point
        ([("Zero APR", [0.0] * 36), ("Also zero", [0.0] * 36)], "Zero APR"),  # all equal
        ([("Short", [10, 20, 30]), ("Long", list(range(1, 100)))], "Missing name"),  # lengths differ
        ([("Gaps", [10, None, 30, float("nan"), 50])], "Gaps"),
        ([("A \u2014 <b>", [1, 2, 3]), ("B & C", [2, 3, 4])], "A \u2014 <b>"),  # labels escaped, em dash replaced
        ([], None),
        ([("Nothing", [None, None])], None),
        (None, None),
    ]
    for compact in (False, True):
        for k, (series, highlight) in enumerate(cases):
            svg = charts.timeline_svg(series, f"te-{k}", highlight=highlight, compact=compact)
            _check(svg, f"te-{k}", compact=compact)
            assert "<b>" not in svg


# ---------------------------------------------------------------- waterfall


def _bars(root):
    return [r for r in root.iter(NS + "rect") if r.get("rx") == "3"]


def test_waterfall_adds_residual_step():
    steps = [("Credit score 660", 1.6), ("Used car", 0.9), ("72-month term", 0.4), ("Loan amount", -0.6)]
    svg = charts.waterfall_svg("Typical loan in the data", 12.1, steps, "Your typical rate", 14.2, "wf-1")
    root = _check(svg, "wf-1")
    texts = _texts(root)
    assert "Other and combined effects" in texts  # 12.1 + 1.6 + 0.9 + 0.4 - 0.6 = 14.4, so -0.2 is left over
    assert "−0.2" in texts and "+1.6" in texts and "12.1%" in texts and "14.2%" in texts
    assert len(_bars(root)) == 5
    fills = {r.get("fill") for r in _bars(root)}
    assert fills == {charts.PALETTE["SECONDARY"], charts.PALETTE["ACCENT"]}
    assert root.find(f".//{NS}g[@fill='{charts.PALETTE['BRAND_DARK']}']") is not None


def test_waterfall_skips_small_residual_and_reaches_the_end():
    steps = [("Credit score 790", -5.2), ("New car", -1.3), ("60-month term", -0.4)]
    svg = charts.waterfall_svg("Typical loan in the data", 12.1, steps, "Your typical rate", 5.23, "wf-2")
    root = _check(svg, "wf-2")
    assert "Other and combined effects" not in svg
    assert len(_bars(root)) == 3
    # The last step's left edge sits within half a pixel-equivalent of where the end value would be.
    steps = [("A", 1.0)]
    root = _check(charts.waterfall_svg("Start", 10.0, steps, "End", 11.04, "wf-3"), "wf-3")
    assert "Other and combined effects" not in _texts(root)
    root = _check(charts.waterfall_svg("Start", 10.0, steps, "End", 11.05, "wf-4"), "wf-4")
    assert "Other and combined effects" in _texts(root)


def test_waterfall_edge_cases():
    cases = [
        ("Start", 12.0, [], "End", 12.0),                 # nothing to explain
        ("Start", 12.0, [("Zero", 0.0)], "End", 12.0),    # a zero step
        ("Start", 12.0, [], "End", 15.0),                 # all residual
        ("Start", None, [("A", 1)], "End", 13.0),         # missing start
        ("Start", 12.0, [("NaN", float("nan")), ("Text", "x")], "End", 12.0),
        ("A very long starting label that has to wrap onto a second line and then some more words", 3.0,
         [("Another label \u2014 with an em dash & <tags>", 9.0)], "End", 12.0),
        ("Start", 0.0, [("Up", 2.0)], "End", 2.0),
    ]
    for compact in (False, True):
        for k, args in enumerate(cases):
            svg = charts.waterfall_svg(*args, uid=f"we-{k}", compact=compact)
            _check(svg, f"we-{k}", compact=compact)
            assert "<tags>" not in svg


# ---------------------------------------------------------------- tile map


def _tiles(root):
    for g in root.iter(NS + "g"):
        if g.get("class") == "mc-tile":
            yield g.find(NS + "rect"), g.find(NS + "text")


def test_tile_map_typical():
    values = {"TX": {"gap": 1.2, "holds": True}, "FL": {"gap": 0.9, "holds": True},
              "GA": {"gap": 0.7, "holds": True}, "LA": {"gap": 2.4, "holds": True},
              "NV": {"gap": 0.5, "holds": False}, "MN": {"gap": -0.9, "holds": True},
              "IA": {"gap": -1.1, "holds": True}, "WA": {"gap": -0.6, "holds": True},
              "MA": {"gap": -1.4, "holds": True}, "OR": {"gap": -0.4, "holds": False},
              "OH": {"gap": 0.0, "holds": True}, "dc": {"gap": 0.25, "holds": False}}
    svg = charts.tile_map_svg(values, "map-1", "APR gap by state")
    root = _check(svg, "map-1", white_ok=True)
    tiles = list(_tiles(root))
    assert len(tiles) == 51
    by_code = {"".join(t.itertext()): (r, t) for r, t in tiles}
    for rect, text in tiles:
        assert charts.contrast(text.get("fill"), rect.get("fill")) >= 4.5, ("".join(text.itertext()),
                                                                             rect.get("fill"), text.get("fill"))
    assert by_code["NV"][0].get("stroke-dasharray") and not by_code["TX"][0].get("stroke-dasharray")
    assert by_code["DC"][0].get("stroke-dasharray"), "lowercase keys are accepted"
    assert by_code["AK"][0].get("stroke") == "none", "missing state"
    assert "Louisiana +2.4, Texas +1.2, Florida +0.9" in svg
    assert "Massachusetts −1.4, Iowa −1.1, Minnesota −0.9" in svg
    assert "Nevada" not in root.find(NS + "desc").text, "only holding gaps are listed"
    for word in ("Pays less", "Pays more", "No data", "Dashed outline: the gap could be chance"):
        assert word in _texts(root), word
    # Stronger with |gap|, capped at 1.5: LA (2.4) and a 1.5 tile share a fill.
    capped = charts.tile_map_svg({"LA": {"gap": 2.4, "holds": True}, "TX": {"gap": 1.5, "holds": True}}, "m", "t")
    fills = {"".join(t.itertext()): r.get("fill") for r, t in _tiles(ET.fromstring(capped))}
    assert fills["LA"] == fills["TX"]


def test_tile_map_every_fill_keeps_label_contrast():
    for k in range(-40, 41):
        gap = k / 20
        for holds in (True, False):
            fill, ink, _ = charts._tile_style(gap, holds)
            assert charts.contrast(ink, fill) >= 4.5, (gap, holds, fill, ink)


def test_tile_map_edge_cases():
    cases = [{}, None, {"ZZ": {"gap": 1}, "TX": {"gap": None}, "FL": "bad", "GA": {"gap": float("inf")}},
             {"TX": {"gap": 0.3}}, {code: {"gap": 0.4, "holds": True} for code in charts._TILES}]
    for compact in (False, True):
        for k, values in enumerate(cases):
            svg = charts.tile_map_svg(values, f"me-{k}", "Gap \u2014 <by state>", compact=compact)
            root = _check(svg, f"me-{k}", white_ok=True, compact=compact)
            assert root.find(NS + "title").text == "Gap \u2013 <by state>"
            for rect, text in _tiles(root):
                assert charts.contrast(text.get("fill"), rect.get("fill")) >= 4.5
    empty = charts.tile_map_svg({}, "me-x", "t")
    assert "No state data" in empty and "No data" in empty
    full = charts.tile_map_svg(cases[-1], "me-y", "t")
    assert ">No data<" not in full


# ---------------------------------------------------------------- tracker


MONTHS = [f"{2023 + (8 + i) // 12}-{(8 + i) % 12 + 1:02d}" for i in range(40)]


def test_tracker_typical():
    ally = [9.1 + 0.03 * i for i in range(40)]
    carmax = [12.4 - 0.02 * i if i not in (10, 11, 12) else None for i in range(40)]
    sant = [15.2 + 0.04 * i if i > 5 else None for i in range(40)]
    svg = charts.tracker_svg(MONTHS, [("Ally", ally), ("CarMax", carmax), ("Santander", sant)], "trk-1")
    root = _check(svg, "trk-1")
    texts = _texts(root)
    assert "Jan 2024" in texts and "Jul 2024" in texts and "Typical APR" in texts
    assert f"Ally {charts._pct(ally[-1])}" in texts
    paths = [p for p in root.iter(NS + "path") if p.get("fill") == "none"]
    carmax_paths = [p for p in paths if p.get("stroke-dasharray") == "7 4"]
    assert len(carmax_paths) == 2, "a None gap breaks the line"
    dashes = {p.get("stroke-dasharray") for p in paths}
    assert len(dashes) == 3, dashes
    assert {p.get("stroke") for p in paths} == {charts.PALETTE[k] for k in ("ACCENT", "BRAND_DARK", "SECONDARY")}
    assert "3 months without data" in svg


def test_tracker_edge_cases():
    cases = [
        (MONTHS[:1], [("Ally", [9.5])]),                          # single month
        (MONTHS, [("Flat", [10.0] * 40), ("Flat too", [10.0] * 40)]),  # all equal
        (MONTHS[:6], [("Island", [None, 9.0, None, None, 9.4, None])]),  # isolated points
        (["2024-01", "garbage", "2024-03"], [("Raw", [1, 2, 3])]),  # unparseable months
        ([], [("A", [1])]),
        (MONTHS, []),
        (MONTHS, [("Nothing", [None] * 40)]),
        (MONTHS[:3], [("Short list", [9.0]), ("Long list", [1, 2, 3, 4, 5, 6])]),
    ]
    for compact in (False, True):
        for k, (months, series) in enumerate(cases):
            svg = charts.tracker_svg(months, series, f"tr-{k}", y_label="Typical APR \u2014 all", compact=compact)
            _check(svg, f"tr-{k}", compact=compact)
    island = ET.fromstring(charts.tracker_svg(MONTHS[:6], cases[2][1], "tr-i"))
    assert len(list(island.iter(NS + "circle"))) >= 2


# ---------------------------------------------------------------- compact variants


def _jordan_charts(compact):
    steps = [("Credit score 660", 1.6), ("Used car, 2019 model", 0.9), ("72-month term", 0.4),
             ("Financing $1,000 more than the price", 0.3), ("Loan amount $18,500", -0.6)]
    series = [("Your offer", _interest(18500, 15.9, 72)), ("Typical loan", _interest(18500, 12.5, 72)),
              ("Low end of range", _interest(18500, 9.9, 72))]
    lenders = [("Ally", [9.1 + 0.03 * i for i in range(40)]),
               ("CarMax", [12.4 - 0.02 * i if i not in (10, 11, 12) else None for i in range(40)]),
               ("Santander Consumer", [15.2 + 0.04 * i if i > 5 else None for i in range(40)])]
    gaps = {"TX": {"gap": 1.2, "holds": True}, "MA": {"gap": -1.4, "holds": True},
            "NV": {"gap": 0.5, "holds": False}, "OH": {"gap": 0.0, "holds": True}}
    return {
        "dist": charts.distribution_svg(QUANTILES, 15.9, 9.9, 15.9, 12.5, "dist", compact=compact),
        "time": charts.timeline_svg(series, "time", highlight="Your offer", compact=compact),
        "wf": charts.waterfall_svg("Typical loan in the data", 12.1, steps, "Your typical rate", 14.4, "wf",
                                   compact=compact),
        "map": charts.tile_map_svg(gaps, "map", "APR gap by state", compact=compact),
        "trk": charts.tracker_svg(MONTHS, lenders, "trk", compact=compact),
    }


def test_compact_variants_pass_every_rule():
    wide, narrow = _jordan_charts(False), _jordan_charts(True)
    for uid in wide:
        _check(wide[uid], uid, white_ok=uid == "map")
        _check(narrow[uid], uid, white_ok=uid == "map", compact=True)
        # Same numbers in both summaries; only the waterfall's axis start may differ (fewer ticks when compact).
        same = [re.sub(r" The scale starts at [\d.]+%, not zero\.", "", ET.fromstring(s).find(NS + "desc").text)
                for s in (wide[uid], narrow[uid])]
        assert same[0] == same[1], uid
    # Both variants of all five charts on one page: every id is unique.
    ids = re.findall(r'id="([^"]+)"', "".join(wide.values()) + "".join(narrow.values()))
    assert len(ids) == len(set(ids)) == 20, ids


def test_compact_is_keyword_only():
    for call in (lambda: charts.distribution_svg(QUANTILES, 15.9, 9.9, 15.9, 12.5, "x", True),
                 lambda: charts.timeline_svg([("A", [1])], "x", None, True),
                 lambda: charts.waterfall_svg("S", 1, [], "E", 1, "x", True),
                 lambda: charts.tile_map_svg({}, "x", "t", True),
                 lambda: charts.tracker_svg(MONTHS, [("A", [1])], "x", "APR", True)):
        try:
            call()
        except TypeError:
            continue
        raise AssertionError("compact must be keyword-only")


def test_compact_layouts():
    narrow = {k: ET.fromstring(v) for k, v in _jordan_charts(True).items()}
    # Distribution: the two labels always sit on rows of their own; 3-4 ticks.
    boxes = _label_boxes(narrow["dist"])
    assert boxes["Typical"][0] != boxes["Your"][0], boxes
    ticks = [t for t in _texts(narrow["dist"]) if re.fullmatch(r"\d+(\.\d+)?%", t)]
    assert 3 <= len(ticks) <= 4, ticks
    # Line charts: one legend row per line (no end labels squeezed beside the lines), fewer ticks.
    for key, n in (("time", 3), ("trk", 3)):
        legend = [t for t in narrow[key].iter(NS + "text") if float(t.get("x")) == 34]
        assert len(legend) == n and len({t.get("y") for t in legend}) == n, key
    texts = _texts(narrow["time"])
    assert len([t for t in texts if re.fullmatch(r"\$[\d,]+", t)]) <= 4
    assert "12 mo" not in texts and "24 mo" in texts
    texts = _texts(narrow["trk"])
    assert "Jan 2024" in texts and not any(t.startswith("Jul ") for t in texts)
    # Waterfall: each label is left-aligned on its own line above its bar.
    labels = [t for t in narrow["wf"].iter(NS + "text") if t.find(NS + "tspan") is not None]
    bars = _bars(narrow["wf"])
    assert all(t.get("text-anchor") == "start" for t in labels)
    for label, bar in zip(labels[1:-1], bars):
        last_baseline = max(float(s.get("y")) for s in label.iter(NS + "tspan"))
        assert last_baseline < float(bar.get("y")), (label, bar.get("y"))
    # Tile map: the same 51-tile grid, with the legend below it.
    tiles = list(_tiles(narrow["map"]))
    assert len(tiles) == 51
    grid_bottom = max(float(r.get("y")) + float(r.get("height")) for r, _ in tiles)
    caption = next(t for t in narrow["map"].iter(NS + "text") if "".join(t.itertext()).startswith("APR gap"))
    assert float(caption.get("y")) > grid_bottom
    for rect, text in tiles:
        assert charts.contrast(text.get("fill"), rect.get("fill")) >= 4.5


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
