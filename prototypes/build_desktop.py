#!/usr/bin/env python3
"""Render each desktop treatment and inline it into the comparison page.

Kept separate from the page itself so the specimen set can be re-rolled without
hand-editing megabytes of base64. Renders at the real 3440x1440 and downscales,
rather than composing small: the treatments size their type against the full
canvas, so a half-size compose would not be the same picture.

Usage:
    scripts/with_pillow.sh python3 prototypes/build_desktop.py
    scripts/with_pillow.sh python3 prototypes/build_desktop.py --variants 3 --seed 20
"""
import argparse
import base64
import io
import json
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import compose  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--template", default=os.path.join(HERE, "desktop.template.html"))
ap.add_argument("--out", default=os.path.join(HERE, "desktop.html"))
ap.add_argument("--variants", type=int, default=2, help="renders per treatment")
ap.add_argument("--seed", type=int, default=41)
ap.add_argument("--width", type=int, default=1376, help="preview width in px")
ap.add_argument("--quality", type=int, default=72)
ap.add_argument("--size", default="3440x1440")
ap.add_argument("--dry-run", action="store_true")
a = ap.parse_args()

W, H = (int(v) for v in a.size.lower().split("x"))
pool = compose.load_pool()
print(f"🍊 {len(pool)} plates · {len(compose.TREATMENTS)} treatments × {a.variants}")

data = {}
for t in compose.TREATMENTS:
    shots = []
    for i in range(a.variants):
        canvas, used = compose.compose(t, pool, compose.Picker(a.seed + i * 17), (W, H))
        canvas.thumbnail((a.width, a.width), Image.LANCZOS)
        buf = io.BytesIO()
        canvas.save(buf, "JPEG", quality=a.quality, optimize=True, progressive=True)
        shots.append({
            "src": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(),
            "plates": [{"id": u["pom_id"],
                        "name": u["variety"] or u["common"] or u["pom_id"],
                        "common": u["common"] or "", "artist": u["artist_short"],
                        "year": u["year"]} for u in used],
        })
        print(f"  {t:8s} {i + 1}/{a.variants}  {len(shots[-1]['src']) / 1e3:6.0f} KB  "
              f"{', '.join(p['id'] for p in shots[-1]['plates'][:4])}")
    data[t] = shots

html = open(a.template).read()
assert "/*__DATA__*/" in html, "template lost its __DATA__ placeholder"
out = html.replace("/*__DATA__*/", json.dumps(data, separators=(",", ":")))
print(f"🍊 {len(out) / 1e6:.2f} MB -> {a.out}")
if not a.dry_run:
    open(a.out, "w").write(out)
