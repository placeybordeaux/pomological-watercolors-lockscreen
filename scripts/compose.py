#!/usr/bin/env python3
"""Compose desktop-sized wallpapers from prepared pomological plates.

The phone problem and the desktop problem are opposites. A phone screen is
narrower than the paintings (0.46 vs 0.65), so filling it crops the width. An
ultrawide monitor is 2.39:1 -- three and a half times wider than a plate -- so
filling it would throw away 85% of the painting. Every treatment here is a
different answer to "what goes in all that width".

    mat       one plate floated on a mat sampled from its own paper
    ledger    plate bled off the right edge, catalogue entry set on the left
    board     four plates in a row, as specimens pinned to a card
    diptych   two plates of the same fruit, facing across a centre rule
    cabinet   many plates tiled small on the copy-stand black
    bleed     a detail crop of one plate, edge to edge

Usage:
    scripts/with_pillow.sh python3 scripts/compose.py --treatment mat
    scripts/with_pillow.sh python3 scripts/compose.py --treatment all --out-dir /tmp/x
    scripts/with_pillow.sh python3 scripts/compose.py --treatment board --seed 7 --size 3440x1440
"""
from __future__ import annotations

import argparse
import colorsys
import json
import os
import random
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import botany  # noqa: E402
import pomlib  # noqa: E402

PLATE_DIR = os.path.join(pomlib.DATA_DIR, "wallpapers")
ANALYSIS = os.path.join(PLATE_DIR, "_analysis.json")
OUT_DIR = os.path.join(pomlib.DATA_DIR, "desktop")

TREATMENTS = ["mat", "ledger", "board", "diptych", "cabinet", "bleed"]

# The copy-stand backdrop the plates were photographed against, reused as the
# one non-paper ground in the set.
STAND = (20, 19, 22)

# Chrome to stay clear of: a 26px panel at the top, a 48px dock at the bottom
# (plus its shadow and hover growth), and the desktop icon column at the left.
CHROME = {"top": 40, "bottom": 96, "left": 200}


# --- typography -------------------------------------------------------------

_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _font_file(pattern: str) -> str:
    """Resolve a fontconfig pattern to a file, so no nix store path is baked in."""
    out = subprocess.run(["fc-match", "-f", "%{file}", pattern],
                         capture_output=True, text=True, check=True).stdout.strip()
    if not out:
        raise RuntimeError(f"no font matches {pattern!r}")
    return out


FACES = {
    "serif": "Noto Serif Display",
    "serif-italic": "Noto Serif Display:italic",
    "mono": "Fira Code",
}


def font(face: str, size: int) -> ImageFont.FreeTypeFont:
    key = (face, size)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ImageFont.truetype(_font_file(FACES[face]), size)
    return _FONT_CACHE[key]


def text(draw: ImageDraw.ImageDraw, xy, s: str, face: str, size: int, fill,
         anchor: str = "la", track: float = 0.0) -> float:
    """Draw a string, optionally letter-spaced, and return its advance width.

    Pillow has no tracking, so tracked text is drawn glyph by glyph. Anchors
    that measure the whole string ("ra", "ma") therefore need the width up
    front, which is why this returns it either way.
    """
    f = font(face, size)
    if not track:
        draw.text(xy, s, font=f, fill=fill, anchor=anchor)
        return draw.textlength(s, font=f)
    width = sum(draw.textlength(ch, font=f) + track for ch in s) - track
    x, y = xy
    if anchor[0] == "r":
        x -= width
    elif anchor[0] == "m":
        x -= width / 2
    for ch in s:
        draw.text((x, y), ch, font=f, fill=fill, anchor="l" + anchor[1])
        x += draw.textlength(ch, font=f) + track
    return width



def wrap_lines(draw: ImageDraw.ImageDraw, body: str, face: str, size: int,
               width: int, max_lines: int = 0) -> list[str]:
    """Greedy wrap to `width` pixels. Pillow measures but does not wrap."""
    f = font(face, size)
    lines, line = [], ""
    for w in body.split():
        trial = f"{line} {w}".strip()
        if line and draw.textlength(trial, font=f) > width:
            lines.append(line)
            line = w
        else:
            line = trial
    if line:
        lines.append(line)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .,;:") + "…"
    return lines


def block_height(lines: list[str], size: int, leading: float) -> int:
    return round(size * leading) * len(lines)


def draw_lines(draw: ImageDraw.ImageDraw, x: int, y: int, lines: list[str],
               face: str, size: int, fill, leading: float = 1.55,
               align: str = "l") -> int:
    """Draw pre-wrapped lines, returning the y below the last one."""
    f = font(face, size)
    step = round(size * leading)
    anchor = {"l": "la", "m": "ma", "r": "ra"}[align]
    for i, ln in enumerate(lines):
        draw.text((x, y + i * step), ln, font=f, fill=fill, anchor=anchor)
    return y + step * len(lines)


def paragraph(draw: ImageDraw.ImageDraw, x: int, y: int, body: str, face: str,
              size: int, fill, width: int, leading: float = 1.55,
              align: str = "l", max_lines: int = 0) -> int:
    lines = wrap_lines(draw, body, face, size, width, max_lines)
    return draw_lines(draw, x, y, lines, face, size, fill, leading, align)


# --- colour -----------------------------------------------------------------

def shift(rgb, *, light: float = 1.0, sat: float = 1.0) -> tuple[int, int, int]:
    h, l, s = colorsys.rgb_to_hls(*[c / 255 for c in rgb])
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, l * light)), max(0.0, min(1.0, s * sat)))
    return (round(r * 255), round(g * 255), round(b * 255))


def mat_for(paper) -> tuple[int, int, int]:
    """A mat board a shade deeper than the sheet it carries.

    Matching the paper exactly makes the plate dissolve into the ground; going
    much darker turns the wallpaper into a frame. ~16% down reads as mat board.
    """
    return shift(paper, light=0.82, sat=0.38)


def ink_for(ground) -> tuple[int, int, int]:
    lum = 0.2126 * ground[0] + 0.7152 * ground[1] + 0.0722 * ground[2]
    return shift(ground, light=0.30, sat=0.55) if lum > 128 else shift(ground, light=3.6, sat=0.35)


# --- plate placement --------------------------------------------------------

def paste_plate(canvas: Image.Image, plate: Image.Image, cx: int, cy: int,
                height: int, shadow: bool = True) -> tuple[int, int, int, int]:
    """Scale a plate to `height`, drop it at (cx, cy), return its box."""
    w = round(plate.width * height / plate.height)
    im = plate.resize((w, height), Image.LANCZOS)
    x, y = round(cx - w / 2), round(cy - height / 2)

    if shadow:
        # Cast from a solid rectangle rather than the image, so the blur is even
        # and the paper's own bright edge doesn't eat into it.
        pad = 60
        sh = Image.new("L", (w + pad * 2, height + pad * 2), 0)
        ImageDraw.Draw(sh).rectangle((pad, pad, pad + w, pad + height), fill=165)
        sh = sh.filter(ImageFilter.GaussianBlur(26))
        dark = Image.new("RGB", sh.size, (0, 0, 0))
        canvas.paste(dark, (x - pad, y - pad + 14), sh)

    canvas.paste(im, (x, y))
    return (x, y, x + w, y + height)


def caption(draw, x, y, meta, ink, ink_soft, *, align: str = "l", scale: float = 1.0) -> int:
    """Variety, then what it is, then the archival line. Right-aligned on `x`
    when align='r', which is what the mat treatment needs to the left of a plate."""
    anchor = "ra" if align == "r" else "la"
    s = lambda n: max(9, round(n * scale))

    text(draw, (x, y), (meta["variety"] or meta["common"] or "—"),
         "serif-italic", s(44), ink, anchor=anchor)
    y += s(62)

    line = " · ".join(p for p in (meta["common"], meta["sci"]) if p)
    if line:
        text(draw, (x, y), line, "serif", s(21), ink_soft, anchor=anchor, track=s(21) * 0.05)
        y += s(38)

    bits = [b for b in (meta["artist_short"], str(meta["year"] or ""), meta["county"]) if b]
    if bits:
        text(draw, (x, y), "  ·  ".join(bits), "mono", s(15), ink_soft,
             anchor=anchor, track=s(15) * 0.04)
        y += s(26)
    if meta["specimen"]:
        text(draw, (x, y), f"USDA {meta['pom_id']}  ·  specimen {meta['specimen']}",
             "mono", s(13), ink_soft, anchor=anchor, track=s(13) * 0.06)
        y += s(26)
    return y


# --- the pool ---------------------------------------------------------------

def artist_short(full: str | None) -> str:
    if not full:
        return ""
    surname, _, rest = full.partition(",")
    given = rest.strip().split()[0] if rest.strip() else ""
    return f"{given} {surname}".strip()


def county(geo: str | None) -> str:
    """'Farmingdale, Sangamon County, Illinois, United States' -> 'Sangamon Co., Ill.'"""
    if not geo:
        return ""
    parts = [p.strip() for p in geo.split(",")]
    co = next((p for p in parts if p.endswith("County")), "")
    state = parts[-2] if len(parts) >= 2 and parts[-1] == "United States" else ""
    if co and state:
        return f"{co.replace(' County', '')} Co., {state}"
    return co or state or parts[0]


class NotPrepared(SystemExit):
    """Raised instead of a traceback when the data has not been built yet."""


def load_pool() -> list[dict]:
    if not os.path.exists(pomlib.DB_PATH):
        raise NotPrepared(
            f"no catalogue at {pomlib.DB_PATH}\n"
            f"  build it first:  pom db            (downloads the metadata, ~4 MB)\n"
            f"  then the scans:  pom fetch --limit 200")
    if not os.path.exists(ANALYSIS):
        raise NotPrepared(
            f"no prepared plates in {PLATE_DIR}\n"
            f"  prepare them first:  pom prepare --all\n"
            f"  or a quick sample:   pom prepare --sample 60")
    with open(ANALYSIS) as fh:
        analysis = json.load(fh)
    conn = pomlib.connect()
    rows = {r["pom_id"]: r for r in conn.execute(
        "SELECT pom_id, common_name, variety, sci_name, artist, year, geo_origin, specimen "
        "FROM items")}
    notes, facts = botany.load_notes(), botany.species_facts(conn)
    pool = []
    for a in analysis:
        r = rows.get(a["pom_id"])
        if not r or not os.path.exists(a["path"]):
            continue
        pool.append({
            "pom_id": a["pom_id"], "path": a["path"], "paper": tuple(a["paper"]),
            "aspect": a["aspect"], "cells": a["cells"], "rows": a["rows"], "cols": a["cols"],
            "common": r["common_name"], "variety": r["variety"], "sci": r["sci_name"],
            "artist_short": artist_short(r["artist"]), "year": r["year"],
            "county": county(r["geo_origin"]), "specimen": r["specimen"],
            "note": notes.get(r["common_name"] or ""),
            "fact": facts.get(r["common_name"] or ""),
        })
    conn.close()
    if not pool:
        raise NotPrepared(
            f"{len(analysis)} plates are analysed but none are on disk in {PLATE_DIR}\n"
            f"  re-run:  pom prepare --all")
    return pool


def open_plate(item: dict) -> Image.Image:
    return Image.open(item["path"]).convert("RGB")



class Picker:
    """Chooses plates for a composition.

    Treatments ask for plates through `next_plate`/`next_plates` rather than
    `rng.choice`, so the caller decides the policy. The default is a fresh
    shuffle per composition; scripts/set_wallpaper.py substitutes a Ring that
    persists its position across runs, so nothing repeats until every plate has
    been shown once.
    """

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)

    def next_plates(self, pool: list[dict], n: int) -> list[dict]:
        return self.rng.sample(pool, min(n, len(pool)))

    def next_plate(self, pool: list[dict]) -> dict:
        return self.next_plates(pool, 1)[0]

    # Non-plate randomness (which fruit family to compare, how much to jitter a
    # plate's height) stays ordinary randomness.
    def choice(self, seq):
        return self.rng.choice(seq)

    def random(self) -> float:
        return self.rng.random()


# --- treatments -------------------------------------------------------------

def t_mat(pool, rng, W, H) -> tuple[Image.Image, list[dict]]:
    """One plate, floated. The width is left honestly empty, as wall."""
    it = rng.next_plate(pool)
    ground = mat_for(it["paper"])
    canvas = Image.new("RGB", (W, H), ground)
    ink, soft = ink_for(ground), shift(ink_for(ground), light=1.7)

    ph = round((H - CHROME["top"] - CHROME["bottom"]) * 0.93)
    cy = CHROME["top"] + (H - CHROME["top"] - CHROME["bottom"]) // 2
    cx = round(W * 0.655)
    box = paste_plate(canvas, open_plate(it), cx, cy, ph)

    d = ImageDraw.Draw(canvas)
    right = box[0] - round(W * 0.055)
    col = round(W * 0.27)
    end = caption(d, right, cy - 190, it, ink, soft, align="r")
    if it["note"]:
        # Right-aligned under the caption, ragged-left against the plate edge.
        end = paragraph(d, right, end + 34, it["note"], "serif", 20, soft, col,
                        leading=1.62, align="r", max_lines=6)
        if it["fact"]:
            paragraph(d, right, end + 18, it["fact"], "mono", 13,
                      shift(soft, light=1.25), col, align="r", max_lines=2)
    return canvas, [it]


def t_ledger(pool, rng, W, H) -> tuple[Image.Image, list[dict]]:
    """Plate bled off the right edge; the left is the catalogue page.

    The ground is the plate's own paper tone rather than a mat, and the join is
    feathered, so the whole screen reads as one sheet that happens to be
    painted at one end -- not as a picture pasted onto a card.
    """
    it = rng.next_plate(pool)
    ground = shift(it["paper"], light=0.985, sat=0.92)
    canvas = Image.new("RGB", (W, H), ground)
    ink, soft = ink_for(ground), shift(ink_for(ground), light=1.9)

    plate = open_plate(it)
    ph = round(H * 1.14)                      # taller than the screen, so it bleeds
    pw = round(plate.width * ph / plate.height)
    im = plate.resize((pw, ph), Image.LANCZOS)
    x = W - round(pw * 0.80)                  # and off the right edge, too

    feather = round(pw * 0.20)
    mask = Image.new("L", (pw, ph), 255)
    md = ImageDraw.Draw(mask)
    for i in range(feather):
        md.line((i, 0, i, ph), fill=round(255 * (i / feather) ** 1.6))
    canvas.paste(im, (x, round((H - ph) / 2)), mask)

    d = ImageDraw.Draw(canvas)
    tx = max(CHROME["left"] + 90, round(W * 0.085))
    ty = round(H * 0.40)
    text(d, (tx, ty - 74), "POMOLOGICAL WATERCOLOUR COLLECTION", "mono", 15, soft, track=3.6)
    d.line((tx, ty - 34, tx + 470, ty - 34), fill=soft, width=1)
    end = caption(d, tx, ty, it, ink, soft, scale=1.75)
    if it["note"]:
        # The ledger has the most room of any treatment, so it gets the note at
        # reading size rather than label size.
        col = min(round(W * 0.30), x - tx - 120)
        end = paragraph(d, tx, end + 52, it["note"], "serif", 25, ink, col,
                        leading=1.66, max_lines=7)
        if it["fact"]:
            paragraph(d, tx, end + 24, it["fact"], "mono", 14, soft, col, max_lines=2)
    return canvas, [it]


def t_board(pool, rng, W, H) -> tuple[Image.Image, list[dict]]:
    """Four specimens in a row, as if pinned to one card."""
    picks = rng.next_plates(pool, 4)
    paper = tuple(round(sum(p["paper"][i] for p in picks) / len(picks)) for i in range(3))
    ground = mat_for(paper)
    canvas = Image.new("RGB", (W, H), ground)
    ink, soft = ink_for(ground), shift(ink_for(ground), light=1.7)
    d = ImageDraw.Draw(canvas)

    top = CHROME["top"] + 40
    avail_h = H - top - CHROME["bottom"] - 130      # 130 reserved for captions
    slot = W / len(picks)
    for i, it in enumerate(picks):
        # Nudge each plate's height a little so the row reads as specimens laid
        # out by hand, not as a template with four holes in it.
        ph = round(avail_h * (0.90 + 0.10 * rng.random()))
        cx = round(slot * (i + 0.5))
        box = paste_plate(canvas, open_plate(it), cx, top + avail_h // 2, ph)
        cy = top + avail_h + 46
        text(d, (cx, cy), (it["variety"] or it["common"] or "—"), "serif-italic", 26, ink, anchor="ma")
        text(d, (cx, cy + 36), (it["common"] or ""), "mono", 13, soft, anchor="ma", track=1.6)
        text(d, (cx, cy + 60), f"{it['artist_short']}  {it['year'] or ''}".strip(),
             "mono", 12, soft, anchor="ma", track=0.8)
    return canvas, picks


def t_diptych(pool, rng, W, H) -> tuple[Image.Image, list[dict]]:
    """Two of the same fruit, facing, for comparison."""
    by_fruit: dict[str, list[dict]] = {}
    for it in pool:
        if it["common"]:
            by_fruit.setdefault(it["common"], []).append(it)
    families = [v for v in by_fruit.values() if len(v) >= 2]
    picks = (rng.next_plates(rng.choice(families), 2) if families
             else rng.next_plates(pool, 2))

    paper = tuple(round((picks[0]["paper"][i] + picks[1]["paper"][i]) / 2) for i in range(3))
    ground = mat_for(paper)
    canvas = Image.new("RGB", (W, H), ground)
    ink, soft = ink_for(ground), shift(ink_for(ground), light=1.7)

    ph = round((H - CHROME["top"] - CHROME["bottom"]) * 0.86)
    cy = CHROME["top"] + round((H - CHROME["top"] - CHROME["bottom"]) * 0.46)
    boxes = [paste_plate(canvas, open_plate(it), round(W * f), cy, ph)
             for it, f in zip(picks, (0.305, 0.695))]

    d = ImageDraw.Draw(canvas)
    head = picks[0]["common"] or ""
    if head:
        text(d, (W // 2, CHROME["top"] + 14), head.upper(), "serif", 19, ink, anchor="ma", track=7.0)

    # The centre column between the two sheets is the one piece of empty space
    # the diptych has to spare, and a museum would put the label there. The
    # authored sentence is about the species; the line under it is counted out
    # of the catalogue at load time.
    gap_l, gap_r = boxes[0][2], boxes[1][0]
    col = gap_r - gap_l - 96
    note, fact = picks[0]["note"], picks[0]["fact"]
    if note and col > 260:
        # Measure before placing, so the label sits centred on the plates
        # rather than hanging from the top of an otherwise empty column.
        n_size, n_lead = 22, 1.62
        lines = wrap_lines(d, note, "serif", n_size, col, max_lines=10)
        f_lines = wrap_lines(d, fact, "mono", 13, col, max_lines=2) if fact else []
        h = block_height(lines, n_size, n_lead) + (
            block_height(f_lines, 13, 1.5) + 22 if f_lines else 0)
        top = cy - h // 2
        end = draw_lines(d, W // 2, top, lines, "serif", n_size, ink, n_lead, "m")
        if f_lines:
            draw_lines(d, W // 2, end + 22, f_lines, "mono", 13, soft, 1.5, "m")
        # Hairlines closing the column above and below the label, so it reads
        # as one object between the sheets instead of floating type.
        d.line((W // 2, cy - ph // 2, W // 2, top - 30), fill=soft, width=1)
        d.line((W // 2, top + h + 30, W // 2, cy + ph // 2), fill=soft, width=1)
    else:
        d.line((W // 2, cy - ph // 2, W // 2, cy + ph // 2), fill=soft, width=1)

    # Captions under the plates rather than beside them: the two sheets are
    # different widths, so anything hung off their edges lines up on nothing.
    for it, box in zip(picks, boxes):
        cx = (box[0] + box[2]) // 2
        cap_y = cy + ph // 2 + 42
        label = it["variety"] or it["pom_id"]
        text(d, (cx, cap_y), label, "serif-italic" if it["variety"] else "mono",
             32 if it["variety"] else 19, ink, anchor="ma")
        text(d, (cx, cap_y + 46), f"{it['artist_short']}  ·  {it['year'] or ''}".strip(" ·"),
             "mono", 14, soft, anchor="ma", track=1.2)
    return canvas, picks


def t_cabinet(pool, rng, W, H) -> tuple[Image.Image, list[dict]]:
    """A drawer of the collection at once, on the copy-stand black."""
    cols, rows = 7, 2
    picks = rng.next_plates(pool, cols * rows)
    canvas = Image.new("RGB", (W, H), STAND)
    soft = (128, 122, 108)
    d = ImageDraw.Draw(canvas)

    top, bot = CHROME["top"] + 28, CHROME["bottom"] + 8
    cell_h = (H - top - bot) / rows
    ph = round(cell_h * 0.80)
    for i, it in enumerate(picks):
        cx = round(W * (i % cols + 0.5) / cols)
        cy = round(top + cell_h * (i // cols + 0.5))
        box = paste_plate(canvas, open_plate(it), cx, cy, ph, shadow=False)
        text(d, (cx, box[3] + 14), it["pom_id"].replace("POM", ""), "mono", 11, soft,
             anchor="ma", track=1.4)
    return canvas, picks


def t_bleed(pool, rng, W, H) -> tuple[Image.Image, list[dict]]:
    """Edge to edge, but on a detail: the busiest band of the plate, which is
    where the fruit is. Read from the original scan, not the 1800px derivative,
    because a 2.39:1 band of a portrait plate is only ~27% of its height."""
    it = rng.next_plate(pool)
    src = os.path.join(pomlib.ORIGINALS_DIR, f"{it['pom_id']}.jpg")
    plate = Image.open(src) if os.path.exists(src) else Image.open(it["path"])
    plate = plate.convert("RGB")
    if os.path.exists(src):
        import prepare
        plate = prepare.trim_backdrop(plate)

    band_h = plate.width / (W / H)
    nrows = it["rows"]
    # Score each grid row by local contrast, blurred over the band's span, and
    # take the centre of the strongest run - the painted fruit, not the pencil.
    span = max(1, round(nrows * band_h / plate.height))
    per_row = [sum(c["detail"] for c in it["cells"] if c["r"] == r) for r in range(nrows)]
    best = max(range(nrows - span + 1), key=lambda r: sum(per_row[r:r + span]))
    cy = plate.height * (best + span / 2) / nrows
    top = max(0, min(plate.height - band_h, cy - band_h / 2))
    band = plate.crop((0, round(top), plate.width, round(top + band_h)))
    canvas = band.resize((W, H), Image.LANCZOS)

    # A caption over a painting needs contrast, but a grey veil over cream
    # paper reads as dirt rather than shade. So measure what is under the text
    # and push the paper further in the ink's own direction -- light paper goes
    # lighter under dark ink, a dark passage goes darker under light ink.
    cap_box = (W - 980, H - CHROME["bottom"] - 250, W - 40, H - CHROME["bottom"] + 40)
    patch = canvas.crop(cap_box).convert("L")
    lum = sum(patch.getdata()) / (patch.width * patch.height)
    dark_ink = lum > 118
    ink = (26, 23, 19) if dark_ink else (245, 241, 232)
    soft = (92, 84, 70) if dark_ink else (206, 198, 182)

    wash = Image.new("L", (W, H), 0)
    ImageDraw.Draw(wash).rectangle(cap_box, fill=132)
    wash = wash.filter(ImageFilter.GaussianBlur(150))
    veil = Image.new("RGB", (W, H), (255, 253, 247) if dark_ink else (18, 16, 14))
    canvas = Image.composite(veil, canvas, wash)

    d = ImageDraw.Draw(canvas)
    caption(d, W - 70, H - CHROME["bottom"] - 210, it, ink, soft, align="r", scale=1.15)
    return canvas, [it]


RENDERERS = {"mat": t_mat, "ledger": t_ledger, "board": t_board,
             "diptych": t_diptych, "cabinet": t_cabinet, "bleed": t_bleed}


def compose(treatment: str, pool, picker, size: tuple[int, int]):
    """Render one composition. `picker` is a Picker (or a subclass of it)."""
    return RENDERERS[treatment](pool, picker, *size)


def main() -> int:
    ap = argparse.ArgumentParser(description="Compose desktop wallpapers from prepared plates.")
    ap.add_argument("--treatment", default="mat", choices=TREATMENTS + ["all"])
    ap.add_argument("--size", default="3440x1440", help="WxH, default the ultrawide")
    ap.add_argument("--seed", type=int, help="reproducible pick; omit for a fresh one")
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--count", type=int, default=1, help="how many to render per treatment")
    ap.add_argument("--quality", type=int, default=92)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    W, H = (int(v) for v in args.size.lower().split("x"))
    names = TREATMENTS if args.treatment == "all" else [args.treatment]
    pool = load_pool()
    print(f"🍏 {len(pool)} plates · {', '.join(names)} · {W}×{H}")
    if args.dry_run:
        for n in names:
            print(f"  would write {os.path.join(args.out_dir, f'{n}.jpg')}")
        return 0

    os.makedirs(args.out_dir, exist_ok=True)
    for n in names:
        for i in range(args.count):
            seed = args.seed if args.seed is not None and args.count == 1 else \
                (None if args.seed is None else args.seed + i)
            canvas, used = compose(n, pool, Picker(seed), (W, H))
            suffix = "" if args.count == 1 else f"-{i + 1}"
            path = os.path.join(args.out_dir, f"{n}{suffix}.jpg")
            canvas.save(path, quality=args.quality, optimize=True, progressive=True)
            print(f"  {n:8s} {pomlib.human_bytes(os.path.getsize(path)):>10s}  "
                  f"{', '.join(u['pom_id'] for u in used)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
