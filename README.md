# Pomological Watercolors

Between 1886 and 1942 the USDA hired artists to paint the fruit it was
cataloguing — 7,584 watercolours, most of them varieties that no longer exist.
[The National Agricultural Library tells that story properly.](https://www.nal.usda.gov/exhibits/ipd/pomological/)

This puts them on your desktop, lock screen and login screen.

![The six treatments at 3440 x 1440](docs/preview.jpg)

## Install

```sh
nix run github:placeybordeaux/pomological-watercolors-lockscreen -- fetch
nix run github:placeybordeaux/pomological-watercolors-lockscreen -- set
```

Without nix it is Python 3 and Pillow and nothing else:

```sh
git clone https://github.com/placeybordeaux/pomological-watercolors-lockscreen
cd pomological-watercolors-lockscreen
pip install pillow                     # or: nix develop
scripts/pom fetch && scripts/pom set
```

`fetch` pulls ~1.3 GB of prepared plates. Then `pom install` keeps it there:

```sh
pom install                      # rotate through all six treatments
pom install --treatment diptych  # or pin one
pom status
```

It changes when your screen locks, at most once an hour, and walks a shuffled
ring so nothing repeats for 224 days.

## The six treatments

The paintings are portrait; screens are not. An ultrawide is 2.39:1 — three and
a half plates wide — so none of these stretch one painting across it.

| | |
| --- | --- |
| `mat` | one sheet floated on a mat sampled from its own paper |
| `ledger` | the sheet bled off the right edge, catalogue entry on the left |
| `board` | four specimens in a row, as if pinned to a card |
| `diptych` | two varieties of one fruit, facing across a centre rule |
| `cabinet` | fourteen plates on black, as a drawer pulled out |
| `bleed` | edge to edge, cropped to the plate's busiest band — the fruit |

Compare them at your own resolution: `python3 prototypes/build_desktop.py`,
then open `prototypes/desktop.html`.

## Will it work on my desktop?

| | Wallpaper | Lock | Login |
| --- | --- | --- | --- |
| XFCE | yes | yes | SDDM, via the NixOS module |
| GNOME | yes | yes | no |
| KDE Plasma | yes | yes | SDDM, via the NixOS module |
| sway / Hyprland | yes | no | no |
| bare X11 | yes | no | no |

Each surface reports `ok`, `unsupported` or `needs-setup` rather than failing
quietly. The login screen needs root on every desktop — see
[docs/desktops.md](docs/desktops.md) for why, and for the NixOS modules.

## More

* [docs/design.md](docs/design.md) — why the treatments look the way they do,
  and why the wallpaper changes in the dark rather than on a timer
* [docs/desktops.md](docs/desktops.md) — how each desktop is driven, the
  greeter problem, NixOS and home-manager modules
* [docs/data.md](docs/data.md) — where the paintings come from, the mirror, the
  pipeline and the schema
* [docs/botany.md](docs/botany.md) — the species notes, and how to add one

## Licence

Code is MIT. The paintings are public domain — US federal works — and the
National Agricultural Library asks only that use carry:

> U.S. Department of Agriculture Pomological Watercolor Collection. Rare and
> Special Collections, National Agricultural Library, Beltsville, MD 20705.

Nothing leaves your machine: plates are composed and analysed locally.
