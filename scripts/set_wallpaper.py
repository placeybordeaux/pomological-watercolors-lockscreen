#!/usr/bin/env python3
"""Put a freshly composed pomological plate on the desktop, the lock screen and
the login screen, and install the machinery that keeps doing it.

Three surfaces, three different mechanisms:

  desktop  xfconf `xfce4-desktop` backdrop keys, one per connected monitor.
           xfdesktop reloads when the path changes, so each render lands on a
           new filename rather than overwriting one.
  lock     xfce4-screensaver has no background setting, but it ships a
           `slideshow` saver that takes a folder. The daemon enumerates savers
           through an XDG menu, so a hand-written .desktop in ~/.local/share is
           not picked up; the supported hook is the stock theme plus its
           arguments in xfconf. We keep the folder stocked and the unlock
           dialog draws over it. Exactly one image is kept there on purpose:
           the saver cycles a folder about once a second with no way to slow it
           down (measured, not guessed -- it has no interval option), which is a
           strobe rather than a slideshow. With one file it holds still, and the
           plate changes once per lock like everything else.
  login    SDDM runs as its own user and cannot read $HOME (mode 0700), so the
           login image has to live somewhere world-readable. It is written to
           /var/lib/pomological, which the nix change in ~/nixos creates.

Selection walks a shuffled ring of the prepared plates, so nothing repeats
until the whole pool has been shown once.

Changes happen while the screen is dark, not on a tick. The phone prototype
settled that argument already: a wallpaper that swaps while you are reading the
screen is a distraction, and the fix is not a slower timer but a dark boundary.
xfce4-screensaver broadcasts `ActiveChanged` on org.xfce.ScreenSaver, so
`--watch` composes the next plate when the saver comes on and the screen
reveals a picture that was already there.

Usage:
    scripts/with_pillow.sh python3 scripts/set_wallpaper.py --dry-run
    scripts/with_pillow.sh python3 scripts/set_wallpaper.py              # next in rotation
    scripts/with_pillow.sh python3 scripts/set_wallpaper.py --treatment board
    scripts/with_pillow.sh python3 scripts/set_wallpaper.py --install    # lock saver + watcher
    scripts/with_pillow.sh python3 scripts/set_wallpaper.py --status
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shlex
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compose  # noqa: E402
import pomlib  # noqa: E402
import surfaces  # noqa: E402

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, ".local", "share", "pomological")
DESKTOP_DIR = os.path.join(ROOT, "desktop")
LOCK_DIR = os.path.join(ROOT, "lock")
STATE = os.path.join(ROOT, "state.json")

# SDDM cannot read $HOME. This is the handoff point; the nix change creates it.
LOGIN_DIR = "/var/lib/pomological"
LOGIN_IMAGE = os.path.join(LOGIN_DIR, "login.jpg")

# The stock slideshow saver, and the xfconf key that carries its command line.
# The daemon strips the "screensavers-" prefix when it looks the key up.
SAVER_THEME_ID = "screensavers-xfce-personal-slideshow"
SAVER_ARGS_PROP = "/screensavers/xfce-personal-slideshow/arguments"
SLIDESHOW = "/run/current-system/sw/libexec/xfce4-screensaver/slideshow"

UNIT_DIR = os.path.join(HOME, ".config", "systemd", "user")
SURFACES = ["desktop", "lock", "login"]


# --- a shuffled ring, persisted -------------------------------------------

class Ring(compose.Picker):
    """A Picker that shows every plate once before showing any of them twice.

    What is persisted is the set of plates already *shown*; the ring is just
    the rest, shuffled fresh each run. Order among plates nobody has seen yet
    carries no information, so there is nothing to preserve, and this way a
    newly prepared scan joins the unshown set for free.

    A draw retires exactly the plates it returns. That distinction matters
    because some treatments restrict the pool -- the diptych wants two plates
    of one fruit -- and an earlier version walked a cursor past every
    non-matching entry and counted those as shown. Finding two pears retired
    708 unseen paintings and lapped the collection in a day.
    """

    def __init__(self, state: dict, pool: list[dict]):
        super().__init__()
        self.state = state
        self.by_id = {p["pom_id"]: p for p in pool}
        ids = set(self.by_id)

        if "pos" in state:      # migrate the old {ring, pos} cursor form
            state["shown"] = state.get("ring", [])[:state.pop("pos")]
        self.shown = {i for i in state.get("shown", []) if i in ids}
        self._reshuffle()

    def _reshuffle(self) -> None:
        self.ring = [i for i in self.by_id if i not in self.shown]
        random.shuffle(self.ring)

    def _refill(self) -> None:
        self.shown.clear()
        self._reshuffle()
        self.state["laps"] = self.state.get("laps", 0) + 1

    def next_plates(self, pool: list[dict], n: int) -> list[dict]:
        allowed = {p["pom_id"] for p in pool}
        out = []
        for pid in self.ring:
            if pid in allowed:
                out.append(self.by_id[pid])
                if len(out) == n:
                    break
        for item in out:
            self.shown.add(item["pom_id"])
            self.ring.remove(item["pom_id"])
        if not self.ring:
            self._refill()
        # A restricted draw can come up short without the ring being spent --
        # the last two pears may already have been shown. Top up at random
        # rather than lapping the whole collection over one treatment.
        while len(out) < n and pool:
            out.append(self.rng.choice(pool))
        return out

    def save(self) -> dict:
        self.state["shown"] = sorted(self.shown)
        self.state.pop("ring", None)
        self.state.pop("pos", None)
        return self.state


def load_state() -> dict:
    try:
        with open(STATE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


# --- surfaces ---------------------------------------------------------------

run = surfaces.run


def apply_desktop(backend, path: str, dry: bool) -> str:
    return backend.set_desktop(path, dry)


def apply_lock(backend, path: str, keep: int, dry: bool) -> str:
    """Stock the folder the lock screen reads, then let the backend point at it.

    `keep` is 1 by default and should stay there on XFCE: its stock saver flips
    through whatever it finds roughly once a second, which is a strobe rather
    than a slideshow. With one file it holds still.
    """
    if dry:
        print(f"    cp {os.path.basename(path)} -> {LOCK_DIR}/ (keep {keep})")
    else:
        os.makedirs(LOCK_DIR, exist_ok=True)
        shutil.copy2(path, os.path.join(LOCK_DIR, os.path.basename(path)))
        prune(LOCK_DIR, keep)
    target = LOCK_DIR if backend.lock_wants_dir else os.path.join(
        LOCK_DIR, os.path.basename(path))
    return backend.set_lock(target, dry)


def apply_login(path: str, dry: bool) -> bool:
    """Copy to the world-readable handoff. Returns False if nix hasn't run yet."""
    if not os.path.isdir(LOGIN_DIR) or not os.access(LOGIN_DIR, os.W_OK):
        return False
    if dry:
        print(f"    cp {os.path.basename(path)} -> {LOGIN_IMAGE}")
        return True
    tmp = LOGIN_IMAGE + ".part"          # SDDM may read at any moment
    shutil.copy2(path, tmp)
    os.chmod(tmp, 0o644)
    os.replace(tmp, LOGIN_IMAGE)
    return True


def prune(directory: str, keep: int) -> None:
    files = sorted((f for f in os.listdir(directory) if f.endswith(".jpg")),
                   key=lambda f: os.path.getmtime(os.path.join(directory, f)))
    for f in files[:-keep] if keep else files:
        os.unlink(os.path.join(directory, f))



# --- change in the dark -----------------------------------------------------

def watch(apply_once, min_seconds: int) -> int:
    """Compose the next plate whenever the screen goes dark, at most hourly.

    dbus-monitor rather than a python D-Bus binding: this runs inside the
    Pillow nix shell, and shelling out keeps that shell from needing pygobject
    too. The signal carries a boolean - true when the saver comes on.
    """
    proc = subprocess.Popen(["dbus-monitor", "--session", *surfaces.SCREENSAVER_MATCHES],
                            stdout=subprocess.PIPE, text=True, bufsize=1)
    print(f"🌙 watching for the screen going dark · at most one change per "
          f"{pomlib.human_time(min_seconds)}", flush=True)
    armed = False
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("signal "):
            armed = "ActiveChanged" in line
            continue
        if not armed or not line.startswith("boolean"):
            continue
        armed = False
        if line != "boolean true":       # the screen coming back, not going dark
            continue
        since = time.time() - load_state().get("at_epoch", 0)
        if since < min_seconds:
            print(f"   screen dark, but only {pomlib.human_time(since)} since the last "
                  f"change - holding", flush=True)
            continue
        print(f"   screen dark after {pomlib.human_time(since)} - composing", flush=True)
        apply_once()
    return proc.wait()


# --- install ----------------------------------------------------------------

SERVICE_TEMPLATE = """[Unit]
Description=Compose and set the next pomological wallpaper
Documentation=file://{repo}/README.md

[Service]
Type=oneshot
ExecStart={repo}/scripts/with_pillow.sh python3 {repo}/scripts/set_wallpaper.py
"""

WATCH_SERVICE_TEMPLATE = """[Unit]
Description=Change the pomological wallpaper whenever the screen goes dark
Documentation=file://{repo}/README.md
PartOf=graphical-session.target
After=graphical-session.target

[Service]
ExecStart={repo}/scripts/with_pillow.sh python3 {repo}/scripts/set_wallpaper.py \\
    --watch --min-interval {interval} --treatment {treatment}
Restart=always
RestartSec=10s

[Install]
WantedBy=graphical-session.target
"""

TIMER_TEMPLATE = """[Unit]
Description=Change the pomological wallpaper hourly

[Timer]
OnActiveSec=5min
OnUnitActiveSec={interval}
Persistent=true

[Install]
WantedBy=timers.target
"""


def install(backend, mode: str, interval: str, treatment: str, dry: bool) -> None:
    print(f"  lock screen ({backend.name})")
    for note in backend.install(LOCK_DIR, dry) or ["nothing to configure"]:
        print(f"    {note}")

    print(f"  rotation ({mode})")
    write(os.path.join(UNIT_DIR, "pomological-wallpaper.service"),
          SERVICE_TEMPLATE.format(repo=pomlib.REPO_ROOT), dry)
    if mode == "watch":
        units = ["pomological-watch.service"]
        write(os.path.join(UNIT_DIR, "pomological-watch.service"),
              WATCH_SERVICE_TEMPLATE.format(repo=pomlib.REPO_ROOT, interval=interval,
                                            treatment=treatment), dry)
    else:
        units = ["pomological-wallpaper.timer"]
        write(os.path.join(UNIT_DIR, "pomological-wallpaper.timer"),
              TIMER_TEMPLATE.format(interval=interval), dry)
    run(["systemctl", "--user", "daemon-reload"], dry)
    for unit in units:
        run(["systemctl", "--user", "enable", "--now", unit], dry)

    print("  login screen")
    if os.path.isdir(LOGIN_DIR):
        print(f"    {LOGIN_DIR} ready")
    else:
        print(f"    {LOGIN_DIR} does not exist - see nix/nixos-module.nix, or "
              f"point your greeter at it yourself")


def write(path: str, body: str, dry: bool) -> None:
    if dry:
        print(f"    would write {path} ({len(body)} bytes)")
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(body)
    print(f"    wrote {path}")


def status() -> int:
    st = load_state()
    pool_n = len(compose.load_pool())
    print(f"   desktop  detected as {surfaces.detect().name}")
    unshown = pool_n - len(st.get("shown", []))
    print(f"🍎 pool {pool_n} plates · {unshown} unshown "
          f"· {st.get('laps', 0)} laps · last {st.get('treatment', '—')}")
    cur = st.get("current")
    print(f"   desktop  {cur or '—'}")
    print(f"   lock     {LOCK_DIR} "
          f"({len(os.listdir(LOCK_DIR)) if os.path.isdir(LOCK_DIR) else 0} images)")
    ok = os.path.isdir(LOGIN_DIR) and os.access(LOGIN_DIR, os.W_OK)
    print(f"   login    {LOGIN_IMAGE if ok else LOGIN_DIR + ' (not set up - see ~/nixos)'}")
    for unit, label in [("pomological-watch.service", "watcher"),
                        ("pomological-wallpaper.timer", "timer  ")]:
        state = subprocess.run(["systemctl", "--user", "is-active", unit],
                               capture_output=True, text=True).stdout.strip()
        print(f"   {label}  {state or 'unknown'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--treatment", choices=compose.TREATMENTS + ["rotate"], default="rotate",
                    help="'rotate' advances through the treatments, one per change. "
                         "With --install it is baked into the unit, so "
                         "`--install --treatment mat` pins the rotation to one treatment")
    ap.add_argument("--surfaces", default=",".join(SURFACES),
                    help=f"comma-separated subset of {SURFACES}")
    ap.add_argument("--size", default=None, help="WxH; defaults to the primary monitor")
    ap.add_argument("--keep", type=int, default=6,
                    help="rendered images to retain in the desktop folder")
    ap.add_argument("--lock-keep", type=int, default=1,
                    help="images in the lock folder. More than 1 makes the stock "
                         "saver cycle them about once a second")
    ap.add_argument("--install", action="store_true",
                    help="install the lock saver and the rotation unit")
    ap.add_argument("--mode", choices=["watch", "timer"], default="watch",
                    help="watch: change when the screen goes dark. timer: change on the hour")
    ap.add_argument("--interval", default="1h", help="minimum time between changes")
    ap.add_argument("--watch", action="store_true",
                    help="run the watcher in the foreground (what the unit does)")
    ap.add_argument("--min-interval", default=None, help="alias for --interval when watching")
    ap.add_argument("--desktop", choices=[c.name for c in surfaces.BACKENDS],
                    help="override desktop detection")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.status:
        return status()

    # Which desktop we are talking to has to be settled before anything that
    # touches a screen, install included.
    backend = surfaces.by_name(args.desktop) if args.desktop else surfaces.detect()
    if backend.name == "none":
        ap.error("could not detect a supported desktop; pass --desktop "
                 f"({', '.join(c.name for c in surfaces.BACKENDS)})")

    if args.install:
        print(f"🍐 installing on {backend.name}{' (dry run)' if args.dry_run else ''}")
        install(backend, args.mode, args.interval, args.treatment, args.dry_run)
        if args.dry_run:
            return 0

    size = args.size or screen_size()
    W, H = (int(v) for v in size.lower().split("x"))
    wanted = [w.strip() for w in args.surfaces.split(",") if w.strip()]
    for w in wanted:
        if w not in SURFACES:
            ap.error(f"unknown surface {w!r}; choose from {SURFACES}")

    pool = compose.load_pool()

    def apply_once() -> None:
        change(args, backend, pool, W, H, wanted)

    if args.watch:
        return watch(apply_once, parse_interval(args.min_interval or args.interval))

    apply_once()
    return 0


def parse_interval(text: str) -> int:
    """'90m' -> 5400. Accepts a bare number of seconds too."""
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    text = text.strip().lower()
    if text[-1] in units:
        return int(float(text[:-1]) * units[text[-1]])
    return int(float(text))


def change(args, backend, pool, W, H, wanted) -> None:
    st = load_state()
    treatment = args.treatment
    if treatment == "rotate":
        # Step through the treatments rather than picking at random, so a week
        # of changes actually shows all six instead of three of them twice.
        order = compose.TREATMENTS
        treatment = order[(order.index(st["treatment"]) + 1) % len(order)
                          if st.get("treatment") in order else 0]

    ring = Ring(st, pool)
    print(f"🍑 {treatment} · {W}×{H} · {len(ring.ring)} unshown"
          f"{' · dry run' if args.dry_run else ''}")

    canvas, used = compose.compose(treatment, pool, ring, (W, H))
    print("   " + ", ".join(f"{u['pom_id']} {u['variety'] or u['common'] or ''}".strip()
                            for u in used[:4]) + (" …" if len(used) > 4 else ""))

    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(DESKTOP_DIR, f"{treatment}-{stamp}.jpg")
    if args.dry_run:
        print(f"   would render {path}")
    else:
        os.makedirs(DESKTOP_DIR, exist_ok=True)
        canvas.save(path, quality=92, optimize=True, progressive=True)
        print(f"   {path} ({pomlib.human_bytes(os.path.getsize(path))})")

    if "desktop" in wanted:
        print("  desktop")
        print(f"    {apply_desktop(backend, path, args.dry_run)}")
    if "lock" in wanted:
        print("  lock")
        print(f"    {apply_lock(backend, path, args.lock_keep, args.dry_run)}")
    if "login" in wanted:
        print("  login")
        if not apply_login(path, args.dry_run):
            print(f"    skipped - {LOGIN_DIR} not writable (needs the nix change)")

    if not args.dry_run:
        prune(DESKTOP_DIR, args.keep)
        st = ring.save()
        st.update({"treatment": treatment, "current": path, "at": stamp})
        os.makedirs(ROOT, exist_ok=True)
        st.update({"at_epoch": time.time()})
        with open(STATE, "w") as fh:
            json.dump(st, fh, indent=1)


def screen_size() -> str:
    for ln in subprocess.run(["xrandr", "--query"], capture_output=True,
                             text=True).stdout.splitlines():
        if " connected" in ln:
            for tok in ln.split():
                if "x" in tok and tok.split("x")[0].isdigit():
                    return tok.split("+")[0]
    return "3440x1440"


if __name__ == "__main__":
    raise SystemExit(main())
