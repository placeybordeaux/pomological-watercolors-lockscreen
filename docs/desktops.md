# Driving each desktop

Composing a wallpaper is portable; *setting* one is not. Every desktop has its
own mechanism, its own idea of what a lock screen is, and its own answer to
"can I theme the greeter" (usually no).

Each backend reports one of three outcomes per surface, and the distinction
matters — "this desktop cannot do it" is worth printing, not papering over:

* `ok` — the image is on that surface now
* `unsupported` — this desktop has no mechanism for it
* `needs-setup` — there is a mechanism, but it needs a step we cannot take

Override detection with `--desktop`. Adding a desktop means one class in
`scripts/surfaces.py` and one entry in `BACKENDS`.

| Desktop | Wallpaper | Lock screen |
| --- | --- | --- |
| XFCE | `xfconf` backdrop keys, one per connected output | stock slideshow saver, pointed at a folder |
| GNOME | `gsettings`, light and dark URIs | `org.gnome.desktop.screensaver` |
| KDE Plasma | `plasma-apply-wallpaperimage` | `kscreenlockerrc`, re-read on next lock |
| sway / Hyprland | `swaybg`, restarted | no shared mechanism |
| bare X11 | `feh` or `xwallpaper` | none |

## XFCE keeps exactly one lock image on purpose

xfce4-screensaver has no background setting. What it does have is a stock
`slideshow` saver that takes a folder, and the supported way to configure it is
the theme's `arguments` key in xfconf — a hand-written `.desktop` under
`~/.local/share` is *not* picked up, because the daemon enumerates savers
through an XDG menu.

That saver has no interval option, and measured over four minutes it cycles
whatever it finds in its folder **about once a second**. That is a strobe, not
a slideshow. With one file it holds still, and the plate changes when the
rotation changes it. `--lock-keep` raises the count if you want the strobe.

Backdrop keys are named after the output (`monitorHDMI-0`), so if `xrandr`
cannot enumerate monitors the backend reports `needs-setup` rather than
guessing a name and writing a key xfdesktop will never read.

## The login screen needs root, everywhere

The greeter runs as its own user before any session exists, and cannot read
`$HOME` — mode 0700 on most systems. So the rotation cannot set the greeter's
wallpaper the way it sets the desktop's. It drops a world-readable copy in
`/var/lib/pomological` instead, and the greeter theme points at that path.

If the image is missing — a fresh boot before the rotation has run — the base
theme falls back to its own colour, so an absent or corrupt file can never keep
anyone out.

GDM is not attempted: theming it means rebuilding a gresource bundle, which
breaks on every GNOME update.

## NixOS

```nix
{
  inputs.pomological.url =
    "github:placeybordeaux/pomological-watercolors-lockscreen";

  # system: the greeter half, which is the part that needs root
  imports = [ inputs.pomological.nixosModules.default ];
  services.pomological.login = { enable = true; user = "alice"; };

  # home-manager: the rotation
  imports = [ inputs.pomological.homeModules.default ];
  services.pomological = { enable = true; treatment = "diptych"; };
}
```

`services.pomological.login` copies an existing SDDM theme and re-points its
`background=` line, rather than writing a theme from scratch — that keeps the
user list, session picker and clock. It fails the build if the key is missing,
so a silently unthemed greeter is not a possible outcome. `baseTheme` and
`baseThemeName` pick which theme to copy.

`nix develop` gives you Python + Pillow for hacking on it.
