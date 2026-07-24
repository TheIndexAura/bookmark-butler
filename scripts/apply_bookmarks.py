#!/usr/bin/env python3
"""Apply an organized bookmark layout to Chromium-family profiles.

Usage:
  python apply_bookmarks.py --plan plan.json PROFILE_DIR [PROFILE_DIR ...]
  python apply_bookmarks.py --plan plan.json --dry-run PROFILE_DIR ...

plan.json format:
{
  "pinned_folders": ["Accounts", "AI"],            # lead the bar (optional)
  "loose": [["Claude", "https://example.com/"]],   # visible on the bar
  "folders": {"AI": [["name","url"], ...], ...},   # everything else
  "folder_order": ["AI", "Jobs", ...],             # after pinned+loose; folders
                                                   # omitted here are appended
                                                   # at the end (never dropped)
  "sort_links": "usage" | "alpha" | "keep",
  "sort_folders": "usage" | "alpha" | "keep",
  "expected_urls": ["https://...", ...]            # REQUIRED guard: the FINAL
                                                   # approved URL list (after
                                                   # root-collapse and repairs,
                                                   # minus approved deletions).
                                                   # Every one must appear in
                                                   # the plan or the run aborts.
                                                   # NOT the raw pre-cleanup
                                                   # list - those URLs were
                                                   # intentionally rewritten.
                                                   # Opt out only with
                                                   # --skip-url-guard.
}

Safety:
- REFUSES to run if a Chromium-family browser appears to be running, and
  FAILS CLOSED if the process list cannot be read.
- Validates the plan (no folder dropped, no duplicate URLs, expected_urls
  guard) before touching anything.
- Writes a timestamped backup of every profile's Bookmarks file first.
- Atomic write: temp file + fsync + os.replace — a crash cannot corrupt the
  live file.
- Never touches the browser's own Bookmarks.bak recovery file.
- Verifies the written JSON re-parses and reports counts.
- "usage" ordering reads visit counts from each profile's History database
  (copied together with its -wal/-shm sidecars). Scores are per-domain, so
  usage order is approximate, not per-exact-URL.
"""
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from collections import defaultdict
from urllib.parse import urlsplit

BROWSER_PROCS = ("chrome", "chromium", "msedge", "microsoft edge", "brave", "vivaldi", "opera")


def browser_running():
    """Return list of running browser names. Raises RuntimeError if the check
    itself fails — callers must treat that as 'assume running' (fail closed)."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(["tasklist"], capture_output=True, text=True, timeout=15).stdout.lower()
        else:
            out = subprocess.run(["ps", "-A", "-o", "comm="], capture_output=True, text=True, timeout=15).stdout.lower()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"could not read process list: {e}") from e
    if not out.strip():
        raise RuntimeError("process list came back empty")
    return sorted({p for p in BROWSER_PROCS if p in out})


def wk_now():
    """Chrome timestamp: microseconds since 1601-01-01."""
    return str(int((time.time() + 11644473600) * 1_000_000))


def validate_plan(plan, skip_url_guard=False):
    """Catch silent data loss before anything is written."""
    errors = []
    folders = plan.get("folders", {})
    known = set(plan.get("pinned_folders", [])) | set(plan.get("folder_order", []))
    orphans = [k for k in folders if k not in known]
    # orphans are appended, not dropped — but surface them so the caller knows
    all_urls = [u for _, u in plan.get("loose", [])]
    for pairs in folders.values():
        all_urls += [u for _, u in pairs]
    dupes = {u for u in all_urls if all_urls.count(u) > 1}
    if dupes:
        errors.append(f"duplicate URLs in plan: {sorted(dupes)[:5]}{'...' if len(dupes) > 5 else ''}")
    missing_folders = [k for k in plan.get("pinned_folders", []) + plan.get("folder_order", [])
                       if k not in folders]
    if missing_folders:
        errors.append(f"folder_order/pinned names with no folder entry: {missing_folders}")
    expected = set(plan.get("expected_urls", []))
    if not expected and not skip_url_guard:
        errors.append("expected_urls missing/empty. Fill it with the full merged URL list "
                      "(the data-loss guard), or pass --skip-url-guard to proceed without it.")
    if expected:
        missing = expected - set(all_urls)
        if missing:
            errors.append(f"{len(missing)} expected URL(s) absent from plan, e.g. {sorted(missing)[:3]}")
    return errors, orphans


def load_history_scores(profile_dirs):
    scores = defaultdict(int)
    for pdir in profile_dirs:
        hist = os.path.join(pdir, "History")
        if not os.path.isfile(hist):
            continue
        tmpdir = tempfile.mkdtemp(prefix="bb_hist_")
        try:
            tmp = os.path.join(tmpdir, "History")
            shutil.copy2(hist, tmp)
            for side in ("-wal", "-shm"):  # WAL sidecars hold recent rows
                if os.path.isfile(hist + side):
                    shutil.copy2(hist + side, tmp + side)
            con = sqlite3.connect(tmp)
            for url, vc in con.execute("SELECT url, visit_count FROM urls"):
                scores[(urlsplit(url).netloc or "").replace("www.", "")] += vc
            con.close()
        except (OSError, sqlite3.Error) as e:
            print(f"  history skip {pdir}: {e}", file=sys.stderr)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    return scores


def atomic_write_json(path, data):
    """Write JSON to path atomically: temp file in same dir, fsync, replace."""
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".bb_tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=3)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


class Builder:
    def __init__(self, plan, scores):
        self.plan = plan
        self.scores = scores
        self.counter = 1000

    def nid(self):
        self.counter += 1
        return str(self.counter)

    def score(self, url):
        return self.scores.get((urlsplit(url).netloc or "").replace("www.", ""), 0)

    def sort_pairs(self, pairs):
        mode = self.plan.get("sort_links", "keep")
        if mode == "alpha":
            return sorted(pairs, key=lambda nu: nu[0].lower())
        if mode == "usage":
            return sorted(pairs, key=lambda nu: (-self.score(nu[1]), nu[0].lower()))
        return list(pairs)

    def url_node(self, name, url, ts):
        return {"date_added": ts, "date_last_used": "0", "guid": str(uuid.uuid4()),
                "id": self.nid(), "name": name, "type": "url", "url": url}

    def folder_node(self, name, pairs, ts):
        return {"date_added": ts, "date_modified": ts, "guid": str(uuid.uuid4()),
                "id": self.nid(), "name": name, "type": "folder",
                "children": [self.url_node(n, u, ts) for n, u in self.sort_pairs(pairs)]}

    def bar_children(self, orphans):
        self.counter = 1000
        ts = wk_now()
        plan = self.plan
        folders = plan.get("folders", {})
        pinned = [k for k in plan.get("pinned_folders", []) if folders.get(k)]
        rest = [k for k in plan.get("folder_order", list(folders)) if k not in pinned and folders.get(k)]
        rest += [k for k in orphans if k not in pinned and k not in rest]  # never drop a folder
        mode = plan.get("sort_folders", "keep")
        if mode == "alpha":
            rest = sorted(rest, key=str.lower)
        elif mode == "usage":
            rest = sorted(rest, key=lambda k: -sum(self.score(u) for _, u in folders[k]))
        kids = [self.folder_node(k, folders[k], ts) for k in pinned]
        kids += [self.url_node(n, u, ts) for n, u in self.sort_pairs(plan.get("loose", []))]
        kids += [self.folder_node(k, folders[k], ts) for k in rest]
        return kids


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True, help="plan.json path")
    ap.add_argument("--dry-run", action="store_true", help="validate + report; write nothing")
    ap.add_argument("--skip-url-guard", action="store_true",
                    help="allow a plan without expected_urls (weaker data-loss protection)")
    ap.add_argument("--assume-closed", action="store_true",
                    help="proceed when the process list CANNOT be read (never bypasses a "
                         "positively-detected running browser)")
    ap.add_argument("profiles", nargs="+", help="profile directories to write")
    args = ap.parse_args()

    with open(args.plan, encoding="utf-8") as f:
        plan = json.load(f)

    errors, orphans = validate_plan(plan, skip_url_guard=args.skip_url_guard)
    if errors:
        sys.exit("PLAN INVALID:\n  " + "\n  ".join(errors))
    if orphans:
        print(f"note: folder(s) not in folder_order, appended at end: {orphans}")

    if not args.dry_run:
        try:
            running = browser_running()
        except RuntimeError as e:
            if args.assume_closed:
                print(f"warning: process check unavailable ({e}); proceeding on --assume-closed")
                running = []
            else:
                sys.exit(f"REFUSING to write (fail closed): {e}. "
                         f"Verify the browser is fully closed yourself, then retry.")
        if running:
            # a positively-detected running browser is NEVER bypassable
            sys.exit(f"REFUSING to write: browser process(es) running: {', '.join(running)}. "
                     f"Close the browser fully and retry.")

    scores = {}
    if "usage" in (plan.get("sort_links"), plan.get("sort_folders")):
        scores = load_history_scores(args.profiles)

    builder = Builder(plan, scores)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    for pdir in args.profiles:
        fp = os.path.join(pdir, "Bookmarks")
        if not os.path.isfile(fp):
            print(f"SKIP {pdir}: no Bookmarks file", file=sys.stderr)
            continue
        with open(fp, encoding="utf-8") as f:
            data = json.load(f)
        new_bar = builder.bar_children(orphans)
        if args.dry_run:
            n_links = sum(1 if c["type"] == "url" else len(c["children"]) for c in new_bar)
            print(f"DRY-RUN {pdir}: would write {n_links} links "
                  f"({sum(1 for c in new_bar if c['type'] == 'folder')} folders)")
            continue
        bak = f"{fp}.backup_{stamp}"
        shutil.copy2(fp, bak)
        data["roots"]["bookmark_bar"]["children"] = new_bar
        data["roots"]["bookmark_bar"]["date_modified"] = wk_now()
        # 'other' and 'synced' were merged into the new bar by the workflow,
        # so clear both to avoid duplicates (documented in SKILL.md)
        for extra_root in ("other", "synced"):
            if extra_root in data["roots"]:
                data["roots"][extra_root]["children"] = []
        # browser recomputes checksums on load; stale ones trigger a false
        # "recovery" from Bookmarks.bak
        data.pop("checksum", None)
        data.pop("checksum_sha256", None)
        atomic_write_json(fp, data)
        # verify
        with open(fp, encoding="utf-8") as f:
            check = json.load(f)
        bar = check["roots"]["bookmark_bar"]["children"]
        n_loose = sum(1 for c in bar if c["type"] == "url")
        n_fold = sum(1 for c in bar if c["type"] == "folder")
        n_links = n_loose + sum(len(c["children"]) for c in bar if c["type"] == "folder")
        leftovers = sum(len(check["roots"].get(rk, {}).get("children", []))
                        for rk in ("other", "synced"))
        if leftovers:
            print(f"WARNING {pdir}: {leftovers} item(s) remain outside the bar", file=sys.stderr)
        print(f"OK {pdir}\n   {n_loose} loose + {n_fold} folders = {n_links} links "
              f"(other/synced cleared) | backup: {bak}")


if __name__ == "__main__":
    main()
