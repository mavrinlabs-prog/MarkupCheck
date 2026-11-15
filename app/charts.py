"""Inline SVG charts for MarkupCheck's results panel.

Each public function returns one self-contained <svg> string for gr.HTML. Standard library only and no
external references, because the page's Content-Security-Policy forbids outside requests. The colours repeat
AdmitPath's constants from app.py; app.py isn't imported so this module stays importable on its own.

Text only ever uses TEXT, SECONDARY, MUTED or BRAND_TEXT, which keep 4.5:1 on the glass card behind the
charts (about #E8EDF3). ACCENT is 4.3:1 there, so it colours marks only. The tile map is the one exception:
each state code is TEXT or white, whichever reaches 4.5:1 on that tile's own fill.
"""

import bisect
import html
import math
import re

PALETTE = {
    "ACCENT": "#4A6FA5",
    "BRAND_TEXT": "#3A5A7E",
    "BRAND_DARK": "#2E4A6E",
    "PRIMARY_LIGHT": "#E8EFF8",
    "TEXT": "#1B2030",
    "SECONDARY": "#454B5E",
    "MUTED": "#535B6E",
    "ERROR": "#DC2626",
    "ERROR_TEXT": "#991B1B",
    "ERROR_LIGHT": "#FEE2E2",
    "HAIRLINE": "rgba(0,0,0,0.09)",
}
CARD = "#E8EDF3"  # the card behind every chart: contrast is checked against it, and dot rings use it
WHITE = "#FFFFFF"
TEXT_COLORS = (PALETTE["TEXT"], PALETTE["SECONDARY"], PALETTE["MUTED"], PALETTE["BRAND_TEXT"])

_ACCENT, _BRAND_DARK, _BRAND_TEXT = PALETTE["ACCENT"], PALETTE["BRAND_DARK"], PALETTE["BRAND_TEXT"]
_TEXT, _SECONDARY, _MUTED = PALETTE["TEXT"], PALETTE["SECONDARY"], PALETTE["MUTED"]
_ERROR, _ERROR_TEXT, _HAIRLINE = PALETTE["ERROR"], PALETTE["ERROR_TEXT"], PALETTE["HAIRLINE"]
_AXIS = "rgba(0,0,0,0.2)"
_MINUS = "−"
_W = 600         # wide variant: a 560 px column at about 100%
_W_NARROW = 340  # compact variant: a 300-340 px phone column, so 12 units render at about 11-12 px
_NUMS = "font-variant-numeric:tabular-nums"


# ---------------------------------------------------------------- numbers and text


def _finite(value):
    """A finite float, or None for None, text, booleans, nan and inf."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _n(value) -> str:
    """A coordinate for an attribute: at most one decimal, never nan or inf."""
    number = _finite(value)
    text = f"{number or 0.0:.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return "0" if text == "-0" else text


def _dec(value: float) -> str:
    """Two decimals with trailing zeros trimmed, keeping at least one: 11.0, 15.9, 15.99."""
    text = f"{abs(float(value)):.2f}".rstrip("0")
    return text + "0" if text.endswith(".") else text


def _pct(value: float) -> str:
    """APR the way app.py prints it: 11.0%, 15.9%, 15.99%."""
    return ("-" if value < 0 and _dec(value) != "0.0" else "") + _dec(value) + "%"


def _signed(value: float) -> str:
    """A change in APR points with a real minus sign: +0.9, −1.3, 0.0."""
    if _dec(value) == "0.0":
        return "0.0"
    return ("+" if value > 0 else _MINUS) + _dec(value)


def _usd(value: float) -> str:
    text = f"${abs(value):,.0f}"
    return _MINUS + text if value < 0 and text != "$0" else text


def _tick_pct(value: float) -> str:
    text = f"{round(value, 6) + 0.0:.2f}".rstrip("0").rstrip(".")
    return text + "%"


def _label(value) -> str:
    """A caller's label on one line, with em dashes turned into en dashes (escaped later, on output)."""
    text = "" if value is None else str(value)
    return " ".join(text.replace("\u2014", "\u2013").split())


def _esc(value) -> str:
    return html.escape(str(value))


def _uid(uid) -> str:
    """Ids must not contain spaces (aria-labelledby is a space-separated list), so keep a safe subset."""
    return re.sub(r"[^A-Za-z0-9_-]+", "-", str(uid or "")).strip("-") or "mc-chart"


def _tw(text: str, size: float, bold: bool = False) -> float:
    """Estimated rendered width of `text` in Inter, in viewBox units (measured against Chromium)."""
    total = 0.0
    for ch in text:
        if ch in "il.,:;'|!":
            total += 0.26
        elif ch in " ()[]/-tfrj":
            total += 0.36
        elif ch.isdigit() or ch in "$+=?" + _MINUS:
            total += 0.62
        elif ch == "%":
            total += 0.84
        elif ch in "mwMW":
            total += 0.86
        elif ch.isupper():
            total += 0.68
        else:
            total += 0.56
    return total * size * (1.06 if bold else 1.0)


def _text(x, y, content, fill=_TEXT, size=12, anchor="start", weight=None, nums=False) -> str:
    attrs = f'x="{_n(x)}" y="{_n(y)}" fill="{fill}" font-size="{size}"'
    if anchor != "start":
        attrs += f' text-anchor="{anchor}"'
    if weight:
        attrs += f' font-weight="{weight}"'
    if nums:
        attrs += f' style="{_NUMS}"'
    return f"<text {attrs}>{_esc(content)}</text>"


def _line(x1, y1, x2, y2, stroke, width=1.0, dash=None, cap=None, opacity=None) -> str:
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    extra += f' stroke-linecap="{cap}"' if cap else ""
    extra += f' stroke-opacity="{opacity}"' if opacity is not None else ""
    return (f'<line x1="{_n(x1)}" y1="{_n(y1)}" x2="{_n(x2)}" y2="{_n(y2)}" stroke="{stroke}" '
            f'stroke-width="{width}"{extra}/>')


def _hit(x, y, w, h, tip) -> str:
    """An invisible hover target carrying a native tooltip (no script: the CSP and gr.HTML allow none)."""
    return (f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(max(w, 1))}" height="{_n(max(h, 1))}" fill="#000" '
            f'fill-opacity="0"><title>{_esc(tip)}</title></rect>')


def _svg(uid, width, height, title, desc, body, compact=False) -> str:
    """The root element. The compact variant's ids end in "n" so both variants can sit on one page."""
    u = _uid(uid) + ("n" if compact else "")
    variant = "mc-chart-narrow" if compact else "mc-chart-wide"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_n(width)} {_n(height)}" role="img" '
            f'aria-labelledby="{u}-t {u}-d" class="mc-chart {variant}" width="100%" '
            f'preserveAspectRatio="xMidYMid meet" font-family="inherit" style="height:auto">'
            f'<title id="{u}-t">{_esc(title)}</title><desc id="{u}-d">{_esc(desc)}</desc>{body}</svg>')


def _empty(uid, title, message, compact=False) -> str:
    width = _W_NARROW if compact else _W
    return _svg(uid, width, 44, title, message, _text(width / 2, 27, message, _MUTED, 13, "middle"), compact)


# ---------------------------------------------------------------- colour


def _rgb(color: str):
    h = color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _luminance(color: str) -> float:
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in _rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG 2 contrast ratio between two #RRGGBB colours."""
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _mix(a: str, b: str, share: float) -> str:
    share = min(max(share, 0.0), 1.0)
    return "#" + "".join(f"{round(x + (y - x) * share):02X}" for x, y in zip(_rgb(a), _rgb(b)))


# ---------------------------------------------------------------- scales


def _steps(span: float):
    exp = math.floor(math.log10(max(span, 1e-9) / 12))
    for k in range(exp, exp + 8):
        for m in (1, 2, 2.5, 5):
            yield m * 10 ** k


def _nice_axis(lo: float, hi: float, max_n: int, min_n: int = 3):
    """Round outward to the tightest round step giving min_n..max_n ticks; returns (lo, hi, ticks)."""
    if hi - lo < 1e-9:
        hi = lo + 1
    best = None
    exp = math.floor(math.log10((hi - lo) / 12))
    for k in range(exp, exp + 8):
        for rank, mult in enumerate((1, 2, 5, 2.5, 4, 3)):
            step = mult * 10 ** k
            a = math.floor(lo / step + 1e-9) * step
            b = math.ceil(hi / step - 1e-9) * step
            count = round((b - a) / step) + 1
            if min_n <= count <= max_n and (best is None or (round(b - a, 9), rank) < best[0]):
                best = ((round(b - a, 9), rank), a, step, count)
    if best is None:
        return lo, hi, [lo, hi]
    _, a, step, count = best
    ticks = [round(a + i * step, 9) for i in range(count)]
    return ticks[0], ticks[-1], ticks


def _ticks_within(lo: float, hi: float, min_n: int = 4, max_n: int = 6):
    """Round ticks inside [lo, hi], aiming for min_n..max_n of them."""
    best, best_cost = [], None
    for step in _steps(hi - lo):
        first, last = math.ceil(lo / step - 1e-9), math.floor(hi / step + 1e-9)
        ticks = [round(k * step, 9) for k in range(first, last + 1)]
        if min_n <= len(ticks) <= max_n:
            return ticks
        cost = min_n - len(ticks) if len(ticks) < min_n else len(ticks) - max_n
        if ticks and (best_cost is None or cost < best_cost):
            best, best_cost = ticks, cost
        if len(ticks) < min_n:
            break
    return best


# ---------------------------------------------------------------- 1. distribution


def _pchip(xs, ys):
    """Monotone cubic (Fritsch-Carlson) interpolant: it never overshoots the data, so a density stays >= 0."""
    n = len(xs)
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    d = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]
    m = [d[0]] * n
    if n > 2:
        for i in range(1, n - 1):
            if d[i - 1] * d[i] <= 0:
                m[i] = 0.0
            else:
                w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
                m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])

        def edge(h0, h1, d0, d1):
            slope = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
            if slope * d0 <= 0:
                return 0.0
            return 3 * d0 if d0 * d1 <= 0 and abs(slope) > abs(3 * d0) else slope

        m[0], m[-1] = edge(h[0], h[1], d[0], d[1]), edge(h[-1], h[-2], d[-1], d[-2])

    def at(x):
        i = min(max(bisect.bisect_right(xs, x) - 1, 0), n - 2)
        t = (x - xs[i]) / h[i]
        return ((1 + 2 * t) * (1 - t) ** 2 * ys[i] + t * (1 - t) ** 2 * h[i] * m[i]
                + t * t * (3 - 2 * t) * ys[i + 1] + t * t * (t - 1) * h[i] * m[i + 1])

    return at


def _histogram(quantiles, low, high, bins):
    """Equal-width bin edges and smoothed bin masses (summing to 1) for the predicted APR distribution, or None
    if the quantiles span no width.

    The CDF runs linearly through the quantiles, so two quantiles that nearly coincide only move their
    probability into one bin instead of drawing a needle. Beyond the outer quantiles the density falls linearly
    to zero (a quadratic CDF), starting at the average density over the outer tenth of probability, and the
    tails reach past low and high. The outermost bin at each end starts empty, and a [1, 2, 1] / 4 kernel then
    smooths the masses into them, so the area tapers instead of ending in a cliff and the total stays 1."""
    pts = []
    for item in quantiles or []:
        try:
            p, q = _finite(item[0]), _finite(item[1])
        except (TypeError, IndexError, KeyError):
            continue
        if p is not None and q is not None and 0 <= p <= 1:
            pts.append((p, q))
    pts.sort()
    xs, ys = [], []
    for p, q in pts:
        if ys and p <= ys[-1]:
            continue
        xs.append(max(q, xs[-1]) if xs else q)  # crossed quantiles: hold the APR
        ys.append(p)
    if len(xs) < 2 or xs[-1] - xs[0] < 1e-6:
        return None
    span = xs[-1] - xs[0]

    def edge_density(order):
        first = order[0]
        far = next((j for j in order if abs(ys[j] - ys[first]) >= 0.1), order[-1])
        dq, dp = abs(xs[far] - xs[first]), abs(ys[far] - ys[first])
        return dp / dq if dq > 1e-9 else None

    d_left, d_right = edge_density(range(len(xs))), edge_density(range(len(xs) - 1, -1, -1))
    w_left = min(2 * ys[0] / d_left, 0.6 * span) if d_left else 0.0
    w_right = min(2 * (1 - ys[-1]) / d_right, 0.6 * span) if d_right else 0.0
    a, b = xs[0] - w_left, xs[-1] + w_right
    if low is not None and low <= a:
        a = low - 0.02 * span
    if high is not None and high >= b:
        b = high + 0.02 * span

    def cdf(x):
        if x <= a:
            return 0.0
        if x >= b:
            return 1.0
        if x < xs[0]:
            return ys[0] * ((x - a) / (xs[0] - a)) ** 2
        if x >= xs[-1]:
            return 1 - (1 - ys[-1]) * ((b - x) / (b - xs[-1])) ** 2
        i = bisect.bisect_right(xs, x) - 1
        return ys[i] + (ys[i + 1] - ys[i]) * (x - xs[i]) / (xs[i + 1] - xs[i])

    pad = (b - a) / (bins - 2)
    edges = [a - pad + (b - a + 2 * pad) * k / bins for k in range(bins + 1)]
    raw = [cdf(edges[k + 1]) - cdf(edges[k]) for k in range(bins)]
    masses = [0.0] * bins
    for k, m in enumerate(raw):
        masses[k] += m / 2
        masses[max(k - 1, 0)] += m / 4
        masses[min(k + 1, bins - 1)] += m / 4
    return edges, masses


_BINS = 16          # wide: 14 bins carry data, plus an empty one at each end before smoothing
_BINS_COMPACT = 11  # compact: 9 plus the two ends


def _density(quantiles, low, high, bins=_BINS, samples=121):
    """Sampled (APR, density) pairs for the soft area: a monotone cubic through the smoothed histogram's bin
    densities, pinned to zero at both ends. It never rises above the tallest bin. None without a histogram."""
    hist = _histogram(quantiles, low, high, bins)
    if hist is None:
        return None
    edges, masses = hist
    width = edges[1] - edges[0]
    centres = [(edges[k] + edges[k + 1]) / 2 for k in range(bins)]
    at = _pchip([edges[0]] + centres + [edges[-1]], [0.0] + [m / width for m in masses] + [0.0])
    grid = [edges[0] + (edges[-1] - edges[0]) * k / (samples - 1) for k in range(samples)]
    curve = [(x, max(at(x), 0.0)) for x in grid]
    return curve if max(v for _, v in curve) > 0 else None


def _top_labels(items, width, stack=False):
    """Place the 'Typical' and 'Your offer' labels: one row if they fit (and `stack` is off), else two.
    Returns (rows, placed) where placed maps key -> (anchor, x, row)."""
    def centered(it):
        left = it["x"] - it["w"] / 2
        if left < 4:
            return "start", 4, 4, 4 + it["w"]
        if left + it["w"] > width - 4:
            return "end", width - 4, width - 4 - it["w"], width - 4
        return "middle", it["x"], left, left + it["w"]

    def outward(it, side):
        if side < 0:
            ax = it["x"] - 6
            return ("end", ax, ax - it["w"], ax) if ax - it["w"] >= 4 else None
        ax = it["x"] + 6
        return ("start", ax, ax, ax + it["w"]) if ax + it["w"] <= width - 4 else None

    if not items:
        return 0, {}
    if len(items) == 1:
        anchor, x, _, _ = centered(items[0])
        return 1, {items[0]["key"]: (anchor, x, 0)}
    first, second = sorted(items, key=lambda it: (it["x"], it["key"] != "typ"))
    if not stack:
        a, b = centered(first), centered(second)
        if a[3] + 12 <= b[2]:
            return 1, {first["key"]: (a[0], a[1], 0), second["key"]: (b[0], b[1], 0)}
        a, b = outward(first, -1), outward(second, +1)
        if a and b and a[3] + 12 <= b[2]:
            return 1, {first["key"]: (a[0], a[1], 0), second["key"]: (b[0], b[1], 0)}
    by_key = {it["key"]: it for it in items}
    offer, typ = by_key["offer"], by_key["typ"]
    o = centered(offer)
    side = -1 if typ["x"] <= offer["x"] else +1
    t = outward(typ, side) or outward(typ, -side) or centered(typ)
    return 2, {"offer": (o[0], o[1], 0), "typ": (t[0], t[1], 1)}


def distribution_svg(quantiles: list[tuple[float, float]], offer_apr: float, low: float, high: float,
                     typical: float, uid: str, *, compact: bool = False) -> str:
    """Predicted APRs for similar loans as a smooth density, with the 80% range, the typical APR and the offer.
    compact=True lays it out 340 wide for a phone column, with the two labels on rows of their own."""
    offer, lo_r, hi_r, typ = (_finite(v) for v in (offer_apr, low, high, typical))
    if lo_r is not None and hi_r is not None and lo_r > hi_r:
        lo_r, hi_r = hi_r, lo_r
    curve = _density(quantiles, lo_r, hi_r, _BINS_COMPACT if compact else _BINS)
    title = "Where your APR sits among similar loans"
    marks = [v for v in (lo_r, hi_r, typ, offer) if v is not None]
    xs_all = marks + ([curve[0][0], curve[-1][0]] if curve else [])
    if not xs_all:
        return _empty(uid, title, "No APR data to show.", compact)
    width = _W_NARROW if compact else _W

    parts = []
    if curve:
        parts.append("The curve shows how common each APR is among similar loans.")
    if lo_r is not None and hi_r is not None:
        parts.append(f"80% of similar loans have an APR between {_pct(lo_r)} and {_pct(hi_r)}.")
    if typ is not None:
        parts.append(f"The typical APR is {_pct(typ)}.")
    if offer is not None:
        sentence = f"Your offer is {_pct(offer)}"
        if lo_r is not None and hi_r is not None:
            where = "below" if offer < lo_r else "above" if offer > hi_r else "inside"
            sentence += f", {where} that range"
        if typ is not None:
            gap = offer - typ
            if _dec(gap) == "0.0":
                sentence += ", the same as the typical APR"
            else:
                sentence += f", {_dec(gap)} points {'above' if gap > 0 else 'below'} the typical APR"
        parts.append(sentence + ".")
    desc = " ".join(parts)

    x_min, x_max = min(xs_all), max(xs_all)
    if x_max - x_min < 2:
        mid = (x_min + x_max) / 2
        x_min, x_max = mid - 1, mid + 1
    pad = 0.04 * (x_max - x_min)
    x_min, x_max = x_min - pad, x_max + pad
    left, right = (14, width - 14) if compact else (20, width - 20)

    def X(v):
        return left + (v - x_min) / (x_max - x_min) * (right - left)

    items = []
    if typ is not None:
        text = "Typical " + _pct(typ)
        items.append({"key": "typ", "x": X(typ), "text": text, "w": _tw(text, 13, True)})
    if offer is not None:
        text = "Your offer " + _pct(offer)
        items.append({"key": "offer", "x": X(offer), "text": text, "w": _tw(text, 14, True)})
    rows, placed = _top_labels(items, width, stack=compact)
    row_y = (18, 36)
    top = 14 + 18 * rows
    base = top + (96 if compact else 110)
    height = base + 30

    body = []
    # The 80% band sits behind everything.
    if lo_r is not None and hi_r is not None:
        bx, bw = X(lo_r), max(X(hi_r) - X(lo_r), 2)
        body.append(f'<g><title>{_esc(f"80% range: {_pct(lo_r)} to {_pct(hi_r)}")}</title>'
                    f'<rect x="{_n(bx)}" y="{_n(top - 4)}" width="{_n(bw)}" height="{_n(base - top + 4)}" rx="4" '
                    f'fill="{_ACCENT}" fill-opacity="0.22" stroke="{_ACCENT}" stroke-width="1.5"/></g>')
    curve_px = []
    if curve:
        d_max = max(dv for _, dv in curve)
        curve_px = [(X(x), base - dv / d_max * (base - top)) for x, dv in curve]
        top_path = " ".join(f"{'M' if k == 0 else 'L'}{_n(x)},{_n(y)}" for k, (x, y) in enumerate(curve_px))
        area = f"M{_n(curve_px[0][0])},{_n(base)} " + top_path.replace("M", "L", 1) + \
               f" L{_n(curve_px[-1][0])},{_n(base)} Z"
        body.append(f'<path d="{area}" fill="{_ACCENT}" fill-opacity="0.1"/>')
        body.append(f'<path d="{top_path}" fill="none" stroke="{_ACCENT}" stroke-width="2" '
                    f'stroke-linejoin="round" stroke-linecap="round"/>')
    body.append(_line(left, base, right, base, _AXIS))
    ticks = _ticks_within(x_min, x_max, 3, 4) if compact else _ticks_within(x_min, x_max, 4, 6)
    for t in ticks:
        x = X(t)
        label = _tick_pct(t)
        w = _tw(label, 12)
        anchor, tx = ("start", 2) if x - w / 2 < 2 else ("end", width - 2) if x + w / 2 > width - 2 else \
            ("middle", x)
        body.append(_line(x, base, x, base + 4, _AXIS))
        body.append(_text(tx, base + 18, label, _MUTED, 12, anchor, nums=True))

    # "80% range" inside the band, where it crosses neither the curve nor a marker line.
    if lo_r is not None and hi_r is not None:
        text, w = "80% range", _tw("80% range", 12)
        blockers = [X(v) for v in (typ, offer) if v is not None]
        text_top, text_base = base - 19, base - 7
        for anchor, tx, l_edge in (("start", X(lo_r) + 6, X(lo_r) + 6), ("end", X(hi_r) - 6, X(hi_r) - 6 - w)):
            r_edge = l_edge + w
            if l_edge < X(lo_r) + 4 or r_edge > X(hi_r) - 4:
                continue
            if any(l_edge - 6 <= bx <= r_edge + 6 for bx in blockers):
                continue
            if any(l_edge - 2 <= cx <= r_edge + 2 and cy > text_top - 2 for cx, cy in curve_px):
                continue
            body.append(_text(tx, text_base, text, _SECONDARY, 12, anchor))
            break

    if typ is not None:
        x = X(typ)
        y0 = row_y[placed["typ"][2]] + 5
        body.append(f'<g><title>{_esc("Typical " + _pct(typ))}</title>{_line(x, y0, x, base, _ACCENT, 2)}'
                    f'{_hit(x - 6, y0, 12, base - y0, "Typical " + _pct(typ))}</g>')
        anchor, tx, row = placed["typ"]
        body.append(_text(tx, row_y[row], "Typical " + _pct(typ), _BRAND_TEXT, 13, anchor, "600", nums=True))
    if offer is not None:
        x = X(offer)
        y0 = row_y[placed["offer"][2]] + 5
        body.append(f'<g class="mc-offer">{_line(x, y0, x, base + 6, _TEXT, 3.5, cap="round")}'
                    f'{_hit(x - 8, y0, 16, base + 6 - y0, "Your offer " + _pct(offer))}</g>')
        anchor, tx, row = placed["offer"]
        body.append(_text(tx, row_y[row], "Your offer " + _pct(offer), _TEXT, 14, anchor, "700", nums=True))
    return _svg(uid, width, height, title, desc, "".join(body), compact)


# ---------------------------------------------------------------- line charts (2 and 5)


def _segments(points):
    """Split [(x, y or None)] at the Nones; returns lists of consecutive (x, y)."""
    runs, run = [], []
    for x, y in points:
        if y is None:
            if run:
                runs.append(run)
            run = []
        else:
            run.append((x, y))
    if run:
        runs.append(run)
    return runs


def _densify(run_px):
    out = list(run_px)
    for (x1, y1), (x2, y2) in zip(run_px, run_px[1:]):
        steps = max(1, int(math.hypot(x2 - x1, y2 - y1) / 4))
        out += [(x1 + (x2 - x1) * k / steps, y1 + (y2 - y1) * k / steps) for k in range(1, steps)]
    return out


def _place_end_labels(ends, obstacles, top, bottom, right, size):
    """Vertical centres for labels set right of each line's end, or None when they would collide."""
    gap = size + 4
    order = sorted(range(len(ends)), key=lambda k: ends[k][1])
    ys, prev = [0.0] * len(ends), -1e9
    for k in order:
        ys[k] = max(ends[k][1], prev + gap)
        prev = ys[k]
    if prev > bottom:
        ys = [y - (prev - bottom) for y in ys]
    for k, (px, py, w) in enumerate(ends):
        if ys[k] < top or abs(ys[k] - py) > size:
            return None
        x0, x1 = px + 6, px + 10 + w
        y0, y1 = ys[k] - size * 0.62, ys[k] + size * 0.45
        if x1 > right:
            return None
        for j, pts in enumerate(obstacles):
            if j != k and any(x0 <= x <= x1 and y0 <= y <= y1 for x, y in pts):
                return None
    return ys


def _line_chart(uid, title, desc, lines, x_dom, tick_sets, y_dom, y_ticks, hover, y_label=None, compact=False):
    """lines: dicts with pts [(x, y or None)], color, width, dash, strong, end_text, name. The compact variant
    puts each line's label on a legend row of its own above the plot instead of beside the line's end."""
    size = 13
    width = _W_NARROW if compact else _W
    plot_left = math.ceil(max((_tw(lbl, 12) for _, lbl in y_ticks), default=20)) + 14
    label_ws = [_tw(ln["end_text"], size, ln["strong"]) for ln in lines]
    modes = ("direct", "legend") if not compact and max(label_ws) <= 0.42 * width else ("legend",)
    x_lo, x_hi = x_dom
    y_lo, y_hi = y_dom
    for mode in modes:
        plot_right = width - 14 - max(label_ws) if mode == "direct" else width - (12 if compact else 16)
        y0 = 4
        body = []
        if y_label:
            body.append(_text(4, y0 + 12, y_label, _MUTED, 12, weight="600"))
            y0 += 20
        if mode == "legend":
            x, rows = 4.0, [[]]
            for ln, w in zip(lines, label_ws):
                item_w = 30 + w
                if rows[-1] and (compact or x + item_w > width - 4):
                    rows.append([])
                    x = 4.0
                rows[-1].append((x, ln))
                x += item_w + 20
            for r, row in enumerate(rows):
                y = y0 + 14 + r * 20
                for x, ln in row:
                    body.append(_line(x, y - 4, x + 24, y - 4, ln["color"], ln["width"], ln["dash"],
                                      None if ln["dash"] else "round"))
                    body.append(_text(x + 30, y, ln["end_text"], _TEXT if ln["strong"] else _SECONDARY, size,
                                      weight="700" if ln["strong"] else None, nums=True))
            y0 += 20 * len(rows) + 4
        top = y0 + 10
        base = top + (150 if compact else 170)
        height = base + 30

        def X(v):
            if x_hi - x_lo < 1e-9:
                return (plot_left + plot_right) / 2
            return plot_left + (v - x_lo) / (x_hi - x_lo) * (plot_right - plot_left)

        def Y(v):
            return base - (v - y_lo) / (y_hi - y_lo) * (base - top)

        px_lines = [[[(X(x), Y(y)) for x, y in run] for run in _segments(ln["pts"])] for ln in lines]
        ends = []
        for ln, runs, w in zip(lines, px_lines, label_ws):
            ex, ey = runs[-1][-1]
            ends.append((ex, ey, w))
        label_ys = None
        if mode == "direct":
            obstacles = [[p for run in runs for p in _densify(run)] for runs in px_lines]
            label_ys = _place_end_labels(ends, obstacles, top - 4, base, width - 2, size)
            if label_ys is None:
                continue

        for v, lbl in y_ticks:
            y = Y(v)
            body.append(_line(plot_left, y, plot_right, y, _AXIS if abs(v - y_lo) < 1e-9 else _HAIRLINE))
            body.append(_text(plot_left - 8, y + 4, lbl, _MUTED, 12, "end", nums=True))
        ticks = tick_sets[-1]
        for candidate in tick_sets:
            pos = [(X(v), _tw(lbl, 12)) for v, lbl in candidate]
            if all(b[0] - a[0] >= (a[1] + b[1]) / 2 + 10 for a, b in zip(pos, pos[1:])):
                ticks = candidate
                break
        for v, lbl in ticks:
            x, w = X(v), _tw(lbl, 12)
            anchor, tx = ("end", width - 2) if x + w / 2 > width - 2 else ("middle", x)
            body.append(_line(x, base, x, base + 4, _AXIS))
            body.append(_text(tx, base + 18, lbl, _MUTED, 12, anchor, nums=True))
        for ln, runs in sorted(zip(lines, px_lines), key=lambda pair: pair[0]["strong"]):
            for run in runs:
                if len(run) == 1:
                    body.append(f'<circle cx="{_n(run[0][0])}" cy="{_n(run[0][1])}" r="3" fill="{ln["color"]}"/>')
                    continue
                d = " ".join(f"{'M' if k == 0 else 'L'}{_n(x)},{_n(y)}" for k, (x, y) in enumerate(run))
                dash = f' stroke-dasharray="{ln["dash"]}" stroke-linecap="butt"' if ln["dash"] else \
                    ' stroke-linecap="round"'
                body.append(f'<path d="{d}" fill="none" stroke="{ln["color"]}" stroke-width="{ln["width"]}" '
                            f'stroke-linejoin="round"{dash}/>')
        for ln, (ex, ey, _) in zip(lines, ends):
            body.append(f'<circle cx="{_n(ex)}" cy="{_n(ey)}" r="4" fill="{ln["color"]}" stroke="{CARD}" '
                        f'stroke-width="2"/>')
        if label_ys is not None:
            for ln, (ex, _, _), ly in zip(lines, ends, label_ys):
                body.append(_text(ex + 8, ly + size * 0.35, ln["end_text"], _TEXT if ln["strong"] else _SECONDARY,
                                  size, weight="700" if ln["strong"] else "500", nums=True))
        for a, b, tip in hover:
            xa, xb = max(X(a), plot_left), min(X(b), plot_right)
            if xb > xa:
                body.append(_hit(xa, top, xb - xa, base - top, tip))
        return _svg(uid, width, height, title, desc, "".join(body), compact)
    return _empty(uid, title, desc, compact)


def timeline_svg(series: list[tuple[str, list[float]]], uid: str, highlight: str | None = None, *,
                 compact: bool = False) -> str:
    """Cumulative interest paid by month, one line per loan, labelled at each line's end (compact=True: 340
    wide, each label on a legend row of its own, fewer ticks)."""
    title = "Interest paid over the loan"
    clean = []
    for item in series or []:
        try:
            name, values = item
        except (TypeError, ValueError):
            continue
        values = list(values) if isinstance(values, (list, tuple)) else []
        pts = [(0, 0.0)] + [(i + 1, _finite(v)) for i, v in enumerate(values)]
        if any(y is not None for _, y in pts[1:]):
            clean.append((_label(name) or f"Loan {len(clean) + 1}", pts))
    if not clean:
        return _empty(uid, title, "No interest data to show.", compact)
    wanted = _label(highlight) if highlight is not None else None
    if not any(name == wanted for name, _ in clean):
        wanted = None
    others = iter([(_ACCENT, 2, None), (_SECONDARY, 2, "7 4"), (_BRAND_DARK, 2, "2 3"), (_TEXT, 2, "10 3 2 3")])
    lines, finals = [], []
    for name, pts in clean:
        last_x, last_y = [(x, y) for x, y in pts if y is not None][-1]
        finals.append((name, last_x, last_y))
        strong = name == wanted
        color, width, dash = (_TEXT, 3, None) if strong else next(others, (_SECONDARY, 2, "1 3"))
        lines.append({"name": name, "pts": pts, "color": color, "width": width, "dash": dash, "strong": strong,
                      "end_text": f"{name} {_usd(last_y)}"})
    n_max = max(x for _, x, _ in finals)
    v_max = max(y for _, pts in clean for _, y in pts if y is not None)
    v_min = min(0.0, min(y for _, pts in clean for _, y in pts if y is not None))
    y_lo, y_hi, y_ticks = _nice_axis(v_min, v_max if v_max > v_min else v_min + 100, 4 if compact else 5)
    tick_sets = [[(m, f"{m} mo") for m in range(step, n_max + 1, step)]
                 for step in ((24, 48) if compact else (12, 24, 48))]
    tick_sets = [t for t in tick_sets if t] or [[(n_max, f"{n_max} mo")]]

    parts = ["Interest paid so far, by month of the loan."]
    parts += [f"{name}: {_usd(v)} after {m} month{'s' if m != 1 else ''}." for name, m, v in finals]
    if wanted is not None:
        mine = next(v for name, _, v in finals if name == wanted)
        for name, _, v in finals:
            if name != wanted and _usd(mine - v).lstrip(_MINUS) != "$0":
                more = "more" if mine > v else "less"
                parts.append(f"{wanted} costs {_usd(abs(mine - v))} {more} in interest than {name}.")
    hover = []
    for m in range(1, n_max + 1):
        cells = []
        for name, pts in clean:
            if m >= len(pts):
                cells.append(f"{name} paid off")
            else:
                cells.append(f"{name} {_usd(pts[m][1])}" if pts[m][1] is not None else f"{name} no data")
        hover.append((m - 0.5, m + 0.5, f"Month {m}: " + ", ".join(cells)))
    return _line_chart(uid, title, " ".join(parts), lines, (0, n_max), tick_sets, (y_lo, y_hi),
                       [(t, _usd(t)) for t in y_ticks], hover, compact=compact)


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def tracker_svg(months: list[str], series: list[tuple[str, list[float | None]]], uid: str,
                y_label: str = "Typical APR", *, compact: bool = False) -> str:
    """Typical APR by month for each lender; None is a month without data and breaks the line (compact=True:
    340 wide, each lender on a legend row of its own, yearly ticks)."""
    y_label = _label(y_label) or "Typical APR"
    title = f"{y_label} by month"
    months = [_label(m) for m in (months or [])]
    if not months:
        return _empty(uid, title, "No monthly data to show.", compact)
    ords = []
    for m in months:
        match = re.fullmatch(r"(\d{4})-(\d{1,2})", m)
        ords.append(int(match.group(1)) * 12 + int(match.group(2)) - 1
                    if match and 1 <= int(match.group(2)) <= 12 else None)
    parsed = None not in ords and all(b > a for a, b in zip(ords, ords[1:]))
    xs = ords if parsed else list(range(len(months)))
    names = [f"{_MONTHS[o % 12]} {o // 12}" for o in ords] if parsed else months

    clean = []
    for item in series or []:
        try:
            name, values = item
        except (TypeError, ValueError):
            continue
        values = list(values) if isinstance(values, (list, tuple)) else []
        ys = [_finite(values[i]) if i < len(values) else None for i in range(len(months))]
        if any(y is not None for y in ys):
            clean.append((_label(name) or f"Lender {len(clean) + 1}", ys))
    if not clean:
        return _empty(uid, title, "No monthly data to show.", compact)

    styles = [(_ACCENT, 2, None), (_BRAND_DARK, 2, "7 4"), (_SECONDARY, 2, "2 3"), (_TEXT, 2, "10 3 2 3"),
              (_ACCENT, 2, "1 4"), (_BRAND_DARK, 2, "12 4")]
    lines, parts = [], []
    for k, (name, ys) in enumerate(clean):
        color, width, dash = styles[k % len(styles)]
        valid = [(i, y) for i, y in enumerate(ys) if y is not None]
        (i0, first), (i1, last) = valid[0], valid[-1]
        lines.append({"name": name, "pts": list(zip(xs, ys)), "color": color, "width": width, "dash": dash,
                      "strong": False, "end_text": f"{name} {_pct(last)}"})
        sentence = f"{name}: {_pct(first)} in {names[i0]}"
        sentence += f", {_pct(last)} in {names[i1]}" if i1 != i0 else ""
        values = [y for _, y in valid]
        if len(values) > 2:
            sentence += f"; lowest {_pct(min(values))}, highest {_pct(max(values))}"
        gaps = len(months) - len(values)
        if gaps:
            sentence += f"; {gaps} month{'s' if gaps != 1 else ''} without data"
        parts.append(sentence + ".")
    every = [y for _, ys in clean for y in ys if y is not None]
    v_lo, v_hi = min(every), max(every)
    if v_hi - v_lo < 0.2:
        v_lo, v_hi = v_lo - 0.5, v_hi + 0.5
    y_lo, y_hi, y_ticks = _nice_axis(v_lo, v_hi, 4 if compact else 5)
    tick_steps = (12, 24) if compact else (6, 12, 24)
    if parsed:
        tick_sets = [[(o, f"{_MONTHS[o % 12]} {o // 12}") for o in ords if o % step == 0] for step in tick_steps]
    else:
        tick_sets = [[(i, months[i]) for i in range(0, len(months), step)] for step in tick_steps]
    tick_sets = [t for t in tick_sets if t] or [[(xs[0], names[0])]]
    if len(tick_sets[0]) < 2 and len(months) > 1:
        tick_sets.insert(0, [(xs[0], names[0]), (xs[-1], names[-1])])
    hover = []
    for i, x in enumerate(xs):
        a = (xs[i - 1] + x) / 2 if i else x - 0.5
        b = (xs[i + 1] + x) / 2 if i + 1 < len(xs) else x + 0.5
        cells = [f"{name} {_pct(ys[i])}" if ys[i] is not None else f"{name} no data" for name, ys in clean]
        hover.append((a, b, f"{names[i]}: " + ", ".join(cells)))
    desc = f"{y_label} by month, {names[0]} to {names[-1]}. " + " ".join(parts)
    return _line_chart(uid, title, desc, lines, (xs[0], xs[-1]), tick_sets, (y_lo, y_hi),
                       [(t, _tick_pct(t)) for t in y_ticks], hover, y_label, compact)


# ---------------------------------------------------------------- 3. waterfall


def _wrap(text, size, width, bold=False, max_lines=2):
    lines, current = [], ""
    for word in text.split(" "):
        trial = f"{current} {word}".strip()
        if current and _tw(trial, size, bold) > width:
            lines.append(current)
            current = word
        else:
            current = trial
    lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and _tw(last + "…", size, bold) > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def _hbar(x0, x1, y, h, radius, broken):
    """A horizontal bar from x0 (square baseline end) to x1 (rounded data end); with `broken`, a slanted gap
    near x0 marks an axis that doesn't start at zero."""
    r = min(radius, max(x1 - x0, 0) / 2, h / 2)
    top, bot = y - h / 2, y + h / 2
    parts = []
    start_top = start_bot = x0
    if broken and x1 - x0 > 24:
        parts.append(f'<path d="M{_n(x0)},{_n(top)} H{_n(x0 + 7)} L{_n(x0 + 4)},{_n(bot)} H{_n(x0)} Z"/>')
        start_top, start_bot = x0 + 11, x0 + 8
    parts.append(f'<path d="M{_n(start_top)},{_n(top)} H{_n(x1 - r)} A{_n(r)},{_n(r)} 0 0 1 {_n(x1)},{_n(top + r)} '
                 f'V{_n(bot - r)} A{_n(r)},{_n(r)} 0 0 1 {_n(x1 - r)},{_n(bot)} H{_n(start_bot)} Z"/>')
    return "".join(parts)


def waterfall_svg(start_label: str, start_value: float, steps: list[tuple[str, float]], end_label: str,
                  end_value: float, uid: str, *, compact: bool = False) -> str:
    """APR points from the typical loan in the data to your typical rate, one bar per one-at-a-time effect
    (compact=True: 340 wide, each label on its own line above its bar)."""
    title = "What moves the typical rate for a loan like yours"
    start, end = _finite(start_value), _finite(end_value)
    if start is None or end is None:
        return _empty(uid, title, "No rate breakdown to show.", compact)
    clean = []
    for item in steps or []:
        try:
            label, value = item
        except (TypeError, ValueError):
            continue
        value = _finite(value)
        if value is not None:
            clean.append((_label(label) or "Other detail", value))
    residual = end - (start + sum(v for _, v in clean))
    if round(abs(residual), 9) >= 0.05:
        clean.append(("Other and combined effects", residual))

    rows = [("start", _label(start_label) or "Start", start, start, start)]
    running = start
    for label, value in clean:
        rows.append(("step", label, value, running, running + value))
        running += value
    rows.append(("end", _label(end_label) or "End", end, end, end))

    values = [v for r in rows for v in (r[3], r[4])] + [start, end]
    v_min, v_max = min(values), max(values)
    span = max(v_max - v_min, 0.5)
    # Steps of a point or two vanish on a 0-15% scale, so the axis starts near the lowest total when the steps
    # span less than half the largest total; the start and end bars then show a break.
    truncate = v_min > 0 and v_max - v_min < 0.5 * v_max
    lo_target = v_min - 0.3 * span if truncate else min(0.0, v_min)
    lo, hi, ticks = _nice_axis(lo_target, v_max + 0.02 * span, *((4, 3) if compact else (6, 4)))
    broken = lo > 0
    bar_h = 16

    # layout: per row, (anchor, x, label baselines, bar centre y).
    if compact:
        # Each label gets a line of its own above its bar, so the bars keep the full width.
        width = _W_NARROW
        bar_x0, bar_x1 = 6, width - 56
        wrapped = [_wrap(r[1], 13, width - 12, r[0] != "step") for r in rows]
        layout, y = [], 4
        for lines in wrapped:
            baselines = [y + 13 + 15 * i for i in range(len(lines))]
            cy = baselines[-1] + 7 + bar_h / 2
            layout.append(("start", bar_x0, baselines, cy))
            y = cy + bar_h / 2 + 8
        top, bottom = 4, y
    else:
        width = _W
        col_w = min(max(_tw(r[1], 13, r[0] != "step") for r in rows), 210)
        bar_x0, bar_x1 = 24 + col_w, width - 58
        wrapped = [_wrap(r[1], 13, col_w, r[0] != "step") for r in rows]
        row_h = 36 if any(len(w) > 1 for w in wrapped) else 30
        top = 8
        layout = []
        for k, lines in enumerate(wrapped):
            cy = top + row_h * k + row_h / 2
            first_y = cy + 4.5 - (len(lines) - 1) * 7.5
            layout.append(("end", 12 + col_w, [first_y + 15 * i for i in range(len(lines))], cy))
        bottom = top + row_h * len(rows)
    height = bottom + 28

    def X(v):
        return bar_x0 + (v - lo) / (hi - lo) * (bar_x1 - bar_x0)

    body = []
    for t in ticks:
        x = X(t)
        if compact:  # gridlines would cross the label lines, so the compact axis keeps tick marks only
            body.append(_line(x, bottom, x, bottom + 4, _AXIS))
        else:
            body.append(_line(x, top, x, bottom, _HAIRLINE))
        label = _tick_pct(t)
        w = _tw(label, 12)
        anchor, tx = ("start", 2) if x - w / 2 < 2 else ("end", width - 2) if x + w / 2 > width - 2 else \
            ("middle", x)
        body.append(_text(tx, bottom + 18, label, _MUTED, 12, anchor, nums=True))
    body.append(_line(bar_x0, bottom, bar_x1, bottom, _AXIS))
    for k, ((kind, label, value, a, b), lines, (anchor, label_x, baselines, cy)) in \
            enumerate(zip(rows, wrapped, layout)):
        strong = kind != "step"
        spans = "".join(f'<tspan x="{_n(label_x)}" y="{_n(by)}">{_esc(line)}</tspan>'
                        for line, by in zip(lines, baselines))
        weight = ' font-weight="600"' if strong else ""
        body.append(f'<text fill="{_TEXT if strong else _SECONDARY}" font-size="13" text-anchor="{anchor}"'
                    f'{weight}>{spans}</text>')
        if strong:
            x_end = X(value)
            tip = f"{label}: {_pct(value)}"
            body.append(f'<g fill="{_BRAND_DARK}"><title>{_esc(tip)}</title>'
                        f'{_hbar(bar_x0, max(x_end, bar_x0 + 2), cy, bar_h, 4, broken)}</g>')
            body.append(_text(x_end + 6, cy + 4.5, _pct(value), _TEXT, 13, weight="700", nums=True))
        else:
            xa, xb = sorted((X(a), X(b)))
            color = _SECONDARY if value > 0 else _ACCENT if value < 0 else _MUTED
            w = max(xb - xa, 2)
            if xb - xa < 2:
                xa -= (2 - (xb - xa)) / 2
            tip = f"{label}: {_signed(value)} points"
            body.append(f'<rect x="{_n(xa)}" y="{_n(cy - bar_h / 2)}" width="{_n(w)}" height="{bar_h}" rx="3" '
                        f'fill="{color}"><title>{_esc(tip)}</title></rect>')
            text = _signed(value)
            tw = _tw(text, 13, True)
            if value < 0 and xa - 6 - tw >= bar_x0 + 2:
                body.append(_text(xa - 6, cy + 4.5, text, _TEXT, 13, "end", "600", nums=True))
            else:
                body.append(_text(xa + w + 6, cy + 4.5, text, _TEXT, 13, weight="600", nums=True))
        if k + 1 < len(rows):
            x = X(b)
            next_anchor, next_x, next_baselines, next_cy = layout[k + 1]
            if compact:
                # The connector would run through the next row's label line; draw it only clear of the text.
                next_w = max(_tw(line, 13, rows[k + 1][0] != "step") for line in wrapped[k + 1])
                if next_x - 3 <= x <= next_x + next_w + 3:
                    continue
            body.append(_line(x, cy + bar_h / 2, x, next_cy - bar_h / 2, _MUTED, 1, opacity=0.6))

    parts = [f"{rows[0][1]}: {_pct(start)}."]
    parts += [f"{label}: {_signed(value)} points." for _, label, value, _, _ in rows[1:-1]]
    parts.append(f"{rows[-1][1]}: {_pct(end)}.")
    parts.append("Each step changes one detail at a time.")
    if any(label == "Other and combined effects" for _, label, *_ in rows[1:-1]):
        parts.append("Other and combined effects is what is left, so the steps add up exactly.")
    if broken:
        parts.append(f"The scale starts at {_tick_pct(lo)}, not zero.")
    return _svg(uid, width, height, title, " ".join(parts), "".join(body), compact)


# ---------------------------------------------------------------- 4. tile map

# The common NPR-style square tile grid: (column, row) on a 12 x 8 grid.
_TILES = {
    "AK": (0, 0), "ME": (11, 0), "VT": (10, 1), "NH": (11, 1),
    "WA": (1, 2), "ID": (2, 2), "MT": (3, 2), "ND": (4, 2), "MN": (5, 2), "IL": (6, 2), "WI": (7, 2),
    "MI": (8, 2), "NY": (9, 2), "RI": (10, 2), "MA": (11, 2),
    "OR": (1, 3), "NV": (2, 3), "WY": (3, 3), "SD": (4, 3), "IA": (5, 3), "IN": (6, 3), "OH": (7, 3),
    "PA": (8, 3), "NJ": (9, 3), "CT": (10, 3),
    "CA": (1, 4), "UT": (2, 4), "CO": (3, 4), "NE": (4, 4), "MO": (5, 4), "KY": (6, 4), "WV": (7, 4),
    "VA": (8, 4), "MD": (9, 4), "DE": (10, 4),
    "AZ": (2, 5), "NM": (3, 5), "KS": (4, 5), "AR": (5, 5), "TN": (6, 5), "NC": (7, 5), "SC": (8, 5),
    "DC": (9, 5),
    "OK": (4, 6), "LA": (5, 6), "MS": (6, 6), "AL": (7, 6), "GA": (8, 6),
    "HI": (1, 7), "TX": (4, 7), "FL": (9, 7),
}
STATE_NAMES = _STATE_NAMES = {
    "AK": "Alaska", "AL": "Alabama", "AR": "Arkansas", "AZ": "Arizona", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DC": "District of Columbia", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "IA": "Iowa", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "MA": "Massachusetts", "MD": "Maryland", "ME": "Maine",
    "MI": "Michigan", "MN": "Minnesota", "MO": "Missouri", "MS": "Mississippi", "MT": "Montana",
    "NC": "North Carolina", "ND": "North Dakota", "NE": "Nebraska", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NV": "Nevada", "NY": "New York", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VA": "Virginia", "VT": "Vermont", "WA": "Washington",
    "WI": "Wisconsin", "WV": "West Virginia", "WY": "Wyoming",
}
_MID = "#F3F4F6"      # diverging midpoint: a neutral gray just lighter than the card
_MISSING = "#DCE1E8"  # no data: flat, darker than the card, no outline
_CAP = 1.5            # |gap| at which the fill reaches full strength


def _ink(fill):
    """TEXT or white, whichever has more contrast on `fill`; None if neither reaches 4.5:1."""
    ratio, color = max((contrast(c, fill), c) for c in (_TEXT, WHITE))
    return color if ratio >= 4.5 else None


def _tile_style(gap, holds):
    pole = _ERROR if gap > 0 else _ACCENT
    share = 0.0 if _dec(gap) == "0.0" else 0.14 + 0.86 * min(abs(gap) / _CAP, 1.0)
    if not holds:
        share *= 0.45
    fill, ink = _mix(_MID, pole, share), None
    for _ in range(60):
        # Mid-tone fills where neither TEXT nor white reaches 4.5:1 step towards the pole, which passes with white.
        ink = _ink(fill)
        if ink:
            break
        share = min(1.0, share + 0.02)
        fill = _mix(_MID, pole, share)
    stroke = _ERROR_TEXT if gap > 0 and _dec(gap) != "0.0" else _BRAND_DARK if gap < 0 and _dec(gap) != "0.0" \
        else _SECONDARY
    return fill, ink or WHITE, stroke


def tile_map_svg(values: dict[str, dict], uid: str, title: str, *, compact: bool = False) -> str:
    """APR gap vs similar loans by state on a square tile grid; dashed tiles didn't survive the multiple-testing
    check (compact=True: 340 wide, the same grid with a smaller legend below it)."""
    title = _label(title) or "APR gap by state"
    data = {}
    for key, entry in (values or {}).items() if isinstance(values, dict) else []:
        code = str(key).strip().upper()
        if code not in _TILES or not isinstance(entry, dict):
            continue
        gap = _finite(entry.get("gap"))
        if gap is not None:
            data[code] = (gap, bool(entry.get("holds")))
    width = _W_NARROW if compact else _W
    pitch, tile, ox, oy, code_size = (28, 26, 3, 4, 12) if compact else (48, 44, 14, 8, 13)
    body = []
    for code, (col, row) in _TILES.items():
        x, y = ox + col * pitch, oy + row * pitch
        name = _STATE_NAMES[code]
        if code in data:
            gap, holds = data[code]
            fill, ink, stroke = _tile_style(gap, holds)
            outline = f'stroke="{stroke}" stroke-width="2"' if holds else \
                f'stroke="{stroke}" stroke-width="1.5" stroke-dasharray="4 3"'
            if _dec(gap) == "0.0":
                tip = f"{name}: about the same as similar loans"
            else:
                tip = f"{name}: pays {_dec(gap)} points {'more' if gap > 0 else 'less'} than similar loans"
            tip += " (holds up)" if holds else " (could be chance)"
        else:
            fill, ink, outline = _MISSING, _MUTED if contrast(_MUTED, _MISSING) >= 4.5 else _TEXT, 'stroke="none"'
            tip = f"{name}: no data"
        body.append(f'<g class="mc-tile"><title>{_esc(tip)}</title>'
                    f'<rect x="{_n(x + 1)}" y="{_n(y + 1)}" width="{tile - 2}" height="{tile - 2}" rx="4" '
                    f'fill="{fill}" {outline}/>'
                    f'{_text(x + tile / 2, y + tile / 2 + code_size * 0.35, code, ink, code_size, "middle", "600")}'
                    f'</g>')

    # Wide: the legend fills the grid's empty top band (columns 1-9 of rows 0-1). Compact: a smaller one below.
    if compact:
        lx, ly = 4, oy + 8 * pitch + 14
        swatch, step, height = 18, 20, oy + 8 * pitch + 98
    else:
        lx, ly = ox + pitch + 4, 22
        swatch, step, height = 24, 26, oy + 8 * pitch + 4
    body.append(_text(lx, ly, "APR gap vs similar loans, in points", _SECONDARY, 12, weight="600"))
    ramp_x = lx + _tw("Pays less", 12) + 8
    body.append(_text(lx, ly + 19, "Pays less", _SECONDARY, 12))
    stops = (-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5)
    for k, g in enumerate(stops):
        body.append(f'<rect x="{_n(ramp_x + k * step)}" y="{_n(ly + 8)}" width="{swatch}" height="14" rx="2" '
                    f'fill="{_tile_style(g, True)[0]}"/>')
    for k, lbl in ((0, f"{_MINUS}1.5"), (3, "0"), (6, "+1.5")):
        body.append(_text(ramp_x + k * step + swatch / 2, ly + 36, lbl, _MUTED, 12, "middle", nums=True))
    more_x = ramp_x + len(stops) * step + 6
    body.append(_text(more_x, ly + 19, "Pays more", _SECONDARY, 12))
    solid, dashed = ("Solid: holds up after testing many states", "Dashed: could be chance") if compact else \
        ("Solid outline: the gap holds up after testing many states", "Dashed outline: the gap could be chance")
    for row, (text, dash) in enumerate(((solid, None), (dashed, "3 2"))):
        ky = ly + 45 + 18 * row
        outline = f'stroke-width="1.5" stroke-dasharray="{dash}"' if dash else 'stroke-width="2"'
        body.append(f'<rect x="{_n(lx + 1)}" y="{_n(ky)}" width="12" height="12" rx="2" '
                    f'fill="{_tile_style(0.9, dash is None)[0]}" stroke="{_ERROR_TEXT}" {outline}/>')
        body.append(_text(lx + 20, ky + 10, text, _SECONDARY, 12))
    if len(data) < len(_TILES):
        if compact:  # beside the dashed key, which is the shorter of the two lines
            nx, ny = lx + 20 + _tw(dashed, 12) + 18, ly + 63
        else:
            nx, ny = more_x + _tw("Pays more", 12) + 16, ly + 8
        body.append(f'<rect x="{_n(nx)}" y="{_n(ny)}" width="14" height="14" rx="2" fill="{_MISSING}"/>')
        body.append(_text(nx + 19, ny + 11, "No data", _SECONDARY, 12))

    def listed(items):
        return ", ".join(f"{_STATE_NAMES[c]} {_signed(g)}" for c, g in items)

    held = [(c, g) for c, (g, h) in data.items() if h]
    more = sorted([p for p in held if p[1] > 0 and _dec(p[1]) != "0.0"], key=lambda p: -p[1])[:3]
    less = sorted([p for p in held if p[1] < 0 and _dec(p[1]) != "0.0"], key=lambda p: p[1])[:3]
    if not data:
        desc = "No state data to show."
    else:
        desc = (f"APR gap versus similar loans, in points, for {len(data)} of 51 states and DC; "
                f"{len(held)} hold up after a multiple-testing check. ")
        desc += f"Largest confirmed gaps where buyers pay more: {listed(more)}. " if more else \
            "No confirmed gaps where buyers pay more. "
        desc += f"Largest confirmed gaps where buyers pay less: {listed(less)}." if less else \
            "No confirmed gaps where buyers pay less."
        missing = len(_TILES) - len(data)
        if missing:
            desc += f" {missing} have no data."
    return _svg(uid, width, height, title, desc, "".join(body), compact)
