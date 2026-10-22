"""Chart artifacts, drawn to the diagram-design skill (default profile, dark variant).

Each chart is a self-contained HTML file in outputs/charts/ that passes the
skill's self_check.py and lint-skin.py. The web app embeds the identical <svg>
node, extracted from that file, so the browser never shows an unvalidated chart.

Size preset: `fit` (derived from content) at a 360-unit width, standard type
ramp, 40-unit outer margins and a bottom legend strip. This keeps chart text
near its nominal size on a phone; on desktop the SVG scales up.

Colours are the dark column of the shipped style guide only; lint-skin rejects
anything else.
"""

from __future__ import annotations

import math
import re
from html import escape
from pathlib import Path

PAPER = "#2d3142"
INK = "#f5f5f5"
MUTED = "#bfc0c0"
ACCENT = "#f08a59"
INK_A = "rgba(245,245,245,{a})"
MUTED_A = "rgba(191,192,192,{a})"
ACCENT_A = "rgba(240,138,89,{a})"

W = 360
L, R = 40, 320  # outer margins
R_EDGE = R
SANS = "'Geist', sans-serif"
MONO = "'Geist Mono', monospace"
FONT_LINK = ("https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1"
             "&family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500;600&display=swap")
MONTH_INITIAL = "JFMAMJJASOND"


def esc(s) -> str:
    return escape(str(s), quote=True)


def t(x, y, text, size=9, fill=MUTED, font=MONO, anchor="start", weight=None, extra="") -> str:
    w = f' font-weight="{weight}"' if weight else ""
    a = f' text-anchor="{anchor}"' if anchor != "start" else ""
    return (f'<text x="{x:g}" y="{y:g}" fill="{fill}" font-size="{size:g}" font-family="{font}"{w}{a}{extra}>'
            f"{esc(text)}</text>")


def text_width(s: str, size: float, mono: bool = False) -> float:
    return len(s) * size * (0.62 if mono else 0.6)


def nice_step(v: float, target: int = 4) -> float:
    """Round tick step (1, 2, 2.5 or 5 x 10^k) giving about `target` intervals up to v."""
    raw = max(v, 1e-9) / target
    exp = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if m * exp >= raw:
            return m * exp
    return 10 * exp


def nice_ceil(v: float) -> float:
    """Smallest multiple of the nice step that contains v (the axis domain ceiling)."""
    if v <= 0:
        return 1.0
    step = nice_step(v)
    return step * math.ceil(v / step - 1e-9)


def ticks(ceil: float) -> list[float]:
    step = nice_step(ceil)
    n = int(round(ceil / step))
    return [round(step * i, 10) for i in range(n + 1)]


def fmt(v: float) -> str:
    return f"{v:,.0f}" if v >= 100 or float(v).is_integer() else f"{v:.1f}"


def legend(y: int, items: list[str]) -> list[str]:
    """Horizontal legend strip: rule, LEGEND eyebrow, then the key row."""
    out = [f'<line x1="{L}" y1="{y}" x2="{R}" y2="{y}" stroke="{INK_A.format(a=0.10)}" stroke-width="0.8"/>',
           t(L, y + 16, "LEGEND", 8, MUTED, MONO, extra=' letter-spacing="0.18em"')]
    out += items
    return out


def wrap_words(text: str, width: int) -> list[str]:
    """Split a source note into lines of at most `width` characters, on word boundaries."""
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}" if cur else word
    return lines + ([cur] if cur else [])


def source_line(y: float, text: str) -> str:
    return t(L, y, text, 8, MUTED, MONO)


def svg_doc(slug: str, title: str, desc: str, height: int, body: list[str]) -> str:
    return "\n".join([
        f'<svg viewBox="0 0 {W} {height}" xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-labelledby="{slug}-title {slug}-desc" data-chart="{slug}">',
        f'<title id="{slug}-title">{esc(title)}</title>',
        f'<desc id="{slug}-desc">{esc(desc)}</desc>',
        f'<rect width="100%" height="100%" fill="{PAPER}"/>',
        *body,
        "</svg>",
    ])


def html_doc(slug: str, eyebrow: str, title: str, svg: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc(title)}</title>
  <link href="{FONT_LINK}" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{ --color-paper: {PAPER}; --color-ink: {INK}; --color-muted: {MUTED}; --color-accent: {ACCENT};
      --font-sans: 'Geist', system-ui, sans-serif; --font-serif: 'Instrument Serif', serif; --font-mono: 'Geist Mono', ui-monospace, monospace; }}
    body {{ font-family: var(--font-sans); background: var(--color-paper); color: var(--color-ink); min-height: 100vh;
      display: flex; align-items: center; justify-content: center; padding: 2rem 1rem; }}
    .frame {{ max-width: 560px; width: 100%; }}
    .eyebrow {{ font-family: var(--font-mono); font-size: 0.66rem; font-weight: 500; letter-spacing: 0.18em;
      text-transform: uppercase; color: var(--color-muted); margin-bottom: 0.5rem; }}
    h1 {{ font-family: var(--font-serif); font-size: clamp(1.5rem, 2.4vw + 0.75rem, 2rem); font-weight: 400;
      letter-spacing: -0.02em; line-height: 1.15; margin-bottom: 1.5rem; }}
    svg {{ width: 100%; display: block; }}
  </style>
</head>
<body>
  <div class="frame">
    <p class="eyebrow">{esc(eyebrow)} · Spotify Rewind</p>
    <h1>{esc(title)}</h1>
{svg}
  </div>
</body>
</html>
"""


# ---------------------------------------------------------------- bar (horizontal)

def bar_chart(slug: str, spec: dict) -> tuple[str, int]:
    bars = spec["bars"]
    ceil = nice_ceil(max(b["value"] for b in bars))
    x0, x1 = 88, 272
    sx = lambda v: x0 + v / ceil * (x1 - x0)
    top, pitch, bh = 56, 32, 20
    bottom = top + pitch * len(bars)
    focal = max(range(len(bars)), key=lambda i: bars[i]["value"])
    out = [t(L, 36, spec["unit"], 8, MUTED, MONO, extra=' letter-spacing="0.14em"')]
    for v in ticks(ceil):
        x = sx(v)
        stroke = INK_A.format(a=0.20) if v == 0 else INK_A.format(a=0.08)
        out.append(f'<line x1="{x:.1f}" y1="{top - 8}" x2="{x:.1f}" y2="{bottom}" stroke="{stroke}" stroke-width="{1 if v == 0 else 0.8}"/>')
        out.append(t(x, bottom + 14, fmt(v), 8, MUTED, MONO, "middle"))
    for i, b in enumerate(bars):
        y = top + i * pitch
        w = sx(b["value"]) - x0
        is_f = i == focal
        fill = ACCENT_A.format(a=0.14) if is_f else MUTED_A.format(a=0.15)
        stroke = ACCENT if is_f else MUTED
        label = b["label"] + ("*" if b["partial"] else "")
        out.append(f'<g data-reveal="{i + 1}" data-bar="{esc(b["label"])}" data-value="{b["value"]}">')
        out.append(t(80, y + 14, label, 11, INK, SANS, "end", 600))
        out.append(f'<rect x="{x0}" y="{y}" width="{w:.1f}" height="{bh}" fill="{PAPER}"/>')
        out.append(f'<rect x="{x0}" y="{y}" width="{w:.1f}" height="{bh}" fill="{fill}" stroke="{stroke}" stroke-width="1"/>')
        out.append(t(x0 + w + 6, y + 14, fmt(b["value"]), 9, ACCENT if is_f else MUTED, MONO))
        out.append("</g>")
    ly = bottom + 32
    keys = [f'<rect x="{L}" y="{ly + 26}" width="16" height="8" fill="{ACCENT_A.format(a=0.14)}" stroke="{ACCENT}" stroke-width="1"/>',
            t(L + 22, ly + 33, "Highest year", 8.5, MUTED, SANS),
            f'<rect x="{L + 120}" y="{ly + 26}" width="16" height="8" fill="{MUTED_A.format(a=0.15)}" stroke="{MUTED}" stroke-width="1"/>',
            t(L + 142, ly + 33, "Other years", 8.5, MUTED, SANS)]
    out += legend(ly, keys)
    out.append(source_line(ly + 52, spec["source"]))
    return "\n".join(out), ly + 64


# ---------------------------------------------------------------- dumbbell

def dumbbell_chart(slug: str, spec: dict) -> tuple[str, int]:
    rows = spec["rows"]
    hi = max(max(r["from"], r["to"]) for r in rows) * 100
    ceil = nice_ceil(hi) if hi > 0 else 1.0
    x0, x1 = 72, 288
    sx = lambda v: round(x0 + v * 100 / ceil * (x1 - x0))
    top, pitch = 48, 40
    bottom = top + pitch * len(rows)
    out = [t(L, 32, "SHARE OF MUSIC MINUTES", 8, MUTED, MONO, extra=' letter-spacing="0.14em"')]
    for v in ticks(ceil):
        x = sx(v / 100)
        stroke = INK_A.format(a=0.20) if v == 0 else INK_A.format(a=0.08)
        out.append(f'<line x1="{x}" y1="{top}" x2="{x}" y2="{bottom}" stroke="{stroke}" stroke-width="{1 if v == 0 else 0.8}"/>')
        out.append(t(x, bottom + 14, f"{fmt(v)}%", 8, MUTED, MONO, "middle"))
    for i, r in enumerate(rows):
        yn = top + i * pitch + 14
        yd = yn + 12
        xa, xb = sx(r["from"]), sx(r["to"])
        rad = 6 if abs(xa - xb) >= 16 else 4
        left, right = (min(xa, xb), max(xa, xb))
        la = f"{r['from'] * 100:.1f}%" if xa <= xb else f"{r['to'] * 100:.1f}%"
        ra = f"{r['to'] * 100:.1f}%" if xa <= xb else f"{r['from'] * 100:.1f}%"
        out.append(f'<g data-reveal="{i + 1}" data-series="{esc(r["name"])}" data-from="{r["from"]}" data-to="{r["to"]}">')
        out.append(t(L, yn, r["name"], 11, INK, SANS, weight=600))
        out.append(f'<line x1="{xa}" y1="{yd}" x2="{xb}" y2="{yd}" stroke="{INK_A.format(a=0.40)}" stroke-width="1"/>')
        out.append(f'<circle cx="{xa}" cy="{yd}" r="{rad}" fill="{PAPER}" stroke="{MUTED}" stroke-width="1.5"/>')
        out.append(f'<circle cx="{xb}" cy="{yd}" r="{rad}" fill="{ACCENT}" stroke="{INK}" stroke-width="1"/>')
        out.append(t(left - 10, yd + 3, la, 8, MUTED, MONO, "end"))
        out.append(t(right + 10, yd + 3, ra, 8, MUTED, MONO))
        out.append("</g>")
    ly = bottom + 32
    keys = [f'<circle cx="{L + 6}" cy="{ly + 30}" r="5" fill="{PAPER}" stroke="{MUTED}" stroke-width="1.5"/>',
            t(L + 16, ly + 33, spec["from_label"], 8.5, MUTED, SANS),
            f'<circle cx="{L + 126}" cy="{ly + 30}" r="5" fill="{ACCENT}" stroke="{INK}" stroke-width="1"/>',
            t(L + 136, ly + 33, spec["to_label"], 8.5, MUTED, SANS)]
    out += legend(ly, keys)
    lines = wrap_words(spec["source"], 62)
    for k, line in enumerate(lines):
        out.append(source_line(ly + 52 + 12 * k, line))
    return "\n".join(out), ly + 52 + 12 * len(lines)


# ---------------------------------------------------------------- line (single focal series)

def line_chart(slug: str, spec: dict) -> tuple[str, int]:
    pts = spec["points"]
    ceil = nice_ceil(max(p["value"] for p in pts))
    x0, x1, y0, y1 = 72, 312, 48, 200
    n = len(pts)
    sx = lambda i: x0 + (x1 - x0) * (i / (n - 1) if n > 1 else 0.5)
    sy = lambda v: y1 - v / ceil * (y1 - y0)
    out = [t(L, 32, spec["unit"], 8, MUTED, MONO, extra=' letter-spacing="0.14em"')]
    if spec.get("band"):
        idx = [i for i, p in enumerate(pts) if spec["band"][0] <= p["label"] <= spec["band"][1]]
        if idx:
            pitch = (x1 - x0) / max(n - 1, 1)
            bx0, bx1 = sx(idx[0]) - pitch / 2, sx(idx[-1]) + pitch / 2
            out.append(f'<rect x="{bx0:.1f}" y="{y0}" width="{bx1 - bx0:.1f}" height="{y1 - y0}" fill="{MUTED_A.format(a=0.10)}"/>')
            out.append(t((bx0 + bx1) / 2, y0 + 12, "GAP", 8, MUTED, MONO, "middle", extra=' letter-spacing="0.14em"'))
    for v in ticks(ceil):
        y = sy(v)
        stroke = INK_A.format(a=0.20) if v == 0 else INK_A.format(a=0.08)
        out.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" stroke="{stroke}" stroke-width="{1 if v == 0 else 0.8}"/>')
        out.append(t(x0 - 8, y + 3, fmt(v), 8, MUTED, MONO, "end"))
    # x labels
    for i, p in enumerate(pts):
        x = sx(i)
        if spec.get("monthly"):
            yy, mm = p["label"].split("-")
            out.append(t(x, y1 + 14, MONTH_INITIAL[int(mm) - 1], 8, MUTED, MONO, "middle"))
            if i == 0 or mm == "01":
                out.append(t(x, y1 + 26, "’" + yy[2:], 8, MUTED, MONO, "middle"))
        else:
            yy, half = p["label"].split("-")
            out.append(t(x, y1 + 14, half, 8, MUTED, MONO, "middle"))
            if half == "H1" or i == 0:
                out.append(t(x, y1 + 26, yy, 8, MUTED, MONO, "middle"))
    coords = " ".join(f"{sx(i):.1f},{sy(p['value']):.1f}" for i, p in enumerate(pts))
    out.append(f'<g data-reveal="1" data-series="{esc(spec["series"])}">')
    out.append(f'<polygon points="{coords} {sx(n - 1):.1f},{y1} {sx(0):.1f},{y1}" fill="{ACCENT_A.format(a=0.08)}"/>')
    out.append(f'<polyline points="{coords}" fill="none" stroke="{ACCENT}" stroke-width="1.8" stroke-linejoin="round"/>')
    out.append("</g>")
    out.append('<g data-reveal="2">')
    any_partial = False
    for i, p in enumerate(pts):
        hollow = p.get("partial")
        any_partial |= bool(hollow)
        fill = PAPER if hollow else ACCENT
        out.append(f'<circle cx="{sx(i):.1f}" cy="{sy(p["value"]):.1f}" r="4" fill="{fill}" stroke="{ACCENT}" '
                   f'stroke-width="1.5" data-point="{esc(p["label"])}" data-value="{p["value"]}"/>')
    peak = max(range(n), key=lambda i: (pts[i]["value"], -i))
    px, py = sx(peak), sy(pts[peak]["value"])
    anchor = "end" if px > 260 else ("start" if px < 100 else "middle")
    out.append(t(px + (-8 if anchor == "end" else 8 if anchor == "start" else 0), py - 10, fmt(pts[peak]["value"]),
                 9, INK, MONO, anchor, extra=' data-peak="1"'))
    out.append("</g>")
    ly = y1 + 48
    keys = [f'<line x1="{L}" y1="{ly + 30}" x2="{L + 24}" y2="{ly + 30}" stroke="{ACCENT}" stroke-width="1.8"/>',
            f'<circle cx="{L + 12}" cy="{ly + 30}" r="4" fill="{ACCENT}"/>',
            t(L + 32, ly + 33, spec["series"], 8.5, MUTED, SANS)]
    if any_partial:
        keys += [f'<circle cx="{L + 160}" cy="{ly + 30}" r="4" fill="{PAPER}" stroke="{ACCENT}" stroke-width="1.5"/>',
                 t(L + 170, ly + 33, "Incomplete period", 8.5, MUTED, SANS)]
    out += legend(ly, keys)
    out.append(source_line(ly + 52, spec["source"]))
    return "\n".join(out), ly + 64


# ---------------------------------------------------------------- gantt (eras)

def gantt_chart(slug: str, spec: dict) -> tuple[str, int]:
    months = spec["months"]
    rows = spec["rows"]
    x0, x1 = 132, 320
    pm = (x1 - x0) / len(months)
    mx = lambda m: x0 + months.index(m) * pm
    top, pitch = 64, 40
    bottom = top + pitch * len(rows)
    out = [t(L, 32, "ERA", 8, MUTED, MONO, extra=' letter-spacing="0.14em"'),
           t(x0, 32, "MONTHS IN EXPORT", 8, MUTED, MONO, extra=' letter-spacing="0.14em"')]
    for m in months:
        if m.endswith("-01") or m == months[0]:
            x = mx(m)
            out.append(f'<line x1="{x:.1f}" y1="{top - 12}" x2="{x:.1f}" y2="{bottom}" stroke="{INK_A.format(a=0.08)}" stroke-width="0.8"/>')
            out.append(t(x + 2, top - 16, "’" + m[2:4], 8, MUTED, MONO))
    out.append(f'<line x1="{x0}" y1="{top - 8}" x2="{x1}" y2="{top - 8}" stroke="{INK_A.format(a=0.15)}" stroke-width="0.8"/>')
    for m in spec.get("excluded", []):
        x = mx(m)
        out.append(f'<rect x="{x:.1f}" y="{top - 4}" width="{pm:.1f}" height="{bottom - top}" fill="{MUTED_A.format(a=0.10)}"/>')
    for i, r in enumerate(rows):
        y = top + i * pitch
        is_f = r["id"] == spec.get("focal")
        xs, xe = mx(r["start"]), mx(r["end"]) + pm
        fill = ACCENT_A.format(a=0.14) if is_f else MUTED_A.format(a=0.15)
        stroke = ACCENT if is_f else MUTED
        dash = ' stroke-dasharray="4,3"' if r["confidence"] == "moderate" else ""
        out.append(f'<g data-reveal="{i + 1}" data-era="{r["id"]}" data-start="{r["start"]}" data-end="{r["end"]}">')
        out.append(t(L, y + 10, r["label"].upper(), 8, MUTED, MONO, extra=' letter-spacing="0.14em"'))
        out.append(t(L, y + 24, r["artist"], 11 if text_width(r["artist"], 11) <= 88 else 10, ACCENT if is_f else INK, SANS, weight=600))
        out.append(f'<rect x="{xs:.1f}" y="{y + 4}" width="{xe - xs:.1f}" height="24" rx="4" fill="{PAPER}"/>')
        out.append(f'<rect x="{xs:.1f}" y="{y + 4}" width="{xe - xs:.1f}" height="24" rx="4" fill="{fill}" stroke="{stroke}" stroke-width="1"{dash}/>')
        out.append("</g>")
    ly = bottom + 12
    keys = [f'<rect x="{L}" y="{ly + 26}" width="16" height="8" rx="2" fill="{ACCENT_A.format(a=0.14)}" stroke="{ACCENT}" stroke-width="1"/>',
            t(L + 22, ly + 33, "After biggest shift", 8.5, MUTED, SANS),
            f'<rect x="{L + 130}" y="{ly + 26}" width="16" height="8" rx="2" fill="{MUTED_A.format(a=0.15)}" stroke="{MUTED}" stroke-width="1" stroke-dasharray="4,3"/>',
            t(L + 152, ly + 33, "Moderate-confidence start", 8.5, MUTED, SANS)]
    out += legend(ly, keys)
    out.append(source_line(ly + 52, spec["source"]))
    note = "Shaded month: excluded (low activity)." if spec.get("excluded") else ""
    if note:
        out.append(source_line(ly + 64, note))
    return "\n".join(out), ly + (76 if note else 64)


# ---------------------------------------------------------------- presence (yearly top N)

def presence_chart(slug: str, spec: dict) -> tuple[str, int]:
    years = spec["years"]
    rows = spec["rows"]
    x0, pitch_x = 148, 28
    top, pitch = 56, 36
    bottom = top + pitch * len(rows)
    out = [t(L, 32, "ARTIST", 8, MUTED, MONO, extra=' letter-spacing="0.14em"'),
           t(x0, 32, "YEARLY RANK BY MINUTES", 8, MUTED, MONO, extra=' letter-spacing="0.14em"')]
    for j, y in enumerate(years):
        cx = x0 + j * pitch_x + pitch_x / 2
        out.append(t(cx, top - 8, "’" + y["label"][2:] + ("*" if y["partial"] else ""), 8, MUTED, MONO, "middle"))
    for i, r in enumerate(rows):
        y = top + i * pitch
        is_f = r["id"] == spec.get("focal")
        stroke = ACCENT if is_f else MUTED
        fill = ACCENT_A.format(a=0.14) if is_f else MUTED_A.format(a=0.15)
        out.append(f'<g data-reveal="{min(i + 1, 8)}" data-artist="{esc(r["name"])}">')
        out.append(t(L, y + 18, r["name"], 11 if text_width(r["name"], 11) <= 104 else 10, ACCENT if is_f else INK, SANS, weight=600))
        out.append(f'<line x1="{x0}" y1="{y + 14}" x2="{x0 + pitch_x * len(years)}" y2="{y + 14}" stroke="{INK_A.format(a=0.08)}" stroke-width="0.8"/>')
        # One bar per run of consecutive top-N years.
        j = 0
        while j < len(years):
            if years[j]["label"] in r["ranks"]:
                k = j
                while k + 1 < len(years) and years[k + 1]["label"] in r["ranks"]:
                    k += 1
                bx, bw = x0 + j * pitch_x + 2, (k - j + 1) * pitch_x - 4
                out.append(f'<rect x="{bx}" y="{y + 4}" width="{bw}" height="20" rx="4" fill="{PAPER}"/>')
                out.append(f'<rect x="{bx}" y="{y + 4}" width="{bw}" height="20" rx="4" fill="{fill}" stroke="{stroke}" stroke-width="1"/>')
                j = k + 1
            else:
                j += 1
        for j, yr in enumerate(years):
            rank = r["ranks"].get(yr["label"])
            if rank:
                cx = x0 + j * pitch_x + pitch_x / 2
                out.append(t(cx, y + 17.5, f"#{rank}", 9, INK, MONO, "middle",
                             extra=f' data-year="{yr["label"]}" data-rank="{rank}"'))
        out.append("</g>")
    ly = bottom + 16
    keys = [f'<rect x="{L}" y="{ly + 26}" width="16" height="8" rx="2" fill="{ACCENT_A.format(a=0.14)}" stroke="{ACCENT}" stroke-width="1"/>',
            t(L + 22, ly + 33, "Featured artist", 8.5, MUTED, SANS),
            f'<rect x="{L + 120}" y="{ly + 26}" width="16" height="8" rx="2" fill="{MUTED_A.format(a=0.15)}" stroke="{MUTED}" stroke-width="1"/>',
            t(L + 142, ly + 33, "In the top 10 that year", 8.5, MUTED, SANS)]
    out += legend(ly, keys)
    out.append(source_line(ly + 52, spec["source"]))
    return "\n".join(out), ly + 64



# ---------------------------------------------------------------- polar (listening clock)

POLAR_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <link href="{font}" rel="stylesheet">
  <style>
    html, body, div, main, header, footer, section, article, p, h1, h2, h3, h4, h5, h6 {{ box-sizing:border-box; margin:0; padding:0; }}
    :root {{ --color-paper:{paper}; --color-ink:{ink}; --color-muted:{muted}; --color-accent:{accent}; --font-sans:'Geist',system-ui,sans-serif; --font-serif:'Instrument Serif',serif; --font-mono:'Geist Mono',ui-monospace,monospace; }}
    body {{ font-family:var(--font-sans); background:var(--color-paper); color:var(--color-ink); min-height:100vh; display:flex; align-items:center; justify-content:center; padding:3rem 2rem; }}
    .frame {{ max-width:1200px; width:100%; }}
    .eyebrow {{ font-family:var(--font-mono); font-size:0.66rem; font-weight:500; letter-spacing:0.18em; text-transform:uppercase; color:var(--color-muted); margin-bottom:0.5rem; }}
    h1 {{ font-family:var(--font-serif); font-size:clamp(1.5rem,2.4vw + 0.75rem,2rem); font-weight:400; letter-spacing:-0.02em; line-height:1.15; color:var(--color-ink); margin-bottom:1.5rem; }}
    svg {{ width:100%; min-width:900px; display:block; }}
  </style>
</head>
<body>
  <div class="frame">
    <p class="eyebrow">Polar chart · Spotify Rewind</p>
    <h1>{title}</h1>
{svg}
  </div>
</body>
</html>
"""


def _r(v: float) -> str:
    return f"{round(v, 3):g}"


def polar_chart(slug: str, spec: dict) -> tuple[str, str]:
    """Polar chart per type-polar.md: one series, 4-8 cyclic categories, radius-only encoding."""
    cats = spec["categories"]
    n = len(cats)
    if not 4 <= n <= 8:
        raise ValueError("polar charts take 4-8 categories")
    vmax = nice_ceil(max(c["value"] for c in cats))
    cx, cy, R = 180, 164, 80
    height = 352
    focal = spec.get("focal")
    ang = lambda i: math.radians(-90) + 2 * math.pi * i / n
    out = [
        f'<svg viewBox="0 0 {W} {height}" xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-labelledby="{slug}-title {slug}-desc" data-chart="{slug}" data-polar-chart="" '
        f'data-polar-cx="{cx}" data-polar-cy="{cy}" data-polar-radius="{R}" data-polar-min="0" '
        f'data-polar-max="{_r(vmax)}" data-polar-start-angle="-90" data-polar-clockwise="true" '
        f'data-polar-radius-encoding="linear" data-polar-inner-radius="0">',
        f'<title id="{slug}-title">{esc(spec["title"])}</title>',
        f'<desc id="{slug}-desc">{esc(spec["desc"])}</desc>',
        f'<rect data-polar-background="" width="100%" height="100%" fill="{PAPER}"/>',
        t(L, 28, f"{spec['unit']} · 0–{fmt(vmax)}", 8, MUTED, MONO, extra=' letter-spacing="0.14em"'),
    ]
    for k in range(1, 6):
        stroke = INK_A.format(a=0.20) if k == 5 else INK_A.format(a=0.10)
        out.append(f'<circle data-polar-ring="" cx="{cx}" cy="{cy}" r="{_r(R * k / 5)}" fill="none" stroke="{stroke}" stroke-width="0.8"/>')
    for i in range(n):
        x, y = cx + R * math.cos(ang(i)), cy + R * math.sin(ang(i))
        out.append(f'<line data-polar-spoke="" data-polar-index="{i}" x1="{cx}" y1="{cy}" x2="{_r(x)}" y2="{_r(y)}" '
                   f'stroke="{INK_A.format(a=0.16)}" stroke-width="0.8"/>')
    for k in range(1, 6):
        out.append(t(cx - 8, cy - R * k / 5 + 3, fmt(vmax * k / 5), 8, MUTED, MONO, "end"))
    out.append(t(cx + 8, cy + 3, "0", 8, MUTED, MONO))
    for i, c in enumerate(cats):
        a = ang(i)
        is_f = i == focal
        v = c["value"]
        rr = R * v / vmax
        x, y = cx + rr * math.cos(a), cy + rr * math.sin(a)
        attrs = f'data-polar-category="{esc(c["label"])}" data-polar-index="{i}" data-polar-value="{_r(v)}"'
        if is_f:
            attrs += ' data-polar-focal="true"'
        out.append(f"<g {attrs}>")
        if v > 0:
            color = ACCENT if is_f else MUTED
            out.append(f'<line data-polar-ray="" x1="{cx}" y1="{cy}" x2="{_r(x)}" y2="{_r(y)}" stroke="{color}" '
                       f'stroke-width="{2.4 if is_f else 2}"/>')
            out.append(f'<circle data-polar-marker="" cx="{_r(x)}" cy="{_r(y)}" r="{5 if is_f else 4}" fill="{PAPER}" '
                       f'stroke="{color}" stroke-width="1.2"/>')
        deg = (math.degrees(a) + 360) % 360  # 270 = up, 90 = down
        near_vertical = min(abs(deg - 270), abs(deg - 90)) <= 15
        anchor = "middle" if near_vertical else ("start" if math.cos(a) > 0 else "end")
        lx, ly = cx + (R + 28) * math.cos(a), cy + (R + 28) * math.sin(a)
        vx, vy = cx + (R + 44) * math.cos(a), cy + (R + 44) * math.sin(a)
        horizontal = abs(math.sin(a)) < 0.2
        dy = 16 if horizontal else (12 if math.sin(a) > 0.2 and not near_vertical else 0)
        out.append(t(lx, ly, c["label"], 11, INK, SANS, anchor, 600))
        dy_attr = f' dy="{dy}"' if dy else ""
        out.append(f'<text data-polar-value-label="" x="{_r(vx)}" y="{_r(vy)}" fill="{MUTED}" font-size="8" '
                   f'font-family="{MONO}" text-anchor="{anchor}"{dy_attr}>{fmt(v)}</text>')
        out.append("</g>")
    out.append(f'<line data-polar-rule="" x1="{L}" y1="316" x2="{R_EDGE}" y2="316" stroke="{INK_A.format(a=0.10)}" stroke-width="0.8"/>')
    out.append(t(L, 334, spec["source"], 8, MUTED, MONO, extra=' letter-spacing="0.08em"'))
    out.append("</svg>")
    svg = "\n".join(out)
    html = POLAR_HTML.format(title=esc(spec["title"]), font=FONT_LINK, paper=PAPER, ink=INK, muted=MUTED,
                             accent=ACCENT, svg=svg)
    return svg, html

RENDERERS = {"bar": bar_chart, "dumbbell": dumbbell_chart, "line": line_chart, "gantt": gantt_chart,
             "presence": presence_chart}
EYEBROWS = {"bar": "Bar chart", "dumbbell": "Dumbbell chart", "line": "Line chart", "gantt": "Gantt chart",
            "presence": "Gantt chart"}


def render(slug: str, spec: dict) -> tuple[str, str]:
    if spec["type"] == "polar":
        return polar_chart(slug, spec)
    body, height = RENDERERS[spec["type"]](slug, spec)
    height = int(math.ceil(height / 4) * 4)
    svg = svg_doc(slug, spec["title"], spec["desc"], height, [body])
    return svg, html_doc(slug, EYEBROWS[spec["type"]], spec["title"], svg)


def extract_svg(html: str) -> str:
    m = re.search(r"<svg\b.*?</svg>", html, re.DOTALL)
    if not m:
        raise ValueError("no svg in chart html")
    return m.group(0)


def build_all(specs: dict, html_dir: Path, svg_dir: Path) -> list[Path]:
    html_dir.mkdir(parents=True, exist_ok=True)
    svg_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for slug, spec in specs.items():
        _svg, html = render(slug, spec)
        path = html_dir / f"{slug}.html"
        path.write_text(html, encoding="utf-8")
        # The app receives the svg node extracted from the validated file, byte for byte.
        (svg_dir / f"{slug}.svg").write_text(extract_svg(path.read_text(encoding="utf-8")) + "\n", encoding="utf-8")
        paths.append(path)
    return paths
