"""Putting a finished image onto the three screens, on whatever desktop you run.

Composing a wallpaper is portable; *setting* one is not. Every desktop has its
own mechanism, its own idea of what a lock screen is, and its own answer to
"can I theme the greeter" (usually no). So each desktop is a backend here, and
the rest of the project never has to know which one it is talking to.

A backend reports one of three outcomes per surface, and the distinction
matters -- "this desktop cannot do it" is a fact worth printing, not a failure
to paper over:

    ok           the image is on that surface now
    unsupported  this desktop has no mechanism for it
    needs-setup  there is a mechanism, but it needs a step we cannot take
                 (a system config change, a package that is not installed)

Adding a desktop means adding one class and listing it in BACKENDS.
"""
from __future__ import annotations

import os
import shutil
import subprocess

OK, UNSUPPORTED, NEEDS_SETUP = "ok", "unsupported", "needs-setup"


def have(*binaries: str) -> bool:
    return all(shutil.which(b) for b in binaries)


def run(cmd: list[str], dry: bool) -> bool:
    if dry:
        print("    $ " + " ".join(cmd))
        return True
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        print(f"    ! {cmd[0]}: {(p.stderr or p.stdout).strip().splitlines()[:1]}")
    return p.returncode == 0


def desktop_env() -> str:
    return (os.environ.get("XDG_CURRENT_DESKTOP")
            or os.environ.get("DESKTOP_SESSION") or "").lower()


class Backend:
    name = "none"
    # Where a lock screen reads its image from, when it reads a folder rather
    # than a file. None means the backend takes a path directly.
    lock_wants_dir = False

    @classmethod
    def detect(cls) -> bool:
        return False

    def set_desktop(self, path: str, dry: bool) -> str:
        return UNSUPPORTED

    def set_lock(self, path: str, dry: bool) -> str:
        return UNSUPPORTED

    def install(self, lock_dir: str, dry: bool) -> list[str]:
        """One-time configuration. Returns human-readable notes."""
        return []


class Xfce(Backend):
    """XFCE 4.18+. Backdrop keys are per monitor and per workspace, and do not
    exist until a wallpaper has been set once, hence `-n -t` to create them."""

    name = "xfce"
    lock_wants_dir = True

    @classmethod
    def detect(cls) -> bool:
        return "xfce" in desktop_env() and have("xfconf-query")

    def _monitors(self) -> list[str]:
        if not have("xrandr"):
            return []
        out = subprocess.run(["xrandr", "--query"], capture_output=True, text=True).stdout
        return [ln.split()[0] for ln in out.splitlines() if " connected" in ln]

    def set_desktop(self, path: str, dry: bool) -> str:
        monitors = self._monitors()
        if not monitors:
            # Backdrop keys are named after the output, so without the real
            # names there is nothing useful to write -- guessing one writes a
            # key xfdesktop will never read, which looks like success and is not.
            print("    ! could not enumerate monitors (is xrandr installed?)")
            return NEEDS_SETUP
        run(["xfconf-query", "-c", "xfce4-desktop", "-p", "/backdrop/single-workspace-mode",
             "-n", "-t", "bool", "-s", "true"], dry)
        for mon in monitors:
            base = f"/backdrop/screen0/monitor{mon}/workspace0"
            run(["xfconf-query", "-c", "xfce4-desktop", "-p", f"{base}/last-image",
                 "-n", "-t", "string", "-s", path], dry)
            run(["xfconf-query", "-c", "xfce4-desktop", "-p", f"{base}/image-style",
                 "-n", "-t", "int", "-s", "5"], dry)
        return OK

    def set_lock(self, path: str, dry: bool) -> str:
        # Handled by keeping the slideshow folder stocked; see install().
        return OK if have("xfce4-screensaver-command") else UNSUPPORTED

    def install(self, lock_dir: str, dry: bool) -> list[str]:
        slideshow = "/run/current-system/sw/libexec/xfce4-screensaver/slideshow"
        notes = []
        if not os.path.exists(slideshow):
            notes.append(f"xfce4-screensaver slideshow saver not at {slideshow}")
        args = (f"--location={lock_dir} --background-color='#141311'")
        for prop, typ, val in [("/screensavers/xfce-personal-slideshow/arguments", "string", args),
                               ("/saver/enabled", "bool", "true"),
                               ("/saver/mode", "int", "2"),
                               ("/lock/enabled", "bool", "true")]:
            run(["xfconf-query", "-c", "xfce4-screensaver", "-p", prop, "-n",
                 "-t", typ, "-s", val], dry)
        run(["xfconf-query", "-c", "xfce4-screensaver", "-p", "/saver/themes/list", "-n",
             "-t", "string", "-a", "-s", "screensavers-xfce-personal-slideshow"], dry)
        notes.append("lock screen uses the stock slideshow saver, pointed at the lock folder")
        return notes


class Gnome(Backend):
    """GNOME. The lock screen is the wallpaper, blurred, and is not separately
    settable since 40 -- so set_lock is a no-op that reports ok rather than
    pretending there is a second image to place."""

    name = "gnome"

    @classmethod
    def detect(cls) -> bool:
        return "gnome" in desktop_env() and have("gsettings")

    def set_desktop(self, path: str, dry: bool) -> str:
        uri = f"file://{path}"
        for key in ("picture-uri", "picture-uri-dark"):
            run(["gsettings", "set", "org.gnome.desktop.background", key, uri], dry)
        run(["gsettings", "set", "org.gnome.desktop.background", "picture-options", "zoom"], dry)
        return OK

    def set_lock(self, path: str, dry: bool) -> str:
        run(["gsettings", "set", "org.gnome.desktop.screensaver",
             "picture-uri", f"file://{path}"], dry)
        return OK


class Plasma(Backend):
    """KDE Plasma 6. The desktop has a helper; the lock screen is a config file
    that kscreenlocker re-reads on next lock."""

    name = "plasma"

    @classmethod
    def detect(cls) -> bool:
        return "kde" in desktop_env() and have("plasma-apply-wallpaperimage")

    def set_desktop(self, path: str, dry: bool) -> str:
        return OK if run(["plasma-apply-wallpaperimage", path], dry) else NEEDS_SETUP

    def set_lock(self, path: str, dry: bool) -> str:
        writer = shutil.which("kwriteconfig6") or shutil.which("kwriteconfig5")
        if not writer:
            return NEEDS_SETUP
        run([writer, "--file", "kscreenlockerrc", "--group", "Greeter",
             "--group", "Wallpaper", "--group", "org.kde.image", "--group", "General",
             "--key", "Image", path], dry)
        return OK


class WaylandWM(Backend):
    """sway / Hyprland and friends: a wallpaper daemon, restarted with a new
    image. There is no shared lock-screen mechanism, so that is left alone."""

    name = "wayland-wm"

    @classmethod
    def detect(cls) -> bool:
        return (os.environ.get("XDG_SESSION_TYPE") == "wayland"
                and have("swaybg") or have("hyprpaper"))

    def set_desktop(self, path: str, dry: bool) -> str:
        if have("swaybg"):
            if not dry:
                subprocess.run(["pkill", "-x", "swaybg"], capture_output=True)
                subprocess.Popen(["swaybg", "-i", path, "-m", "fill"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                print(f"    $ swaybg -i {path} -m fill")
            return OK
        return NEEDS_SETUP


class X11(Backend):
    """Any bare X11 window manager, via feh or xwallpaper."""

    name = "x11"

    @classmethod
    def detect(cls) -> bool:
        return os.environ.get("XDG_SESSION_TYPE") == "x11" and have("feh") or have("xwallpaper")

    def set_desktop(self, path: str, dry: bool) -> str:
        if have("feh"):
            return OK if run(["feh", "--no-fehbg", "--bg-fill", path], dry) else NEEDS_SETUP
        if have("xwallpaper"):
            return OK if run(["xwallpaper", "--zoom", path], dry) else NEEDS_SETUP
        return NEEDS_SETUP


# Most specific first: XFCE and GNOME both run on X11, so the generic X11
# backend has to be the last thing tried.
BACKENDS = [Xfce, Gnome, Plasma, WaylandWM, X11]


def detect() -> Backend:
    for cls in BACKENDS:
        try:
            if cls.detect():
                return cls()
        except Exception:            # a probe must never take the whole run down
            continue
    return Backend()


def by_name(name: str) -> Backend:
    for cls in BACKENDS:
        if cls.name == name:
            return cls()
    raise SystemExit(f"unknown desktop {name!r}; choose from "
                     f"{', '.join(c.name for c in BACKENDS)}")


# The screen going dark, on any of the interfaces a desktop might announce it
# on. All three carry a boolean: true when the saver/locker comes on.
SCREENSAVER_MATCHES = [
    "type='signal',interface='org.xfce.ScreenSaver',member='ActiveChanged'",
    "type='signal',interface='org.gnome.ScreenSaver',member='ActiveChanged'",
    "type='signal',interface='org.freedesktop.ScreenSaver',member='ActiveChanged'",
]
