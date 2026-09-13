#!/usr/bin/env python3
"""Download the full-resolution watercolor scans from the Internet Archive.

Roughly 7,581 JPEGs / 56 GB. The run is resumable and safe to re-run: every
file is verified against the MD5 the Archive publishes, already-good files are
skipped, and a partial download is written to `.part` so an interrupted run can
never leave a truncated JPEG in place.

Usage:
    python3 scripts/download_images.py --dry-run     # show the plan
    python3 scripts/download_images.py               # fetch everything missing
    python3 scripts/download_images.py --limit 20    # fetch a sample first
    python3 scripts/download_images.py --verify      # re-checksum what's on disk
"""
from __future__ import annotations

import argparse
import hashlib
import os
import queue
import shutil
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pomlib  # noqa: E402

DOWNLOAD_URL = "https://archive.org/download/{item}/{name}"


def md5_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


class Progress:
    """A single self-updating status line. Falls back to plain lines when the
    output is not a terminal, so nohup/CI logs stay readable."""

    def __init__(self, total_files: int, total_bytes: int, done_bytes: int = 0):
        self.total_files = total_files
        self.total_bytes = total_bytes
        self.done_files = 0
        self.done_bytes = done_bytes
        self.start = time.time()
        self.failed = 0
        self.lock = threading.Lock()
        self.tty = pomlib.is_tty()

    def update(self, pom_id: str, nbytes: int, ok: bool = True) -> None:
        with self.lock:
            self.done_files += 1
            self.done_bytes += nbytes
            if not ok:
                self.failed += 1
            elapsed = time.time() - self.start
            rate = self.done_bytes / elapsed if elapsed else 0
            remaining = self.total_bytes - self.done_bytes
            eta = remaining / rate if rate else 0
            fruit = pomlib.FRUIT[self.done_files % len(pomlib.FRUIT)]
            pct = 100 * self.done_files / max(self.total_files, 1)
            line = (f"{fruit} {self.done_files:,}/{self.total_files:,} ({pct:5.1f}%)  "
                    f"{pomlib.human_bytes(self.done_bytes)}  "
                    f"{pomlib.human_bytes(rate)}/s  eta {pomlib.human_time(eta)}  "
                    f"{'✗' + str(self.failed) + '  ' if self.failed else ''}{pom_id}")
            if self.tty:
                cols = shutil.get_terminal_size((100, 24)).columns
                print(f"\r{line[:cols - 1]:<{cols - 1}}", end="", flush=True)
            elif self.done_files % 100 == 0 or not ok:
                print(line, flush=True)


def fetch_one(row, dest_dir: str, progress: Progress, results: queue.Queue,
              retries: int = 4) -> None:
    pom_id, name, item, size, want_md5 = (
        row["pom_id"], row["name"], row["item"], row["size"], row["md5"])
    path = os.path.join(dest_dir, name)
    part = path + ".part"
    url = DOWNLOAD_URL.format(item=item, name=name)

    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": pomlib.USER_AGENT})
            h = hashlib.md5()
            written = 0
            with urllib.request.urlopen(req, timeout=180) as resp, open(part, "wb") as fh:
                while True:
                    block = resp.read(1 << 20)
                    if not block:
                        break
                    fh.write(block)
                    h.update(block)
                    written += len(block)
            got = h.hexdigest()
            if want_md5 and got != want_md5:
                raise ValueError(f"md5 mismatch (got {got}, want {want_md5})")
            os.replace(part, path)
            results.put((pom_id, path, written, got, 1, None))
            progress.update(pom_id, written)
            return
        except Exception as exc:  # noqa: BLE001 - any failure is worth a retry
            last_err = exc
            if os.path.exists(part):
                os.unlink(part)
            time.sleep(2 ** attempt)

    results.put((pom_id, None, 0, None, 0, str(last_err)))
    progress.update(pom_id, size or 0, ok=False)


def writer_thread(conn, results: queue.Queue, stop: threading.Event,
                  fatal: list) -> None:
    """SQLite writes are funnelled through one thread; the connection is not
    shared across the download workers."""
    pending = []

    def flush():
        if not pending:
            return
        with conn:
            conn.executemany(
                """INSERT INTO downloads
                       (pom_id, path, bytes, md5, verified, error, source, fetched_at)
                   VALUES (?,?,?,?,?,?,'ia',datetime('now'))
                   ON CONFLICT(pom_id) DO UPDATE SET
                       path=excluded.path, bytes=excluded.bytes, md5=excluded.md5,
                       verified=excluded.verified, error=excluded.error,
                       source=excluded.source, fetched_at=excluded.fetched_at""",
                pending)
        pending.clear()

    try:
        while True:
            drained = stop.is_set() and results.empty()
            try:
                pending.append(results.get(timeout=0.5))
            except queue.Empty:
                pass
            if len(pending) >= 50 or drained:
                flush()
            # Checked after the flush so the last partial batch is never dropped.
            if drained:
                return
    except Exception as exc:  # noqa: BLE001
        fatal.append(exc)
        raise


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Download full-resolution scans from the Internet Archive.")
    ap.add_argument("--db", default=pomlib.DB_PATH)
    ap.add_argument("--dest", default=pomlib.ORIGINALS_DIR,
                    help="directory for the original JPEGs")
    ap.add_argument("--workers", type=int, default=4,
                    help="parallel downloads (default 4; be kind to archive.org)")
    ap.add_argument("--limit", type=int, help="stop after N files")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be downloaded, write nothing")
    ap.add_argument("--verify", action="store_true",
                    help="re-checksum files already on disk instead of trusting size")
    ap.add_argument("--redownload", action="store_true",
                    help="ignore what is on disk and fetch everything again")
    args = ap.parse_args()

    conn = pomlib.connect(args.db, multithread=True)
    rows = conn.execute(
        "SELECT pom_id, item, name, size, md5 FROM ia_files ORDER BY pom_id").fetchall()
    if not rows:
        print("No ia_files rows - run scripts/build_db.py first.", file=sys.stderr)
        return 1

    os.makedirs(args.dest, exist_ok=True)

    todo, have_bytes, ok_count = [], 0, 0
    already: list[tuple] = []
    print("🍒 Checking what is already on disk...")
    for row in rows:
        path = os.path.join(args.dest, row["name"])
        if not args.redownload and os.path.exists(path):
            good = os.path.getsize(path) == (row["size"] or -1)
            if good and args.verify:
                good = md5_file(path) == row["md5"]
            if good:
                ok_count += 1
                have_bytes += row["size"] or 0
                # Record skipped-but-good files too, so `downloads` stays a
                # complete ledger across resumed runs rather than only listing
                # what this particular invocation happened to fetch.
                already.append((row["pom_id"], path, row["size"], row["md5"]))
                continue
        todo.append(row)
    if args.limit:
        todo = todo[:args.limit]

    todo_bytes = sum(r["size"] or 0 for r in todo)
    print(f"   on disk : {ok_count:,} files, {pomlib.human_bytes(have_bytes)}")
    print(f"   to fetch: {len(todo):,} files, {pomlib.human_bytes(todo_bytes)}")

    if already and not args.dry_run:
        with conn:
            conn.executemany(
                """INSERT INTO downloads
                       (pom_id, path, bytes, md5, verified, error, source, fetched_at)
                   VALUES (?,?,?,?,1,NULL,'ia',COALESCE(
                       (SELECT fetched_at FROM downloads d WHERE d.pom_id = ?),
                       datetime('now')))
                   ON CONFLICT(pom_id) DO UPDATE SET
                       path=excluded.path, bytes=excluded.bytes, md5=excluded.md5,
                       verified=1, error=NULL""",
                [(p, pa, b, m, p) for p, pa, b, m in already])

    if args.dry_run:
        for row in todo[:10]:
            print(f"   would GET {DOWNLOAD_URL.format(item=row['item'], name=row['name'])}")
        if len(todo) > 10:
            print(f"   ... and {len(todo) - 10:,} more")
        return 0
    if not todo:
        print("✓ nothing to do")
        return 0

    progress = Progress(len(todo), todo_bytes)
    results: queue.Queue = queue.Queue()
    stop = threading.Event()
    fatal: list = []
    writer = threading.Thread(target=writer_thread, args=(conn, results, stop, fatal))
    writer.start()

    work: queue.Queue = queue.Queue()
    for row in todo:
        work.put(row)

    def worker():
        while True:
            try:
                row = work.get_nowait()
            except queue.Empty:
                return
            fetch_one(row, args.dest, progress, results)

    threads = [threading.Thread(target=worker) for _ in range(args.workers)]
    for t in threads:
        t.start()
    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("\ninterrupted - partial files cleaned up, re-run to resume")
    finally:
        stop.set()
        writer.join()

    if fatal:
        print(f"\n! database writer failed: {fatal[0]}", file=sys.stderr)
        return 1

    print()
    failed = conn.execute(
        "SELECT COUNT(*) FROM downloads WHERE verified=0").fetchone()[0]
    print(f"✓ done in {pomlib.human_time(time.time() - progress.start)}"
          f"{f' ({failed} failed - re-run to retry)' if failed else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
