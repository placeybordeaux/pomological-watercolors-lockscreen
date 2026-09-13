#!/usr/bin/env python3
"""Inline the specimen images + metadata into the treatments prototype.

Kept as a build step so the specimen set can be changed without hand-editing
half a megabyte of base64 inside the HTML.

Usage:
    python3 prototypes/build.py [--assets PATH] [--out PATH]
"""
import argparse, json, os

HERE = os.path.dirname(os.path.abspath(__file__))

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--assets", default=os.path.join(HERE, "assets.json"))
ap.add_argument("--template", default=os.path.join(HERE, "treatments.template.html"))
ap.add_argument("--out", default=os.path.join(HERE, "treatments.html"))
ap.add_argument("--dry-run", action="store_true")
a = ap.parse_args()

data = json.load(open(a.assets))
html = open(a.template).read()
assert "/*__DATA__*/" in html, "template lost its __DATA__ placeholder"
out = html.replace("/*__DATA__*/", json.dumps(data, separators=(",", ":")))
print(f"🍇 {len(data)} specimens, {len(out)/1e6:.2f} MB -> {a.out}")
if a.dry_run:
    raise SystemExit(0)
open(a.out, "w").write(out)
