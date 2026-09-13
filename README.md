# USDA Pomological Watercolors

A local, checksum-verified copy of the [USDA Pomological Watercolor
Collection](https://search.nal.usda.gov/discovery/collectionDiscovery?vid=01NAL_INST:MAIN&collectionId=81279629860007426):
7,584 paintings of fruit and nut varieties made for the USDA between 1886 and
1942, plus the metadata needed to browse, filter and caption them.

Intended downstream use: a wallpaper / lock screen that cycles through the
collection — on a phone, and on this machine's desktop, lock and login screens.

## Where the data actually comes from

The NAL discovery portal (Primo/Alma) is the catalogue of record, but it is not
a practical bulk source — guest sessions are capped at `offset < 1000`, so the
full 7,584 records cannot be paged out, and the Alma-D viewer serves only a
100×100 placeholder over any simple URL. The Internet Archive carries complete
public-domain mirrors, so the scans come from there and the catalogue is used
only as the tiebreaker for what "the whole set" means.

| Source | Role |
| --- | --- |
| [`usda-pomological-watercolor-collection`](https://archive.org/details/usda-pomological-watercolor-collection) | 7,581 full-resolution JPEGs (~56 GB), one per painting, with MD5s |
| [`usda_pomological_watercolors_20200211`](https://archive.org/details/usda_pomological_watercolors_20200211) | `pom_metadata.csv` — NAL's own metadata export, 7,583 rows |
| [NAL Primo](https://search.nal.usda.gov/) | Live catalogue; confirms the 7,584 total and fills records the CSV misses |

Neither mirror alone is complete, and the gaps do not overlap:

* the CSV has no row for `POM00007584` (pulled from the live catalogue instead);
* the image item has no scan for `POM00000390`, `POM00001143` and `POM00007550`.

Those three are catalogued paintings with no publicly retrievable scan anywhere
— NAL's own download page returns an HTML stub for them, which is also what the
2020 crawl captured inside its tarball. They are kept as rows with
`scan_status = 'no_public_scan'` rather than quietly dropped.

The union is exactly 7,584, matching the catalogue's own count.

## Layout

```
scripts/build_db.py        sources -> data/pom.sqlite
scripts/download_images.py data/pom.sqlite -> data/originals/*.jpg
scripts/stats.py           what is in the collection, and what shape it is
scripts/prepare.py         originals -> trimmed, analysed plates
scripts/botany.py          species notes: authored sentence + counted fact
scripts/compose.py         plates -> one screen-sized composition
scripts/set_wallpaper.py   composition -> desktop, lock and login screens
prototypes/treatments.html the six phone treatments, side by side
prototypes/desktop.html    the six desktop treatments, at 3440x1440
data/pom.sqlite            the index
data/originals/            7,581 full-resolution JPEGs (~56 GB)
data/wallpapers/           trimmed plates, 1800 px tall, plus _analysis.json
data/botany.json           one authored sentence per species (98.2% of plates)
```

Stdlib-only Python 3 — no virtualenv, no dependencies.

## Usage

```sh
python3 scripts/build_db.py --dry-run      # reconcile sources, write nothing
python3 scripts/build_db.py                # build data/pom.sqlite

python3 scripts/download_images.py --dry-run
python3 scripts/download_images.py --limit 20      # sample first
python3 scripts/download_images.py --workers 12    # the full ~56 GB
python3 scripts/download_images.py --verify        # re-checksum what's on disk

python3 scripts/stats.py --shapes
```

The download is resumable and idempotent: every file is verified against the
Archive's published MD5, verified files are skipped on a re-run, and partial
downloads are staged as `.part` so an interrupted run can never leave a
truncated JPEG behind. Throughput against archive.org tops out around
9 MB/s regardless of worker count, so a cold full run takes roughly 1h45m.


## The desktop

The phone screen is *narrower* than the paintings, so filling it crops the
width. An ultrawide monitor is the opposite problem and a much bigger one: at
3440 x 1440 the screen is 2.39:1, about three and a half plates wide, so
filling it with one painting throws away roughly 85% of it.

None of the treatments fill the screen with a single plate. Ordered by how far
they drift from "a painting on a wall":

| Treatment | What goes in the width |
| --- | --- |
| `mat` | one sheet floated on a mat sampled from its own paper; the rest is wall |
| `ledger` | the sheet bled off the right edge, catalogue entry set on the left |
| `board` | four specimens in a row, as if pinned to one card |
| `diptych` | two varieties of one fruit, facing across a centre rule |
| `cabinet` | fourteen plates on the copy-stand black, as a drawer |
| `bleed` | edge to edge, but cropped to the plate's busiest band — the fruit |

```sh
scripts/with_pillow.sh python3 scripts/compose.py --treatment all --out-dir /tmp/x
scripts/with_pillow.sh python3 prototypes/build_desktop.py   # rebuild the comparison page
```

### Three surfaces, three mechanisms

| Surface | How it is set |
| --- | --- |
| Desktop | `xfconf` backdrop keys, one per connected monitor. Each change lands on a new filename, because xfdesktop only reloads when the path changes. |
| Lock | xfce4-screensaver has no background setting, but its stock `slideshow` saver takes a folder. The rotation keeps that folder stocked and the unlock dialog draws over it. The supported hook is the theme's `arguments` key in xfconf — a hand-written `.desktop` under `~/.local/share` is *not* picked up, because the daemon enumerates savers through an XDG menu. |
| Login | SDDM runs as its own user and cannot read `$HOME` (mode 0700), so the image goes to `/var/lib/pomological` and a breeze-derived theme reads it from there. That part is a system change: `~/nixos/common/pomological-login.nix`. |

```sh
scripts/with_pillow.sh python3 scripts/set_wallpaper.py --dry-run
scripts/with_pillow.sh python3 scripts/set_wallpaper.py --install   # lock saver + watcher
scripts/with_pillow.sh python3 scripts/set_wallpaper.py --status
```


### The botanical note

Every composition with room for it carries a note about the species, in two
halves that are kept apart on purpose:

* **the sentence** is authored, in `data/botany.json`, one per `common_name`.
  It is held to what is uncontroversial about the plant or its arrival in
  American orchards — never about the individual variety, which would be 7,584
  claims nobody can check. 59 entries cover 98.2% of the plates, because the
  collection is wildly skewed: apples alone are half of it, and twenty species
  are 95%.
* **the fact** underneath is computed from `data/pom.sqlite` at render time —
  how many plates of this species there are, and the years they span. It is
  never hand-maintained, so it cannot drift as more scans are prepared.

A species with no entry gets no note and the composition closes the gap.
`diptych` sets it as a museum label in the empty column between the two sheets;
`ledger` gives it reading size in the left field; `mat` hangs it under the
caption.

### How fast the lock screen changes

Once per lock, like everything else — and that is a deliberate workaround, not
a setting. The stock `slideshow` saver has no interval option, and measured
over four minutes it cycles whatever it finds in its folder **about once a
second**, which is a strobe rather than a slideshow. So exactly one image is
kept in the lock folder (`--lock-keep`, default 1), which makes it hold still;
the plate then changes when the rotation changes it. Raising `--lock-keep`
above 1 brings the strobe back.

### Changing it without you noticing

The wallpaper changes on a **dark boundary**, not on a tick — a swap while you
are looking at the screen is a distraction, and a slower timer does not fix
that. xfce4-screensaver broadcasts `ActiveChanged` on `org.xfce.ScreenSaver`;
`set_wallpaper.py --watch` composes the next plate when that goes true, gated to
at most one change an hour, so unlocking reveals a picture that was already
there. Selection walks one shuffled ring of the prepared plates and remembers
its place, so nothing repeats until everything has been seen — at one an hour
over the full collection, 316 days.

## Schema

`items` — one row per catalogued painting (7,584)

| column | notes |
| --- | --- |
| `pom_id`, `seq` | `POM00000266` and its numeric form, for ordering |
| `artist` | 26 distinct; Deborah Griscom Passmore alone painted 1,516 |
| `sci_name`, `common_name`, `variety` | e.g. `Malus domestica` / `apples` / `York` |
| `geo_origin` | where the specimen was grown |
| `phys_description`, `specimen` | physical description, NAL specimen number |
| `year`, `date_created` | 1886–1942 |
| `rights` | public domain, attribution requested (see below) |
| `sources` | which of `csv,ia,nal` supplied the row |
| `scan_status` | `available` or `no_public_scan` |

`ia_files` — the Archive's inventory: filename, size, MD5, SHA1.

`downloads` — what has been fetched, its on-disk MD5, and any error.

## Shape of the images

Relevant to the wallpaper plan: the scans are ~4000 px tall and **98% portrait**,
but their median aspect is **0.672 (roughly 2:3)** — noticeably wider than a
modern phone screen at ~0.46. Filling a phone screen edge-to-edge means
cropping about a third of the width, so a presentation that mats or letterboxes
the painting will show more of it than one that fills the screen.

## Attribution

Public domain. NAL asks that use carry:

> U.S. Department of Agriculture Pomological Watercolor Collection. Rare and
> Special Collections, National Agricultural Library, Beltsville, MD 20705.
