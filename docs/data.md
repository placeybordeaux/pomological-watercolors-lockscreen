# The data

## `pom fetch` does not touch the archives

The paintings only exist at the Internet Archive and the National Agricultural
Library, and this project is not going to pretend otherwise. What it avoids is
every user pulling **56 GB** of full-resolution scans off a nonprofit archive to
derive the same 1.3 GB of plates that everyone else derived.

So the scans are fetched, checksum-verified and prepared **once**, by a
maintainer, and the result is published as release assets on this repo:
CDN-backed, 2 GiB per file, 1000 assets per release, and
[no cap on total release size or download bandwidth](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).

```
pom fetch          8 tar shards (~157 MB each) + the index + the analysis
                   = 1.2 GB, each verified against its published SHA-256
```

Resumable and idempotent: shards stage as `.part`, a checksum mismatch is
refused rather than used, and a re-run skips what is already verified.

## Rebuilding the mirror

Only a maintainer needs this, and only when the derivative format changes.

```sh
pom fetch --source ia        # the 56 GB, from the Internet Archive
pom prepare --all            # trim and analyse -> data/wallpapers
scripts/mirror.py build      # shard, checksum, manifest
scripts/mirror.py upload --dry-run
scripts/mirror.py upload
```

`FORMAT` in `scripts/mirror.py` is the release tag and the on-disk stamp. Bump
it when the plate height or the trim changes, so clients can tell.

Two things the published artifacts must never carry, both learned the hard way
by fetching into a clean directory and watching it resolve zero plates:

* `_analysis.json` stores no file paths — a consumer rebuilds them from their
  own plate directory and the id.
* `botany.json` travels with the *code*, not the data, so it is still found
  when `POMOLOGICAL_DATA` points elsewhere.

## Where the paintings come from

The NAL discovery portal is the catalogue of record but not a practical bulk
source: guest sessions are capped at `offset < 1000`, so the full 7,584 records
cannot be paged out, and the Alma-D viewer serves a 100×100 placeholder over any
simple URL. The Internet Archive carries complete public-domain mirrors.

| Source | Role |
| --- | --- |
| [`usda-pomological-watercolor-collection`](https://archive.org/details/usda-pomological-watercolor-collection) | 7,581 full-resolution JPEGs (~56 GB), with MD5s |
| [`usda_pomological_watercolors_20200211`](https://archive.org/details/usda_pomological_watercolors_20200211) | `pom_metadata.csv` — NAL's metadata export, 7,583 rows |
| [NAL Primo](https://search.nal.usda.gov/) | confirms the 7,584 total, fills records the CSV misses |

Neither mirror alone is complete and the gaps do not overlap: the CSV has no row
for `POM00007584`, and the image item has no scan for `POM00000390`,
`POM00001143` or `POM00007550`. Those three are catalogued paintings with no
publicly retrievable scan anywhere — NAL's own download page returns an HTML
stub. They are kept as rows with `scan_status = 'no_public_scan'` rather than
quietly dropped. The union is exactly 7,584.

## The pipeline

```
pom db        sources        -> data/pom.sqlite
pom fetch     the mirror     -> data/wallpapers/*.jpg  (1800 px tall)
  --source ia the Archive    -> data/originals/*.jpg   (~56 GB)
pom prepare   originals      -> data/wallpapers        (maintainers)
pom compose   wallpapers     -> one screen-sized image
pom set       that image     -> desktop, lock, login
```

The raw scans are photographs of a sheet on a dark copy-stand, not cropped
artwork. `prepare` finds the sheet inside the backdrop and crops to it, then
measures a luminance/detail grid and the paper tone — see
[design.md](design.md) for what the compositions do with that.

`POMOLOGICAL_DATA` relocates all of it; the nix package sets it automatically,
since its code lives in the read-only store.

## Schema

`items` — one row per catalogued painting (7,584)

| column | notes |
| --- | --- |
| `pom_id`, `seq` | `POM00000266` and its numeric form, for ordering |
| `artist` | 26 distinct; Passmore alone painted 1,516 |
| `sci_name`, `common_name`, `variety` | `Malus domestica` / `apples` / `York` |
| `geo_origin` | where the specimen was grown |
| `year`, `date_created` | 1886–1942 |
| `sources` | which of `csv,ia,nal` supplied the row |
| `scan_status` | `available` or `no_public_scan` |

`ia_files` — the Archive's inventory: filename, size, MD5, SHA1.
`downloads` — what has been fetched, its on-disk MD5, and any error.
