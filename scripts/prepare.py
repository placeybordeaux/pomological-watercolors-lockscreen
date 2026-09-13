#!/usr/bin/env python3
"""Turn raw archival scans into wallpaper-ready images, plus the analysis a
wallpaper app needs to place UI text over them.

The raw scans are photographs of a sheet on a dark backdrop, not cropped
artwork: there is a black (sometimes grey) border around a cream sheet, and the
lower part of the sheet carries the artist's handwritten annotations. Three
things therefore happen here:

  trim   - find the sheet inside the backdrop and crop to it
  read   - measure paper tone and a luminance/detail grid over the sheet, so a
           UI can decide where text is safe and what color it should be
  emit   - write a downscaled derivative

Usage:
    scripts/with_pillow.sh python3 scripts/prepare.py --sample 24 --contact-sheet
    scripts/with_pillow.sh python3 scripts/prepare.py --ids POM00000855,POM00003515
    scripts/with_pillow.sh python3 scripts/prepare.py --all --height 2340
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from PIL import Image, ImageStat

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pomlib  # noqa: E402

DERIV_DIR = os.path.join(pomlib.DATA_DIR, "wallpapers")


def _luma_rows(im: Image.Image) -> list[float]:
    g = im.convert("L")
    w, h = g.size
    return [sum(g.crop((0, y, w, y + 1)).getdata()) / w for y in range(h)]


def trim_backdrop(im: Image.Image, margin_frac: float = 0.002) -> Image.Image:
    """Crop the dark photographic backdrop away, leaving the paper sheet.

    Works on a small proxy for speed, then scales the box back up. The test is
    "is this row/column mostly brighter than the darkest 10% of the image",
    which survives both the black backdrop and the occasional grey mount.
    """
    proxy = im.copy()
    proxy.thumbnail((400, 400), Image.BILINEAR)
    g = proxy.convert("L")
    w, h = g.size
    px = g.load()

    values = sorted(g.getdata())
    dark = values[int(len(values) * 0.10)]
    bright = values[int(len(values) * 0.90)]
    # A sheet has to be clearly brighter than the backdrop; if the image has no
    # such separation it is probably already cropped, so leave it alone.
    if bright - dark < 40:
        return im
    thresh = dark + (bright - dark) * 0.45

    def row_bright(y):
        return sum(1 for x in range(w) if px[x, y] > thresh) / w

    def col_bright(x):
        return sum(1 for y in range(h) if px[x, y] > thresh) / h

    top = next((y for y in range(h) if row_bright(y) > 0.6), 0)
    bottom = next((y for y in range(h - 1, -1, -1) if row_bright(y) > 0.6), h - 1)
    left = next((x for x in range(w) if col_bright(x) > 0.6), 0)
    right = next((x for x in range(w - 1, -1, -1) if col_bright(x) > 0.6), w - 1)
    if bottom - top < h * 0.3 or right - left < w * 0.3:
        return im

    sx, sy = im.width / w, im.height / h
    m = int(min(im.width, im.height) * margin_frac)
    return im.crop((max(0, int(left * sx) + m), max(0, int(top * sy) + m),
                    min(im.width, int((right + 1) * sx) - m),
                    min(im.height, int((bottom + 1) * sy) - m)))


def analyse(im: Image.Image, cols: int = 6, rows: int = 12) -> dict:
    """Grid of mean luminance and detail (stddev) over the trimmed sheet.

    A UI overlay uses this two ways: luminance picks the text color, and
    stddev finds the quiet regions where text will not fight with brushwork.
    """
    g = im.convert("L")
    g.thumbnail((cols * 40, rows * 40), Image.BILINEAR)
    w, h = g.size
    cells = []
    for r in range(rows):
        for c in range(cols):
            box = (int(c * w / cols), int(r * h / rows),
                   int((c + 1) * w / cols), int((r + 1) * h / rows))
            st = ImageStat.Stat(g.crop(box))
            cells.append({"r": r, "c": c,
                          "luma": round(st.mean[0], 1),
                          "detail": round(st.stddev[0], 1)})
    # Paper tone: the modal light color, taken from the outer frame of the
    # sheet where there is rarely any painting.
    edge = im.convert("RGB").copy()
    edge.thumbnail((120, 120), Image.BILINEAR)
    ew, eh = edge.size
    px = edge.load()
    samples = [px[x, y] for x in range(ew) for y in range(eh)
               if x < ew * .08 or x > ew * .92 or y < eh * .06]
    samples.sort(key=lambda p: -(p[0] + p[1] + p[2]))
    mid = samples[len(samples) // 2] if samples else (240, 236, 225)
    return {"cols": cols, "rows": rows, "cells": cells,
            "paper": [int(v) for v in mid],
            "aspect": round(im.width / im.height, 4)}


def process(pom_id: str, src_dir: str, height: int, quality: int) -> dict | None:
    src = os.path.join(src_dir, f"{pom_id}.jpg")
    if not os.path.exists(src):
        return None
    im = Image.open(src)
    im.draft("RGB", (height * 2, height * 2))
    im = im.convert("RGB")
    raw = im.size
    im = trim_backdrop(im)
    trimmed = im.size
    if im.height > height:
        im = im.resize((round(im.width * height / im.height), height), Image.LANCZOS)
    os.makedirs(DERIV_DIR, exist_ok=True)
    out = os.path.join(DERIV_DIR, f"{pom_id}.jpg")
    im.save(out, quality=quality, optimize=True, progressive=True)
    info = analyse(im)
    info.update({"pom_id": pom_id, "path": out, "raw": raw, "trimmed": trimmed,
                 "out": im.size, "bytes": os.path.getsize(out)})
    return info


def main() -> int:
    ap = argparse.ArgumentParser(description="Crop and analyse scans for wallpaper use.")
    ap.add_argument("--originals", default=pomlib.ORIGINALS_DIR)
    ap.add_argument("--ids", help="comma-separated POM ids")
    ap.add_argument("--sample", type=int, help="process N spread across the collection")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--height", type=int, default=1200, help="output height in px")
    ap.add_argument("--quality", type=int, default=82)
    ap.add_argument("--contact-sheet", metavar="PATH", nargs="?",
                    const=os.path.join(DERIV_DIR, "_contact.jpg"),
                    help="write a before/after sheet to check the trim")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    have = sorted(f[:-4] for f in os.listdir(args.originals) if f.endswith(".jpg"))
    if args.ids:
        ids = [i.strip() for i in args.ids.split(",")]
    elif args.sample:
        step = max(1, len(have) // args.sample)
        ids = have[::step][:args.sample]
    elif args.all:
        ids = have
    else:
        ap.error("choose --ids, --sample or --all")

    print(f"🍋 {len(ids)} scans -> {DERIV_DIR} at {args.height}px tall")
    if args.dry_run:
        print("(dry run)", ", ".join(ids[:8]), "..." if len(ids) > 8 else "")
        return 0

    results = []
    for i, pom_id in enumerate(ids, 1):
        info = process(pom_id, args.originals, args.height, args.quality)
        if not info:
            print(f"  ! {pom_id} not on disk")
            continue
        results.append(info)
        cut = 100 * (1 - (info["trimmed"][0] * info["trimmed"][1]) /
                     (info["raw"][0] * info["raw"][1]))
        print(f"  [{i}/{len(ids)}] {pom_id} {info['raw'][0]}×{info['raw'][1]} "
              f"→ trim {cut:4.1f}% → {info['out'][0]}×{info['out'][1]} "
              f"{pomlib.human_bytes(info['bytes'])}")

    with open(os.path.join(DERIV_DIR, "_analysis.json"), "w") as fh:
        json.dump(results, fh)

    if args.contact_sheet and results:
        make_contact_sheet(results, args.originals, args.contact_sheet)
        print(f"✓ {args.contact_sheet}")
    return 0


def make_contact_sheet(results: list[dict], src_dir: str, path: str) -> None:
    """Raw scan above, trimmed result below, so the crop can be eyeballed."""
    TH, COLS = 150, 8
    rows = (len(results) + COLS - 1) // COLS
    sheet = Image.new("RGB", (COLS * (TH + 6) + 6, rows * (TH * 2 + 22) + 6), (250, 249, 245))
    for i, info in enumerate(results):
        x = 6 + (i % COLS) * (TH + 6)
        y = 6 + (i // COLS) * (TH * 2 + 22)
        for j, p in enumerate((os.path.join(src_dir, f"{info['pom_id']}.jpg"), info["path"])):
            im = Image.open(p); im.draft("RGB", (TH * 2, TH * 2)); im = im.convert("RGB")
            im.thumbnail((TH, TH), Image.LANCZOS)
            sheet.paste(im, (x + (TH - im.width) // 2, y + j * (TH + 8)))
    sheet.save(path, quality=86)


if __name__ == "__main__":
    raise SystemExit(main())
