"""Botanical notes for the species in the collection.

Every on-screen note is two halves with different provenance, and they are kept
apart on purpose:

  the sentence   authored, in data/botany.json, one per common_name. Held to
                 what is uncontroversial about the plant or its arrival in
                 American orchards -- never about the individual variety, which
                 would be 7,584 claims nobody can check.
  the fact       computed from data/pom.sqlite at load time: how many plates of
                 this species there are, the years they span, who painted most
                 of them. Never hand-maintained, so it cannot drift out of date
                 as more scans are prepared.

A species with no entry simply gets no note, and the composition closes the gap.
"""
from __future__ import annotations

import json
import os

import pomlib

# The authored notes ship with the code, not with the downloaded data, so the
# nix package points here rather than into the writable data directory.
BOTANY_PATH = (os.environ.get("POMOLOGICAL_BOTANY")
               or os.path.join(pomlib.DATA_DIR, "botany.json"))


def load_notes() -> dict[str, str]:
    with open(BOTANY_PATH) as fh:
        return {k: v for k, v in json.load(fh).items() if not k.startswith("_")}


def species_facts(conn) -> dict[str, str]:
    """One computed sentence per common_name, from the catalogue itself."""
    total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    facts: dict[str, str] = {}
    rows = conn.execute("""
        SELECT common_name, COUNT(*) n, MIN(year) lo, MAX(year) hi
        FROM items WHERE common_name IS NOT NULL AND common_name != ''
        GROUP BY common_name
    """).fetchall()
    for r in rows:
        span = ""
        if r["lo"] and r["hi"]:
            span = f", painted {r['lo']}" + (f"–{r['hi']}" if r["hi"] != r["lo"] else "")
        facts[r["common_name"]] = (
            f"{r['n']:,} of the collection's {total:,} plates{span}.")
    return facts


def top_artist(conn, common_name: str) -> str | None:
    r = conn.execute("""
        SELECT artist, COUNT(*) n FROM items
        WHERE common_name = ? AND artist IS NOT NULL AND artist != ''
        GROUP BY artist ORDER BY n DESC LIMIT 1
    """, (common_name,)).fetchone()
    return r["artist"] if r else None
