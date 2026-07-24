#!/usr/bin/env python3
"""Find every browser profile on this machine and report account + bookmark count.

Usage:  python find_profiles.py [--json] [--show-emails]

Read-only. Safe to run while browsers are open.
Covers Chromium-family (Chrome, Edge, Brave, Vivaldi, Opera) fully and
detects Firefox profiles (read-only support).

Privacy: signed-in account emails are MASKED by default (a**@g**.com) so the
output is safe to paste in screenshots/issues. Pass --show-emails for full
addresses.
"""
import argparse
import json
import os
import glob
import platform

HOME = os.path.expanduser("~")
OS = platform.system()  # Windows / Darwin / Linux


def chromium_roots():
    """Yield (browser_name, user_data_dir) for installed Chromium browsers."""
    if OS == "Windows":
        local = os.environ.get("LOCALAPPDATA", os.path.join(HOME, "AppData", "Local"))
        roaming = os.environ.get("APPDATA", os.path.join(HOME, "AppData", "Roaming"))
        candidates = [
            ("Chrome", os.path.join(local, "Google", "Chrome", "User Data")),
            ("Edge", os.path.join(local, "Microsoft", "Edge", "User Data")),
            ("Brave", os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data")),
            ("Vivaldi", os.path.join(local, "Vivaldi", "User Data")),
            ("Opera", os.path.join(roaming, "Opera Software", "Opera Stable")),
        ]
    elif OS == "Darwin":
        app = os.path.join(HOME, "Library", "Application Support")
        candidates = [
            ("Chrome", os.path.join(app, "Google", "Chrome")),
            ("Edge", os.path.join(app, "Microsoft Edge")),
            ("Brave", os.path.join(app, "BraveSoftware", "Brave-Browser")),
            ("Vivaldi", os.path.join(app, "Vivaldi")),
            ("Opera", os.path.join(app, "com.operasoftware.Opera")),
        ]
    else:  # Linux
        cfg = os.path.join(HOME, ".config")
        candidates = [
            ("Chrome", os.path.join(cfg, "google-chrome")),
            ("Chromium", os.path.join(cfg, "chromium")),
            ("Edge", os.path.join(cfg, "microsoft-edge")),
            ("Brave", os.path.join(cfg, "BraveSoftware", "Brave-Browser")),
            ("Vivaldi", os.path.join(cfg, "vivaldi")),
            ("Opera", os.path.join(cfg, "opera")),
        ]
    for name, root in candidates:
        if os.path.isdir(root):
            yield name, root


def count_bookmarks(bookmarks_path):
    try:
        with open(bookmarks_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    def walk(node):
        n = 0
        for ch in node.get("children", []):
            n += 1 if ch.get("type") == "url" else walk(ch)
        return n

    roots = data.get("roots", {})
    return sum(walk(roots[k]) for k in ("bookmark_bar", "other", "synced") if k in roots)


def profile_account(profile_dir):
    """Best-effort signed-in account email / profile label from Preferences."""
    pref = os.path.join(profile_dir, "Preferences")
    try:
        with open(pref, encoding="utf-8") as f:
            p = json.load(f)
    except (OSError, json.JSONDecodeError):
        return "(unknown)"
    info = p.get("account_info") or []
    if info and info[0].get("email"):
        return info[0]["email"]
    return p.get("profile", {}).get("name", "(unnamed)")


def chromium_profiles(root):
    """Yield profile dirs inside a user-data root (or the root itself for Opera-style)."""
    if os.path.isfile(os.path.join(root, "Bookmarks")):
        yield root  # single-profile layout (Opera on Windows)
        return
    for d in [os.path.join(root, "Default")] + sorted(glob.glob(os.path.join(root, "Profile *"))):
        if os.path.isfile(os.path.join(d, "Bookmarks")):
            yield d


def firefox_profiles():
    if OS == "Windows":
        base = os.path.join(os.environ.get("APPDATA", ""), "Mozilla", "Firefox", "Profiles")
    elif OS == "Darwin":
        base = os.path.join(HOME, "Library", "Application Support", "Firefox", "Profiles")
    else:
        base = os.path.join(HOME, ".mozilla", "firefox")
    if not os.path.isdir(base):
        return
    for d in sorted(glob.glob(os.path.join(base, "*"))):
        if os.path.isfile(os.path.join(d, "places.sqlite")):
            yield d


def mask_email(s):
    """a**@g**.com — recognizable to the owner, safe in screenshots."""
    if "@" not in s:
        return s
    local, _, dom = s.partition("@")
    dparts = dom.split(".")
    return f"{local[:1]}**@{dparts[0][:1]}**.{'.'.join(dparts[1:])}" if len(dparts) > 1 else f"{local[:1]}**@**"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--show-emails", action="store_true",
                    help="show full account emails (masked by default)")
    args = ap.parse_args()

    rows = []
    for browser, root in chromium_roots():
        for pdir in chromium_profiles(root):
            rows.append({
                "browser": browser,
                "profile": os.path.basename(pdir) if pdir != root else "(single)",
                "account": profile_account(pdir),
                "bookmarks": count_bookmarks(os.path.join(pdir, "Bookmarks")),
                "path": pdir,
                "writable": True,
            })
    for pdir in firefox_profiles():
        rows.append({
            "browser": "Firefox",
            "profile": os.path.basename(pdir),
            "account": "(n/a)",
            "bookmarks": None,
            "path": pdir,
            "writable": False,
        })

    if not args.show_emails:
        for r in rows:
            r["account"] = mask_email(r["account"])
    if args.json:
        print(json.dumps(rows, indent=1))
        return
    if not rows:
        print("No browser profiles found.")
        return
    w = max(len(r["browser"]) for r in rows) + 2
    for r in rows:
        rw = "" if r["writable"] else "  [read-only: Firefox]"
        bm = "?" if r["bookmarks"] is None else r["bookmarks"]
        print(f"{r['browser']:<{w}}{r['profile']:<12} {r['account']:<34} bookmarks={bm}{rw}")
        print(f"{'':<{w}}{r['path']}")


if __name__ == "__main__":
    main()
