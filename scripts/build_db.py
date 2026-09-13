#!/usr/bin/env python3
"""Build data/pom.sqlite: one row per watercolor, plus the Internet Archive
file inventory used to fetch and verify the scans.

Three sources are reconciled here, because no single one is complete:

  * pom_metadata.csv      - NAL's own metadata export (7,583 rows, but it is
                            missing POM00007584).
  * IA image item         - 7,581 full-resolution JPEGs (missing 390, 1143
                            and 7550, which NAL never published as scans).
  * NAL Primo/Alma        - the live catalog, which reports 7,584 records and
                            is the tiebreaker for what "the whole set" means.

The union is exactly 7,584 ids, so every row here is backed by at least one
authoritative source; the `sources` column records which.

Usage:
    python3 scripts/build_db.py                 # build/refresh the database
    python3 scripts/build_db.py --dry-run       # report what would change
    python3 scripts/build_db.py --no-nal        # skip the live NAL catalog pass
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pomlib  # noqa: E402

CSV_PATH = os.path.join(pomlib.DATA_DIR, "pom_metadata.csv")
CSV_URL = (
    f"https://archive.org/download/{pomlib.IA_METADATA_ITEM}/pom_metadata.csv"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    pom_id           TEXT PRIMARY KEY,
    seq              INTEGER NOT NULL,
    artist           TEXT,
    sci_name         TEXT,
    common_name      TEXT,
    variety          TEXT,
    geo_origin       TEXT,
    nal_note         TEXT,
    phys_description TEXT,
    specimen         TEXT,
    year             INTEGER,
    date_created     TEXT,
    rights           TEXT,
    nal_title        TEXT,
    nal_mms_id       TEXT,
    sources          TEXT NOT NULL,
    -- 'no_public_scan': NAL catalogues the painting but no downloadable scan
    -- exists anywhere public (NAL's own download page returns an HTML stub).
    scan_status      TEXT
);
CREATE INDEX IF NOT EXISTS items_seq       ON items(seq);
CREATE INDEX IF NOT EXISTS items_year      ON items(year);
CREATE INDEX IF NOT EXISTS items_common    ON items(common_name);
CREATE INDEX IF NOT EXISTS items_artist    ON items(artist);

CREATE TABLE IF NOT EXISTS ia_files (
    pom_id   TEXT PRIMARY KEY,
    item     TEXT NOT NULL,
    name     TEXT NOT NULL,
    size     INTEGER,
    md5      TEXT,
    sha1     TEXT,
    mtime    INTEGER
);

-- Download bookkeeping lives beside the metadata so a re-run can tell
-- "never fetched" apart from "fetched and verified".
CREATE TABLE IF NOT EXISTS downloads (
    pom_id     TEXT PRIMARY KEY,
    path       TEXT,
    bytes      INTEGER,
    md5        TEXT,
    verified   INTEGER NOT NULL DEFAULT 0,
    source     TEXT,
    fetched_at TEXT,
    error      TEXT
);
"""


def parse_year(raw: str) -> int | None:
    m = re.search(r"\b(1[6-9]\d\d)\b", raw or "")
    return int(m.group(1)) if m else None


def load_csv(path: str) -> dict[str, dict]:
    if not os.path.exists(path):
        print(f"  fetching {CSV_URL}")
        data = pomlib.http_get(CSV_URL)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
    with open(path, newline="", encoding="utf-8") as fh:
        rows = {r["id"]: r for r in csv.DictReader(fh)}
    return rows


def load_ia_inventory() -> dict[str, dict]:
    meta = pomlib.ia_metadata(pomlib.IA_IMAGE_ITEM)
    out = {}
    for f in meta.get("files", []):
        m = re.fullmatch(r"(POM\d{8})\.jpg", f.get("name", ""))
        if not m:
            continue
        out[m.group(1)] = {
            "item": pomlib.IA_IMAGE_ITEM,
            "name": f["name"],
            "size": int(f.get("size", 0)) or None,
            "md5": f.get("md5"),
            "sha1": f.get("sha1"),
            "mtime": int(f["mtime"]) if f.get("mtime") else None,
        }
    return out


# --- NAL Primo (Alma) ------------------------------------------------------
# Primo caps guest paging at offset < 1000, so the 7,584-record collection
# cannot simply be walked. It does answer exact id lookups, which is all we
# need: the IA mirror plus the CSV already cover every id but a handful, and
# those handful get looked up directly.
PRIMO_BASE = "https://search.nal.usda.gov/primaws/rest/pub/pnxs"
COLLECTION_ID = "81279629860007426"


def primo_query(extra: dict, limit: int = 50, offset: int = 0) -> dict:
    params = {
        "blendFacetsSeparately": "false",
        "disableCache": "false",
        "getMore": "0",
        "inst": "01NAL_INST",
        "lang": "en",
        "limit": str(limit),
        "offset": str(offset),
        "pcAvailability": "false",
        "q": "any,contains,pomological watercolor",
        "rtaLinks": "false",
        "scope": "MyInstitution",
        "searchInFulltextUserSelection": "false",
        "skipDelivery": "Y",
        "sort": "date_a",
        "tab": "LibraryCatalog",
        "vid": "01NAL_INST:MAIN",
        "multiFacets": f"digital_collection,include,{COLLECTION_ID}",
    }
    params.update(extra)
    url = f"{PRIMO_BASE}?{urllib.parse.urlencode(params)}"
    return json.loads(pomlib.http_get(url))


def nal_collection_total() -> int:
    """How many records the live catalog says the collection holds."""
    return primo_query({}, limit=1)["info"]["total"]


def parse_primo_doc(doc: dict) -> dict | None:
    disp = (doc.get("pnx") or {}).get("display") or {}
    m = re.search(r"(POM\d{8})", json.dumps(doc))
    if not m:
        return None

    def first(key):
        v = disp.get(key) or []
        # Primo packs display-vs-search variants as "value$$Qsearchable".
        return v[0].split("$$")[0].strip() if v else None

    # Titles read "Scientific name: Variety"; that is the same split the CSV
    # stores as separate sci_name / variety columns.
    title = first("title") or ""
    sci, _, variety = title.partition(":")
    return {
        "pom_id": m.group(1),
        "nal_title": title or None,
        "nal_mms_id": first("mms"),
        "year": parse_year(first("creationdate") or ""),
        "artist": first("contributor"),
        "sci_name": sci.strip() or None,
        "variety": variety.strip() or None,
        "geo_origin": (first("coverage") or "").replace("--", ", ") or None,
        "phys_description": first("format"),
    }


def fetch_nal_records(ids: list[str]) -> dict[str, dict]:
    """Look up specific records by their POM id in the live catalog."""
    out: dict[str, dict] = {}
    for i, pom_id in enumerate(ids, 1):
        try:
            page = primo_query({"q": f"any,contains,{pom_id}"}, limit=3)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {pom_id}: {exc}")
            continue
        for doc in page.get("docs") or []:
            rec = parse_primo_doc(doc)
            if rec and rec["pom_id"] == pom_id:
                out[pom_id] = rec
                break
        print(f"  [{i}/{len(ids)}] {pom_id} "
              f"{'✓ ' + (out[pom_id]['nal_title'] or '')[:48] if pom_id in out else '— not found'}")
        time.sleep(0.3)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build the pomological watercolor index database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Usage:")[-1],
    )
    ap.add_argument("--db", default=pomlib.DB_PATH, help="sqlite path")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be written, change nothing")
    ap.add_argument("--no-nal", action="store_true",
                    help="skip the live NAL catalog pass (offline / faster)")
    args = ap.parse_args()

    print("🍑 Building the pomological watercolor index\n")

    print("· NAL metadata CSV")
    csv_rows = load_csv(CSV_PATH)
    print(f"  {len(csv_rows):,} rows")

    print("· Internet Archive scan inventory")
    ia = load_ia_inventory()
    print(f"  {len(ia):,} JPEGs, {pomlib.human_bytes(sum(f['size'] or 0 for f in ia.values()))}")

    nal: dict[str, dict] = {}
    if not args.no_nal:
        print("· NAL live catalog")
        try:
            total = nal_collection_total()
            union_so_far = set(csv_rows) | set(ia)
            gaps = sorted(union_so_far - set(csv_rows), key=lambda i: int(i[3:]))
            print(f"  catalog holds {total:,} records; "
                  f"{len(gaps)} scan(s) lack CSV metadata")
            nal = fetch_nal_records(gaps)
            if len(union_so_far) != total:
                print(f"  ! union is {len(union_so_far):,} but the catalog says "
                      f"{total:,}; some records may be unaccounted for")
        except Exception as exc:  # noqa: BLE001 - the catalog is a nice-to-have
            print(f"  ! NAL pass failed ({exc}); continuing without it")

    all_ids = sorted(set(csv_rows) | set(ia) | set(nal),
                     key=lambda i: int(i[3:]))
    print(f"\n· Union: {len(all_ids):,} records")
    print(f"  metadata but no scan: {sorted(set(csv_rows) - set(ia))}")
    print(f"  scan but no metadata: {sorted(set(ia) - set(csv_rows))}")

    if args.dry_run:
        print("\n(dry run) would write "
              f"{len(all_ids):,} items and {len(ia):,} ia_files rows to {args.db}")
        return 0

    conn = pomlib.connect(args.db)
    conn.executescript(SCHEMA)
    with conn:
        for pom_id in all_ids:
            row = csv_rows.get(pom_id, {})
            n = nal.get(pom_id, {})
            sources = ",".join(s for s, present in (
                ("csv", pom_id in csv_rows),
                ("ia", pom_id in ia),
                ("nal", pom_id in nal),
            ) if present)
            conn.execute(
                """INSERT INTO items (pom_id, seq, artist, sci_name, common_name,
                       variety, geo_origin, nal_note, phys_description, specimen,
                       year, date_created, rights, nal_title, nal_mms_id, sources,
                       scan_status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(pom_id) DO UPDATE SET
                       -- COALESCE on the columns the live catalog can fill, so a
                       -- --no-nal rebuild never blanks out what an earlier NAL
                       -- pass supplied for records the CSV does not cover.
                       artist=COALESCE(excluded.artist, items.artist),
                       sci_name=COALESCE(excluded.sci_name, items.sci_name),
                       common_name=excluded.common_name,
                       variety=COALESCE(excluded.variety, items.variety),
                       geo_origin=COALESCE(excluded.geo_origin, items.geo_origin),
                       nal_note=excluded.nal_note,
                       phys_description=COALESCE(excluded.phys_description,
                                                 items.phys_description),
                       specimen=excluded.specimen, year=excluded.year,
                       date_created=excluded.date_created, rights=excluded.rights,
                       nal_title=COALESCE(excluded.nal_title, items.nal_title),
                       nal_mms_id=COALESCE(excluded.nal_mms_id, items.nal_mms_id),
                       sources=excluded.sources, scan_status=excluded.scan_status""",
                (pom_id, int(pom_id[3:]),
                 row.get("artist") or n.get("artist"), row.get("sci_name") or n.get("sci_name"),
                 row.get("common_name") or None, row.get("variety") or n.get("variety"),
                 row.get("geo_origin") or n.get("geo_origin"), row.get("nal_note") or None,
                 row.get("phys_description") or n.get("phys_description"), row.get("specimen") or None,
                 parse_year(row.get("year") or "") or n.get("year"),
                 row.get("date_created") or None, row.get("rights") or None,
                 n.get("nal_title"), n.get("nal_mms_id"), sources,
                 "available" if pom_id in ia else "no_public_scan"),
            )
        for pom_id, f in ia.items():
            conn.execute(
                """INSERT INTO ia_files (pom_id, item, name, size, md5, sha1, mtime)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(pom_id) DO UPDATE SET
                       size=excluded.size, md5=excluded.md5,
                       sha1=excluded.sha1, mtime=excluded.mtime""",
                (pom_id, f["item"], f["name"], f["size"], f["md5"], f["sha1"], f["mtime"]),
            )

    counts = dict(conn.execute(
        "SELECT 'items', COUNT(*) FROM items UNION ALL SELECT 'ia_files', COUNT(*) FROM ia_files"
    ).fetchall())
    print(f"\n✓ {args.db}")
    print(f"  items    {counts['items']:,}")
    print(f"  ia_files {counts['ia_files']:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
